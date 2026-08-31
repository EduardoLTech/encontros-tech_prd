# Empacotamento em Container

## Requirements

### Requirement: Imagem única multi-stage

A aplicação SHALL ser empacotada em uma imagem Docker única, construída em múltiplos estágios
a partir da base `python:3.12-slim`, reaproveitável tanto no ambiente de desenvolvimento quanto
no alvo Kubernetes.

#### Scenario: build produz imagem sem artefatos de construção

- **WHEN** a imagem é construída a partir do `Dockerfile` na raiz do projeto
- **THEN** o estágio final não contém cache do pip nem dependências de teste
- **AND** a imagem final é baseada em `python:3.12-slim`

#### Scenario: contexto de build não vaza arquivos sensíveis

- **WHEN** a imagem é construída
- **THEN** `.env`, `.git/`, diretórios de ambiente virtual e pastas de ferramentas de agente
  não são enviados ao contexto de build nem incorporados à imagem

### Requirement: Execução como usuário não-root

O container SHALL executar a aplicação sob um usuário não-root, reduzindo a superfície de ataque.

#### Scenario: processo da aplicação não roda como root

- **WHEN** o container é iniciado
- **THEN** o processo do Gunicorn executa sob um usuário sem privilégios de root
- **AND** todos os diretórios que a aplicação precisa escrever em runtime são graváveis por esse usuário

### Requirement: Servidor de aplicação idêntico em dev e produção

A aplicação SHALL ser servida por Gunicorn em ambos os ambientes, configurado por um único
`gunicorn.conf.py` versionado cujos valores vêm de variáveis de ambiente.

#### Scenario: dev e produção compartilham a configuração do servidor

- **WHEN** a aplicação sobe em desenvolvimento ou em produção
- **THEN** ambos usam o mesmo `gunicorn.conf.py`
- **AND** as diferenças entre os ambientes se expressam apenas por variáveis de ambiente,
  sem flags duplicadas entre `Dockerfile` e `docker-compose.yml`

### Requirement: Separação de dependências de runtime e de teste

O projeto SHALL manter as dependências de runtime separadas das de teste em arquivos distintos.

#### Scenario: imagem de runtime não contém dependências de teste

- **WHEN** a imagem final é construída a partir de `src/requirements.txt`
- **THEN** `pytest` e demais dependências exclusivas de teste não estão presentes na imagem
- **AND** essas dependências permanecem declaradas em `src/requirements-dev.txt`

### Requirement: Ambiente de desenvolvimento orquestrado por Docker Compose

Um `docker-compose.yml` SHALL orquestrar a imagem da aplicação junto de um serviço PostgreSQL,
espelhando deliberadamente a produção.

#### Scenario: aplicação só sobe após o banco estar pronto

- **GIVEN** que a aplicação cria as tabelas durante a inicialização e falha se o banco estiver indisponível
- **WHEN** o ambiente é levantado com `docker compose up`
- **THEN** o serviço do banco expõe um healthcheck baseado em `pg_isready`
- **AND** o serviço da aplicação só inicia após o banco ser reportado como saudável

#### Scenario: alteração no código-fonte recarrega a aplicação

- **GIVEN** que o código-fonte está montado no container por bind mount
- **WHEN** um arquivo Python da aplicação é alterado no host
- **THEN** o Gunicorn recarrega os workers automaticamente
- **AND** a detecção da alteração não depende de eventos de filesystem que não atravessam
  bind mounts a partir de hosts Windows

### Requirement: Identidade única de imagem entre desenvolvimento e cluster

A imagem SHALL ser identificada pelo mesmo nome e pela mesma tag de versão em todos os
ambientes que a consomem. A orquestração de desenvolvimento e o manifesto de implantação SHALL
referenciar essa mesma identidade, de modo que o artefato construído localmente seja
literalmente o mesmo que o cluster executa.

#### Scenario: build de desenvolvimento produz a imagem que o cluster consome

- **WHEN** a imagem é construída pela orquestração de desenvolvimento
- **THEN** ela recebe o nome e a tag de versão declarados para a implantação
- **AND** não recebe um nome derivado automaticamente do diretório do projeto

#### Scenario: identidade da imagem é declarada em um lugar reconhecível

- **WHEN** a orquestração de desenvolvimento e o manifesto de implantação são inspecionados
- **THEN** ambos referenciam a mesma imagem, pelo mesmo nome e pela mesma tag
- **AND** nenhum dos dois utiliza uma tag móvel cujo conteúdo possa mudar sem alteração do arquivo
