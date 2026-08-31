# Design — Manifesto Kubernetes

## Context

A ADR 002 fixou o alvo original de produção: **Amazon EKS** com Managed Node Groups `t3.small`
(x86), mínimo de um nó por AZ em 3 AZs, e banco em **Amazon RDS Multi-AZ** fora do cluster. A
ADR 003 revisou a parte de banco: o Postgres passa a rodar **dentro do cluster**
(`StatefulSet` + `PersistentVolumeClaim`), mantendo o compute (EKS) como a ADR 002 decidiu. A
ADR 001 entregou o artefato: a imagem única, não-root, servida por Gunicorn, construída no
change `containerizacao-docker`. O que falta é o manifesto que liga tudo isso.

O estado alvo desta mudança:

```
   ┌──────────────────────── namespace: encontros-tech ─────────────────────────┐
   │                                                                            │
   │   ConfigMap ──┐                                                            │
   │   (env não-   │                                                            │
   │    sensível)  ▼                                                            │
   │            ┌─────────────────────┐                                        │
   │  Secret ──▶│ Deployment (1 pod)  │◀── ServiceAccount                      │
   │  (externo) │ teclinux/encontros- │    (sem token montado)                 │
   │  DATABASE_ │ tech-prd:1.0.0      │                                        │
   │  URL       │                     │                                        │
   │            │ runAsNonRoot        │                                        │
   │  imagePull │ readOnlyRootFS      │                                        │
   │  Secret ──▶│  + emptyDir /tmp    │                                        │
   │  (externo) │                     │                                        │
   │            │ ready: httpGet /    │                                        │
   │            │ live:  tcp :8000    │                                        │
   │            └──────────┬──────────┘                                        │
   │                       │ :8000                                             │
   │            ┌──────────▼──────────┐                                        │
   │            │ Service (ClusterIP) │                                        │
   │            └─────────────────────┘                                        │
   │                                                                            │
   │                       │ DATABASE_URL → postgres.encontros-tech.svc:5432    │
   │                       ▼                                                    │
   │            ┌─────────────────────┐                                        │
   │  Secret ──▶│ StatefulSet (1 pod) │◀── Service headless (postgres)         │
   │  (externo) │ postgres:16-alpine  │                                        │
   │  POSTGRES_ │                     │                                        │
   │  USER/PASS │  volumeClaimTemplate│                                        │
   │  /DB       │  ──▶ PVC "data" (1Gi, ReadWriteOnce)                         │
   │            └─────────────────────┘                                        │
   └────────────────────────────────────────────────────────────────────────────┘
```

Três lacunas do repositório moldam este design e aparecem repetidamente abaixo: **não há
`/health` nem `/ready`** (PRD-0001 nunca implementado), **`create_all` roda em tempo de import**
(`src/main.py:30`), e **a ADR 002 promete HA que uma réplica não entrega** — dívida que a ADR 003
estende também ao banco, agora sem o failover automático que o RDS Multi-AZ dava.

## Goals / Non-Goals

**Goals:**

- Um manifesto aplicável (`kubectl apply -f k8s/manifesto.yaml`) que sobe a aplicação no EKS.
- Endurecimento de segurança coerente com a ADR 001 (não-root) e com as boas práticas do
  Kubernetes — sem privilégios, sem capabilities, raiz somente-leitura.
- Nenhum segredo versionado no repositório.
- Registrar com honestidade o que **não** está cumprido, para que a distância entre a ADR 002 e
  a realidade fique visível no repositório, e não apenas na cabeça de quem escreveu.

**Non-Goals:**

- Alta disponibilidade (ver D2), Ingress, IaC, CI/CD, HPA, PDB — vale também para o Postgres
  (ver D12): réplica única, sem failover.
- Implementar `/health` e `/ready` (PRD-0001) ou alterar qualquer coisa em `src/`.
- Backup/restore, upgrade de versão e monitoramento do volume do Postgres (ver D12/ADR 003).

## Decisions

### D1 — Arquivo único multi-documento em `k8s/`

**Decisão:** todos os recursos em `k8s/manifesto.yaml`, separados por `---`, com o `Namespace`
como **primeiro documento**.

A convenção mais difundida é um recurso por arquivo, ou Kustomize com bases e overlays. Para
cinco recursos de uma aplicação única, isso adicionaria estrutura sem pagar por si. O arquivo
único mantém a implantação inteira legível numa tela.

A ordem importa: `kubectl apply` processa os documentos na ordem em que aparecem, e recursos
com `namespace: encontros-tech` falham se o `Namespace` ainda não existir. Colocá-lo primeiro
resolve.

**Custo aceito:** quando surgir um segundo ambiente (homologação, produção), o arquivo único
tende a virar duplicação — é o ponto em que Kustomize passa a valer, e a migração ficará
pendente.

### D2 — Réplica única: HA conscientemente adiada · **DÍVIDA 1**

A ADR 002 é explícita: *"A alta disponibilidade e a escala da aplicação residem na camada de pod
— múltiplas réplicas com spread por AZ (`topologySpreadConstraints`/anti-affinity) e HPA"*.
Este manifesto entrega **uma réplica**.

```
        AZ-1            AZ-2            AZ-3
         │               │               │
         ▼               ▼               ▼
      (vazio)      [ pod único ]      (vazio)

   Perder esse nó, ou essa AZ  ──▶  aplicação inteira fora do ar.
   O node group continua com 3 AZs; a app não usa nenhuma delas.
```

**Decisão:** aceitar, como estado provisório declarado. A ADR 002 **continua valendo como alvo**
— não está revogada nem emendada. O caminho de saída é conhecido e barato (subir `replicas`,
adicionar `topologySpreadConstraints` e um `PodDisruptionBudget`), e não exige rediscussão de
arquitetura.

**Por que isso é dívida e não configuração:** a linha "Disponibilidade/SLA" do TRD descreve
réplicas espalhadas por 3 AZs como característica do sistema. Enquanto este manifesto for o que
está no ar, essa linha descreve uma intenção, não o comportamento real.

### D3 — Probes provisórias · **DÍVIDA 3**

`/health` e `/ready` não existem no código. As probes precisam apontar para alguma coisa.

| | readinessProbe | livenessProbe |
|---|---|---|
| Alvo | `httpGet /` | `tcpSocket :8000` |
| Toca o banco? | **Sim** (a rota lista eventos) | **Não** |
| Efeito ao falhar | Pod sai da rotação do Service | Pod é **reiniciado** |

**Decisão:** readiness em `/`, liveness em TCP.

A readiness em `/` é uma aproximação defensável do P5 do PRD-0001: com o banco fora, a rota
tende a devolver 500, o pod sai da rotação e **não** é reiniciado. Não é o contrato do PRD
(o corpo não diagnostica nada, e um 500 por bug de aplicação seria confundido com banco fora),
mas produz o efeito principal.

A liveness em TCP é deliberadamente um **sinal fraco**:

```
   tcpSocket :8000  ──▶  o socket do master do Gunicorn está aberto?

   detecta ......... processo morto; master que largou o socket
   NÃO detecta ..... todos os workers encalhados com o socket ainda aberto
   independente do banco  ← o ponto (R1/I2 do PRD-0001: vivacidade
                            não pode depender de dependência externa)
```

A alternativa — liveness em `/` — foi rejeitada: transformaria uma indisponibilidade transitória
do RDS (exatamente o failover Multi-AZ que a ADR 002 celebra) em reinício do pod, que é a
patologia que o PRD-0001 existe para eliminar.

**Saída da dívida:** quando o PRD-0001 for implementado, `readinessProbe` → `httpGet /ready` e
`livenessProbe` → `httpGet /health`. Só então a promessa da ADR 002 fica cumprida.

### D4 — Boot acoplado ao banco: sem rede de proteção no cluster · **DÍVIDA 2**

`src/main.py:30` chama `Base.metadata.create_all(bind=engine)` em **tempo de import**. O change
`containerizacao-docker` registrou isso como dívida (seu D2) e aceitou-a em desenvolvimento,
onde o `depends_on: condition: service_healthy` do Compose segura a aplicação até o banco estar
pronto. **Em Kubernetes não existe equivalente.**

```
   pod é agendado (rollout, nó reciclado, reagendamento)
        │
        ▼
   import de main.py  ──▶  create_all()  ──▶  RDS inacessível
        │
        ▼
   exceção no import → processo morre
        │
        ▼
   o container encerra com código ≠ 0
        │
        ▼
   kubelet reinicia → CrashLoopBackOff (backoff progressivo)

   ⚠ Nenhuma probe participa disso. O processo morre ANTES de existir
     servidor HTTP; readiness e liveness nunca chegam a ser avaliadas.
     A readiness provisória de D3 não cobre este caso.
```

Alternativas consideradas:

- **(a) InitContainer que espera o banco** — resolveria o boot, mas apenas empurra a espera para
  outro container; e insere comportamento que o PRD-0001 deliberadamente não especificou (seu
  F2 manda o "como" para ADR/TRD, mas o "o quê" — P7, boot gracioso — é requisito de produto
  ainda não implementado).
- **(b) Mover `create_all` para fora do import** — é alteração de aplicação, fora do escopo
  "manifesto"; e é justamente parte do que o PRD-0001 exige (P7/I4).
- **(c) Aceitar e registrar.**

**Decisão: (c)**, coerente com o precedente do change anterior. A dívida não é nova — é a mesma,
agora com consequência maior: em dev ela custa uma mensagem de erro; em produção, com réplica
única tanto na aplicação quanto no banco (D2, D12), um Postgres indisponível no momento errado
— por exemplo, `postgres-0` ainda remontando o PVC após reciclo de nó — significa a aplicação
inteira em `CrashLoopBackOff` até o banco voltar. Sem o failover do RDS Multi-AZ, essa janela de
indisponibilidade tende a ser maior do que era antes da ADR 003.

### D5 — Segredos e credencial de registry fora do repositório

**Decisão:** o manifesto **referencia** três secrets por nome; nenhum é versionado.

| Secret | Conteúdo | Por que fora do repo |
|---|---|---|
| `encontros-tech-db` | `DATABASE_URL`, apontando para o Postgres interno (ver D12) | `Secret` do Kubernetes é **base64, não criptografia** — versioná-lo publicaria a credencial |
| `encontros-tech-db-postgres` | `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` do `StatefulSet` (ver D12) | idem — mesma credencial que compõe o `DATABASE_URL` acima |
| `dockerhub-pull` | credencial do Docker Hub privado (ADR 001) | idem; é credencial de conta, não de aplicação |

Todos passam a ser **pré-requisito operacional** do `kubectl apply`, documentado no README. A
consequência aceita é que o manifesto não é auto-suficiente: aplicá-lo num cluster limpo sem
criar os secrets antes produz um pod em `CreateContainerConfigError` / `ImagePullBackOff`.

A alternativa madura (External Secrets Operator, Sealed Secrets, IRSA + Secrets Manager) fica
registrada como evolução natural — mas depende de infraestrutura de cluster que a ADR 002
explicitamente não decidiu.

### D6 — `readOnlyRootFilesystem: true` exige `emptyDir` em `/tmp`

A boa prática pede raiz somente-leitura. A aplicação precisa escrever em exatamente um lugar:
`PROMETHEUS_MULTIPROC_DIR = /tmp/prometheus_multiproc`.

```
   readOnlyRootFilesystem: true
        │
        ├─ toda a árvore do container fica somente-leitura
        │
        └─ volume emptyDir montado em /tmp  ──▶  única região gravável

   O mount sobre /tmp apaga o mkdir/chown que o Dockerfile fez ali.
   Isso NÃO quebra nada: gunicorn.conf.py (on_starting) e src/main.py
   recriam o diretório no boot com os.makedirs(..., exist_ok=True).
```

O `emptyDir` também satisfaz, de graça, o cenário *"reinício não deixa métricas residuais"* da
spec `observabilidade`: o volume nasce vazio a cada pod.

**Decisão:** `readOnlyRootFilesystem: true` + `emptyDir` em `/tmp`, sem alterar código.

### D7 — Sem `PersistentVolumeClaim` no `Deployment` da aplicação

**Decisão:** a aplicação continua sem armazenamento persistente — só o Postgres tem PVC (D12).

O único diretório gravável do container da aplicação é o de métricas multiproc, que **deve** ser
efêmero — persistir contadores entre pods produziria exatamente as "métricas residuais" que a
spec `observabilidade` proíbe. Isso não mudou com a ADR 003: o que passou a ter estado local no
cluster foi o Postgres, não a aplicação.

### D8 — `GUNICORN_WORKERS` explícito no ConfigMap

Este é o ponto onde o manifesto precisa corrigir uma armadilha do `gunicorn.conf.py`:

```python
workers = int(os.getenv("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
```

`multiprocessing.cpu_count()` lê as CPUs do **nó**, não o limite de CPU do cgroup do container.
Num `t3.small` (2 vCPUs), o default vira **5 workers** — cinco processos Flask dentro de um
limite de memória de 256Mi, com o `limits.cpu` de 500m servindo apenas para estrangular todos
eles. O resultado provável é `OOMKilled`.

**Decisão:** fixar `GUNICORN_WORKERS` explicitamente no `ConfigMap` (valor inicial: `2`), nunca
deixar o default agir dentro do cluster.

### D9 — Dimensionamento conservador, para ser corrigido por observação

**Decisão:** `requests` `128Mi`/`250m`, `limits` `256Mi`/`500m`.

Não há medição de consumo real da aplicação — os valores são um chute deliberadamente modesto,
adequado ao `t3.small` cujos 2 GB são partilhados com o overhead do EKS (kubelet + DaemonSets),
conforme a ADR 002. `requests` baixos favorecem o agendamento; `limits` contêm o dano de um
vazamento.

O par (D8, D9) é o mais frágil deste design: 1 master + 2 workers dentro de 256Mi é plausível,
não verificado. A verificação mede o RSS real e ajusta — ver Riscos.

### D10 — Tag de imagem versionada, `ServiceAccount` dedicada, labels padrão

Três escolhas de higiene, agrupadas por serem pouco controversas:

- **`teclinux/encontros-tech-prd:1.0.0`**, espelhando `SERVICE_VERSION`. `latest` tornaria o
  que está rodando indeterminado e quebraria o rastreio que a ADR 001 pediu (tag versionada
  além da corrente).
- **`ServiceAccount` dedicada com `automountServiceAccountToken: false`** — a aplicação não fala
  com a API do Kubernetes; montar o token seria entregar credencial sem uso. Usar a
  `ServiceAccount` `default` do namespace funcionaria, mas mistura identidades.
- **Labels `app.kubernetes.io/*`** (`name`, `instance`, `version`, `component`, `part-of`,
  `managed-by`) em todos os recursos, com o seletor do `Deployment`/`Service` apoiado num
  subconjunto **imutável** (`name` + `instance`) — `version` muda a cada release e não pode
  entrar em `selector.matchLabels`, que é imutável após a criação do Deployment.

### D11 — Identidade única de imagem, declarada também no Compose

A ADR 001 decidiu "imagem única, reaproveitável no alvo Kubernetes", e a spec
`empacotamento-container` repete a promessa. Mas o `docker-compose.yml` tem apenas `build: .`,
sem `image:` — e o Compose então batiza o resultado com um nome derivado do diretório:

```
   hoje                              com D11
   ────                              ───────
   compose build                     compose build
        ▼                                 ▼
   encontros-tech_prd-app:latest     teclinux/encontros-tech-prd:1.0.0
                                              │
   manifesto k8s                              │  mesma identidade
        ▼                                     ▼
   teclinux/encontros-tech-prd:1.0.0   manifesto k8s

   duas imagens com o mesmo conteúdo     uma imagem
   e nomes diferentes
```

**Decisão:** declarar `image: teclinux/encontros-tech-prd:1.0.0` no serviço `app` do
`docker-compose.yml`, ao lado do `build:` existente. O `docker compose build` passa a produzir
exatamente o artefato que o cluster consome, e o teste em kind (ver tasks) carrega essa imagem
direto, sem passar pelo registry.

Sem isso, "imagem única" é verdade apenas no nível do Dockerfile, não no nível do artefato — e
a paridade dev/prod que motivou a ADR 001 se perde justamente onde deveria ser verificável.

**Trade-off aceito:** a tag `1.0.0` fica fixa no Compose, então builds de desenvolvimento
sobrescrevem a mesma tag e ela deixa de identificar univocamente um conteúdo na máquina local.
Isso incomoda pouco no dia a dia — em dev o código vem do bind mount, não da imagem (D3 do change
`containerizacao-docker`) — mas exige disciplina antes de publicar: **rebuild limpo antes do
`docker push`**. A alternativa (tag vinda de variável de ambiente, com default de dev) foi
considerada e rejeitada por reintroduzir divergência entre os arquivos, que é o problema que esta
decisão existe para eliminar.

### D12 — Postgres em `StatefulSet` + PVC, no mesmo arquivo · substitui o RDS (ADR 003)

**Decisão:** o Postgres roda dentro do cluster como `StatefulSet` de 1 réplica
(`postgres:16-alpine`), com `PersistentVolumeClaim` via `volumeClaimTemplates` (`1Gi`,
`ReadWriteOnce`) e exposto por um `Service` **headless** (`clusterIP: None`) — o padrão correto
para dar identidade de rede estável ao pod de um `StatefulSet`. Entra em `k8s/manifesto.yaml`,
mantendo D1 (arquivo único): não se justifica separar em outro arquivo por um único recurso a
mais.

A ADR 002 já havia avaliado "banco em container dentro do cluster" e rejeitado, mas registrou
que, se essa rota fosse tomada, "o mínimo aceitável seria `StatefulSet` com storage persistente"
— nunca um `Deployment` puro (sem identidade estável de volume, um reagendamento pode perder a
associação pod↔disco). Esta decisão aplica esse próprio critério.

Credenciais seguem o padrão de D5: um `Secret` `encontros-tech-db-postgres`
(`POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`), criado manualmente e nunca versionado,
consumido via `envFrom.secretRef` pelo `StatefulSet`. O `Secret` `encontros-tech-db` da aplicação
passa a apontar para `postgres.encontros-tech.svc.cluster.local:5432` em vez de um endpoint RDS.

**Custo aceito, herdado da ADR 003:** perde-se o failover automático, backup gerenciado e patch
automático que o RDS Multi-AZ dava. Um nó reciclado onde `postgres-0` está agendado é
indisponibilidade do banco até o `StatefulSet` reagendar e remontar o PVC — sem standby síncrono.
Isso soma à dívida 1 (D2): agora tanto a aplicação quanto o banco são pontos únicos de falha.

## Risks / Trade-offs

| Risco | Mitigação |
|---|---|
| **Postgres fora/indisponível no momento em que o pod da app sobe → `CrashLoopBackOff`, e com 1 réplica isso é a app inteira fora** | Aceito por decisão (D4/D2); registrado no TRD. Saída real é o PRD-0001 (P7: boot gracioso) |
| **Perda de um nó ou AZ derruba a aplicação e/ou o Postgres** | Aceito e declarado (D2, D12). Saída conhecida e barata para a app: `replicas` > 1 + spread + PDB. Para o Postgres exige mais (Patroni/operador de HA) — não decidido |
| **Perda do nó onde `postgres-0` está agendado → indisponibilidade do banco até reagendar e remontar o PVC, sem standby síncrono** | Aceito por decisão (ADR 003/D12); é a perda mais significativa em relação ao RDS Multi-AZ que esta mudança de plano introduz |
| **2 workers + master estourarem o limite de 256Mi → `OOMKilled`** | Verificar RSS real com `kubectl top pod` sob uso; ajustar `limits` ou `GUNICORN_WORKERS`. Prioridade na verificação (D8/D9) |
| **`readinessProbe` em `/` confunde bug de aplicação (500) com banco indisponível** | Aceito como aproximação (D3); resolvido quando `/ready` existir |
| **Manifesto não é auto-suficiente: exige 3 secrets criados à mão** | Documentar como pré-requisito no README; falha é ruidosa e diagnosticável (`ImagePullBackOff`, `CreateContainerConfigError`) |
| **`readOnlyRootFilesystem` quebrar alguma escrita não mapeada** | O único caminho de escrita conhecido é o diretório multiproc (D6); a verificação deve confirmar que `/metrics` responde no pod |
| **Arquivo único virar duplicação ao surgir um segundo ambiente** | Aceito (D1); Kustomize é a evolução natural quando isso acontecer |
| **Tag fixa no Compose ser sobrescrita por builds de dev e publicada sem querer** | Rebuild limpo antes do `docker push`, documentado no README (D11) |
| **`PersistentVolumeClaim` do Postgres depende da `StorageClass` `default` do cluster de destino, não fixada** | Aceito (D12); ajustar quando o cluster real (EKS) for provisionado |

## Migration Plan

Não há migração de estado — é uma primeira implantação. Sequência:

1. Publicar `teclinux/encontros-tech-prd:1.0.0` no Docker Hub (publicação manual, ADR 001).
2. Criar o `Namespace` e, dentro dele, os três secrets (`encontros-tech-db-postgres`,
   `encontros-tech-db`, `dockerhub-pull`).
3. `kubectl apply -f k8s/manifesto.yaml`.
4. Verificar: pods `Running` e `Ready` (app e `postgres-0`), `/` respondendo via `port-forward`,
   processo da app não-root, `/metrics` agregando, consumo de memória dentro do limite.

**Rollback:** `kubectl delete -f k8s/manifesto.yaml` remove tudo, **incluindo o `PersistentVolumeClaim`
do Postgres se a `StorageClass` usada tiver `reclaimPolicy: Delete`** (o default mais comum) —
diferente do estado anterior (D7 original), o rollback agora **pode perder dados** do banco. Ver
ADR 003: essa é justamente a garantia que o RDS Multi-AZ dava e que foi trocada pela eliminação
da dependência externa.

## Open Questions

- **Quando a HA entra?** D2 é provisório por definição, mas nada fixa o gatilho — próxima
  release? Antes de tráfego real? Fica em aberto, e é a pergunta mais importante da lista.
- **`GUNICORN_WORKERS = 2` sobrevive à medição?** Depende do RSS real, ainda não medido.
- **Anotações de scrape do Prometheus** (`prometheus.io/scrape`, `/port`, `/path`) devem entrar
  no `Deployment`? A spec `observabilidade` exige que `/metrics` agregue corretamente, mas quem
  coleta no cluster não está decidido — o TRD registra o dono do Prometheus como "não definido".
- **Namespace por ambiente ou cluster por ambiente?** Só existe um ambiente hoje; a resposta
  muda o desenho no momento em que surgir o segundo (ver D1).
- **Backup do Postgres em cluster?** A ADR 003 troca o backup automático do RDS por nada — fica
  em aberto se/quando um `CronJob` de `pg_dump`, um snapshot do volume, ou um operador dedicado
  entra no escopo.
