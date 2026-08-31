# Tasks — Containerização Docker

## 1. Preparação do contexto de build

- [x] 1.1 Criar `.dockerignore` na raiz, excluindo no mínimo `.env`, `.git/`, `__pycache__/`,
      `.venv/`, `.pytest_cache/`, `docs/`, `openspec/` e as pastas de agente
      (`.agent/`, `.claude/`, `.codex/`, `.cursor/`, `.opencode/`)
- [x] 1.2 Confirmar que `.env` continua ignorado pelo Git **e** pelo Docker (hoje só pelo Git)

## 2. Split de dependências

- [x] 2.1 Remover `pytest==8.3.4` de `src/requirements.txt`
- [x] 2.2 Criar `src/requirements-dev.txt` referenciando o de runtime (`-r requirements.txt`) e
      acrescentando as dependências de teste
- [x] 2.3 Verificar que `pytest` ainda roda no host após o split (host local é Python 3.14,
      sem wheel `psycopg2-binary`; validado via container `python:3.12-slim` com
      `requirements-dev.txt` — 7 passed)

## 3. Configuração do Gunicorn

- [x] 3.1 Criar `gunicorn.conf.py` na raiz, com `bind`, `workers` e nível de log lidos de env
- [x] 3.2 Configurar a recarga automática por env, usando `reload_engine = "poll"` (ver D4)
- [x] 3.3 Implementar o hook `child_exit` para marcar o worker encerrado no registry multiproc
- [x] 3.4 Garantir que `PROMETHEUS_MULTIPROC_DIR` esteja definida e o diretório limpo antes do
      início dos workers

## 4. Métricas multiproc na aplicação

- [x] 4.1 Ajustar `src/main.py` para usar o registry multiproc em vez de `PrometheusMetrics(app)`
      com o registry padrão
- [x] 4.2 Assegurar que a variável de ambiente seja lida antes do import do cliente Prometheus
- [x] 4.3 Manter a métrica `app_info` e o middleware de logging funcionando após a mudança

## 5. Dockerfile multi-stage

- [x] 5.1 Estágio `builder` sobre `python:3.12-slim` instalando `src/requirements.txt`
- [x] 5.2 Estágio final sobre `python:3.12-slim` recebendo apenas o runtime, sem cache do pip
- [x] 5.3 Criar usuário não-root e definir `USER`; garantir permissão de escrita no diretório
      multiproc
- [x] 5.4 `WORKDIR` recebendo o **conteúdo** de `src/` (imports são planos — ver D7); comando
      `gunicorn main:app` via `gunicorn.conf.py`
- [x] 5.5 Expor a porta da aplicação

## 6. Docker Compose de desenvolvimento

- [x] 6.1 Serviço `db` (PostgreSQL) com volume nomeado e healthcheck `pg_isready`, consumindo
      `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` (já previstos em `.env.exemple`)
- [x] 6.2 Serviço `app` a partir da mesma imagem, com `depends_on: condition: service_healthy`
- [x] 6.3 Bind mount de `./src` sobre o `WORKDIR`, com recarga automática habilitada por env
- [x] 6.4 Ajustar `DATABASE_URL` do ambiente Compose para apontar ao host `db` (o `.env.exemple`
      hoje aponta para `localhost`)
- [x] 6.5 **Não** definir healthcheck para o serviço `app` — `/health` e `/ready` ainda não
      existem no código (PRD-0001 não implementado)

## 7. Documentação

- [x] 7.1 Corrigir a linha 11 do `docs/trd.md`: base explícita `python:3.12-slim` em vez de
      "a mesma versão usada localmente"
- [x] 7.2 Registrar no TRD a dívida remanescente: `create_all` no boot continua podendo derrubar
      o processo em produção; o `depends_on` protege apenas o ambiente de desenvolvimento
- [x] 7.3 Atualizar o `README.md` com o fluxo de subida via `docker compose up`
- [x] 7.4 Atualizar `.env.exemple` se novas variáveis forem introduzidas (workers, reload,
      diretório multiproc)

## 8. Verificação

- [x] 8.1 `docker compose up` sobe banco e aplicação, e a listagem de eventos responde em `/`
- [x] 8.2 Confirmar que o processo dentro do container **não** roda como root
- [x] 8.3 Alterar um arquivo em `src/` no host e confirmar que o Gunicorn recarrega
- [x] 8.4 Com mais de um worker, consultar `/metrics` repetidamente e confirmar valores
      agregados e estáveis (não variando conforme o worker que atendeu)
- [x] 8.5 Derrubar o `db` e subir de novo, confirmando o comportamento esperado do `depends_on`
- [x] 8.6 Inspecionar a imagem final: sem `pytest`, sem `.env`, sem cache do pip
