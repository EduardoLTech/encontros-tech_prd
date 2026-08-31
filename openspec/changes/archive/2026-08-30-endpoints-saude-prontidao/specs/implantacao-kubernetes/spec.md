# Implantação Kubernetes

**PRD de origem:** `docs/prds/PRD-0001-health-readiness.md` (revisão de 2026-08-30).
**Predicados cobertos:** P5, P6, P9.2 · **Invariantes:** I1, I2 · **Restrições:** R2.1, R2.3 · **Escopo:** exceção a F1 registrada na revisão de 2026-08-30 — o *timeout* da probe de readiness entra no escopo desta feature por depender do teto de tempo da verificação; cadência, `initialDelaySeconds` e `failureThreshold` são declarados aqui como decorrência dessa relação de temporização.

O requisito existente de sinais de saúde era abstrato: exigia "um sinal de prontidão" e "um sinal de vivacidade" sem dizer o que os produz, porque na época `/health` e `/ready` não existiam e o manifesto usava aproximações provisórias (`httpGet /` e `tcpSocket`). Com o PRD-0001 implementado, ele passa a nomear os endpoints e a temporização.

## MODIFIED Requirements

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

## ADDED Requirements

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
