# Design — Correção da serialização da API JSON de eventos

## Context

O TRD (`docs/trd.md`, seção "Módulos / camadas principais") descreve a arquitetura em camadas
**router → service → model**, com "routers tratam HTTP e validação via schemas Pydantic" e "lógica
de acesso a dados isolada na camada de service". A implementação atual de `api_router.py` viola a
primeira metade dessa frase: ela **importa** `schemas.event.Event` e nunca o usa, chamando
`model_dump()` direto sobre o objeto ORM que o `event_service` devolve.

Estado atual, verificado em execução (`openspec/changes/seed-eventos-iniciais/validacao.md`):

| Endpoint | Handler | Linha do defeito | Resultado |
|---|---|---|---|
| `POST /api/events/` | `create_event` | `api_router.py:34` | 500 — **após gravar a linha** |
| `GET /api/events/` | `read_events` | `api_router.py:63` | 500 |
| `GET /api/events/by-token/<t>` | `get_event_by_token` | `api_router.py:83` | 500 |
| `PUT /api/events/by-token/<t>` | `update_event` | `api_router.py:111` | 500 |

O 500 vem do `except Exception` genérico de cada handler, que captura o `AttributeError` real
(`'Event' object has no attribute 'model_dump'`) e o converte em `abort(500)`. É o padrão de
tratamento de erro que o TRD descreve na seção de erros — ele funciona como projetado; o defeito
está antes dele.

O caminho HTML (`page_router` → templates Jinja) consome os objetos ORM diretamente, sem passar
por Pydantic, e por isso nunca quebrou. Ele não faz parte desta mudança.

**Restrições.** ADR 001 (containerização), ADR 002 (EKS) e ADR 003 (Postgres em `StatefulSet`) são
indiferentes a esta correção e não são reabertos: não há mudança de imagem, de topologia nem de
banco. A suíte de testes segue o padrão do TRD (seção de testes): `unittest.mock.MagicMock` sobre
a camada de baixo, sem banco real.

## Goals / Non-Goals

**Goals:**

- Os quatro endpoints de `/api/events` devolvem o recurso em JSON, com os campos declarados em
  `schemas.event.Event`.
- Uma escrita bem-sucedida nunca é reportada ao cliente como erro.
- O formato de `date` na saída é o mesmo aceito na entrada.
- Desbloquear as tarefas 9.4 e 9.5 do change `seed-eventos-iniciais`, tornando o CA6 do PRD-0002
  verificável pelo caminho JSON.
- A conversão vira responsabilidade explícita e testada do router, alinhando o código ao que o TRD
  já descreve.

**Non-Goals:**

- Persistir `technologies` — exige coluna nova e migração; fora de escopo (D3).
- Mudar rota, verbo, nome de campo ou código de status de sucesso.
- Introduzir camada de serialização genérica, `marshmallow`, ou migrar para FastAPI.
- Refatorar o `event_service` para devolver schemas em vez de ORM (D1, alternativa descartada).
- Corrigir o `page_router` ou a suíte HTML — não têm defeito.
- Autenticação, versionamento de API ou paginação além do `skip`/`limit` existentes.

## Decisions

### D1 — A conversão ORM → schema acontece no router, não no service

`Event.model_validate(obj)` é chamado no handler, imediatamente antes de serializar. O
`event_service` continua devolvendo objetos ORM.

*Por quê.* É o que o TRD já descreve — "os routers tratam HTTP e validação via schemas Pydantic".
Mudar o service para devolver schemas resolveria a API mas quebraria o `page_router`, que consome
os mesmos objetos ORM nos templates, e alteraria a assinatura de uma camada que 18 testes
existentes exercitam. O router é a fronteira certa: é onde o formato de saída importa.

*Alternativas consideradas.*

- **Service devolve Pydantic.** Rejeitada: blast radius muito maior (page_router + testes de
  service), e o HTML não precisa de conversão nenhuma.
- **`jsonify` sobre `__dict__` do ORM.** Rejeitada: vaza `_sa_instance_state`, não valida nada e
  não aplica os defaults do schema.
- **Serializador manual (dict literal por handler).** Rejeitada: duplica o schema em quatro
  lugares e diverge silenciosamente dele quando um campo mudar.

### D2 — `date` sai em ISO 8601, via `model_dump(mode="json")`

A serialização usa `mode="json"`, que converte `datetime` para string ISO 8601 antes de chegar ao
`jsonify`.

*Por quê.* Sem `mode="json"`, `model_dump()` devolve um `datetime` e o `jsonify` do Flask o
formata em **RFC 822** (`"Sun, 15 Feb 2026 19:00:00 GMT"`). A API aceitaria
`"2026-02-15T19:00:00"` na entrada — como faz o `api-requests.http` — e devolveria outro formato
na saída, obrigando todo cliente a tratar dois. ISO 8601 é o formato que o próprio arquivo de
requisições do projeto usa e o que o Pydantic aceita na desserialização, então entrada e saída
fecham o ciclo.

*Alternativa considerada.* Registrar um JSON provider customizado no Flask (`app.json`) para
formatar todo `datetime` da aplicação em ISO. Rejeitada nesta mudança: altera `main.py` e afeta
respostas fora da API, ampliando o blast radius de uma correção pontual. Fica registrada como
melhoria possível se outros endpoints JSON surgirem.

### D3 — `technologies` permanece não persistido, e o contrato diz isso

O campo continua no schema com default `[]`. Na leitura, `model_validate` não encontra o atributo
no ORM e aplica o default — a API devolve `[]`. Na criação e na atualização, o `event_service` já
atribui `db_event.technologies = event.technologies` na instância em memória (linhas 28 e 127),
então `model_validate` **ecoa** o que o cliente enviou, sem gravar nada.

*Por quê.* `models/event.py` não tem coluna correspondente. Persistir exigiria migração de schema
— outra mudança, outro blast radius. O comportamento de eco já era o pretendido pelo código atual
(os comentários no service dizem isso explicitamente); esta mudança apenas o torna observável e
o registra no contrato, em vez de deixá-lo implícito num campo que nunca chegava ao cliente.

*Consequência aceita.* Um cliente que cria um evento com `technologies` recebe a lista de volta e
não a encontra na leitura seguinte. É assimétrico, mas é o comportamento real do sistema — e agora
está escrito na spec, não escondido atrás de um 500.

### D4 — Falha de conversão é erro explícito, com o registro identificado no log

Se `model_validate` levantar `ValidationError` para alguma linha (por exemplo, `location` nulo no
banco, que o schema declara obrigatório), o handler registra em log o `id` do registro
problemático e a resposta é `500` — o mesmo desfecho de hoje, nunca um corpo parcial apresentado
como lista completa.

*Por quê.* Devolver os eventos que converteram e omitir os que falharam produziria uma listagem
silenciosamente incompleta — o pior desfecho possível para quem consome. O `ValidationError` do
Pydantic é subclasse de `ValueError`, e o `except ValueError` dos handlers de escrita já mapeia
para 400: sem cuidado, um dado corrompido no banco seria relatado como "payload inválido do
cliente".

*Como.* Ordenar os `except` por tipo não basta — a `ValidationError` do payload
(`EventCreate(**data)`) e a da conversão são do **mesmo tipo**; o que as distingue é onde ocorrem.
Por isso o helper `serializar()` captura a `ValidationError` e relança uma `SerializationError`
própria, que deliberadamente **não** herda de `ValueError`. O handler a captura antes do
`except ValueError`, e as duas origens ficam separadas por tipo, não por posição frágil no bloco.

*Alternativa considerada.* Serialização tolerante, pulando linhas inválidas. Rejeitada pelo motivo
acima.

### D5 — A gravação-fantasma do `POST` é resolvida pela própria correção

Hoje o `POST` grava a linha (o `commit` acontece dentro do `event_service.create_event`) e só
depois estoura no `model_dump()`, devolvendo 500 sobre uma escrita bem-sucedida. Removida a causa
do `AttributeError`, o caminho de sucesso passa a responder 200 com o evento criado.

*Por quê não vai além disso.* Uma garantia transacional mais forte — só commitar depois de
serializar — exigiria mover o controle de transação do service para o router, invertendo a
separação de camadas do TRD por um cenário que, depois desta correção, deixa de ocorrer na
prática. A spec fixa a invariante observável ("escrita bem-sucedida não é reportada como erro") e
esta correção a satisfaz.

### D6 — Testes de router com o service mockado, no padrão existente

Novos testes em `src/tests/routers/test_api_router.py`, usando o test client do Flask e
`unittest.mock.patch` sobre `services.event_service`, no mesmo estilo de
`src/tests/routers/test_health_router.py` e `src/tests/services/test_event_service.py`.

*Por quê.* Mantém a suíte sem banco real (TRD, seção de testes) e permite forçar os cenários de
borda — token inexistente, payload inválido, exceção do service, registro incompatível com o
schema — que um teste integrado tornaria caro de montar.

*Regressão explícita.* Um teste monta um objeto **sem** `model_dump` (um `SimpleNamespace` com os
atributos do evento, como o ORM) como retorno do service e exige `200` com corpo correto. Esse
teste falha na implementação atual e passa na corrigida — é o guardião contra a reintrodução do
defeito.

> **Nota de execução.** A suíte roda a partir de `src/`, não da raiz: `python -m pytest` insere o
> diretório atual no `sys.path`, e é assim que `core`, `routers` e `services` se tornam
> importáveis. Sem dependências de teste no host, use o container:
> `docker run --rm -v "/$(pwd)":/w -w //w/src python:3.12-slim sh -c "pip install -q -r requirements-dev.txt && python -m pytest tests/ -q"`

## Risks / Trade-offs

- **[Endpoints saem do estado "sempre 500" e passam a funcionar]** → É o objetivo, mas amplia a
  superfície de escrita efetivamente usada: o `POST` volta a ser um caminho viável de criação em
  produção. Mitigação: nenhuma mudança de autorização é introduzida — o endpoint já estava
  exposto, apenas quebrado —, e a spec cobre os desfechos de falha para que o comportamento sob
  erro seja conhecido, não descoberto em produção.

- **[Mudança do formato de `date` para ISO 8601]** → Teórico: não há consumidor de um endpoint que
  responde 500. Mitigação: o formato escolhido é o mesmo que a API já aceita na entrada e o mesmo
  que o `api-requests.http` usa, então a mudança alinha os dois lados em vez de criar um terceiro
  formato. Registrado como **BREAKING** formal no `proposal.md`.

- **[Dados legados incompatíveis com o schema]** → Uma linha com `location` ou `title` nulo faz o
  `GET /` falhar por inteiro (D4). Mitigação: o log identifica o `id` do registro, transformando um
  500 opaco num diagnóstico acionável. O risco é baixo na prática — o caminho de escrita atual
  (HTML e seed) sempre preenche esses campos.

- **[Custo por requisição na listagem]** → `model_validate` sobre até 100 objetos (`limit` padrão)
  por requisição. Desprezível frente à consulta ao banco, e o limite já existia. Sem mitigação
  necessária.

- **[Correção pontual em vez de estrutural]** → A conversão vive em um helper `serializar()` no
  próprio `api_router.py`, chamado pelos quatro handlers. É o menor denominador entre repetir a
  linha quatro vezes (o `mode="json"` do D2 divergiria no dia em que alguém esquecesse de um) e
  extrair uma camada de serialização compartilhada, que ampliaria o blast radius de uma correção
  que precisa ser pequena e auditável. Se um segundo módulo JSON surgir, é o momento de promover o
  helper.

## Migration Plan

Não há migração de dados nem de schema. O deploy é um rolling update comum do Deployment
(`k8s/manifesto.yaml` intocado), sem coordenação com o banco e sem feature flag.

1. Merge → build da imagem → rollout. Nenhum passo manual.
2. Verificação pós-deploy: `GET /api/events/` responde `200` com o array de eventos.
3. **Rollback:** `git revert` do merge ou `kubectl rollout undo`. O efeito é voltar ao 500 nos
   quatro endpoints — o estado de partida, não um estado pior. Nenhuma reversão de dados: as
   linhas criadas por `POST` durante a vigência da correção são eventos normais e continuam
   válidas. Ver `proposal.md`, seção "Plano de rollback".

## Open Questions

Nenhuma bloqueante. Registradas para depois, fora do escopo desta mudança:

1. **JSON provider global em ISO 8601** (D2, alternativa) — vale a pena se surgirem outros
   endpoints JSON fora de `/api/events`.
2. **Persistência de `technologies`** (D3) — exige coluna, migração e decisão sobre o tipo
   (array nativo do Postgres vs. tabela de associação). Merece PRD próprio.
3. **`POST` devolvendo `201` em vez de `200`** — mais correto em REST, mas é mudança de contrato
   que vai além de consertar o defeito. Deliberadamente não incluída.
