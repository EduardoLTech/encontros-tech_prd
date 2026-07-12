# TRD — Encontros Tech

> Documento técnico global do projeto. Granularidade baixa: cobre o que é global e estável.
> Regras finas ficam em ADRs.

## Stack

| Dimensão | Valor |
|---|---|
| Linguagem principal | Python |
| Runtime/plataforma | Gunicorn como servidor de aplicação **em produção e em desenvolvimento** (dev espelha produção, com recarga automática + montagem do código-fonte); execução containerizada em Docker sobre imagem base oficial slim do Python na mesma versão usada localmente, como usuário **não-root** (ADR 001) |
| Framework principal | Flask 3.0.0 |
| Banco de dados | PostgreSQL (via SQLAlchemy 2.0.43 + psycopg2-binary) |
| Ferramentas de build | Build de imagem Docker **multi-stage**: estágio de build compila as dependências (inclusive sem artefatos pré-compilados), estágio final recebe só o runtime; separa dependências de runtime das de teste (ADR 001) |
| Gerenciador de pacotes | pip (`src/requirements.txt`) |

## Arquitetura

### Padrão arquitetural
Camadas: router (blueprints Flask) → service (`event_service`) → model (SQLAlchemy ORM). Os routers tratam HTTP e validação via schemas Pydantic; a lógica de acesso a dados fica isolada na camada de service.

A aplicação é **stateless**: não mantém estado no processo/nó — o estado persistente reside integralmente no banco externo (Amazon RDS) —, o que permite replicá-la horizontalmente como recurso descartável (ADR 002). O empacotamento é feito como **imagem única de container** (Dockerfile multi-stage na raiz do projeto), executada sob Gunicorn; um `docker-compose.yml` orquestra essa mesma imagem junto de um serviço PostgreSQL para compor o ambiente de desenvolvimento, deliberadamente espelhando produção (ADR 001).

### Estrutura de pastas dominante
```
src/
├── core/        # configurações, engine/sessão de banco, logging
├── models/      # modelos SQLAlchemy (ORM)
├── schemas/     # schemas Pydantic (validação/serialização)
├── services/    # lógica de negócio e acesso a dados
├── routers/     # blueprints Flask (API e páginas)
├── templates/   # templates Jinja2 (HTML)
├── static/      # assets estáticos (css, js)
└── tests/       # testes com pytest
```

### Módulos / camadas principais

| Módulo | Responsabilidade |
|---|---|
| `core/settings.py` | Configuração via variáveis de ambiente (Pydantic Settings) |
| `core/database.py` | Engine SQLAlchemy, `SessionLocal` e context manager `get_db` |
| `core/logging.py` | Setup de logging, formatter colorido e helpers de log |
| `models/event.py` | Modelo ORM `Event` |
| `schemas/event.py` | Schemas Pydantic de entrada/saída de evento |
| `services/event_service.py` | CRUD de eventos e regras de negócio |
| `routers/api_router.py` | Endpoints REST JSON (`/api/events`) |
| `routers/page_router.py` | Páginas HTML e formulários |
| `main.py` | Criação do app Flask, registro de blueprints, métricas e middleware |

### Rotas

**API (prefixo `/api/events`)**

| Método | Rota | Handler |
|---|---|---|
| POST | `/api/events/` | `api_router.create_event` |
| GET | `/api/events/` | `api_router.read_events` |
| GET | `/api/events/by-token/<edit_token>` | `api_router.get_event_by_token` |
| PUT | `/api/events/by-token/<edit_token>` | `api_router.update_event` |

**Páginas**

| Método | Rota | Handler |
|---|---|---|
| GET | `/` | `page_router.list_events_page` |
| GET | `/events/new` | `page_router.new_event_page` |
| GET | `/events/edit/<edit_token>` | `page_router.edit_event_page` |
| GET | `/events/<int:event_id>` | `page_router.event_detail_page` |
| POST | `/events/` | `page_router.create_event_form` |
| POST | `/events/edit/<edit_token>` | `page_router.update_event_form` |

### Modelo de dados

**events**

| Coluna | Tipo | Constraints/Default |
|---|---|---|
| id | Integer | primary key, index |
| title | String | index |
| description | Text | — |
| date | DateTime | default `datetime.utcnow` |
| location | String | — |
| edit_token | String | unique, index, default `uuid4()` |

> Schema criado por `create_all` na inicialização, sem ferramenta de migração. Com a escala horizontal em múltiplas réplicas (ADR 002), a criação no boot vira **corrida entre réplicas** — dívida conhecida registrada nas ADRs 001/002, ainda sem decisão.

## Requisitos Não-Funcionais

| Dimensão | Requisito |
|---|---|
| Performance | Acesso ao banco cross-AZ entre nós EKS e primário RDS com latência desprezível (~1–2 ms) e custo mínimo de transferência entre AZs (ADR 002). Demais metas: não definido |
| Disponibilidade/SLA | HA na camada de aplicação: múltiplas réplicas de pod distribuídas por **3 AZs** (spread via `topologySpreadConstraints`/anti-affinity), sobreviventes à perda de um nó ou de uma AZ. Camada de dados em **Amazon RDS Multi-AZ**, standby síncrono e **failover automático** (primário e standby em AZs distintas). Durante o failover, a indisponibilidade transitória do banco é absorvida pelo contrato de readiness do PRD Health & Readiness: `/ready` → 503 retira a instância da rotação sem reiniciá-la, readmitindo-a ao voltar 200. SLA numérico: não definido (ADR 002) |
| Escalabilidade | Escala horizontal na **camada de pod** (múltiplas réplicas + HPA), aproveitando a natureza stateless da aplicação; execução em **Amazon EKS** com **Managed Node Groups** `t3.small` (x86), mínimo de **1 nó por AZ** em 3 AZs. Sob empilhamento de réplicas, o caminho é adicionar nós (escala horizontal), não verticalizar — os 2 GB do `t3.small` são partilhados entre overhead do EKS e os pods. Escalar a aplicação **não** escala o banco: o RDS tem primário único legível, que é o teto de throughput de dados; mais réplicas × workers Gunicorn pressionam o `max_connections` do RDS — mitigação por pool de conexões (ex.: pgbouncer) pendente e fora do escopo das ADRs. Autoscaling de nós (Cluster Autoscaler/Karpenter) ainda não decidido. Mantém-se o suporte a multiprocessing via Gunicorn, com métricas Prometheus em diretório multiproc (`PROMETHEUS_MULTIPROC_DIR`) (ADR 002) |
| Segurança | Container executa como **usuário não-root**, reduzindo a superfície de ataque (ADR 001). Conectividade ao RDS em subnets privadas, com Security Group liberando os nós do EKS na porta 5432 — premissa de rede a detalhar no material de deploy (ADR 002). **Dívida conhecida (não endereçada pelas ADRs):** segredo de aplicação fixado no código-fonte. Demais controles: não definido |
| Observabilidade | Logging estruturado em stdout (nível configurável via `LOG_LEVEL`) e métricas Prometheus expostas via `prometheus-flask-exporter` |

## Dependências Externas

| Serviço / Sistema | Tipo | Constraint relevante | Dono |
|---|---|---|---|
| PostgreSQL / Amazon RDS | Banco relacional gerenciado | Prod: RDS **Multi-AZ**, standby síncrono não-legível, failover automático, acesso cross-AZ (~1–2 ms) na 5432. Dev: PostgreSQL em container via Docker Compose. Conexão via `DATABASE_URL` (psycopg2). Primário único legível = teto de throughput; `max_connections` sob pressão com réplicas (pool pendente) | Time DevOps |
| Amazon EKS | Plataforma de execução (Kubernetes) | Cluster novo dedicado, 3 AZs, Managed Node Groups `t3.small` x86 (≥1 nó/AZ); control plane e ciclo de vida dos nós sob operação própria | Time DevOps |
| Docker Hub | Registry de imagens (privado) | Distribuição da imagem única; **publicação manual**; tag versionada + tag corrente para rastreabilidade; k8s exige credencial de pull | Time DevOps |
| Prometheus | Sistema de métricas | Coleta de métricas expostas pela aplicação | Não definido |

## Padrões

### Testes

| Item | Valor |
|---|---|
| Framework | pytest 8.3.4 |
| Comando completo | `pytest` (com `pythonpath = .` em `pytest.ini`) |
| Cobertura mínima | Não definido |
| Estratégia | Testes unitários da camada de service com mocks (`unittest.mock.MagicMock`) |

### Estilo de código
- Linter: Não aplicável
- Formatter: Não aplicável
- Convenções de nomenclatura: Não aplicável

### Error handling
Nas camadas de router, blocos `try/except` capturam `EventNotFoundError` (retornando 404 na API / template `not_found` nas páginas), `ValueError` de validação (400 na API / `flash` + redirect nas páginas) e `Exception` genérica (500 / mensagem de erro). Na camada de service, exceções são logadas, revertidas com `db.rollback()` quando aplicável e relançadas.

### Logging
- Formato: `%(asctime)s | %(levelname)s | %(name)s | %(funcName)s:%(lineno)d | %(message)s`, com cores ANSI opcionais (`LOG_FORMAT=colored`)
- Nível padrão: `INFO` (ou `DEBUG` quando `DEBUG=true`)
- Biblioteca: módulo `logging` da biblioteca padrão

### Autenticação / autorização
Não há autenticação de usuário. A edição de um evento é controlada por um `edit_token` (UUID) por evento, usado para acessar as rotas de edição.

## Decisões Globais (ADRs)

| # | Título | Data | Status | Link |
|---|---|---|---|---|
| 001 | Adotar containerização Docker para empacotamento e ambiente de desenvolvimento | 2026-07-12 | aceito | [ADR 001](./adrs/001-containerizacao-docker.md) |
| 002 | Executar a aplicação em Amazon EKS (Managed Node Groups) com banco em Amazon RDS Multi-AZ | 2026-07-12 | aceito | [ADR 002](./adrs/002-plataforma-execucao-eks-rds.md) |
