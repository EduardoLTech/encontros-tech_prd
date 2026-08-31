# Implantação em Kubernetes

## Purpose

Definir como a aplicação e sua camada de dados são implantadas em Kubernetes: um manifesto único
aplicável em um passo, configuração e segredos injetados pelo ambiente, endurecimento de segurança do
pod, e os sinais que o orquestrador consome para decidir quando reiniciar um pod e quando enviar-lhe
tráfego.
## Requirements
### Requirement: Manifesto único aplicável em um passo

A implantação SHALL ser descrita por um único manifesto versionado em `k8s/`, aplicável com um
comando `kubectl apply`, contendo todos os recursos do ambiente em documentos YAML sucessivos,
incluindo a camada de dados. O recurso de namespace SHALL preceder qualquer recurso que o
referencie.

#### Scenario: aplicação em cluster limpo cria todos os recursos

- **GIVEN** um cluster sem nenhum recurso da aplicação
- **WHEN** o manifesto é aplicado em uma única invocação de `kubectl apply`
- **THEN** o namespace, a service account, a configuração, o deployment e o serviço da aplicação,
  e o statefulset, o serviço e o volume persistente do banco de dados são criados
- **AND** nenhum recurso falha por referenciar um namespace ainda inexistente

#### Scenario: remoção completa pode incluir os dados do banco

- **WHEN** o manifesto é removido do cluster
- **THEN** todos os recursos criados por ele deixam de existir
- **AND** a remoção do volume persistente do banco, se ocorrer, é reconhecida como perda de
  dados possível — não há mais garantia de que o estado de negócio sobrevive fora do cluster

### Requirement: Configuração injetada pelo ambiente, sem segredos versionados

A aplicação SHALL receber sua configuração do ambiente do cluster, com valores não-sensíveis
declarados no manifesto e valores sensíveis referenciados a partir de recursos criados fora do
repositório. O manifesto SHALL NOT conter credenciais, nem em texto claro nem codificadas.

#### Scenario: credencial do banco vem de recurso externo

- **WHEN** o pod é iniciado
- **THEN** a URL de conexão com o banco é lida de um recurso de segredo referenciado por nome
- **AND** nenhum valor dessa credencial aparece em qualquer arquivo do repositório

#### Scenario: pré-requisito ausente falha de forma diagnosticável

- **GIVEN** que os segredos exigidos não foram criados no cluster
- **WHEN** o manifesto é aplicado
- **THEN** o pod não entra em execução e reporta um estado que identifica a configuração ausente

#### Scenario: número de workers é explícito, não inferido do nó

- **GIVEN** que o servidor de aplicação, sem configuração explícita, dimensiona seus workers a
  partir da contagem de CPUs visível no sistema — que em um container reflete o nó inteiro, e
  não o limite de CPU atribuído ao pod
- **WHEN** o pod é iniciado
- **THEN** a quantidade de workers vem de um valor declarado na configuração do manifesto
- **AND** não é derivada da contagem de CPUs do nó

### Requirement: Endurecimento de segurança do pod

O pod SHALL executar sob restrições que reduzam sua superfície de ataque: usuário não-root,
sem escalonamento de privilégios, sem capabilities do kernel e com o sistema de arquivos raiz
em modo somente-leitura.

#### Scenario: processo não executa como root

- **WHEN** o pod está em execução
- **THEN** o processo da aplicação executa sob um usuário sem privilégios de root
- **AND** o container é impedido de escalar privilégios

#### Scenario: raiz somente-leitura com região gravável para métricas

- **GIVEN** que o sistema de arquivos raiz do container é somente-leitura
- **WHEN** a aplicação inicializa
- **THEN** o diretório de métricas multiproc permanece gravável pelo usuário da aplicação
- **AND** o endpoint de métricas responde normalmente

#### Scenario: credencial de acesso à API do cluster não é montada

- **GIVEN** que a aplicação não interage com a API do Kubernetes
- **WHEN** o pod é iniciado
- **THEN** nenhum token de service account é montado no container

### Requirement: Imagem versionada obtida de registry privado

A implantação SHALL referenciar a imagem da aplicação por uma tag de versão explícita, nunca
por uma tag móvel, e SHALL obter a credencial de acesso ao registry privado de um recurso criado
fora do repositório.

#### Scenario: versão em execução é determinável

- **WHEN** o deployment é inspecionado
- **THEN** a imagem referenciada indica uma versão explícita
- **AND** não utiliza uma tag cujo conteúdo possa mudar sem alteração do manifesto

#### Scenario: credencial de registry não é versionada

- **WHEN** o manifesto é inspecionado
- **THEN** a credencial de acesso ao registry é referenciada por nome
- **AND** seu conteúdo não está presente no repositório

### Requirement: Sinais de saúde consumidos pelo orquestrador

A implantação SHALL declarar um sinal de prontidão que determine se o pod recebe tráfego e um
sinal de vivacidade que determine se o pod deve ser reiniciado. O sinal de vivacidade SHALL NOT
depender da disponibilidade do banco de dados.

A probe de prontidão SHALL consultar, por HTTP, o endpoint de prontidão da aplicação, e a probe de
vivacidade SHALL consultar o endpoint de vivacidade. Rotas de negócio NÃO SHALL ser usadas como
probe, nem verificação de socket TCP como sinal de vivacidade.

#### Scenario: readiness aponta para o endpoint de prontidão

- **WHEN** o manifesto do workload da aplicação é inspecionado
- **THEN** a `readinessProbe` do container da aplicação é um `httpGet` para o endpoint de prontidão
- **AND** não aponta para nenhuma rota de negócio

#### Scenario: liveness aponta para o endpoint de vivacidade

- **WHEN** o manifesto do workload da aplicação é inspecionado
- **THEN** a `livenessProbe` do container da aplicação é um `httpGet` para o endpoint de vivacidade
- **AND** não é uma verificação de socket TCP

#### Scenario: banco indisponível retira o pod da rotação sem reiniciá-lo

- **GIVEN** que o pod está em execução e o banco de dados torna-se indisponível
- **WHEN** o orquestrador avalia os sinais do pod
- **THEN** o pod deixa de receber tráfego novo
- **AND** o pod não é reiniciado por conta da indisponibilidade do banco

#### Scenario: retorno automático à rotação

- **GIVEN** que o pod está fora da rotação por indisponibilidade do banco
- **WHEN** o banco volta a responder
- **THEN** o pod é readmitido ao tráfego automaticamente, sem intervenção manual e sem reinício

#### Scenario: falha de readiness não dispara liveness

- **GIVEN** que a readiness falha de forma sustentada por indisponibilidade do banco
- **WHEN** a `livenessProbe` é avaliada na cadência configurada
- **THEN** a `livenessProbe` continua tendo sucesso
- **AND** a contagem de reinícios do pod permanece inalterada

#### Scenario: todas as réplicas não-prontas esvaziam o Service

- **GIVEN** que o banco está indisponível para todas as réplicas
- **WHEN** o orquestrador avalia a prontidão de todas elas
- **THEN** o `Service` fica sem endpoints prontos
- **AND** nenhum pod é reiniciado em decorrência disso

#### Scenario: processo encerrado é detectado

- **WHEN** o processo servidor deixa de aceitar conexões na porta da aplicação
- **THEN** o orquestrador reinicia o container

#### Scenario: probes não geram tráfego em rotas de negócio

- **GIVEN** que as probes rodam na cadência configurada
- **WHEN** os registros de acesso e as métricas da aplicação são inspecionados
- **THEN** o tráfego das probes não é contabilizado como acesso a rotas de negócio

### Requirement: Exposição interna do serviço

A aplicação SHALL ser alcançável dentro do cluster por um nome estável, independente do
endereço dos pods, sem exposição direta para fora do cluster.

#### Scenario: tráfego interno alcança a aplicação

- **WHEN** um consumidor dentro do cluster acessa o serviço pelo seu nome na porta da aplicação
- **THEN** a requisição é encaminhada a um pod pronto
- **AND** o serviço não expõe a aplicação diretamente para fora do cluster

### Requirement: Consumo de recursos declarado

O pod SHALL declarar reserva e teto de CPU e memória, de modo que o agendador possa posicioná-lo
e que um consumo anômalo fique contido.

#### Scenario: agendamento e contenção

- **WHEN** o pod é agendado
- **THEN** existe uma reserva declarada de CPU e memória usada como critério de posicionamento
- **AND** existe um teto declarado que limita o consumo do container

### Requirement: Pod da aplicação sem estado persistente

O pod da aplicação SHALL NOT reivindicar armazenamento persistente. A área gravável do
container é efêmera por decisão — apenas os dados de negócio, no banco, persistem.

#### Scenario: reinício descarta a área gravável

- **GIVEN** que uma execução anterior gravou arquivos de métricas na área gravável do container
- **WHEN** o pod é substituído por um novo
- **THEN** a nova execução começa com essa área vazia
- **AND** os contadores não incluem valores de execuções anteriores

#### Scenario: nenhuma reivindicação de volume persistente pelo pod da aplicação

- **WHEN** o deployment da aplicação é inspecionado
- **THEN** nenhum volume persistente é reivindicado por ele

### Requirement: Banco de dados dentro do cluster, com armazenamento persistente

O banco de dados SHALL rodar dentro do cluster, com identidade de rede estável e armazenamento
persistente próprio, dispensando um serviço de banco gerenciado externo. As credenciais do banco
SHALL vir de um recurso criado fora do repositório, no mesmo padrão exigido para a URL de conexão
consumida pela aplicação.

#### Scenario: banco tem armazenamento persistente dedicado

- **WHEN** o manifesto é inspecionado
- **THEN** o banco de dados reivindica um volume persistente próprio
- **AND** esse volume não é compartilhado com o pod da aplicação

#### Scenario: banco mantém identidade de rede estável entre reagendamentos

- **WHEN** o pod do banco é substituído (reagendamento, atualização de nó)
- **THEN** ele é alcançável pelo mesmo nome de rede
- **AND** volta a montar o mesmo volume persistente que usava antes

#### Scenario: credenciais do banco não são versionadas

- **WHEN** o manifesto é inspecionado
- **THEN** usuário, senha e nome do banco são referenciados a partir de um recurso de segredo
  criado fora do repositório
- **AND** nenhum desses valores está presente em qualquer arquivo do repositório

### Requirement: A temporização das probes comporta o teto da verificação

A janela de avaliação da probe de readiness SHALL ser estritamente maior que o teto de tempo
configurado para a verificação de prontidão na aplicação, e o intervalo entre avaliações SHALL ser
estritamente maior que essa janela. Os campos de temporização SHALL ser declarados explicitamente no
manifesto, sem depender dos valores padrão implícitos do orquestrador. *(P9.2, R2.3)*

#### Scenario: janela da probe é maior que o teto do app

- **WHEN** o manifesto do workload da aplicação é inspecionado
- **THEN** o `timeoutSeconds` da `readinessProbe` é maior que o teto de tempo da verificação declarado
  na configuração da aplicação
- **AND** o `periodSeconds` é maior que o `timeoutSeconds`

#### Scenario: temporização declarada explicitamente

- **WHEN** o manifesto do workload da aplicação é inspecionado
- **THEN** `timeoutSeconds`, `periodSeconds`, `failureThreshold` e `initialDelaySeconds` estão
  declarados em ambas as probes
- **AND** nenhum deles depende do valor padrão implícito do orquestrador

#### Scenario: resposta de diagnóstico chega ao orquestrador

- **GIVEN** que o banco está inalcançável e a verificação de prontidão consome o teto de tempo integral
- **WHEN** o orquestrador avalia a readiness da instância
- **THEN** a resposta 503, com o corpo de diagnóstico completo, é recebida pelo orquestrador
- **AND** a tentativa não é encerrada por esgotamento da janela de avaliação antes da resposta

### Requirement: Teto da verificação é fornecido por configuração declarada no manifesto

O teto de tempo da verificação de prontidão SHALL ser fornecido às instâncias por configuração
declarada no manifesto de implantação, permitindo ajuste no deploy sem alteração da imagem.
*(R2.1, R2.3)*

#### Scenario: teto declarado na configuração do workload

- **WHEN** o manifesto é inspecionado
- **THEN** a variável de ambiente do teto de tempo da verificação está declarada na configuração
  consumida pelo container da aplicação

#### Scenario: ajuste do teto no deploy

- **GIVEN** que o valor do teto é alterado na configuração declarada no manifesto
- **WHEN** um novo rollout das instâncias é realizado
- **THEN** as instâncias passam a aplicar o novo valor
- **AND** nenhuma reconstrução de imagem foi necessária

#### Scenario: alteração da configuração sem rollout

- **GIVEN** que o valor do teto é alterado na configuração sem que um rollout seja realizado
- **WHEN** as instâncias em execução são consultadas
- **THEN** elas continuam aplicando o valor vigente no início de cada pod

