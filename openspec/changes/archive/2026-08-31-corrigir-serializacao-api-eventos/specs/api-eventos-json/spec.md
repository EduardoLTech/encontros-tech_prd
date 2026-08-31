# API JSON de eventos

> **PRD de origem:** não há PRD dedicado à API JSON. O contrato abaixo formaliza o comportamento
> que o `api-requests.http` (raiz do repositório) já assumia e que o **CA6 do PRD-0002**
> (`docs/prds/PRD-0002-seed-eventos.md` — "com a aplicação no ar, os eventos semeados aparecem na
> listagem e na busca") exige e não pôde ser verificado pelo caminho JSON: ver
> `openspec/changes/seed-eventos-iniciais/validacao.md`, tarefas 9.4 e 9.5 bloqueadas.
>
> **Predicados cobertos.** Do PRD-0002: CA6 (leitura pela aplicação). Do defeito observado, os
> predicados que esta mudança fixa como contrato: **B1** — resposta de sucesso é o JSON do recurso,
> nunca 500; **B2** — escrita bem-sucedida jamais é relatada como erro; **B3** — formato de data
> na saída é o mesmo aceito na entrada; **B4** — falha de conversão não corrompe nem duplica dado.
>
> **Fora de escopo:** paginação além do `skip`/`limit` já existentes, autenticação, versionamento
> de rota e persistência de `technologies` (a coluna não existe no modelo — ver `design.md` D3).

## ADDED Requirements

### Requirement: Corpo de resposta serializável

Todo endpoint da API de eventos SHALL devolver o recurso como objeto JSON derivado do schema
Pydantic `schemas.event.Event`, nunca do objeto ORM diretamente. O corpo de sucesso SHALL conter
os campos `id`, `title`, `description`, `date`, `location` e `edit_token`. *(B1)*

#### Scenario: listagem devolve JSON dos eventos

- **GIVEN** que existem eventos persistidos na tabela `events`
- **WHEN** um cliente faz `GET /api/events/`
- **THEN** a resposta tem status `200`
- **AND** o corpo é um array JSON com um objeto por evento
- **AND** cada objeto contém `id`, `title`, `description`, `date`, `location` e `edit_token`

#### Scenario: listagem de tabela vazia devolve array vazio

- **GIVEN** que a tabela `events` não contém nenhum registro
- **WHEN** um cliente faz `GET /api/events/`
- **THEN** a resposta tem status `200` e o corpo é `[]`
- **AND** **não** é um erro `404` nem `500`

#### Scenario: busca por texto devolve apenas os eventos correspondentes

- **GIVEN** que existem eventos cujo título, descrição ou local contêm o termo buscado
- **WHEN** um cliente faz `GET /api/events/?search=<termo>`
- **THEN** a resposta tem status `200`
- **AND** o corpo contém somente os eventos que casam com o termo, no mesmo formato da listagem

#### Scenario: consulta por token devolve o evento correspondente

- **GIVEN** que existe um evento com o `edit_token` informado
- **WHEN** um cliente faz `GET /api/events/by-token/<token>`
- **THEN** a resposta tem status `200` e o corpo é o objeto JSON daquele evento
- **AND** o `edit_token` do corpo é igual ao token consultado

#### Scenario: nenhum objeto ORM chega ao serializador

- **WHEN** qualquer um dos quatro endpoints monta sua resposta de sucesso
- **THEN** o valor serializado provém do schema Pydantic, não da instância de `models.event.Event`
- **AND** nenhuma resposta de sucesso falha por ausência de `model_dump` no objeto

### Requirement: Escrita bem-sucedida reportada como sucesso

Quando a persistência de um evento concluir com sucesso, a API SHALL responder com o recurso
persistido e status de sucesso. Um evento gravado no banco SHALL NUNCA ser reportado ao cliente
como erro. *(B2)*

#### Scenario: criação devolve o evento criado

- **GIVEN** um payload válido de criação
- **WHEN** um cliente faz `POST /api/events/`
- **THEN** a resposta tem status `200`
- **AND** o corpo contém o evento criado, com `id` e `edit_token` atribuídos pelo banco
- **AND** o `edit_token` do corpo permite recuperar o mesmo evento por
  `GET /api/events/by-token/<token>`

#### Scenario: atualização devolve o evento atualizado

- **GIVEN** um evento existente e um payload válido de atualização
- **WHEN** um cliente faz `PUT /api/events/by-token/<token>`
- **THEN** a resposta tem status `200`
- **AND** o corpo reflete os valores atualizados de `title`, `description`, `date` e `location`
- **AND** o `id` e o `edit_token` permanecem os mesmos de antes da atualização

#### Scenario: sem gravação fantasma seguida de erro

- **GIVEN** um payload válido de criação
- **WHEN** um cliente faz `POST /api/events/` e recebe uma resposta de erro
- **THEN** nenhuma linha correspondente existe na tabela `events`
- **AND** repetir a requisição não produz eventos duplicados por tentativa

#### Scenario: fluxo completo do api-requests.http

- **GIVEN** a aplicação no ar com o banco alcançável
- **WHEN** os `POST` do arquivo `api-requests.http` são executados em sequência
- **THEN** cada um responde com status de sucesso e o corpo do evento criado
- **AND** o `GET /api/events/` seguinte lista todos os eventos criados

### Requirement: Formato de data estável entre entrada e saída

O campo `date` SHALL ser serializado em **ISO 8601**, o mesmo formato aceito no corpo das
requisições de criação e atualização. A API SHALL NOT devolver a data em formato diferente do que
aceita. *(B3)*

#### Scenario: data enviada é devolvida no mesmo formato

- **GIVEN** um payload de criação com `"date": "2026-02-15T19:00:00"`
- **WHEN** o evento é criado e depois lido por qualquer endpoint da API
- **THEN** o campo `date` da resposta está em ISO 8601
- **AND** o valor é reinterpretável pelo mesmo cliente que o enviou, sem conversão de formato

#### Scenario: resposta é consumível por cliente JSON genérico

- **WHEN** um cliente lê o corpo de qualquer endpoint da API e faz parse de `date`
- **THEN** o parse ISO 8601 padrão da linguagem do cliente sucede sem tratamento especial

### Requirement: Desfechos de falha distinguíveis

A API SHALL responder com código de status que distinga os desfechos de falha: `404` para recurso
inexistente, `400` para payload inválido e `500` para falha interna. Cada falha SHALL ser
registrada em log com a causa. *(B1, B4)*

#### Scenario: token inexistente devolve 404

- **GIVEN** que nenhum evento tem o `edit_token` informado
- **WHEN** um cliente faz `GET /api/events/by-token/<token>` ou
  `PUT /api/events/by-token/<token>`
- **THEN** a resposta tem status `404`
- **AND** **não** é `500`

#### Scenario: payload inválido devolve 400

- **GIVEN** um corpo de requisição sem campo obrigatório, ou com `date` em formato irreconhecível
- **WHEN** um cliente faz `POST /api/events/` ou `PUT /api/events/by-token/<token>`
- **THEN** a resposta tem status `400`
- **AND** nenhum evento é criado ou alterado

#### Scenario: falha do banco devolve 500 sem vazar detalhe interno

- **GIVEN** que o banco está inalcançável
- **WHEN** um cliente faz qualquer requisição à API de eventos
- **THEN** a resposta tem status `500`
- **AND** o corpo não expõe credenciais nem stack trace
- **AND** o log do servidor registra a causa

#### Scenario: registro incompatível com o schema não derruba a listagem inteira em silêncio

- **GIVEN** que uma linha da tabela `events` tem valor incompatível com o schema — por exemplo,
  `location` nulo, declarado obrigatório
- **WHEN** um cliente faz `GET /api/events/`
- **THEN** a falha de conversão é registrada em log identificando o `id` do registro problemático
- **AND** a resposta é um erro explícito, não um corpo parcial apresentado como completo

### Requirement: Campo technologies coerente com a persistência

O campo `technologies` SHALL constar do contrato da API com valor padrão de lista vazia, refletindo
que **não** há coluna correspondente no modelo. A API SHALL NOT prometer persistência desse campo.

#### Scenario: leitura devolve lista vazia

- **GIVEN** um evento persistido no banco
- **WHEN** um cliente o lê por `GET /api/events/` ou `GET /api/events/by-token/<token>`
- **THEN** o campo `technologies` está presente no corpo com valor `[]`

#### Scenario: escrita ecoa o valor recebido sem persistir

- **GIVEN** um payload de criação com `"technologies": ["Python", "FastAPI"]`
- **WHEN** o cliente faz `POST /api/events/`
- **THEN** a resposta de criação ecoa a lista recebida
- **AND** uma leitura posterior do mesmo evento devolve `technologies` como `[]`

### Requirement: Caminho HTML preservado

A interface web SHALL continuar renderizando eventos exatamente como antes desta mudança. A
correção da API SHALL NOT alterar o comportamento de `page_router`.

#### Scenario: listagem HTML inalterada

- **GIVEN** que existem eventos persistidos
- **WHEN** um usuário acessa a página inicial da aplicação
- **THEN** os eventos são renderizados como antes da mudança

#### Scenario: edição por token via HTML inalterada

- **GIVEN** um evento com `edit_token` conhecido
- **WHEN** um usuário acessa a página de edição por esse token
- **THEN** a página responde `200` renderizando o evento, como antes da mudança
