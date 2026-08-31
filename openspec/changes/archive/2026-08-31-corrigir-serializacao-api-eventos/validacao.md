# Relatório de validação — `corrigir-serializacao-api-eventos`

**Data:** 2026-08-31 · **Ambiente:** Docker Compose local (`postgres:16-alpine` + imagem
`teclinux/encontros-tech-prd:1.0.0`) · **Suíte:** 105 passed (77 pré-existentes + 28 novos)

## Estado de partida (grupo 1) — o defeito reproduzido

| # | Verificação | Observado | Veredito |
|---|---|---|---|
| 1.2 | `GET /api/events/` | `500` — `'Event' object has no attribute 'model_dump'` no log | ⛔ defeito |
| 1.2 | `GET /api/events/?search=…` | `500` (mesmo handler) | ⛔ defeito |
| 1.2 | `GET /api/events/by-token/<t>` | `500` | ⛔ defeito |
| 1.2 | `PUT /api/events/by-token/<t>` | `500` | ⛔ defeito |
| 1.3 | gravação-fantasma do `POST` | `http=500`, contagem **10 → 11** | ⛔ defeito |
| 1.4 | teste de regressão escrito | 4 failed, com o erro exato de produção | ✅ captura o defeito |

> **Achado além do previsto no `design.md` (D5):** o `PUT` **também** gravava antes de estourar. O
> teste de 1.2 alterou o evento `id=1` para os valores enviados (`title='t'`, `location='l'`) e
> devolveu `500`. A gravação-fantasma não era exclusiva do `POST` — o `commit` acontece dentro do
> service nos dois caminhos, e o `AttributeError` vinha depois em ambos. A correção fecha os dois
> pelo mesmo motivo; a spec já cobria isso pela invariante "escrita bem-sucedida não é reportada
> como erro", que não distingue verbo.

## Testes automatizados

```
docker run --rm -v "/$(pwd)":/w -w //w/src python:3.12-slim \
  sh -c "pip install -q -r requirements-dev.txt && python -m pytest tests/ -q"
→ 105 passed, 2 warnings (ambos pré-existentes: declarative_base e pydantic config)
```

Os 4 testes de regressão (`-k regressao`) falham na versão anterior à correção e passam na
corrigida — é o critério que distingue "teste que cobre o defeito" de "teste que apenas passa".
O dublê do service devolve `SimpleNamespace`, que **não** tem `model_dump`, como o ORM: um mock
genérico (`MagicMock`) responderia ao método e esconderia exatamente o que está sob teste.

## Grupo 6 — End-to-end em containers

| # | Verificação | Comando / observado | Veredito |
|---|---|---|---|
| 6.1 | build e ambiente pronto | `docker compose build app` + `up -d` → `/ready` = `200` | ✅ |
| 6.2 | **listagem JSON (desbloqueia 9.4 do seed)** | `GET /api/events/` → `200`, `len = 10` | ✅ |
| 6.3 | **busca JSON (desbloqueia 9.5 do seed)** | por título (`Python` → 1), por **descrição** (`deploy` → 1, termo ausente do título), por **local** (`Rio de Janeiro` → 1, ausente de título e descrição), com acento (`Introdução` → 2) | ✅ |
| 6.4 | `date` em ISO 8601 (D2) | `2026-09-01T01:15:41.944089`; ocorrências de `GMT` no corpo: **0** | ✅ |
| 6.5 | ciclo completo de escrita | `POST` → `200` com `id=11` e token; `GET /by-token/<t>` recupera o mesmo `id`; `PUT` → `200` com `title`/`location`/`date` novos e `id`/`edit_token` **estáveis** | ✅ |
| 6.6 | fim da gravação-fantasma (D5) | `POST` válido → `http=200`, contagem `11 → 12` (contra `http=500`, `10 → 11` em 1.3) | ✅ |
| 6.6b | payload inválido não grava | `http=400`, contagem `12 → 12` | ✅ |
| 6.7 | **`api-requests.http` volta a funcionar** | ambiente limpo (`down -v`), 10 blocos `POST` extraídos do arquivo e disparados: **10/10 → `200`**; `GET /api/events/` → `len = 10` | ✅ |
| 6.8 | `404` token inexistente | `GET` e `PUT` por token inexistente → `404`, não `500` | ✅ |
| 6.8 | `400` payload inválido | sem `title` → `400`; `date` irreconhecível → `400` | ✅ |
| 6.8 | `500` banco parado, sem vazar | `docker compose stop db` → `500`; ocorrências de senha/URL/`traceback` no corpo: **0** | ✅ |
| 6.9 | caminho HTML sem regressão | home: 5/5 títulos semeados presentes; `GET /events/edit/<token>` → `200` renderizando o evento | ✅ |
| 6.11 | restauração | `down -v` + `up -d` → `/ready` = `200`, `count = 0` | ✅ |

### Duas observações de método

**A busca por termo acentuado devolveu `0` numa primeira medição.** Investigado antes de reportar:
com percent-encoding UTF-8 explícito (`?search=Introdu%C3%A7%C3%A3o`) o mesmo termo devolve **2**
eventos. O `0` vinha do `--data-urlencode` do `curl` neste shell, não da aplicação. A API trata
acentos corretamente.

**A home devolveu `0` títulos numa primeira medição de 6.9.** Também investigado: a medição rodou
logo após o replay do `api-requests.http`, cujos eventos têm datas de **2024** — e a home lista
apenas eventos futuros. É exatamente o problema que o PRD-0002 descreve como motivação do seed, não
uma regressão desta mudança. Refeita com o catálogo semeado (datas futuras), a home mostra 5/5.

## Cobertura dos cenários da spec

19 cenários em `specs/api-eventos-json/spec.md`, 25 funções de teste (várias parametrizadas).

| Requisito | Cenários | Onde é verificado |
|---|---|---|
| Corpo de resposta serializável | 5 | testes `listagem`, `lista_vazia`, `busca`, `por_token` + os 4 de `regressao` |
| Escrita bem-sucedida reportada como sucesso | 4 | testes `criacao`, `atualizacao`; **e2e 6.6** (gravação-fantasma) e **6.7** (`api-requests.http`) — dependem de banco real |
| Formato de data estável | 2 | `data_iso_8601_e_nao_rfc_822`, `data_iso_faz_o_ciclo_fechar`; e2e 6.4 |
| Desfechos de falha distinguíveis | 4 | `nao_encontrado`, `payload_invalido`, `erro_interno_*`, `conversao_invalida_*`; e2e 6.8 |
| `technologies` coerente | 2 | `technologies_vazio_na_leitura`, `technologies_ecoa_na_escrita_sem_persistir`; e2e 6.5 (POST ecoou `["Python"]`) |
| Caminho HTML preservado | 2 | **e2e 6.9** — o `page_router` renderiza templates, não JSON; só é verificável com a aplicação no ar |

Nenhum cenário sem cobertura. Os quatro verificáveis apenas end-to-end estão nomeados acima com a
razão: dependem de persistência real ou de renderização de template.

## Efeito sobre o change `seed-eventos-iniciais`

As tarefas **9.4** e **9.5**, bloqueadas por este defeito, foram verificadas em 6.2 e 6.3 e estão
desbloqueadas. O **CA6 do PRD-0002** deixa de ser "✅ parcial" — a leitura pela aplicação agora é
demonstrável tanto pelo caminho HTML quanto pelo JSON. O caminho equivalente da API para o CA5
(`/api/events/by-token/<token>`), também citado como bloqueado, responde `200` (6.5).

## Escopo confirmado

- Único arquivo de produção modificado: `src/routers/api_router.py`.
- Novo: `src/tests/routers/test_api_router.py`.
- `Dockerfile`, `docker-compose.yml`, `k8s/`, `main.py`, `schemas/`, `services/`, `models/` e
  `page_router.py` **intocados**. Nenhuma dependência nova. Nenhum ADR reaberto.
