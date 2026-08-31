# Observabilidade

## Requirements

### Requirement: Métricas Prometheus agregadas entre workers

Com a aplicação servida por Gunicorn com múltiplos workers, o endpoint de métricas SHALL
reportar valores agregados de todos os workers do processo, e não de um worker isolado.

#### Scenario: métricas refletem todos os workers

- **GIVEN** que a aplicação executa sob Gunicorn com mais de um worker
- **WHEN** o endpoint `/metrics` é consultado
- **THEN** os valores retornados agregam as contribuições de todos os workers ativos
- **AND** consultas sucessivas não apresentam valores divergentes conforme o worker que atendeu a requisição

#### Scenario: diretório multiproc gravável pelo usuário não-root

- **GIVEN** que o container executa como usuário não-root
- **WHEN** a aplicação inicializa
- **THEN** o diretório indicado por `PROMETHEUS_MULTIPROC_DIR` existe e é gravável por esse usuário
- **AND** a variável de ambiente está definida antes da inicialização do cliente Prometheus

#### Scenario: reinício não deixa métricas residuais

- **GIVEN** que uma execução anterior gravou arquivos de métricas no diretório multiproc
- **WHEN** o container é reiniciado
- **THEN** os arquivos residuais são descartados antes de a aplicação começar a servir
- **AND** os contadores não incluem valores de execuções anteriores

#### Scenario: término de worker libera suas métricas

- **WHEN** um worker do Gunicorn encerra
- **THEN** suas métricas são marcadas como encerradas no diretório multiproc,
  evitando que séries de workers mortos permaneçam sendo reportadas
