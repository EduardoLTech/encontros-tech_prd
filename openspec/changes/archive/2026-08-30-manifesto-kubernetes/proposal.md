# Manifesto Kubernetes: implantação da imagem única em EKS

## Why

A ADR 002 (aceita, 2026-07-12) decidiu executar a aplicação em **Amazon EKS** com Managed Node
Groups e banco em **Amazon RDS Multi-AZ**. A ADR 003 (aceita, 2026-08-30) revisou a parte de
banco: o Postgres passa a rodar **dentro do cluster** (`StatefulSet` + `PersistentVolumeClaim`),
eliminando o RDS como dependência externa; a decisão de compute (EKS) não mudou. A ADR 001 já
entregou o artefato que o cluster consome — a imagem única, construída no change
`containerizacao-docker` (arquivado em 2026-08-30). Faltava o elo final: **o repositório não
tinha nenhum manifesto Kubernetes**. A decisão existe, a imagem existe, mas não havia como
implantá-la.

Esta mudança escreve esse manifesto. Ela é deliberadamente **menor que a ambição da ADR 002**:
entrega uma implantação funcional e segura de **uma réplica**, deixando a alta disponibilidade
(múltiplas réplicas, spread por AZ, HPA) para um passo posterior. Isso é uma escolha consciente,
registrada como dívida — não um esquecimento.

## What Changes

- **`k8s/manifesto.yaml`** — arquivo único multi-documento (separado por `---`) contendo, nesta
  ordem: `Namespace`, `ServiceAccount`, `ConfigMap`, `Deployment` e `Service`.
- **`Namespace` `encontros-tech`** como primeiro documento do arquivo, evitando corrida de
  criação no `kubectl apply`.
- **`Deployment`** de **1 réplica** da imagem `teclinux/encontros-tech-prd:1.0.0` (tag versionada
  explícita, nunca `latest`), com:
  - `securityContext` restritivo: `runAsNonRoot`, `allowPrivilegeEscalation: false`,
    `capabilities.drop: [ALL]`, `readOnlyRootFilesystem: true`
  - volume `emptyDir` montado em `/tmp` — exigido pelo sistema de arquivos raiz somente-leitura,
    já que `PROMETHEUS_MULTIPROC_DIR` aponta para `/tmp/prometheus_multiproc`
  - `readinessProbe` `httpGet /` e `livenessProbe` `tcpSocket :8000` (ambas **provisórias**)
  - `requests` de `128Mi`/`250m` e `limits` de `256Mi`/`500m`
  - referência a um `Secret` externo para `DATABASE_URL` e a `imagePullSecrets` para o registry
    privado — **ambos criados fora do repositório**
- **`Service`** do tipo `ClusterIP` na porta 8000.
- **`StatefulSet` `postgres`** de 1 réplica (`postgres:16-alpine`), com `PersistentVolumeClaim`
  (`volumeClaimTemplates`, `1Gi`, `ReadWriteOnce`) e `Service` headless (`clusterIP: None`) na
  porta 5432 — substitui o RDS como camada de dados, conforme ADR 003. Credenciais
  (`POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`) vêm de um `Secret` externo, mesmo padrão do
  `DATABASE_URL` da aplicação (D5).
- **`ConfigMap`** com as variáveis não-sensíveis já consumidas pela aplicação
  (`GUNICORN_WORKERS`, `GUNICORN_LOG_LEVEL`, `LOG_LEVEL`, `SERVICE_NAME`, `SERVICE_VERSION`,
  `PROMETHEUS_MULTIPROC_DIR`).
- **`ServiceAccount`** dedicada, com `automountServiceAccountToken: false` — a aplicação não
  conversa com a API do Kubernetes.
- **Labels `app.kubernetes.io/*`** recomendadas em todos os recursos.
- **Documentação** do procedimento de criação dos secrets e do fluxo de aplicação do manifesto.

## Non-Goals

Ficam **explicitamente fora**, para não vazar escopo:

- **Ingress, Registry, Infraestrutura como Código e CI/CD** — a própria ADR 002 os exclui do
  escopo da decisão. O `Service` é `ClusterIP`; como o tráfego externo chega até ele é assunto
  de outra etapa.
- **Alta disponibilidade** — HPA, `topologySpreadConstraints`/anti-affinity e
  `PodDisruptionBudget` não entram. Ver a dívida 1 em `design.md`. Vale também para o Postgres:
  segue réplica única, sem failover (ADR 003 já registra essa perda em relação ao RDS Multi-AZ).
- **Implementação do PRD-0001 (`/health` e `/ready`)** — continua não implementado; as probes
  desta mudança são provisórias por consequência. Ver a dívida 3.
- **Backup/restore, upgrade de versão e monitoramento do volume do Postgres** — a ADR 003 decide
  rodar o banco no cluster, mas não resolve nenhuma dessas responsabilidades que o RDS cobria de
  graça; ficam registradas como dívida, não endereçadas aqui.
- **`StorageClass` explícita no `PersistentVolumeClaim`** — usa a `default` do cluster de destino;
  fixar uma classe específica (ex.: `gp3` no EKS) fica para quando o ambiente real for definido.
- **Ferramenta de migração de schema (Alembic)** e **`SECRET_KEY` fixada em `src/main.py:34`** —
  dívidas herdadas das ADRs 001/002, sem decisão; não são endereçadas aqui.
- **Alterações no código da aplicação** — esta mudança não toca `src/`. O manifesto se adapta ao
  comportamento atual da aplicação, inclusive aos seus defeitos conhecidos.

## Capabilities

### New Capabilities

- `implantacao-kubernetes`: como a imagem única é implantada no cluster — identidade e
  isolamento dos recursos, configuração e segredos injetados por ambiente, endurecimento de
  segurança do pod, sinais de saúde consumidos pelo orquestrador, exposição interna do serviço e
  a camada de dados (Postgres em `StatefulSet` com `PersistentVolumeClaim`, conforme ADR 003).

### Modified Capabilities

- `empacotamento-container`: ganha um requisito de **identidade única de imagem**. A capability
  já promete uma imagem "reaproveitável tanto no ambiente de desenvolvimento quanto no alvo
  Kubernetes", mas nada fixa o nome — e o `docker-compose.yml` atual, tendo apenas `build: .`,
  faz o Compose gerar `encontros-tech_prd-app:latest`. Na prática, dev e cluster consumiriam
  identidades diferentes. O novo requisito fecha essa lacuna.

A capability `observabilidade` **não** muda: o manifesto apenas precisa satisfazer seus
requisitos existentes (diretório multiproc gravável e limpo a cada start) em um ambiente novo.

## Impact

- **Affected specs:** `implantacao-kubernetes` (novo), `empacotamento-container` (novo requisito
  de identidade de imagem)
- **Affected code:**
  - novo: `k8s/manifesto.yaml` (inclui `StatefulSet`/`Service`/`PVC` do Postgres), ADR 003
  - alterado: `docker-compose.yml` (declarar `image:` com o mesmo nome e tag do manifesto),
    `README.md` (procedimento de implantação e criação dos secrets), `docs/trd.md`
    (registro das dívidas de implantação), ADR 002 (marcada `superseded` pela ADR 003 na parte
    de banco)
  - **não alterado:** nada em `src/`
- **Dependências operacionais externas ao repositório** (pré-requisitos para o `kubectl apply`
  funcionar): dois secrets de banco (`encontros-tech-db-postgres` com as credenciais do Postgres
  e `encontros-tech-db` com `DATABASE_URL` apontando para o Service interno do banco) e um
  secret de pull do Docker Hub privado, todos criados manualmente no namespace. Não há mais
  dependência de um RDS externo (ver ADR 003).
- **Dívidas conhecidas que esta mudança NÃO remove** (detalhadas em `design.md`): implantação
  com réplica única, sem HA — agora vale tanto para a aplicação quanto para o Postgres, que
  perdeu o failover automático que o RDS Multi-AZ dava; `create_all` em tempo de import podendo
  gerar `CrashLoopBackOff` quando o Postgres não está pronto no momento em que um pod da app
  sobe; probes provisórias enquanto o PRD-0001 não existir; e backup/restore do Postgres em
  cluster, não resolvido por esta mudança.
