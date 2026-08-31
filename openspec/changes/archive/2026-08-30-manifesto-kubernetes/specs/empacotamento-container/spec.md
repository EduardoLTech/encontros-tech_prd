# Empacotamento em Container

## ADDED Requirements

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
