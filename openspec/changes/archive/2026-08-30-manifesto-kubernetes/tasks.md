# Tasks — Manifesto Kubernetes

## 1. Estrutura e identidade dos recursos

- [x] 1.1 Criar a pasta `k8s/` na raiz e o arquivo `k8s/manifesto.yaml`
- [x] 1.2 Definir o conjunto de labels `app.kubernetes.io/*` (`name`, `instance`, `version`,
      `component`, `part-of`, `managed-by`) a ser aplicado a todos os recursos, mantendo o
      seletor restrito ao subconjunto imutável `name` + `instance` (ver D10)
- [x] 1.3 Primeiro documento: `Namespace` `encontros-tech` (precisa vir antes de tudo — ver D1)
- [x] 1.4 `ServiceAccount` dedicada com `automountServiceAccountToken: false`

## 2. Configuração e segredos

- [x] 2.1 `ConfigMap` com as variáveis não-sensíveis consumidas por `src/core/settings.py` e por
      `gunicorn.conf.py` (`LOG_LEVEL`, `LOG_FORMAT`, `SERVICE_NAME`, `SERVICE_VERSION`,
      `PROMETHEUS_MULTIPROC_DIR`, `GUNICORN_BIND`, `GUNICORN_LOG_LEVEL`)
- [x] 2.2 Fixar `GUNICORN_WORKERS` explicitamente no `ConfigMap` — sem isso o default lê as CPUs
      do **nó**, não o limite do pod (ver D8)
- [x] 2.3 Referenciar o `Secret` `encontros-tech-db` (chave `DATABASE_URL`) por nome, sem criar
      o recurso nem versionar qualquer valor (ver D5)
- [x] 2.4 Confirmar que nenhum segredo, em texto claro ou base64, entra no repositório

## 3. Deployment

- [x] 3.1 `Deployment` com `replicas: 1` e imagem `teclinux/encontros-tech-prd:1.0.0` (tag
      explícita, nunca `latest`)
- [x] 3.2 `imagePullSecrets` referenciando `dockerhub-pull`, criado externamente (ver D5)
- [x] 3.3 `envFrom` do `ConfigMap` e `env` da chave do `Secret`
- [x] 3.4 `securityContext`: `runAsNonRoot: true`, `allowPrivilegeEscalation: false`,
      `capabilities.drop: [ALL]`, `readOnlyRootFilesystem: true`, `seccompProfile` default
- [x] 3.5 Volume `emptyDir` montado em `/tmp` — exigido pela raiz somente-leitura, já que
      `PROMETHEUS_MULTIPROC_DIR` aponta para dentro dele (ver D6)
- [x] 3.6 `readinessProbe` `httpGet /` na porta 8000 (provisória — ver D3)
- [x] 3.7 `livenessProbe` `tcpSocket :8000`, deliberadamente independente do banco (ver D3)
- [x] 3.8 `resources`: requests `128Mi`/`250m`, limits `256Mi`/`500m` (ver D9)
- [x] 3.9 `containerPort: 8000` nomeado, para o `Service` referenciar pelo nome
- [x] 3.10 **Não** declarar HPA, PDB ou `topologySpreadConstraints` no `Deployment` da aplicação
      — fora de escopo por decisão (D2). `PersistentVolumeClaim` passou a existir, mas só para o
      Postgres (D12) — ver seção 3a

## 3a. StatefulSet do Postgres (ADR 003 — substitui o RDS)

- [x] 3a.1 `StatefulSet` `postgres` com `replicas: 1`, imagem `postgres:16-alpine`, `serviceName`
      apontando para o `Service` headless (ver 4a)
- [x] 3a.2 `envFrom` do `Secret` `encontros-tech-db-postgres` (`POSTGRES_USER`,
      `POSTGRES_PASSWORD`, `POSTGRES_DB`), criado externamente, nunca versionado (mesmo padrão
      de D5)
- [x] 3a.3 `volumeClaimTemplates` com um `PersistentVolumeClaim` `data` (`1Gi`,
      `ReadWriteOnce`), montado em `/var/lib/postgresql/data`
- [x] 3a.4 `readinessProbe` via `pg_isready` e `livenessProbe` via `tcpSocket :5432`
- [x] 3a.5 `resources`: requests `128Mi`/`100m`, limits `256Mi`/`500m` — conservador, sem medição
      real ainda (mesmo espírito de D9)
- [x] 3a.6 Confirmar que nenhuma credencial do Postgres entra no repositório em texto claro

## 4. Service

- [x] 4.1 `Service` do tipo `ClusterIP` na porta 8000, apontando para a porta nomeada do
      container e usando o seletor imutável definido em 1.2

## 4a. Service do Postgres

- [x] 4a.1 `Service` **headless** (`clusterIP: None`) na porta 5432, dando identidade de rede
      estável ao pod do `StatefulSet` (`postgres-0.postgres.encontros-tech.svc.cluster.local`)

## 5. Identidade da imagem no Docker Compose

- [x] 5.1 Declarar `image: teclinux/encontros-tech-prd:1.0.0` no serviço `app` do
      `docker-compose.yml`, ao lado do `build:` existente (ver D11)

## 6. Documentação

- [x] 6.1 Atualizar o `README.md` com o fluxo de implantação: publicar a imagem, criar os dois
      secrets no namespace, aplicar o manifesto
- [x] 6.2 Documentar no `README.md` os comandos de criação dos secrets `encontros-tech-db` e
      `dockerhub-pull`, deixando claro que são pré-requisito e não fazem parte do repositório
- [x] 6.3 Documentar no `README.md` a necessidade de rebuild limpo antes do `docker push`, já que
      a tag `1.0.0` é sobrescrita por builds de desenvolvimento (ver D11)
- [x] 6.4 Registrar no `docs/trd.md` as três dívidas desta implantação: réplica única sem HA
      (contraria a ADR 002, que segue valendo como alvo), `CrashLoopBackOff` no boot com o RDS
      fora, e probes provisórias até o PRD-0001 existir
- [x] 6.5 Registrar no `docs/trd.md` a existência do manifesto em `k8s/` como artefato de
      implantação

## 7. Verificação estática (sem cluster)

- [x] 7.1 Validar a sintaxe e o schema do manifesto
      (`kubectl apply --dry-run=client -f k8s/manifesto.yaml`)
- [x] 7.2 Confirmar a ordem dos documentos: o `Namespace` é o primeiro do arquivo
- [x] 7.3 Revisar o arquivo em busca de qualquer credencial — não deve haver nenhuma

## 8. Verificação do ambiente de desenvolvimento (Docker Compose)

> Roda **antes** da verificação em Kubernetes. A mudança em `docker-compose.yml` mexe no
> ambiente que já funcionava; esta seção prova que nada regrediu e produz a imagem que a
> seção 9 vai consumir.

- [x] 8.1 `docker compose build` produz `teclinux/encontros-tech-prd:1.0.0` — confirmar em
      `docker images` que a tag antiga derivada do diretório (`encontros-tech_prd-app:latest`)
      não é mais o artefato usado pelo serviço `app`
- [x] 8.2 Anotar o **image ID** da imagem recém-construída; ele será reconferido dentro do pod
      na task 9.7, fechando a prova de "imagem única" ponta a ponta (ver D11)
      — `sha256:71fed2b15c4f415b4f82884724e96aed691fb256c84d81ef793229ce23e31725`
- [x] 8.3 `docker compose up` sobe `db` e `app`, e a listagem de eventos responde em `/`
- [x] 8.4 Confirmar que o processo dentro do container **não** roda como root — regressão do
      requisito de usuário não-root da spec `empacotamento-container`
- [x] 8.5 Consultar `/metrics` repetidamente e confirmar valores agregados entre workers —
      regressão da spec `observabilidade`
- [x] 8.6 Alterar um arquivo em `src/` e confirmar que a recarga automática do Gunicorn continua
      funcionando (o bind mount não foi afetado pela mudança de tag)
- [x] 8.7 `docker compose down` encerra o ambiente sem resíduo

## 9. Verificação funcional em cluster kind

> Roda **depois** da seção 8, reaproveitando a imagem que o Compose construiu. O cluster kind
> valida o manifesto de verdade: agendamento, probes, `securityContext` e conectividade.
> **Não** valida o que depende do ambiente real — spread por AZ, failover do RDS e a pressão de
> recurso de um `t3.small`.

- [x] 9.1 Criar o cluster de teste (`kind create cluster --name encontros-tech`)
- [x] 9.2 Carregar no cluster a imagem já construída na task 8.1
      (`kind load docker-image teclinux/encontros-tech-prd:1.0.0 --name encontros-tech`); como a
      tag é explícita, o `imagePullPolicy` cai em `IfNotPresent` e o registry privado não é
      acionado
- [x] 9.3 ~~Subir um PostgreSQL efêmero, imperativo, fora do manifesto~~ — **superado pela ADR
      003**: o Postgres agora é `StatefulSet`/`Service`/`PVC` dentro do próprio
      `k8s/manifesto.yaml` (ver seções 3a/4a), então sobe junto no `kubectl apply` da task 9.5
- [x] 9.4 Criar no namespace os três secrets que o manifesto referencia:
      `encontros-tech-db-postgres` (credenciais do Postgres), `encontros-tech-db` (`DATABASE_URL`
      apontando para `postgres.encontros-tech.svc.cluster.local:5432`) e `dockerhub-pull` como
      placeholder
- [x] 9.5 Aplicar o manifesto e confirmar o pod em `Running` e `Ready`
      — achado real durante a verificação: `runAsNonRoot: true` sozinho falha em
      `CreateContainerConfigError` porque o Dockerfile declara `USER app` (nome, não UID) e o
      kubelet não consegue verificar não-root por nome; corrigido adicionando
      `runAsUser: 999`/`runAsGroup: 999` ao `securityContext` (UID real do usuário `app`,
      confirmado via `docker exec ... id`)
- [x] 9.6 Confirmar que o processo não roda como root (`kubectl exec -- id`) — `uid=999(app)`
- [x] 9.7 Confirmar que o `imageID` reportado pelo pod corresponde ao image ID anotado na task
      8.2 — a mesma imagem que o Compose construiu está rodando no cluster (ver D11). Nota: o
      `imageID` do pod é o digest do **config** da imagem (`sha256:da84767d...`), não o digest do
      manifest-list multi-plataforma que `docker inspect .Id` mostra (`sha256:71fed2b1...`);
      confirmado via `docker save` que o config é o mesmo em ambos os casos — identidade validada
- [x] 9.8 Confirmar via `port-forward` que `/` responde e que `/metrics` responde — prova de que
      a raiz somente-leitura não bloqueou o diretório multiproc (ver D6)
- [x] 9.9 Confirmar que nenhum token de service account está montado no container
- [x] 9.10 Medir o consumo real de memória e confrontar com o limite de `256Mi`; ajustar
      `GUNICORN_WORKERS` ou os limites se estiver perto do teto (ver D8/D9). O kind não traz
      `metrics-server` — instalar (com `--kubelet-insecure-tls`) ou ler o RSS pelo `/proc` de
      dentro do pod. Medido via `/proc/*/status`: master 38,9Mi + 2 workers × 68,9Mi + 1,8Mi ≈
      175Mi de RSS total, ~65% do limite de 256Mi — sem necessidade de ajuste
- [x] 9.11 Derrubar o PostgreSQL com o pod já no ar e confirmar o comportamento esperado: sai da
      rotação do `Service` (some dos `Endpoints`), o contador de `RESTARTS` **permanece zero** e,
      ao religar o banco, o pod volta sozinho (ver D3). Verificado com um Postgres de teste
      apoiado em PVC (Deployment escalado 1→0→1), preservando o schema entre os ciclos: readiness
      falhou (500 → probe HTTP), `Endpoints` esvaziou, `RESTARTS` permaneceu no baseline (1, do
      boot inicial) durante toda a indisponibilidade, e o pod voltou sozinho à rotação quando o
      banco religou — sem intervenção manual e sem reinício
- [x] 9.12 **Reproduzir a dívida 2 deliberadamente:** com o banco fora, recriar o pod
      (`kubectl delete pod`) e confirmar o `CrashLoopBackOff` — registrar a evidência, em vez de
      apenas afirmar a dívida no design (ver D4). Reproduzido: com `test-postgres` escalado a 0 e
      o pod da app recriado, `create_all()` falhou no import
      (`OperationalError: connection to server at "test-postgres" ... Connection refused`), o
      worker morreu, o master encerrou (`Reason: Worker failed to boot`) e o kubelet reportou
      `BackOff restarting failed container` / status `CrashLoopBackOff`
- [x] 9.13 Destruir o cluster de teste (`kind delete cluster --name encontros-tech`)

## 9a. Reverificação após a ADR 003 (Postgres em `StatefulSet`, no manifesto)

> A ADR 003 mudou a decisão desta change depois da verificação original (seção 9): o Postgres
> deixou de ser efêmero/imperativo e passou a fazer parte de `k8s/manifesto.yaml`. Reverificado
> num cluster kind já em uso (não recriado do zero), sem repetir 9.1/9.2/9.13.

- [x] 9a.1 Criar os três secrets (`encontros-tech-db-postgres`, `encontros-tech-db` apontando
      para `postgres.encontros-tech.svc.cluster.local:5432`, `dockerhub-pull`) e aplicar o
      manifesto atualizado
- [x] 9a.2 Confirmar `statefulset.apps/postgres` `1/1` e `pod/postgres-0` `Running`/`Ready`, com
      o `PersistentVolumeClaim` `data-postgres-0` provisionado
- [x] 9a.3 Reiniciar o `Deployment` da aplicação e confirmar reconexão ao Postgres interno via
      `DATABASE_URL` (`postgresql://...@postgres.encontros-tech.svc.cluster.local:5432/...`)
- [x] 9a.4 Confirmar `/` respondendo `200` via `port-forward`, com o Postgres em cluster
