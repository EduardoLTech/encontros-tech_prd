# seed-dados-iniciais Specification

## Purpose
TBD - created by archiving change seed-eventos-iniciais. Update Purpose after archive.
## Requirements
### Requirement: Semeadura condicionada a tabela vazia

O script de seed SHALL inserir o catálogo inicial **somente** quando a tabela `events` estiver vazia.
Encontrando qualquer registro, ele SHALL encerrar com **sucesso** sem inserir, alterar ou remover
dado algum, registrando em log que a semeadura foi ignorada por já haver dados. *(P1, P2, R3, I1)*

#### Scenario: tabela vazia é semeada

- **GIVEN** que a tabela `events` existe, está migrada e não contém nenhum registro
- **WHEN** o script de seed é executado
- **THEN** o catálogo inicial completo é inserido
- **AND** o script encerra com código de saída de sucesso
- **AND** o log informa quantos eventos foram semeados

#### Scenario: tabela populada é ignorada sem erro

- **GIVEN** que a tabela `events` contém ao menos um registro
- **WHEN** o script de seed é executado
- **THEN** nenhum evento é inserido, alterado ou removido
- **AND** o script encerra com código de saída de **sucesso**, não de falha
- **AND** o log declara explicitamente que a semeadura foi ignorada por já haver dados

#### Scenario: tabela com um único registro de origem externa também bloqueia

- **GIVEN** que a tabela `events` contém exatamente um evento criado por um usuário pela aplicação
- **WHEN** o script de seed é executado
- **THEN** esse evento permanece inalterado e nenhum evento do catálogo é inserido

### Requirement: Idempotência entre execuções

Execuções sucessivas do script SHALL deixar a tabela `events` com a mesma quantidade e o mesmo
conteúdo produzidos pela primeira semeadura bem-sucedida, sem gerar duplicatas nem divergência.
*(P3, I2)*

#### Scenario: reexecução não duplica

- **GIVEN** que o script já foi executado com sucesso uma vez sobre a tabela vazia
- **WHEN** o script é executado novamente, uma ou mais vezes
- **THEN** a contagem de eventos permanece igual à da primeira execução
- **AND** o conteúdo dos eventos permanece idêntico, inclusive as datas e os tokens de edição
- **AND** nenhuma execução posterior encerra em falha

#### Scenario: execução concorrente não é coberta

- **GIVEN** que duas execuções do script começam simultaneamente sobre a tabela vazia
- **WHEN** ambas avaliam a condição de tabela vazia antes de qualquer inserção ser confirmada
- **THEN** o resultado NÃO é garantido por esta especificação — a execução serializada é premissa
  declarada da mudança, e a orquestração é responsabilidade de quem invoca o script

### Requirement: Catálogo inicial fixo e completo

O catálogo de eventos iniciais SHALL ser fixo e definido no próprio código do script, derivado dos
10 eventos presentes em `api-requests.http`. Ele SHALL NOT depender de arquivo externo de dados, de
argumento de linha de comando, de variável de ambiente ou de qualquer outra entrada do operador.
Após uma semeadura em tabela vazia, a tabela SHALL conter exatamente esse catálogo — sem itens a
mais nem a menos. *(P4, R2, F7)*

#### Scenario: semeadura produz exatamente o catálogo

- **GIVEN** a tabela `events` vazia
- **WHEN** o script conclui a semeadura
- **THEN** a tabela contém exatamente 10 eventos
- **AND** cada um corresponde, em título, descrição e local, a um dos eventos do `api-requests.http`

#### Scenario: catálogo não é parametrizável

- **WHEN** o script é executado com qualquer combinação de argumentos ou variáveis de ambiente
- **THEN** o conjunto de eventos semeados é sempre o mesmo catálogo de 10 itens
- **AND** não existe forma suportada de selecionar um subconjunto, um dataset alternativo ou uma
  quantidade diferente

### Requirement: Campos persistidos por evento

Cada evento semeado SHALL gravar os campos `title`, `description`, `date` e `location`. O campo
`technologies`, presente no `api-requests.http`, SHALL NOT ser gravado enquanto a tabela `events` não
possuir coluna correspondente. *(P5, R4, F4)*

#### Scenario: campos de negócio preenchidos

- **GIVEN** um evento do catálogo inicial
- **WHEN** ele é inserido
- **THEN** `title`, `description`, `date` e `location` estão preenchidos e não são nulos nem vazios

#### Scenario: technologies não é persistido

- **WHEN** a semeadura conclui
- **THEN** nenhuma coluna referente a `technologies` é criada, gravada ou exigida
- **AND** a ausência desse campo não impede a leitura dos eventos pela aplicação

### Requirement: Datas futuras por deslocamento em bloco

As datas dos eventos semeados SHALL ser calculadas em relação ao instante da execução, e não
herdadas como valores fixos do `api-requests.http`. O cálculo SHALL preservar os intervalos relativos
entre os eventos do catálogo original — deslocando o conjunto inteiro por um mesmo delta — e SHALL
garantir que **todo** evento semeado fique estritamente no futuro em relação ao instante da execução,
inclusive o mais antigo do conjunto. *(P6, I5)*

#### Scenario: nenhum evento no passado

- **GIVEN** a tabela `events` vazia
- **WHEN** o script é executado em um instante qualquer
- **THEN** a data de cada um dos 10 eventos semeados é posterior a esse instante

#### Scenario: evento mais antigo do catálogo não cai sobre o instante da execução

- **WHEN** o deslocamento é aplicado
- **THEN** o evento de data original mais antiga recebe uma data estritamente maior que o instante da
  execução, com margem suficiente para não estar no passado quando a transação é confirmada

#### Scenario: espaçamento relativo preservado

- **GIVEN** dois eventos do catálogo original separados por um intervalo qualquer
- **WHEN** ambos são semeados
- **THEN** o intervalo entre as datas gravadas é o mesmo intervalo do catálogo original
- **AND** a ordem cronológica relativa entre todos os eventos do catálogo é preservada

#### Scenario: execuções em instantes diferentes produzem datas diferentes

- **GIVEN** duas semeaduras em tabelas vazias distintas, feitas em instantes distintos
- **WHEN** ambas concluem
- **THEN** as datas gravadas diferem entre as duas, refletindo o instante de cada execução
- **AND** em ambas os eventos continuam no futuro

### Requirement: Token de edição único por evento

Cada evento semeado SHALL receber um `edit_token` único e não-nulo, de modo que a aplicação consiga
localizá-lo e editá-lo pelos fluxos existentes de busca e edição por token. *(P7, I4)*

#### Scenario: tokens únicos e não-nulos

- **WHEN** a semeadura conclui
- **THEN** cada um dos 10 eventos tem `edit_token` preenchido
- **AND** não há dois eventos com o mesmo `edit_token`

#### Scenario: evento semeado é editável pelo fluxo existente

- **GIVEN** um evento semeado e seu `edit_token`
- **WHEN** a aplicação é consultada pelo fluxo de busca por token
- **THEN** o evento é encontrado
- **AND** o fluxo de edição por token o atualiza sem erro

### Requirement: Legibilidade pela aplicação

Os eventos semeados SHALL ser legíveis pela aplicação sem erro por campo ausente ou inválido,
aparecendo corretamente na listagem e na busca. A ausência de `technologies` no schema SHALL NOT
impedir nenhuma leitura. *(P8)*

> **Limite de verificação conhecido.** Este requisito foi demonstrado pela camada HTML
> (`page_router`). A verificação equivalente pela API JSON está bloqueada por um defeito
> **pré-existente e independente desta mudança**: `src/routers/api_router.py` chama `model_dump()`
> sobre objetos ORM em vez do schema Pydantic, e os quatro endpoints de `/api/events` respondem 500 —
> para qualquer evento, semeado ou criado por usuário. Ver `validacao.md`. O defeito não é causado
> nem agravado pela semeadura, e sua correção é escopo de change próprio.

#### Scenario: eventos aparecem na listagem

- **GIVEN** que o script concluiu a semeadura e a aplicação está no ar
- **WHEN** a listagem de eventos é consultada
- **THEN** todos os 10 eventos semeados aparecem
- **AND** nenhuma leitura falha por campo ausente ou inválido

#### Scenario: eventos aparecem na busca

- **WHEN** a busca é feita por um termo presente no título, na descrição ou no local de um evento
  semeado
- **THEN** esse evento é retornado entre os resultados

#### Scenario: leitura não depende de technologies

- **GIVEN** que a tabela `events` não possui coluna `technologies`
- **WHEN** um evento semeado é lido por qualquer caminho da aplicação
- **THEN** a leitura conclui sem erro de campo ausente

### Requirement: Independência do ciclo de vida da aplicação

O script SHALL ser standalone e autocontido: sua execução SHALL NOT fazer parte da inicialização da
aplicação, SHALL NOT ser disparada por ela, e SHALL concluir com sucesso com a aplicação desligada,
desde que o banco exista e esteja migrado. *(P9, R1, I7, F3)*

#### Scenario: semeadura com a aplicação desligada

- **GIVEN** que a aplicação não está em execução, mas o banco existe e a tabela `events` está migrada
- **WHEN** o script de seed é executado
- **THEN** a semeadura conclui com sucesso
- **AND** ao subir a aplicação em seguida, os eventos semeados aparecem na listagem e na busca

#### Scenario: boot da aplicação não dispara o seed

- **GIVEN** a tabela `events` vazia e migrada
- **WHEN** a aplicação é inicializada, com ou sem reinícios sucessivos
- **THEN** nenhum evento é semeado por efeito da inicialização
- **AND** a semeadura só ocorre por invocação explícita do script

### Requirement: Pré-condição de schema existente

O script SHALL NOT criar nem alterar o schema do banco em nenhuma circunstância. Não existindo a
tabela `events`, ele SHALL encerrar com **falha explícita** e mensagem clara indicando a pré-condição
não atendida. *(P10, I3, R5, F2)*

#### Scenario: tabela ausente resulta em falha explícita

- **GIVEN** que o banco está acessível mas a tabela `events` não existe
- **WHEN** o script de seed é executado
- **THEN** o script encerra com código de saída de falha
- **AND** a mensagem identifica a tabela ausente como pré-condição não atendida, distinguindo-a de
  uma falha de conexão
- **AND** a tabela `events` continua inexistente — nenhum DDL é emitido

#### Scenario: script nunca emite DDL

- **WHEN** o script é executado em qualquer cenário — tabela vazia, populada ou ausente
- **THEN** nenhuma instrução de criação ou alteração de schema é emitida ao banco

### Requirement: Falha de conexão explícita e sem efeito parcial

Estando o banco inalcançável, o script SHALL encerrar com falha explícita e mensagem clara, sem
deixar a tabela `events` em estado parcialmente semeado. *(P11)*

#### Scenario: banco inalcançável

- **GIVEN** que o banco de dados não aceita conexões
- **WHEN** o script de seed é executado
- **THEN** o script encerra com código de saída de falha
- **AND** a mensagem identifica a falha de conexão, distinguindo-a da pré-condição de schema ausente
- **AND** o script não fica pendurado indefinidamente aguardando o banco

#### Scenario: banco cai durante a semeadura

- **GIVEN** que a semeadura está em andamento
- **WHEN** a conexão é perdida antes da confirmação da transação
- **THEN** o script encerra em falha
- **AND** a tabela `events` permanece vazia

### Requirement: Atomicidade tudo-ou-nada da semeadura

A semeadura SHALL ser atômica: ou todos os eventos do catálogo são inseridos, ou nenhum permanece.
A tabela `events` SHALL NOT ficar em estado parcialmente semeado. *(P12, I6)*

#### Scenario: erro no meio da inserção não deixa resíduo

- **GIVEN** a tabela `events` vazia e a semeadura em andamento
- **WHEN** ocorre um erro após parte dos eventos ter sido inserida e antes da confirmação
- **THEN** nenhum evento permanece na tabela
- **AND** o script encerra em falha, com o motivo registrado em log

#### Scenario: contagem final é o catálogo inteiro ou zero

- **WHEN** o script termina uma execução iniciada sobre a tabela vazia
- **THEN** a tabela contém exatamente 10 eventos, em caso de sucesso, ou exatamente 0, em caso de
  falha — nunca um valor intermediário

### Requirement: Desfecho observável em log e código de saída

Toda execução SHALL deixar o desfecho explícito em log — semeou e quantos, ignorou por já haver
dados, ou falhou e por quê — e SHALL refletir esse desfecho no código de saída do processo, de modo
que um orquestrador consiga distinguir sucesso de falha sem interpretar texto. *(R6)*

#### Scenario: log de semeadura bem-sucedida

- **WHEN** a semeadura conclui com sucesso
- **THEN** o log informa que semeou e a quantidade de eventos inseridos
- **AND** o código de saída indica sucesso

#### Scenario: log de no-op

- **WHEN** a execução é ignorada por já haver dados
- **THEN** o log declara o motivo da ignorância
- **AND** o código de saída indica **sucesso**

#### Scenario: log de falha

- **WHEN** a execução falha por pré-condição de schema ou por conexão
- **THEN** o log informa o motivo da falha de forma distinguível entre esses casos
- **AND** o código de saída indica falha

#### Scenario: log é emitido mesmo fora do processo da aplicação

- **GIVEN** que o script roda como processo independente, sem a inicialização da aplicação Flask
- **WHEN** qualquer mensagem de desfecho é registrada
- **THEN** ela é efetivamente escrita na saída padrão do processo, e não descartada por ausência de
  configuração de logging

#### Scenario: alvo do banco é identificável antes da escrita

- **WHEN** o script vai semear
- **THEN** o log identifica o banco de destino de forma suficiente para o operador reconhecer o
  ambiente
- **AND** nenhuma credencial aparece na saída

