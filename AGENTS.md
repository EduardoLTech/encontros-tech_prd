# AGENTS.md

## Sobre o projeto

Encontros Tech: aplicação web Flask para cadastrar, listar e editar eventos de tecnologia, com API
JSON e páginas HTML sobre PostgreSQL. Toda mudança nasce de especificação: PRD, TRD, ADR e changes
do OpenSpec.

## Arquitetura e stack

- Python 3.12 (`python:3.12-slim`), Flask 3.0, SQLAlchemy 2.0 + psycopg2, Pydantic 2 e
  pydantic-settings, Jinja2, Gunicorn 21 com worker `gthread`, prometheus-flask-exporter.
  Versões fixadas em `src/requirements.txt`.
- PostgreSQL 16 (`postgres:16-alpine`), no devcontainer, no compose e no cluster.
- Camadas: router (blueprints Flask) → service → model (ORM). Schemas Pydantic validam a entrada
  e serializam a saída.
- Aplicação stateless: o estado vive só no Postgres.
- Dev: devcontainer em `.devcontainer/` (imagem própria com pytest, Postgres com volume próprio),
  operado pelos scripts de `scripts/`. O `docker-compose.yml` da raiz sobe a imagem de produção
  com reload e lê `.env`; não suba os dois juntos, ambos usam a porta 8000.
- Deploy manual, sem CI no repo: build e push de `teclinux/encontros-tech-prd:1.0.0` para o Docker
  Hub privado, depois `kubectl apply -f k8s/manifesto.yaml` (app + Postgres em StatefulSet). Alvo:
  Amazon EKS (ADR 002 e 003). Passo a passo em `README.md`, seção "Implantação em Kubernetes".
- Stack detalhada, rotas, modelo de dados, RNFs e dívidas: `docs/trd.md`.

## Estrutura do projeto

- `src/`: código da aplicação. É o `/app` da imagem de produção.
  - `core/`: settings, engine e sessão do banco, logging, preparo do schema.
  - `models/`, `schemas/`, `services/`, `routers/`: as camadas.
  - `scripts/`: scripts operacionais da aplicação (seed), rodados como módulo.
  - `templates/` e `static/`: páginas Jinja2 e assets.
  - `tests/`: pytest, espelhando os pacotes de `src/`.
- `scripts/`: operação do ambiente de dev (`up`, `start`, `test`, `exec`, `down`), em bash.
  Lógica comum em `scripts/_lib.sh`.
- `.devcontainer/`: `Dockerfile`, `docker-compose.yml` e `devcontainer.json`, só para dev.
- `docs/trd.md`, `docs/adrs/`, `docs/prds/`: design docs.
- `openspec/specs/`: specs vigentes por capacidade. `openspec/changes/`: changes em andamento;
  `openspec/changes/archive/` guarda as concluídas. Regras dos artefatos em `openspec/config.yaml`.
- `k8s/manifesto.yaml`: implantação inteira em um arquivo.
- `Dockerfile`, `docker-compose.yml`, `gunicorn.conf.py`: execução de produção.
- `api-requests.http`: requisições de exemplo para a API (REST Client).
- `.agent/`, `.codex/`, `.cursor/`, `.opencode/`: skills e comandos do OpenSpec por ferramenta,
  gerados pela CLI. `.claude/` tem o equivalente e fica fora do git.

## Comandos de build e teste

Tudo que executa a aplicação (servidor, testes, seed, psql, Python) roda dentro do devcontainer,
pelos scripts abaixo, a partir da raiz. Pré-requisitos: Docker no ar e o devcontainer CLI
(`npm install -g @devcontainers/cli`).

```bash
scripts/up.sh                  # sobe app + db; idempotente
scripts/start.sh               # inicia o Gunicorn com reload em http://localhost:8000
scripts/test.sh                # suíte completa, rodada a partir de src/
scripts/test.sh -k <trecho>    # argumentos extras vão para o pytest
scripts/exec.sh <comando>      # executa no container, na raiz do workspace
scripts/down.sh                # derruba; preserva o volume do banco de dev
```

Exemplos de `exec.sh` (para `cd`, `&&` e `|`, passe via `sh -c`):

```bash
scripts/exec.sh sh -c "cd src && python -m scripts.seed_events"
scripts/exec.sh psql postgresql://encontros_tech:encontros_tech@db:5432/encontros_tech
scripts/exec.sh tail -f /tmp/gunicorn.log
```

- Shell: bash. No Windows, use o Git Bash. No PowerShell, `bash` abre o WSL; chame o Git Bash:
  `& "C:/Program Files/Git/bin/bash.exe" scripts/up.sh`.
- Falha sai como `ERRO:` seguido de `Como corrigir:`. Siga a instrução antes de contornar o script.
- Fluxo de spec: `/opsx:explore`, `/opsx:propose`, `/opsx:apply`, `/opsx:archive`.
  Estado: `openspec list` e `openspec list --specs` (CLI no host).

## Convenções de código

- Um blueprint por arquivo em `src/routers/<nome>_router.py`, exposto como `bp` e registrado em
  `src/main.py`.
- Logger por módulo: `logger = get_logger("<modulo>")`, de `core.logging`.
- Router trata HTTP e mapeia exceções; service acessa dados, loga, faz `db.rollback()` e relança.
  Mapeamento de erros em `docs/trd.md`, seção "Error handling".
- Resposta da API sai do schema: `Event.model_validate(obj).model_dump(mode="json")`. Não
  serialize objeto ORM direto. Datas trafegam em ISO 8601 nos dois sentidos.
- Variável de configuração nova entra em `src/core/settings.py`, em `.env.exemple` e, se o
  container precisar, em `docker-compose.yml`, em `.devcontainer/docker-compose.yml` e no
  ConfigMap de `k8s/manifesto.yaml`.
- Comentários e docstrings em PT-BR explicam o porquê e citam a origem: predicado do PRD
  (`PRD-0001 · R1/I3`), decisão de design (`design D4`), change ou spec.
- Script operacional da aplicação fica em `src/scripts/` e roda como módulo
  (`python -m scripts.<nome>`), via `scripts/exec.sh`.
- Script de ambiente fica em `scripts/<nome>.sh`, carrega `_lib.sh` e reporta falha com
  `fail "<o que deu errado>" "<como corrigir>"`.
- Testes com pytest e `unittest.mock`. A docstring do módulo de teste cita a change e a spec
  cobertas.
- Nomes: `docs/prds/PRD-NNNN-<slug>.md`, `docs/adrs/NNN-<slug>.md`, changes em kebab-case,
  arquivadas com prefixo `AAAA-MM-DD-`.
- Não há linter nem formatter configurados.
- Não há padrão de mensagem de commit no histórico.

## Políticas e limites

- Não chame `devcontainer`, `docker compose` ou `docker exec` direto para operar a app, nem rode
  Python ou pytest no host: use `scripts/`. Faltou uma operação, estenda os scripts.
- Comando de validação de task nova do OpenSpec: `scripts/test.sh -k <trecho>`. As tasks
  arquivadas citam `cd src && python -m pytest`, fluxo anterior aos scripts.
- `start.sh` fala com o container sem TTY de propósito (`dc_run`): com PTY, o fim da sessão manda
  SIGHUP e mata o Gunicorn em segundo plano.
- Os `.sh` precisam de final de linha LF. O repo não tem `.gitattributes` que garanta isso.
- Não reabra ADR aceito e não reescreva o TRD por conta própria: referencie. O ADR 002 está
  superado pelo 003 na parte de banco.
- Proponha mudança de comportamento como change do OpenSpec. Cada artefato segue as regras de
  `openspec/config.yaml` (rollback, blast radius, cenários de falha, comando de validação por task).
- Não faça o boot depender do banco nem de configuração válida: a app sobe com o Postgres fora
  (PRD-0001 · P7/I4). Por isso os dois composes usam `condition: service_started`.
- `/health` nunca toca o banco. `/health` e `/ready` ficam fora das métricas e do log de requisição.
- Mantenha `periodSeconds 10 > timeoutSeconds 6 > READINESS_DB_TIMEOUT_SECONDS 5` na
  readinessProbe. Mudou um, revise os outros.
- Não troque o worker `gthread` do Gunicorn por `sync`.
- `gunicorn.conf.py` vai para `/etc` na imagem de produção, fora de `/app`: o bind mount do
  compose da raiz o esconderia.
- Dependência de teste só em `src/requirements-dev.txt`. A imagem de runtime não leva pytest.
- O seed só semeia tabela vazia, não cria schema e nunca roda no boot.
- Não versione `.env` nem segredos. Os três Secrets do Kubernetes são criados à mão no namespace;
  a lista está no cabeçalho de `k8s/manifesto.yaml`.
- A tag `1.0.0` é sobrescrita a cada `docker compose build` local. Antes de publicar, rode
  `docker compose build --no-cache app`.
- Dívidas conhecidas, não repita o padrão: `SECRET_KEY` fixa em `src/main.py` e schema por
  `create_all` no boot, sem ferramenta de migração. Detalhe em `docs/trd.md`.
- `technologies` existe no contrato da API com default `[]`, mas não é persistido.
- Use `.env.exemple` da raiz. `src/.env.example` está defasado.
- `README.md` está em UTF-16 LE. Preserve a codificação ao editar.
