# saude-prontidao Specification

## Purpose
TBD - created by archiving change endpoints-saude-prontidao. Update Purpose after archive.
## Requirements
### Requirement: Sinal de vivacidade independente de dependências externas

A aplicação SHALL expor um endpoint de vivacidade em `GET /health` que responde HTTP 200 enquanto o
processo estiver em execução e responsivo. O resultado SHALL depender exclusivamente do próprio
processo: nenhuma dependência externa — o banco de dados incluído — pode influenciar a resposta.
*(P1, P2, I3, R1)*

#### Scenario: processo saudável

- **GIVEN** que o processo da aplicação está em execução e responsivo
- **WHEN** `GET /health` é consultado
- **THEN** a resposta é HTTP 200 indicando estado vivo

#### Scenario: banco indisponível não afeta a vivacidade

- **GIVEN** que o banco de dados está inalcançável
- **WHEN** `GET /health` é consultado
- **THEN** a resposta continua sendo HTTP 200
- **AND** nenhuma conexão com o banco é aberta para produzir essa resposta

#### Scenario: banco pendurado não atrasa a vivacidade

- **GIVEN** que o banco aceita conexões mas não responde a consultas
- **WHEN** `GET /health` é consultado
- **THEN** a resposta é HTTP 200 emitida imediatamente, sem aguardar o banco

### Requirement: Sinal de prontidão reflete a conectividade atual com o banco

A aplicação SHALL expor um endpoint de prontidão em `GET /ready` que verifica a conectividade com o
banco de dados **no momento da consulta** e responde HTTP 200 com corpo
`{"status": "ready", "checks": {"database": "ok"}}` quando o banco está alcançável, ou HTTP 503 com
corpo `{"status": "not_ready", "checks": {"database": "down"}}` quando não está. O resultado NÃO SHALL
ser reaproveitado de consultas anteriores. *(P3, P4, I6, R5)*

#### Scenario: banco disponível

- **GIVEN** que o banco de dados está alcançável e respondendo
- **WHEN** `GET /ready` é consultado
- **THEN** a resposta é HTTP 200
- **AND** o corpo é `{"status": "ready", "checks": {"database": "ok"}}`

#### Scenario: banco inalcançável

- **GIVEN** que o banco de dados está inalcançável
- **WHEN** `GET /ready` é consultado
- **THEN** a resposta é HTTP 503
- **AND** o corpo é `{"status": "not_ready", "checks": {"database": "down"}}`

#### Scenario: resultado nunca é reaproveitado entre consultas

- **GIVEN** que uma consulta anterior a `/ready` retornou 200
- **WHEN** o banco se torna inalcançável e `/ready` é consultado novamente
- **THEN** a resposta é 503 já nessa consulta
- **AND** nenhum resultado de verificação anterior é reutilizado para responder

#### Scenario: conexão recusada de imediato

- **GIVEN** que o banco recusa conexões ativamente (porta fechada)
- **WHEN** `GET /ready` é consultado
- **THEN** a resposta 503 é emitida assim que a recusa é conhecida, sem aguardar o teto de tempo

#### Scenario: banco alcançável mas credenciais inválidas

- **GIVEN** que o banco aceita a conexão TCP mas rejeita a autenticação
- **WHEN** `GET /ready` é consultado
- **THEN** a resposta é HTTP 503 com o banco reportado como `down`
- **AND** o corpo não contém a mensagem de erro do driver, a string de conexão nem qualquer credencial

#### Scenario: nenhuma dependência além do banco é avaliada

- **WHEN** `GET /ready` é consultado
- **THEN** o objeto `checks` do corpo contém exclusivamente a chave `database`

### Requirement: Teto de tempo da verificação de prontidão

A verificação de prontidão SHALL concluir dentro de um teto de tempo configurado, cujo valor padrão é
**5 segundos**. Esgotado o teto sem confirmação de que o banco está saudável, a aplicação SHALL
responder 503 em vez de permanecer aguardando. O teto SHALL cobrir a verificação inteira — espera por
conexão disponível, estabelecimento da conexão e execução da consulta de verificação —, não apenas uma
de suas fases. *(P9, R2)*

#### Scenario: banco não responde

- **GIVEN** que o banco está inalcançável de forma a não responder
- **WHEN** `GET /ready` é consultado
- **THEN** a resposta 503 é emitida dentro do teto configurado
- **AND** a requisição não permanece pendente além desse teto

#### Scenario: banco lento porém dentro do teto

- **GIVEN** que o banco responde à verificação em tempo inferior ao teto configurado
- **WHEN** `GET /ready` é consultado
- **THEN** a resposta é HTTP 200 com o banco reportado como `ok`

#### Scenario: esgotamento na espera por conexão disponível

- **GIVEN** que todas as conexões do pool estão ocupadas por tráfego de negócio
- **WHEN** `GET /ready` é consultado e nenhuma conexão se libera dentro do teto
- **THEN** a resposta 503 é emitida dentro do teto
- **AND** a requisição não permanece pendente aguardando indefinidamente por uma conexão

### Requirement: Teto de tempo configurável por variável de ambiente

O teto de tempo da verificação de prontidão SHALL ser parametrizável por variável de ambiente, lida na
inicialização do processo. Na ausência da variável, o valor padrão de 5 segundos SHALL ser aplicado.
Valores configurados abaixo de 2 segundos SHALL ser tratados como 2 segundos, que é o piso efetivo
imposto pela camada de conexão. Não há ajuste a quente: a alteração só passa a valer após novo rollout.
*(P9.1, R2.1, R2.2)*

#### Scenario: variável ausente aplica o padrão

- **GIVEN** que a variável de ambiente do teto não está definida
- **WHEN** a aplicação inicializa
- **THEN** o teto vigente é de 5 segundos

#### Scenario: valor configurado é respeitado

- **GIVEN** que a variável de ambiente do teto está definida com um valor entre 2 e 5 segundos
- **WHEN** `GET /ready` é consultado com o banco inalcançável
- **THEN** a resposta 503 é emitida dentro do valor configurado

#### Scenario: valor abaixo do piso é elevado a 2 segundos

- **GIVEN** que a variável de ambiente do teto está definida com valor menor que 2
- **WHEN** a aplicação inicializa
- **THEN** o teto vigente é de 2 segundos

#### Scenario: valor inválido não impede a inicialização

- **GIVEN** que a variável de ambiente do teto está definida com um valor não numérico ou negativo
- **WHEN** a aplicação inicializa
- **THEN** o processo conclui a inicialização normalmente aplicando o valor padrão
- **AND** um registro de aviso identifica a configuração inválida

#### Scenario: alteração exige novo rollout

- **GIVEN** que a aplicação está em execução com um teto vigente
- **WHEN** o valor da variável de ambiente é alterado sem que as instâncias sejam reiniciadas
- **THEN** as instâncias em execução continuam aplicando o teto lido em sua inicialização

### Requirement: Inicialização resiliente à indisponibilidade do banco

O processo SHALL concluir sua inicialização e passar a atender requisições mesmo que o banco de dados
esteja indisponível no momento em que sobe. A indisponibilidade do banco NÃO SHALL, em nenhuma
circunstância, impedir o boot. *(P7, I4)*

#### Scenario: boot com banco indisponível

- **GIVEN** que o banco de dados está indisponível
- **WHEN** a aplicação inicia
- **THEN** o processo conclui a inicialização sem encerrar com erro
- **AND** `GET /health` responde 200
- **AND** `GET /ready` responde 503

#### Scenario: preparação de schema não bloqueia o boot

- **GIVEN** que a criação das tabelas não pôde ser executada por indisponibilidade do banco
- **WHEN** a aplicação inicia
- **THEN** o processo conclui a inicialização
- **AND** a falha na preparação do schema é registrada em log sem interromper o boot

#### Scenario: schema é preparado quando o banco fica disponível

- **GIVEN** que a aplicação subiu sem conseguir preparar o schema
- **WHEN** o banco fica disponível
- **THEN** o schema é preparado sem que o processo seja reiniciado
- **AND** as funcionalidades de negócio passam a operar

#### Scenario: preparação concorrente entre workers

- **GIVEN** que a aplicação executa com múltiplos workers, cada um capaz de preparar o schema
- **WHEN** mais de um worker tenta preparar o schema simultaneamente
- **THEN** nenhum worker encerra com erro em decorrência da concorrência
- **AND** o schema resultante é o mesmo que seria produzido por uma única execução

### Requirement: Convergência para pronto sem reinício

Uma instância que esteja reportando não-prontidão SHALL voltar a reportar prontidão assim que o banco
voltar a estar disponível, sem reinício do processo e sem intervenção manual. A indisponibilidade de
uma dependência externa NUNCA SHALL, por si só, provocar o reinício do processo. *(P6, P8, I2)*

#### Scenario: retorno automático após restabelecimento do banco

- **GIVEN** que `/ready` está retornando 503 por indisponibilidade do banco
- **WHEN** o banco volta a ficar disponível
- **THEN** `/ready` volta a retornar 200 na consulta seguinte
- **AND** o processo não foi reiniciado nesse intervalo

#### Scenario: indisponibilidade prolongada não reinicia o processo

- **GIVEN** que o banco permanece indisponível por um período prolongado
- **WHEN** as consultas de vivacidade e prontidão prosseguem na cadência configurada
- **THEN** `/health` continua respondendo 200 durante todo o período
- **AND** o processo não é reiniciado em decorrência da indisponibilidade do banco

### Requirement: A verificação de prontidão não compromete a vivacidade

A verificação de prontidão NÃO SHALL consumir a capacidade de atendimento da instância a ponto de
impedir que `/health` seja respondido. A indisponibilidade do banco não pode converter-se, por
saturação da capacidade de atendimento durante as verificações, em falha de vivacidade. *(I7, I2, R1)*

#### Scenario: vivacidade atendida sob banco pendurado

- **GIVEN** que o banco aceita conexões mas não responde, de modo que cada verificação de prontidão
  consome o teto de tempo integral
- **WHEN** as probes de prontidão e de vivacidade são consultadas na cadência configurada, de forma
  concorrente e por um período sustentado
- **THEN** `GET /health` continua respondendo 200 dentro da janela de avaliação do orquestrador
- **AND** o processo não é reiniciado

#### Scenario: verificação concorrente em todas as réplicas

- **GIVEN** que todas as réplicas verificam a prontidão contra o mesmo banco indisponível
- **WHEN** as verificações ocorrem simultaneamente na cadência configurada
- **THEN** cada réplica responde `/health` com 200 e `/ready` com 503
- **AND** nenhuma réplica é reiniciada

### Requirement: Sinais são read-only e idempotentes

As consultas aos endpoints de vivacidade e de prontidão NÃO SHALL criar, alterar ou remover qualquer
dado de negócio, independentemente do número de consultas. *(P10, I5)*

#### Scenario: consultas repetidas não alteram dados de negócio

- **GIVEN** um conjunto conhecido de eventos cadastrados
- **WHEN** `/health` e `/ready` são consultados repetidamente
- **THEN** nenhum evento é criado, alterado ou removido
- **AND** o conjunto de eventos permanece idêntico ao estado inicial

### Requirement: Corpo de diagnóstico sem vazamento de informação

O corpo das respostas dos sinais SHALL identificar qual dependência verificada está não-saudável e
NÃO SHALL expor dados de negócio, credenciais, segredos, informações pessoais, mensagens de erro do
driver, endereços de host ou strings de conexão. *(P11, R3)*

#### Scenario: diagnóstico em falha identifica a dependência

- **GIVEN** que `/ready` está retornando 503
- **WHEN** um operador inspeciona o corpo da resposta
- **THEN** o corpo identifica o banco de dados como a dependência não-saudável

#### Scenario: diagnóstico não vaza informação sensível

- **GIVEN** que `/ready` está retornando 503 por erro de conexão com o banco
- **WHEN** o corpo da resposta é inspecionado
- **THEN** o corpo não contém host, porta, usuário, senha, string de conexão, stack trace nem
  mensagem bruta do driver

### Requirement: Endpoints acessíveis sem autenticação

Os endpoints de vivacidade e de prontidão SHALL ser consultáveis sem autenticação, para que o
orquestrador os consulte livremente. *(R4)*

#### Scenario: consulta anônima

- **GIVEN** uma requisição sem qualquer credencial ou cabeçalho de autorização
- **WHEN** `GET /health` ou `GET /ready` é consultado
- **THEN** a resposta é produzida normalmente, sem HTTP 401 ou 403

