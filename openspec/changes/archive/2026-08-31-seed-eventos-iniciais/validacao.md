# Relatório de validação — `seed-eventos-iniciais`

**Data:** 2026-08-31 · **Ambiente:** Docker Compose local (`postgres:16-alpine` + imagem
`teclinux/encontros-tech-prd:1.0.0`) · **Suíte:** 77 passed (18 pré-existentes + 59 novos)

## Testes automatizados

```
docker run --rm -v "/$(pwd)":/w -w //w/src python:3.12-slim \
  sh -c "pip install -q -r requirements-dev.txt && python -m pytest tests/ -q"
→ 77 passed, 2 warnings (ambos pré-existentes: declarative_base e pydantic config)
```

Duas camadas, por necessidade (design D12): sessão mockada para fluxo, guardas e mensagens; SQLite em
memória para o que só existe no flush — geração do `edit_token`, rollback efetivo e idempotência real.

## Grupo 8 — Imagem e ambiente

| # | Verificação | Comando | Observado | Veredito |
|---|---|---|---|---|
| 8.1 | build da imagem | `docker compose build app` | `Built` | ✅ |
| 8.2 | `Dockerfile` intocado | `git status --porcelain Dockerfile` | sem modificação | ✅ |
| 8.3 | script **dentro da imagem** | `docker run --rm <img> ls -la /app/scripts/` | `seed_events.py` 12363 B | ✅ |
| 8.3 | importa sem bind mount | `docker run --rm <img> python -c "import scripts.seed_events"` | `import ok, catalogo = 10` | ✅ |
| 8.4 | usuário não-root (ADR 001) | `docker run --rm <img> whoami` | `app` | ✅ |
| 8.5 | ambiente limpo pronto | `docker compose up -d` + `/ready` | `200` | ✅ |
| 8.6 | schema criado, tabela vazia | `\dt events` + `count(*)` | tabela presente, `0` | ✅ |

> A verificação de empacotamento roda por `docker run`, não por `docker compose exec`: o compose monta
> `./src:/app`, então `exec` executaria o código do host e não provaria nada sobre a imagem.

## Grupo 9 — End-to-end (CA1–CA9)

| # | CA | Verificação | Observado | Veredito |
|---|---|---|---|---|
| 9.1 | CA1, CA9 | seed em tabela vazia | `exit=0`, `Semeadura concluida: 10 eventos inseridos`, destino `db:5432/encontros_tech` sem credenciais; `count=10` | ✅ |
| 9.2 | CA3, CA4, CA5 | campos, datas, tokens | `passado=0`, `sem_token=0`, `campo_vazio=0`, `tokens=10`, `total=10` | ✅ |
| 9.3 | — | espaçamento em bloco | deltas de `3d 11:30` a `16d 02:00` (não uniformes); 1ª data `2026-09-01` = execução + `MARGEM` de 1 dia | ✅ |
| 9.4 | CA6 | listagem via API JSON | `200` com `len = 10` — **desbloqueada** por `corrigir-serializacao-api-eventos` (6.2) | ✅ |
| 9.5 | CA6 | busca via API JSON | título `Python` → 1, descrição `deploy` → 1, local `Rio de Janeiro` → 1 — **desbloqueada** (6.3) | ✅ |
| 9.6 | CA6 | listagem via HTML | 5/5 títulos conferidos presentes no corpo | ✅ |
| 9.7 | CA5 | edição por token (HTML) | `/events/edit/<token>` → `200` com o evento renderizado | ✅ |
| 9.8 | CA2 | 2ª execução = no-op | `exit=0`, log `Semeadura ignorada`, conteúdo byte-a-byte idêntico (10 linhas) | ✅ |
| 9.9 | I2 | 3ª e 4ª execuções | ambas no-op, `count=10` | ✅ |
| 9.10 | P9 | 3 restarts do app | `ready=200` a cada um, `count=10` ao final | ✅ |
| 9.11 | P9, F3 | boot com tabela **vazia** | após `TRUNCATE` + restart: `ready=200`, `count=0` — o boot não semeia | ✅ |
| 9.12 | CA6 | app **desligada** | `docker compose ps -q app` → 0 containers; `docker compose run --rm app …` → `exit=0`, `count=10` | ✅ |
| 9.13 | CA6 | subir app depois | `ready=200`, 5/5 títulos no HTML | ✅ |
| 9.14 | CA7 | tabela ausente | `exit=1`, `Pre-condicao nao atendida: a tabela 'events' nao existe em db:5432/…`; tabela **continua ausente** | ✅ |
| 9.15 | CA8 | banco inalcançável | `exit=1`, `Banco inalcancavel em db:5432/…: OperationalError: could not translate host name "db"`; **6s**, não indefinido | ✅ |
| 9.17 | — | restauração | `down -v` + `up -d` → `ready=200`, `count=0` | ✅ |

**Mensagens distinguíveis (D2) confirmadas em execução real:** 9.14 diz "pré-condição não atendida /
tabela não existe"; 9.15 diz "banco inalcançável / could not translate host name". Um operador não
confunde os dois casos.

## Cobertura dos critérios de aceite do PRD-0002

| CA | Status | Onde |
|---|---|---|
| CA1 — semeia catálogo em tabela vazia | ✅ | 9.1 |
| CA2 — 2ª execução não altera nada | ✅ | 9.8, 9.9 |
| CA3 — campos preenchidos | ✅ | 9.2 |
| CA4 — datas no futuro | ✅ | 9.2, 9.3 |
| CA5 — token único e editável | ✅ | 9.2 (unicidade), 9.7 (edição via HTML e via API) |
| CA6 — app desligada, depois lista | ✅ | 9.12, 9.13, 9.6 via HTML; 9.4/9.5 via API JSON |
| CA7 — schema ausente falha | ✅ | 9.14 |
| CA8 — banco inalcançável falha | ✅ | 9.15 |
| CA9 — log deixa o desfecho claro | ✅ | 9.1, 9.8, 9.14, 9.15 |

## Bloqueio conhecido — bug pré-existente na API JSON · **RESOLVIDO**

> **Situação em 2026-08-31:** corrigido pela change `corrigir-serializacao-api-eventos`. As tarefas
> 9.4 e 9.5 foram executadas e passaram (ver `openspec/changes/corrigir-serializacao-api-eventos/validacao.md`,
> tasks 6.2 e 6.3). O relato abaixo fica como registro do que foi observado durante esta validação.
>
> Um detalhe do diagnóstico original se mostrou incompleto: a gravação sem resposta afetava também
> o `PUT`, não só o `POST` — o `commit` acontece dentro do service nos dois caminhos.

`src/routers/api_router.py` chama `model_dump()` sobre objetos **ORM** devolvidos pela camada de
service, mas `model_dump()` pertence ao schema Pydantic que o módulo importa e nunca usa para
converter. Os 4 endpoints da API são afetados (`POST /`, `GET /`, `GET /by-token/<t>`,
`PUT /by-token/<t>`).

**Independente desta mudança:**

- `api_router.py` está intocado — é a versão commitada.
- O `POST` falha igualmente, ou seja, o fluxo manual do `api-requests.http` descrito no PRD-0002 como
  "único meio de popular eventos hoje" **já não funciona**.
- Efeito colateral observado: o `POST` **grava a linha** e só depois estoura o 500 (contagem foi de 10
  para 11 num teste), então o erro esconde uma escrita bem-sucedida.
- A camada HTML (`page_router`) não passa por esse caminho e funciona normalmente.

**Encaminhamento:** change próprio, fora do escopo aditivo declarado no `proposal.md`. A correção é
pequena — converter com `Event.model_validate(obj)` antes de `model_dump()` nos 4 pontos — mas mexe na
superfície da API, o que muda o blast radius desta mudança.
**Feito:** change `corrigir-serializacao-api-eventos`, que além da conversão fixou o formato de data
em ISO 8601 e separou a falha de conversão (500) do payload inválido do cliente (400).

**Impacto no seed:** nenhum. A semeadura grava corretamente; o que falha é a leitura por um caminho
que já estava quebrado antes.
