---
adr_number: "002"
status: superseded
created: 2026-07-12
supersedes: ""
superseded_by: "003"
---

# ADR 002: Executar a aplicação em Amazon EKS com Managed Node Groups e banco em Amazon RDS Multi-AZ

> **Superseded por [ADR 003](003-banco-postgres-no-cluster.md):** a decisão de compute (EKS com
> Managed Node Groups) permanece válida. A decisão de banco (RDS Multi-AZ, fora do cluster) foi
> revertida — o Postgres passou a rodar dentro do cluster. Este documento fica como registro
> histórico da decisão original e de por que o RDS foi escolhido primeiro.

## Contexto

A ADR 001 estabeleceu a containerização Docker como estratégia de empacotamento, tratando a imagem como artefato de produção e fixando Kubernetes como alvo de deploy. Restava decidir, sobre a AWS já adotada como Cloud Provider, **qual serviço executa a aplicação** e **como fica a camada de dados** em produção.

A aplicação (Encontros Tech) é uma web app Flask relativamente simples e leve: uma única imagem de container, um serviço, uma tabela (`events`), sem autenticação de usuário. A stack não tem componentes pesados de CPU ou memória. O objetivo de produção nesta decisão é deliberadamente estreito — **serviço de execução, modelo de compute e camada de dados** — deixando de fora, por opção explícita, Ingress, Registry, Infraestrutura como Código e CI/CD.

A tensão central é entre o custo operacional de operar Kubernetes para uma app pequena e o alinhamento com o padrão organizacional. Pesou também a natureza stateless da aplicação (uma vez que o estado sai para um banco gerenciado), que abre espaço para tratar a camada de compute como recurso descartável e escalável horizontalmente.

## Alternativas Consideradas

- **Amazon ECS (Fargate) para execução** — sem custo de control plane e sem gestão de nós; mas rompe o padrão Kubernetes da empresa, subaproveita o conhecimento do time de DevOps e gera lock-in mais forte na AWS.
- **Amazon EKS com Fargate** — remove a gestão de nós mantendo Kubernetes; mas abre mão do controle sobre provisionamento de recurso e placement, justamente o que se quer reter.
- **Amazon EKS com Managed Node Groups** — mantém o padrão k8s e devolve controle sobre onde e como os pods rodam; custo de assumir a operação dos nós (ciclo de vida, upgrades) e o control plane fixo do EKS.
- **Banco em container dentro do cluster (Deployment/StatefulSet)** — evita mais um serviço gerenciado; mas rodar banco de dados stateful no cluster traz risco de corrupção/perda de dados no reciclo de nós e exige desenhar storage, backup e failover manualmente. Um `Deployment` para banco é antipadrão; o mínimo aceitável seria `StatefulSet` com storage persistente — complexidade que o RDS elimina.
- **Banco em Amazon RDS single-AZ** — mais barato; mas sem failover automático, deixando a camada de dados como ponto único de falha.
- **Banco em Amazon RDS com read replica** — replicação assíncrona legível para escalar leitura; mas não é o objetivo (não se busca escala de leitura nem HA de réplicas ativas), e a promoção em falha é manual.
- **Perfil de nó com poucos nós grandes vs. muitos nós pequenos** — nós grandes reduzem overhead agregado, mas concentram blast radius; nós pequenos espalhados por AZs favorecem HA e o spread de pods, ao custo de overhead por nó um pouco maior.
- **Node group x86 (`t3`) vs. Graviton/arm64 (`t4g`)** — Graviton oferece melhor preço/desempenho, mas exigiria build multi-arch da imagem (hoje single-arch, conforme ADR 001).

## Decisão

A aplicação será executada em **Amazon EKS**, em um **cluster novo e dedicado, distribuído em 3 zonas de disponibilidade**. O compute usará **Managed Node Groups** (não Fargate), com perfil de nó **`t3.small` (x86)** e no mínimo **um nó por AZ**. A alta disponibilidade e a escala da aplicação residem na **camada de pod** — múltiplas réplicas com spread por AZ (`topologySpreadConstraints`/anti-affinity) e HPA —, tirando proveito da natureza **stateless** da aplicação; o node group apenas oferece pluralidade de nós e AZs como terreno.

O banco de dados sai do cluster para o **Amazon RDS**, em topologia **Multi-AZ com instância standby síncrona**: primário em uma AZ e standby em outra, com **failover automático**. O standby é de contingência e **não é legível** — não serve escala de leitura nem HA de réplicas ativas.

O que pesou mais: o Kubernetes é padrão da empresa e o time de DevOps já o domina, o que supera a economia marginal do ECS; os Managed Node Groups devolvem o controle desejado sobre provisionamento e placement sem a operação de banco no cluster; e mover o estado para o RDS torna a app genuinamente stateless, viabilizando escala horizontal barata e eliminando o risco de rodar banco stateful em nós recicláveis.

## Consequências

- **Positivas:**
  - Alinhamento com o padrão Kubernetes da organização e reuso direto do conhecimento do time de DevOps.
  - Aplicação stateless com HA e escala horizontal na camada de pod: réplicas espalhadas por 3 AZs, sobreviventes à perda de nó ou de zona.
  - Controle sobre provisionamento de recurso e placement via Managed Node Groups.
  - Camada de dados gerenciada (backup, patch e failover automático pelo RDS Multi-AZ), sem o antipadrão de banco stateful no cluster.
  - Perfil de nó enxuto (`t3.small`) adequado a uma app leve, com custo dominado pela pluralidade de nós/AZs e não pelo tamanho de cada nó.

- **Negativas:**
  - Assume-se a operação do control plane do EKS (custo fixo) e do ciclo de vida dos nós (upgrades, reciclagem).
  - Os 2 GB de memória do `t3.small` são partilhados entre o overhead do EKS (kubelet + DaemonSets) e os pods; sob empilhamento de réplicas no mesmo nó, o caminho é escalar horizontalmente (mais nós), não verticalizar.
  - Escalar a aplicação horizontalmente **não** escala o banco: o RDS tem primário único legível, que passa a ser o teto de throughput de dados.
  - Mais réplicas × workers Gunicorn tendem a pressionar o `max_connections` do RDS — mitigação por pool de conexões (ex.: pgbouncer) fica pendente e fora do escopo desta ADR.

- **Neutras / trade-offs aceitos:**
  - Nós em múltiplas AZs acessam o primário RDS **cross-AZ**: latência desprezível (~1–2 ms) e custo mínimo de transferência entre AZs.
  - Escolha de **x86 (`t3`)** em vez de Graviton: abre-se mão de melhor preço/desempenho para evitar, por ora, o build multi-arch da imagem.
  - Conectividade RDS (subnets privadas + Security Group liberando os nós do EKS na 5432) é premissa de rede a detalhar no material de deploy, fora desta decisão.
  - **Companheiro natural não decidido aqui:** Cluster Autoscaler ou Karpenter para que os nós acompanhem a escala dos pods.
  - **Dívidas herdadas (ADR 001) que ganham relevância com escala horizontal:** criação de schema no boot (`create_all`) vira corrida entre réplicas, e o segredo hardcoded permanece pendente. Apenas registradas, sem decisão nesta ADR.
