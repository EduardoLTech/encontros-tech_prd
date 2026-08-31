import threading
import time
from sqlalchemy import text

from core.database import health_engine
from core.logging import get_logger

logger = get_logger("schema")

# Chave arbitrária e estável do advisory lock do Postgres. Serializa a preparação
# do schema entre workers do Gunicorn e entre réplicas, sem coordenação externa.
SCHEMA_LOCK_KEY = 8145201

RETRY_INITIAL_SECONDS = 1.0
RETRY_MAX_SECONDS = 30.0


def prepare_schema(base) -> bool:
    """
    Prepara o schema uma vez, em regime best-effort.

    Usa o health_engine porque ele tem connect_timeout: com o engine de negócio,
    que não tem timeout algum, um banco pendurado penduraria o boot — exatamente
    o que I4 proíbe.

    Retorna True em caso de sucesso. Nunca levanta exceção: a indisponibilidade do
    banco não pode impedir o processo de concluir a inicialização (PRD-0001 · P7/I4).
    """
    try:
        with health_engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": SCHEMA_LOCK_KEY})
            try:
                base.metadata.create_all(bind=conn)
                conn.commit()
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": SCHEMA_LOCK_KEY})
                conn.commit()

        logger.info("Schema do banco de dados preparado")
        return True
    except Exception as exc:
        logger.warning(
            f"Nao foi possivel preparar o schema agora: {type(exc).__name__}: {exc}"
        )
        return False


def _repair_loop(base):
    delay = RETRY_INITIAL_SECONDS

    while True:
        time.sleep(delay)
        if prepare_schema(base):
            logger.info("Schema preparado pela rotina de reparo; encerrando retentativas")
            return

        delay = min(delay * 2, RETRY_MAX_SECONDS)
        logger.info(f"Nova tentativa de preparar o schema em {delay}s")


def ensure_schema(base):
    """
    Garante a preparação do schema sem bloquear a inicialização.

    Se o banco estiver indisponível no boot, o processo sobe assim mesmo e uma
    thread de reparo retenta com backoff exponencial até conseguir — de modo que a
    aplicação converge para pronta sem reinício quando o banco volta
    (PRD-0001 · P7/P8/I4).
    """
    if prepare_schema(base):
        return

    logger.warning(
        "Boot prosseguindo sem schema preparado - /ready respondera 503 ate que o "
        "banco fique disponivel"
    )
    threading.Thread(
        target=_repair_loop,
        args=(base,),
        name="schema-repair",
        daemon=True,
    ).start()
