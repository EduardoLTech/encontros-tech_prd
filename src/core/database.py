import math
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from contextlib import contextmanager
from core.settings import settings
from core.logging import get_logger

logger = get_logger("database")

# Timeout do trafego de negocio. Nao e o teto da prontidao (esse e configuravel):
# e o limite que impede uma requisicao de negocio de prender uma thread para
# sempre contra um banco pendurado. Sem ele, oito requisicoes travadas esgotam as
# threads e /health deixa de ser respondido - I7 violada pelo trafego, nao pelas
# probes (design D3.1).
BUSINESS_TIMEOUT_SECONDS = 10

# keepalives + tcp_user_timeout sao o que efetivamente derruba uma conexao com um
# servidor congelado: o connect_timeout so cobre o handshake, e um banco que
# aceitou a conexao e parou de responder deixaria o cliente esperando no recv.
_TCP_LIVENESS_ARGS = {
    "keepalives": 1,
    "keepalives_idle": 2,
    "keepalives_interval": 2,
    "keepalives_count": 2,
}

engine = create_engine(
    settings.DATABASE_URL,
    pool_timeout=BUSINESS_TIMEOUT_SECONDS,
    connect_args={
        "connect_timeout": BUSINESS_TIMEOUT_SECONDS,
        "tcp_user_timeout": BUSINESS_TIMEOUT_SECONDS * 1000,
        **_TCP_LIVENESS_ARGS,
    },
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Engine dedicado à verificação de prontidão (PRD-0001 · P3/P4/I6, design D3).
#
# Separado do engine de negócio por três motivos:
#   1. Evita falso-negativo por saturação: se a verificação disputasse o pool de
#      negócio, um pico de tráfego legítimo derrubaria a readiness e tiraria o pod
#      da rotação por estar ocupado, reduzindo capacidade justamente sob carga.
#   2. Isola o timeout curto da verificação do tráfego de negócio.
#   3. NullPool satisfaz I6 estruturalmente: sem conexão reaproveitada que possa
#      estar morta desde antes do incidente e mascarar o estado real.
#
# connect_timeout é inteiro porque a libpq só aceita segundos inteiros, e tem
# piso 2 porque valores menores são silenciosamente elevados para 2 por ela.
health_engine = create_engine(
    settings.DATABASE_URL,
    poolclass=NullPool,
    connect_args={
        "connect_timeout": max(2, math.floor(settings.READINESS_DB_TIMEOUT_SECONDS)),
        # Sem isto, a thread orfa de uma verificacao que estourou o teto ficaria
        # pendurada para sempre no recv e o executor saturaria.
        "tcp_user_timeout": int(settings.READINESS_DB_TIMEOUT_SECONDS * 1000),
        **_TCP_LIVENESS_ARGS,
    },
)


@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# O connect_timeout da libpq limita o connect TCP com precisao, mas NAO cobre a
# resolucao de nome - e o DATABASE_URL usa hostname (o Service do Postgres no
# cluster). Sem um prazo por fora, um DNS lento faz a verificacao estourar o teto
# e o kubelet corta a tentativa antes da resposta 503, levando junto o corpo de
# diagnostico (PRD-0001 - P9.2/P11). Dai o executor: ele da o teto de tempo de
# parede real. Threads orfas terminam sozinhas quando a resolucao falha.
_check_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="db-check")


def _probe(deadline: float) -> bool:
    """Executa a verificação propriamente dita. Só é chamada pelo executor."""
    with health_engine.connect() as conn:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False

        # Sessão descartada logo em seguida pelo NullPool, então o SET não
        # vaza para nenhuma outra conexão.
        conn.execute(text(f"SET statement_timeout = {int(remaining * 1000)}"))
        conn.execute(text("SELECT 1"))

    return True


def check_database() -> bool:
    """
    Verifica a conectividade com o banco dentro do teto de tempo configurado.

    O teto é um orçamento TOTAL de tempo de parede (design D2): a verificação roda
    em uma thread e o resultado é aguardado por, no máximo, o teto — cobrindo
    resolução de nome, conexão e consulta. Os timeouts do driver (connect_timeout,
    statement_timeout) continuam valendo como limites internos, para que a thread
    não fique pendurada além do necessário.

    Nunca levanta exceção: qualquer falha significa "não pronto". O detalhe do erro
    vai para o log (onde o operador precisa dele), nunca para o corpo da resposta
    (PRD-0001 · R3).
    """
    budget = settings.READINESS_DB_TIMEOUT_SECONDS
    future = _check_executor.submit(_probe, time.monotonic() + budget)

    try:
        return future.result(timeout=budget)
    except FutureTimeoutError:
        logger.warning(
            f"Verificacao de prontidao excedeu o teto de {budget}s - reportando down"
        )
        return False
    except Exception as exc:
        logger.warning(f"Verificacao de prontidao falhou: {type(exc).__name__}: {exc}")
        return False
