# Containerização Docker: imagem única multi-stage + Compose de desenvolvimento

## Why

A ADR 001 (aceita, 2026-07-12) decidiu substituir o modelo Systemd por containerização Docker,
com **imagem única production-grade** e um **Docker Compose** que orquestra essa mesma imagem
junto de um PostgreSQL para compor o ambiente de desenvolvimento. O TRD já descreve esse
empacotamento como se existisse — mas o repositório **não tem Dockerfile, docker-compose.yml
nem .dockerignore**. Esta mudança executa a decisão da ADR 001.

Ao cruzar a decisão com o código, três lacunas apareceram e entram no escopo:

1. `src/requirements.txt` mistura runtime e teste (`pytest`), contrariando o TRD
   ("separa dependências de runtime das de teste").
2. `src/main.py:35` usa `PrometheusMetrics(app)` com o registry padrão. Sob Gunicorn
   multi-worker, `/metrics` devolve os números de **um** worker sorteado — o TRD promete
   métricas em diretório multiproc (`PROMETHEUS_MULTIPROC_DIR`), o que hoje não acontece.
3. O TRD (linha 11) fixa a base como "a mesma versão usada localmente" (Python 3.14.3).
   Adotamos **`python:3.12-slim`** explícito; a frase do TRD passa a ser falsa e precisa
   ser corrigida.

## What Changes

- **Dockerfile multi-stage** na raiz: estágio `builder` instala dependências, estágio final
  recebe só o runtime, sobre `python:3.12-slim`, executando como **usuário não-root**.
- **`gunicorn.conf.py`** versionado, com valores lidos de variáveis de ambiente — fonte única
  de configuração do servidor para dev e produção (evita flags duplicadas entre Dockerfile e Compose).
- **`docker-compose.yml`** com serviços `app` e `db`, bind mount de `./src`, recarga automática
  via `--reload` com `--reload-engine=poll`, e `depends_on: condition: service_healthy`.
- **`.dockerignore`** — hoje inexistente; sem ele `.env`, `.git/`, `.venv` e as pastas de
  agente entram no contexto de build (o `.env` na imagem é o item grave).
- **Split de dependências**: `src/requirements.txt` (runtime) + `src/requirements-dev.txt` (teste).
- **Correção das métricas multiproc**: `main.py` passa a usar o registry multiproc e
  `gunicorn.conf.py` ganha o hook `child_exit`; o diretório multiproc fica gravável pelo
  usuário não-root e é limpo a cada start.
- **Atualização do TRD**: linha 11 (versão base explícita) e registro das dívidas remanescentes.

## Non-Goals

Ficam **explicitamente fora**, para não vazar escopo:

- **`SECRET_KEY` fixada em `src/main.py:25`** — registrada como dívida na própria ADR 001,
  sem decisão. Não é endereçada aqui.
- **Ferramenta de migração de schema (Alembic)** — mesma situação; `create_all` no boot
  permanece.
- **Rotas `/health` e `/ready`** — o PRD-0001 ainda não foi implementado; não existem no
  código. O Compose terá healthcheck no `db` (`pg_isready`), mas **não** no `app`, por não
  haver endpoint em que se apoiar.
- **Manifests Kubernetes e publicação no Docker Hub** — pertencem à ADR 002, em mudança própria.

## Impact

- **Affected specs:** `empacotamento-container` (novo), `observabilidade` (novo)
- **Affected code:**
  - novo: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `gunicorn.conf.py`,
    `src/requirements-dev.txt`
  - alterado: `src/requirements.txt`, `src/main.py`, `docs/trd.md`
- **Dívida conhecida que esta mudança NÃO remove:** em produção, `create_all` no boot
  (`src/main.py:21`) continua podendo derrubar o processo quando o banco está fora — o
  `depends_on` só protege o ambiente de desenvolvimento. Ver `design.md`.
