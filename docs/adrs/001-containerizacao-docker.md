---
adr_number: "001"
status: aceito
created: 2026-07-12
supersedes: ""
superseded_by: ""
---

# ADR 001: Adotar containerização Docker para empacotamento e ambiente de desenvolvimento

## Contexto

A aplicação hoje é executada via Systemd, sem qualquer tecnologia de containers, tanto em desenvolvimento quanto em produção. Isso exige que cada ambiente provisione manualmente o runtime e as dependências externas — em especial o banco de dados PostgreSQL — o que torna o setup frágil e divergente entre máquinas. *(premissa — confirme ou corrija: a fragilidade/divergência de setup como dor principal foi inferida; você citou a dependência de serviços externos como o motivador explícito.)*

O alvo de deploy da aplicação é Kubernetes (herdado do PRD de health/readiness), o que torna a imagem de container o artefato natural de produção — e não apenas uma conveniência de desenvolvimento. Está em tensão, portanto, o desejo de facilitar o desenvolvimento local contra a necessidade de que esse ambiente seja fiel à produção, evitando a classe de problemas "funciona no meu ambiente, quebra no cluster". Decidir agora estabelece a base de empacotamento antes que a app avance rumo ao k8s.

## Alternativas Consideradas

- **Manter Systemd sem containers (status quo)** — sem custo de migração e sem nova ferramenta; mas perpetua o provisionamento manual de runtime e banco, a divergência entre ambientes e a distância em relação ao alvo Kubernetes.
- **Containerizar apenas o ambiente de desenvolvimento** — resolveria o atrito de setup local mais rápido; mas criaria um artefato de dev descartável, sem reuso em produção, e adiaria (com retrabalho) a imagem que o k8s vai exigir.
- **Imagem única production-grade, com dev espelhando produção** — maior fidelidade dev/prod e artefato único aproveitável no k8s; custo de desenhar desde já multi-stage, usuário não-root e o mesmo servidor de aplicação em ambos os ambientes.
- **Ambiente de dev com servidor de desenvolvimento diferente do de produção** — melhor ergonomia de edição ao vivo; mas rompe a paridade dev/prod, que é justamente o objetivo perseguido.
- **Imagem base "slim" vs. Alpine vs. distroless** — Alpine/distroless produzem imagens menores, porém atritam com bibliotecas que dependem de extensões C/compilação; a variante slim oficial equilibra tamanho e compatibilidade. *(premissa — confirme ou corrija: distroless entrou como opção apenas de passagem; o debate central foi slim vs. Alpine.)*

## Decisão

Fica adotada a containerização Docker como estratégia de empacotamento e de ambiente, substituindo o modelo Systemd. A aplicação será empacotada em uma **imagem única, production-grade, construída em múltiplos estágios**, executando sob o mesmo servidor de aplicação de produção e rodando como usuário não-root, sobre a imagem base slim oficial do Python na mesma versão já usada localmente. Um **Docker Compose** orquestra essa mesma imagem junto de um serviço de PostgreSQL para compor o ambiente de desenvolvimento, deliberadamente espelhando produção. A distribuição da imagem se dá via **Docker Hub como registry privado, com publicação manual**.

O que pesou mais: o alvo já é Kubernetes, então tratar produção como "futuro distante" geraria retrabalho; a paridade dev/produção elimina a classe de falhas de ambiente; e o multi-stage viabiliza uma imagem final enxuta mesmo quando as dependências precisam ser compiladas.

## Consequências

- **Positivas:**
  - Ambiente de desenvolvimento reproduzível e fiel à produção, com as dependências externas (banco) provisionadas junto — elimina o setup manual do Systemd.
  - Artefato único de imagem reaproveitável diretamente no alvo Kubernetes.
  - Imagem final enxuta e com menor superfície: o estágio de build absorve a compilação de dependências (inclusive quando não há artefatos pré-compilados para a versão do Python adotada) e o estágio final recebe só o necessário; separação entre dependências de runtime e de teste.
  - Execução como não-root reduz a superfície de segurança do container.

- **Negativas:**
  - Perde-se o recarregamento automático "nativo" do servidor de desenvolvimento; a fidelidade a produção impõe um mecanismo de recarga próprio no ambiente de dev para preservar a ergonomia. *(premissa — confirme ou corrija: fechamos que dev usa o servidor de produção com recarga + montagem do código; descrevi isso como consequência sem citar o mecanismo, que é detalhe de TRD.)*
  - Introduz Docker como dependência obrigatória e nova curva operacional para quem hoje opera via Systemd. *(premissa — confirme ou corrija.)*
  - Registry privado implica que o Kubernetes precisará de credencial de pull da imagem — a documentar no material de deploy.
  - Publicação manual no registry: sem automação de build/push nesta etapa, o passo depende de disciplina do operador.

- **Neutras / trade-offs aceitos:**
  - A aplicação acopla sua inicialização à disponibilidade do banco; no ambiente de dev, a subida do container da aplicação fica condicionada à prontidão do serviço de banco.
  - Adoção de esquema de tag versionada além da tag corrente, para rastreabilidade da imagem no cluster.
  - **Dívidas conhecidas não endereçadas por este ADR:** segredo de aplicação fixado no código-fonte e ausência de ferramenta de migração de schema (criação de tabelas no boot). Ficam apenas registradas aqui, sem decisão nesta ADR.
