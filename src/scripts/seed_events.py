"""
Script standalone de semeadura da tabela `events` (PRD-0002).

Executado fora do ciclo de vida da aplicacao:

    cd src && python -m scripts.seed_events

Regra central: semeia SOMENTE com a tabela vazia. Havendo qualquer registro, e
no-op que encerra com sucesso (P2/R3). O script nunca cria nem altera schema —
tabela ausente e falha explicita, nao convite para criar (P10/I3, design D1).
"""

import sys
from collections import namedtuple
from datetime import datetime, timedelta, timezone

from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from core.database import SessionLocal, engine
from core.logging import get_logger, setup_logging
from core.settings import settings
from models.event import Event

logger = get_logger("seed_events")

TABELA = "events"

# Margem entre o instante da execucao e o evento mais antigo do catalogo.
#
# Sem ela, o evento de data original mais antiga receberia exatamente "agora" e
# ja estaria no passado quando a transacao fosse confirmada — I5 violada por
# alguns milissegundos (design D3).
MARGEM = timedelta(days=1)

EXIT_SUCESSO = 0
EXIT_FALHA = 1

DESFECHO_SEMEADO = "semeado"
DESFECHO_IGNORADO = "ignorado"

Resultado = namedtuple("Resultado", ["desfecho", "quantidade"])


class PreCondicaoNaoAtendida(Exception):
    """A tabela `events` nao existe. Pre-condicao do operador, nao do script."""


class BancoInalcancavel(Exception):
    """O banco nao respondeu. Distinta de PreCondicaoNaoAtendida por design (D2)."""


class FalhaNaSemeadura(Exception):
    """
    Erro de banco ja durante a insercao.

    Separada de BancoInalcancavel porque aqui a conexao existia: pode ser perda
    de conexao no meio do lote ou violacao de constraint. Em ambos os casos o
    rollback ja ocorreu e a tabela permanece vazia (P12/I6).
    """


# Catalogo fixo e hardcoded (R2/F7).
#
# ORIGEM: `api-requests.http`, na raiz do repositorio — os 10 POST de criacao de
# evento. A duplicacao e deliberada: R2 exige o catalogo dentro do script, e
# derivar do .http em tempo de execucao significaria parsear um formato de
# cliente REST para popular um banco (design D11).
#
# O campo `technologies` do arquivo original NAO e transportado: a tabela nao
# tem coluna correspondente, e carrega-lo aqui sugeriria um caminho de
# persistencia que nao existe (R4/F4).
#
# `data_original` nao e gravada como esta: serve de base para o deslocamento em
# bloco calculado por `calcular_datas` (D3).
CATALOGO = (
    {
        "title": "Workshop: Introdução ao FastAPI",
        "description": (
            "Aprenda a criar APIs REST modernas com FastAPI, incluindo documentação "
            "automática, validação de dados e deploy em produção."
        ),
        "location": "Centro de Convenções - São Paulo, SP",
        "data_original": datetime(2024, 2, 15, 19, 0, 0),
    },
    {
        "title": "Meetup React: Performance com Next.js 14",
        "description": (
            "Discussão sobre otimização de performance em aplicações React usando as "
            "novas funcionalidades do Next.js 14."
        ),
        "location": "Hub de Inovação - Rio de Janeiro, RJ",
        "data_original": datetime(2024, 2, 20, 18, 30, 0),
    },
    {
        "title": "DevOps Conference 2024: Kubernetes na Prática",
        "description": (
            "Evento focado em práticas DevOps modernas, com palestras sobre Kubernetes, "
            "CI/CD, monitoramento e observabilidade."
        ),
        "location": "Expo Center Norte - São Paulo, SP",
        "data_original": datetime(2024, 3, 5, 9, 0, 0),
    },
    {
        "title": "Hackathon Mobile: Apps para Sustentabilidade",
        "description": (
            "48 horas de desenvolvimento intensivo para criar aplicativos móveis que "
            "promovam sustentabilidade e consciência ambiental."
        ),
        "location": "Campus Universitário - Belo Horizonte, MG",
        "data_original": datetime(2024, 2, 25, 8, 0, 0),
    },
    {
        "title": "IA na Prática: Machine Learning com Python",
        "description": (
            "Como implementar soluções de Machine Learning em produção usando Python, "
            "scikit-learn e TensorFlow."
        ),
        "location": "Auditório Tech Hub - Brasília, DF",
        "data_original": datetime(2024, 3, 10, 14, 0, 0),
    },
    {
        "title": "AWS na Prática: Serverless com Lambda",
        "description": (
            "Workshop hands-on sobre desenvolvimento serverless na AWS usando Lambda, "
            "API Gateway e DynamoDB."
        ),
        "location": "Centro de Treinamento - Porto Alegre, RS",
        "data_original": datetime(2024, 3, 15, 10, 0, 0),
    },
    {
        "title": "PostgreSQL Avançado: Otimização e Performance",
        "description": (
            "Técnicas avançadas de otimização em PostgreSQL, incluindo índices, "
            "particionamento e análise de performance."
        ),
        "location": "Coworking Space - Florianópolis, SC",
        "data_original": datetime(2024, 2, 28, 19, 30, 0),
    },
    {
        "title": "Cybersecurity Summit: Proteção de APIs",
        "description": (
            "Estratégias para proteger APIs REST contra ataques comuns, incluindo "
            "autenticação, autorização e monitoramento."
        ),
        "location": "Centro Empresarial - Curitiba, PR",
        "data_original": datetime(2024, 3, 20, 13, 0, 0),
    },
    {
        "title": "Modern Frontend: Vue.js 3 + TypeScript",
        "description": (
            "Desenvolvimento de aplicações frontend modernas com Vue.js 3, "
            "Composition API e TypeScript."
        ),
        "location": "Innovation Lab - Salvador, BA",
        "data_original": datetime(2024, 4, 5, 15, 0, 0),
    },
    {
        "title": "Blockchain & Web3: Desenvolvimento de DApps",
        "description": (
            "Introdução ao desenvolvimento de aplicações descentralizadas (DApps) "
            "usando Solidity e frameworks Web3."
        ),
        "location": "Tech Park - Recife, PE",
        "data_original": datetime(2024, 4, 10, 11, 0, 0),
    },
)


def agora_utc():
    """
    Instante atual como datetime ingenuo em UTC.

    Ingenuo porque a coluna `Event.date` e `DateTime` sem fuso: misturar um
    datetime com tzinfo produziria comparacao incorreta na ordenacao por data
    que `event_service.get_events` aplica. A escolha e consistencia com o schema
    existente, nao opiniao sobre fuso (D4).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def calcular_datas(agora):
    """
    Desloca o catalogo inteiro para o futuro preservando os intervalos originais.

        data_semeada = agora + MARGEM + (data_original - data_original_mais_antiga)

    O deslocamento e o mesmo para todos, entao os intervalos entre eventos —
    que no arquivo original variam de ~5 a ~15 dias — sobrevivem intactos, e a
    ordem cronologica se mantem (D3/P6).

    `agora` e ingenuo em UTC, coerente com a coluna `DateTime` sem fuso e com o
    default do modelo `Event` (D4).
    """
    mais_antiga = min(item["data_original"] for item in CATALOGO)
    base = agora + MARGEM

    return [base + (item["data_original"] - mais_antiga) for item in CATALOGO]


def montar_eventos(agora):
    """
    Constroi os objetos ORM do catalogo.

    `edit_token` NAO e atribuido aqui de proposito: vem do default do modelo
    `Event`, que gera um uuid4 por instancia. Atribuir manualmente duplicaria a
    regra; inserir por SQL cru a perderia, porque o default e do ORM e nao do
    banco (D5/P7/I4).
    """
    return [
        Event(
            title=item["title"],
            description=item["description"],
            location=item["location"],
            date=data,
        )
        for item, data in zip(CATALOGO, calcular_datas(agora))
    ]


def descrever_destino():
    """
    Descreve o banco de destino sem credenciais.

    Semear o ambiente errado e o risco de maior consequencia da feature: R3
    protege bancos populados, mas um banco de producao vazio seria semeado sem
    reclamar. Logar o destino da ao operador a chance de reconhecer o alvo antes
    da escrita.
    """
    url = make_url(settings.DATABASE_URL)
    porta = f":{url.port}" if url.port else ""

    return f"{url.host or 'local'}{porta}/{url.database}"


def verificar_tabela():
    """
    Confirma a pre-condicao de schema (P10/I3).

    Nao cria nada. A distincao entre os dois modos de falha e deliberada: um
    banco fora do ar levanta erro do driver AQUI, na primeira operacao que toca
    o banco, antes de qualquer conclusao sobre a tabela. Sem essa separacao, um
    banco inalcancavel apareceria como "tabela nao encontrada" e mandaria o
    operador investigar migrations quando o problema e rede (D2/P11).
    """
    try:
        existe = inspect(engine).has_table(TABELA)
    except SQLAlchemyError as exc:
        raise BancoInalcancavel(
            f"Banco inalcancavel em {descrever_destino()}: {type(exc).__name__}: {exc}"
        ) from exc

    if not existe:
        raise PreCondicaoNaoAtendida(
            f"Pre-condicao nao atendida: a tabela '{TABELA}' nao existe em "
            f"{descrever_destino()}. Rode as migrations antes do seed - este script "
            f"nao cria nem altera schema."
        )


def tabela_vazia(session):
    """
    Responde "existe algum registro?" parando no primeiro (D7).

    COUNT(*) percorreria a tabela inteira para responder uma pergunta booleana.
    """
    return session.query(Event.id).limit(1).first() is None


def semear(agora=None):
    """
    Executa a semeadura.

    Retorna `Resultado`. Levanta `PreCondicaoNaoAtendida` ou `BancoInalcancavel`
    nas falhas previstas; qualquer outra excecao sobe apos o rollback.

    A insercao inteira vai em um unico commit: um erro no meio do lote desfaz
    tudo, e a tabela nunca fica parcialmente semeada (P12/I6).
    """
    agora = agora or agora_utc()

    verificar_tabela()

    session = SessionLocal()
    try:
        if not tabela_vazia(session):
            return Resultado(DESFECHO_IGNORADO, 0)

        logger.info(f"Tabela '{TABELA}' vazia - semeando em {descrever_destino()}")

        eventos = montar_eventos(agora)
        session.add_all(eventos)
        session.commit()

        return Resultado(DESFECHO_SEMEADO, len(eventos))
    except SQLAlchemyError as exc:
        session.rollback()
        raise FalhaNaSemeadura(
            f"Falha de banco durante a semeadura em {descrever_destino()} - "
            f"nenhum evento permanece: {type(exc).__name__}: {exc}"
        ) from exc
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main():
    """
    Ponto de entrada.

    O setup_logging aqui nao e cerimonia: `get_logger` devolve um filho de
    `encontros-tech`, que so ganha handler quando setup_logging roda — e quem
    faz isso hoje e o main.py da aplicacao. Sem esta chamada, um script rodando
    fora do processo Flask escreveria em um logger sem handler e as mensagens de
    desfecho exigidas por R6 sumiriam em silencio (D8).

    Codigo de saida: 0 para semeou E para no-op, 1 para falha. O no-op e
    desfecho esperado e correto — um pipeline nao pode falhar porque o ambiente
    ja estava semeado (D9/P2).
    """
    setup_logging(
        service_name=settings.SERVICE_NAME,
        log_level=settings.LOG_LEVEL,
        use_colors=settings.LOG_FORMAT == "colored",
    )

    try:
        resultado = semear()
    except PreCondicaoNaoAtendida as exc:
        logger.error(f"Semeadura falhou: {exc}")
        return EXIT_FALHA
    except (BancoInalcancavel, FalhaNaSemeadura) as exc:
        logger.error(f"Semeadura falhou: {exc}")
        return EXIT_FALHA
    except Exception as exc:
        logger.error(f"Semeadura falhou: {type(exc).__name__}: {exc}")
        return EXIT_FALHA

    if resultado.desfecho == DESFECHO_IGNORADO:
        logger.info(
            f"Semeadura ignorada: a tabela '{TABELA}' ja contem dados. "
            f"Nenhum evento inserido, alterado ou removido."
        )
    else:
        logger.info(f"Semeadura concluida: {resultado.quantidade} eventos inseridos")

    return EXIT_SUCESSO


if __name__ == "__main__":
    sys.exit(main())
