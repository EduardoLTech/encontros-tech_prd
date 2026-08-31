# Correção da serialização da API JSON de eventos

## Why

Os quatro endpoints de `/api/events` respondem **500** hoje. `src/routers/api_router.py` chama
`model_dump()` sobre os objetos **ORM** (`models.event.Event`) devolvidos pelo `event_service` —
mas `model_dump()` pertence ao schema Pydantic `schemas.event.Event`, que o módulo importa e nunca
usa para converter. O erro observado é `'Event' object has no attribute 'model_dump'`.

O impacto é maior do que "um endpoint quebrado":

- O `POST /api/events/` **grava a linha no banco** e só depois estoura o 500 (contagem observada
  indo de 10 para 11 numa validação). O erro esconde uma escrita bem-sucedida, e um cliente que
  reenvia por achar que falhou duplica o evento.
- O fluxo manual do `api-requests.http` — descrito no PRD-0002 como "único meio de popular eventos
  hoje" — **já não funciona**.
- As tarefas 9.4 e 9.5 do change `seed-eventos-iniciais` estão bloqueadas por esta causa (ver
  `openspec/changes/seed-eventos-iniciais/validacao.md`, seção "Bloqueio conhecido"). O CA6 do
  PRD-0002 só pôde ser demonstrado pelo caminho HTML.

A camada HTML (`page_router`) não passa por esse caminho e funciona normalmente — o defeito é
exclusivo da fronteira de serialização da API JSON.

## What Changes

**Correção na fronteira router → JSON**

- Converter o objeto ORM para o schema Pydantic `schemas.event.Event` (`model_validate`, que já
  tem `from_attributes = True`) **antes** de serializar, nos quatro pontos: `POST /`, `GET /`,
  `GET /by-token/<token>` e `PUT /by-token/<token>`.
- A conversão passa a ser responsabilidade explícita do router, mantendo a arquitetura em camadas
  do TRD (router → service → model): o service continua devolvendo ORM, o router continua sendo o
  único lugar que conhece o formato de saída.
- **Formato de data fixado como ISO 8601 (UTC)**, e não o RFC 822 que o `jsonify` do Flask aplica
  por padrão a `datetime`. É o formato que o próprio `api-requests.http` envia no `POST` — hoje a
  API aceitaria um formato e devolveria outro. Ver `design.md` (D2).
- `technologies` continua **não persistido** (a coluna não existe no modelo). O schema já define
  `technologies: List[str] = []`, então a leitura devolve lista vazia e a escrita ecoa o que veio
  na requisição, exatamente como o comportamento atual pretendia. Nenhuma mudança de schema de
  banco.

**Não muda**

- Nenhuma rota, nenhum verbo, nenhum nome de campo, nenhum código de status de sucesso ou de erro.
- Nenhum service, nenhum model, nenhuma migração, nenhuma dependência nova.
- Nenhum manifesto Kubernetes, `Dockerfile`, ConfigMap ou variável de ambiente.

**BREAKING (formalmente):** o corpo de resposta muda de "erro 500" para "JSON do evento", e o
campo `date` passa a sair em ISO 8601. Como nenhum consumidor pode depender do comportamento atual
— ele é um 500 —, o impacto prático em clientes é nulo.

**Testes**

- Novos testes em `src/tests/routers/test_api_router.py`, no estilo dos existentes
  (`unittest.mock` sobre o service, sem banco real), cobrindo os quatro endpoints no caminho feliz
  e nos de falha (404 por token inexistente, 400 por payload inválido, 500 por erro do service),
  além de uma regressão que falha se um objeto ORM voltar a ser serializado direto.

## Capabilities

### New Capabilities

- `api-eventos-json`: contrato observável da API JSON de eventos — forma do corpo de resposta de
  cada endpoint (campos presentes, tipos, formato de data), códigos de status por desfecho
  (sucesso, não encontrado, payload inválido, erro interno), e a invariante de que uma escrita
  bem-sucedida nunca é reportada como erro ao cliente.

### Modified Capabilities

Nenhuma. Não há spec existente cobrindo a API de eventos — `openspec/specs/` hoje tem
`empacotamento-container`, `implantacao-kubernetes`, `observabilidade` e `saude-prontidao`, e
nenhuma delas fala da superfície JSON:

- `saude-prontidao` — `/health` e `/ready` estão em `health_router.py`, intocado.
- `observabilidade` — o padrão de log (`log_business_event`) é preservado; nenhuma métrica muda.
- `empacotamento-container` / `implantacao-kubernetes` — nenhum artefato de build ou deploy é
  tocado.

## Impact

**Código afetado**

| Arquivo | Natureza da mudança |
|---|---|
| `src/routers/api_router.py` | modificado — conversão ORM → schema nos 4 handlers |
| `src/tests/routers/test_api_router.py` | novo — testes dos 4 endpoints e regressão |

`schemas/event.py`, `services/event_service.py` e `models/event.py` são **lidos/reusados**, não
alterados. `page_router.py` não é tocado.

**Superfície pública.** As quatro rotas de `/api/events` passam a responder o que sempre deveriam
ter respondido. Nenhuma rota nova, nenhum campo novo, nenhum contrato removido.

**Dependências.** Nenhuma nova. Pydantic e Flask já estão em `src/requirements.txt`.

**ADRs e TRD.** Nenhum ADR é reaberto — 001 (containerização), 002 (plataforma) e 003 (Postgres no
cluster) são indiferentes a esta mudança. O TRD ganha, no máximo, a nota do formato de data na
descrição da API; a arquitetura em camadas que ele descreve é **reforçada**, não alterada.

**Desbloqueio.** Com esta correção, as tarefas 9.4 e 9.5 de `seed-eventos-iniciais` deixam de estar
bloqueadas e o CA6 do PRD-0002 passa a ser demonstrável também pelo caminho JSON.

### Impacto em disponibilidade / HA

**Sobre a aplicação em execução: nenhum risco de indisponibilidade.** A mudança é uma conversão em
memória dentro de handlers já existentes. Não altera boot, não altera schema, não altera as probes
de `/health` e `/ready` (`health_router.py` intocado), não abre conexão nova e não muda o custo por
requisição de forma perceptível — `model_validate` sobre 100 objetos é desprezível frente à própria
consulta ao banco.

O deploy é um rolling update comum do Deployment. Como o estado atual dos endpoints é 500, qualquer
janela de convivência entre pods antigos e novos só melhora a disponibilidade percebida.

**Riscos introduzidos.**

1. **Endpoints saem do estado "sempre 500" e passam a funcionar.** O `POST` volta a ser um caminho
   de escrita utilizável pela API — antes, quem tentava usá-lo desistia por causa do erro. É o
   objetivo da mudança, mas amplia a superfície de escrita efetivamente exercida em produção.
2. **Mudança de formato de `date`.** Se algum cliente interno estiver tolerando o 500 e fazendo
   parsing de outra coisa, ele muda. Risco tratado como teórico: não há consumidor conhecido de um
   endpoint que não responde.
3. **`GET /` com `limit` alto.** A conversão acontece por objeto; com `limit=100` (padrão) são 100
   validações Pydantic por requisição. Sem impacto prático nesta escala, e o limite já existia.

### Blast radius

```
              ┌──────────────────────────────────────────────┐
              │ MÉDIO — corpo de resposta dos 4 endpoints    │
              │ de /api/events (hoje: 500 em todos)          │
              ├──────────────────────────────────────────────┤
              │ BAIXO — imagem do container                  │
              │ um arquivo alterado, entra via COPY src/ já  │
              │ existente; CMD, runtime e boot inalterados   │
              ├──────────────────────────────────────────────┤
              │ NENHUM — schema, dados, page_router (HTML),  │
              │ probes, manifesto k8s, dependências, ADRs    │
              └──────────────────────────────────────────────┘
```

- **Escopo de dados:** nenhum. Nenhum `INSERT`, `UPDATE` ou DDL é adicionado ou removido — o que a
  mudança faz é **relatar corretamente** escritas que já aconteciam.
- **Escopo de schema:** nenhum.
- **Escopo de infraestrutura:** nenhum.
- **Caminho HTML:** intocado. `page_router` não passa pelo `api_router`, então a interface web —
  hoje o único caminho de leitura funcional — não corre risco algum.
- **Consumidores externos:** nenhum conhecido, e nenhum possível, já que os endpoints estão
  quebrados.
- **Pior caso realista:** a conversão falhar para alguma linha com dado inesperado (por exemplo,
  `location` nulo no banco, que o schema declara obrigatório) e o `GET /` voltar a dar 500 — mesmo
  estado de hoje, sem piora. Coberto em `design.md` (D4) e por cenário de spec.

### Plano de rollback

O rollback é trivial: a mudança é um único arquivo de produção alterado, sem efeito persistente.

**Gatilhos.** Regressão no corpo de resposta; erro de conversão em dados reais que hoje não são
exercitados; qualquer cliente interno quebrado pela mudança de formato de `date`.

1. **Reverter o código.** `git revert` do merge devolve `api_router.py` ao estado atual. O efeito
   é voltar ao 500 nos quatro endpoints — o estado de partida, não um estado pior.
2. **Reverter o deploy.** `kubectl rollout undo deployment/<app>` volta à imagem anterior. Sem
   passo de coordenação: não há schema, migração ou feature flag envolvida.
3. **Sem reversão de dados.** Nada foi migrado, nada foi reescrito. As linhas gravadas por `POST`
   durante a vigência da correção continuam válidas depois do rollback — são eventos normais, no
   mesmo formato de sempre.

**Ponto sem retorno:** nenhum. Não há estado persistente criado pela mudança que sobreviva ao
`revert`.
