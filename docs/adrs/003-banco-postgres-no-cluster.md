---
adr_number: "003"
status: aceito
created: 2026-08-30
supersedes: "002"
superseded_by: ""
---

# ADR 003: Banco de dados em PostgreSQL dentro do cluster, substituindo o RDS

## Contexto

A ADR 002 decidiu compute em Amazon EKS e banco em Amazon RDS Multi-AZ, fora do cluster. Ela
considerou explicitamente "Banco em container dentro do cluster" como alternativa e a rejeitou,
citando risco de corrupção/perda de dados no reciclo de nós e a complexidade de desenhar storage,
backup e failover manualmente — mas já registrou que, se essa rota fosse tomada, "o mínimo
aceitável seria `StatefulSet` com storage persistente", nunca um `Deployment` puro.

A decisão mudou: o banco passa a rodar **dentro do cluster**, eliminando o RDS como dependência
externa. Esta ADR aplica o próprio critério mínimo que a ADR 002 havia deixado registrado.

## Decisão

O compute continua como a ADR 002 decidiu: **Amazon EKS** com Managed Node Groups. Isso **não**
muda.

O que muda é a camada de dados: o PostgreSQL passa a rodar como um **`StatefulSet` de uma réplica,
com `PersistentVolumeClaim`**, dentro do próprio namespace `encontros-tech`, exposto por um
`Service` `ClusterIP` interno. `k8s/manifesto.yaml` continua sendo o único arquivo de implantação
— o `StatefulSet`, o `Service` e o `PersistentVolumeClaim` do banco entram nele, na mesma ordem de
dependência que os demais recursos (depois do `Namespace`).

As credenciais do banco continuam **fora do repositório** (ver ADR 002 / D5 do manifesto): um
`Secret` com usuário/senha/nome do banco, consumido tanto pelo `StatefulSet` do Postgres quanto
pela variável `DATABASE_URL` da aplicação, criado manualmente no namespace antes do
`kubectl apply`.

## Alternativas Consideradas

- **Manter RDS (ADR 002 original)** — mais operacionalmente seguro (backup, failover, patch
  gerenciados), mas foi descartado pela decisão de negócio de eliminar a dependência de um serviço
  gerenciado externo ao cluster.
- **`Deployment` simples para o Postgres** — mais simples de escrever, mas a própria ADR 002 já
  qualificou isso como antipadrão: sem identidade estável de volume, um reagendamento pode montar
  o `PersistentVolume` errado ou perder a associação pod↔disco. Rejeitado.
- **`StatefulSet` com `PersistentVolumeClaim`** — replica a topologia mínima que um banco stateful
  exige em Kubernetes (identidade de rede estável, um volume dedicado por réplica). **Escolhida.**

## Consequências

- **Positivas:**
  - Elimina a dependência de um serviço gerenciado externo (RDS) — implantação inteira contida no
    cluster, único `kubectl apply`.
  - `k8s/manifesto.yaml` continua auto-suficiente para a topologia de rede: não há mais
    conectividade cross-serviço com a AWS a configurar para o banco.

- **Negativas:**
  - **Perde tudo que o RDS Multi-AZ dava de graça:** failover automático, backup gerenciado,
    patch automático. Um nó reciclado onde o pod do Postgres está agendado é indisponibilidade do
    banco até o `StatefulSet` reagendar e remontar o `PersistentVolume` — sem standby síncrono.
  - **Escala horizontal da aplicação não escala o banco** (isso já era verdade com RDS single-
    primary, mas agora sem read replica gerenciada como opção futura de baixo esforço).
  - Backup/restore, upgrade de versão do Postgres e monitoramento do volume passam a ser
    responsabilidade deste repositório — nenhum desses pontos está resolvido por esta ADR.
  - `StatefulSet` de uma réplica é ponto único de falha para o banco, sem caminho de HA sem
    reintroduzir a complexidade que o RDS existia para absorver (réplicas Postgres, operador de
    HA como Patroni/Zalando etc.) — não decidido aqui.

- **Neutras / trade-offs aceitos:**
  - O `PersistentVolumeClaim` depende da `StorageClass` do cluster de destino (no EKS, tipicamente
    `gp3` via EBS CSI driver) — não fixada nesta ADR, fica como configuração de ambiente.
  - Dívidas herdadas da ADR 002 que dependiam do RDS (pool de conexões para `max_connections`)
    mudam de natureza mas não desaparecem: agora é `max_connections` do Postgres em pod, com
    recursos definidos pelo próprio manifesto, não por uma instância gerenciada.
