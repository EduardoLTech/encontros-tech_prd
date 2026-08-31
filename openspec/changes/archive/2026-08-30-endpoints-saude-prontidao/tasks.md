# Tasks — Endpoints de saúde e prontidão

> Referências: `specs/saude-prontidao/spec.md`, `specs/implantacao-kubernetes/spec.md` (o quê),
> `design.md` D1–D8 (como), `docs/prds/PRD-0001-health-readiness.md` (critérios de aceite CA1–CA10).
>
> Pré-requisito de ambiente: `cd src && pip install -r requirements-dev.txt`

## 1. Configuração do teto de tempo

- [x] 1.1 Adicionar `READINESS_DB_TIMEOUT_SECONDS` (float, padrão `5.0`) em `src/core/settings.py`,
  com normalização conforme D6: valores `< 2` viram `2.0`; valor não numérico ou negativo aplica o
  padrão e registra aviso — **sem** levantar exceção na inicialização.
  *Validação:* `cd src && python -c "from core.settings import settings; print(settings.READINESS_DB_TIMEOUT_SECONDS)"` → `5.0`
- [x] 1.2 Confirmar tolerância a valor inválido e aplicação do piso.
  *Validação (Bash):* `cd src && READINESS_DB_TIMEOUT_SECONDS=abc python -c "from core.settings import settings; print(settings.READINESS_DB_TIMEOUT_SECONDS)"` → `5.0` + aviso em log;
  `cd src && READINESS_DB_TIMEOUT_SECONDS=0.5 python -c "from core.settings import settings; print(settings.READINESS_DB_TIMEOUT_SECONDS)"` → `2.0`
- [x] 1.3 Documentar a variável em `.env.exemple` (seção nova de saúde/prontidão) e declará-la no
  serviço `app` de `docker-compose.yml`.
  *Validação:* `grep -c READINESS_DB_TIMEOUT_SECONDS .env.exemple docker-compose.yml` → `1` em cada

## 2. Verificação de conectividade com o banco

- [x] 2.1 Criar em `src/core/database.py` o engine dedicado da verificação (D3): `create_engine` com
  `poolclass=NullPool`, separado do `engine` de negócio, que permanece inalterado.
  *Validação:* `cd src && python -c "from core.database import engine, health_engine; print(type(health_engine.pool).__name__, engine is not health_engine)"` → `NullPool True`
- [x] 2.2 Implementar `check_database()` com orçamento por prazo (D2): `connect_timeout = max(2, floor(T))`
  no `connect_args`, `statement_timeout` da sessão derivado do tempo restante, retorno booleano e
  `down` imediato se o restante for `<= 0`. Nenhuma exceção do driver deve escapar da função.
  *Validação:* `cd src && python -m pytest tests -q -k check_database`
- [x] 2.3 Escrever testes unitários de `check_database()` cobrindo: sucesso, conexão recusada,
  autenticação inválida, banco pendurado (estouro do prazo) e ausência de vazamento de detalhe do
  driver no retorno.
  *Validação:* `cd src && python -m pytest tests -q -k check_database` → todos passando

## 3. Endpoints

- [x] 3.1 Criar `src/routers/health_router.py` (D1) com `GET /health` → 200 sem tocar o banco, e
  `GET /ready` → 200/503 com os corpos exatos
  `{"status":"ready","checks":{"database":"ok"}}` / `{"status":"not_ready","checks":{"database":"down"}}`.
  *Validação:* `cd src && python -m pytest tests -q -k "health or ready"`
- [x] 3.2 Registrar o blueprint em `src/main.py`, sem `url_prefix`.
  *Validação:* `cd src && python -c "import main; print([str(r) for r in main.app.url_map.iter_rules() if 'health' in str(r) or 'ready' in str(r)])"` → contém `/health` e `/ready`
- [x] 3.3 Excluir os dois endpoints do exporter Prometheus e do middleware de log de requisição (D8).
  *Validação:* subir a app, consultar `/health` 5×, então `curl -s localhost:8000/metrics | grep -c '/health'` → `0`; nenhuma linha de log de requisição para `/health` no stdout
- [x] 3.4 Testes de integração dos endpoints cobrindo banco disponível, banco fora, corpo exato,
  ausência de autenticação (sem 401/403) e idempotência (P10: contagem de eventos inalterada após N
  consultas).
  *Validação:* `cd src && python -m pytest tests -q`

## 4. Inicialização resiliente

- [x] 4.1 Remover `create_all` do import de `src/main.py` e movê-lo para uma função de preparação de
  schema best-effort, protegida por `try/except` com log, que **não** interrompe o boot (D5).
  *Validação:* `cd src && DATABASE_URL=postgresql://x:x@127.0.0.1:1/x python -c "import main; print('boot ok')"` → imprime `boot ok`
- [x] 4.2 Implementar a thread de reparo com backoff exponencial (1s → teto de 30s), serializada por
  `pg_advisory_lock` para tolerar concorrência entre workers e réplicas (D5).
  *Validação:* `cd src && python -m pytest tests -q -k schema`
- [x] 4.3 Ajustar `depends_on` do serviço `app` em `docker-compose.yml` de `service_healthy` para
  `service_started`, para que o boot resiliente seja exercitável localmente.
  *Validação:* `docker compose up -d app` com o serviço `db` parado → container `app` fica `running`,
  não `exited`

## 5. Modelo de concorrência (I7)

- [x] 5.1 Configurar `worker_class = "gthread"` e `threads` (via `GUNICORN_THREADS`, ponto de partida
  `4`) em `gunicorn.conf.py`, mantendo `GUNICORN_WORKERS` em 2 (D4).
  *Validação:* `docker compose up -d && docker compose logs app | grep -i "using worker: gthread"`
- [x] 5.2 Confirmar que as métricas Prometheus multiproc continuam corretas sob `gthread` (contrato da
  spec `observabilidade` já arquivada).
  *Validação:* `curl -s localhost:8000/metrics | grep flask_http_request_total` → valores agregados,
  estáveis entre consultas sucessivas

## 6. GATE local — não prosseguir sem passar

- [x] 6.1 Suíte completa verde.
  *Validação:* `cd src && python -m pytest tests -q` → 0 falhas
- [x] 6.2 **CA1** — com o banco no ar: `/health` 200 e `/ready` 200 com `database: ok`.
  *Validação:* `docker compose up -d && curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/health && curl -s localhost:8000/ready`
- [x] 6.3 **CA2 + CA5** — derrubar o banco com a app no ar e medir; depois reiniciar a app com o banco
  ainda fora.
  *Validação:* `docker compose stop db && curl -s -o /dev/null -w "%{http_code} %{time_total}s\n" localhost:8000/ready` → `503` em ≤ 5s;
  `curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/health` → `200`;
  `docker compose restart app && curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/health` → `200`
- [x] 6.4 **CA4 + CA8** — religar o banco e confirmar convergência sem reinício; depois alterar o teto
  e confirmar que só passa a valer após novo start.
  *Validação:* `docker compose start db && sleep 2 && curl -s localhost:8000/ready` → `ready`, com
  `docker compose ps app` mostrando o mesmo container sem reinício;
  em seguida `READINESS_DB_TIMEOUT_SECONDS=2 docker compose up -d app` com `db` parado →
  `curl -w "%{time_total}s\n"` sobre `/ready` responde em ≤ 2s
- [x] 6.5 **CA10 (gate de I7 — o mais importante)** — com o banco pendurado (não parado: pausado, para
  que aceite conexões e não responda), martelar `/ready` na cadência das probes por período sustentado
  e confirmar que `/health` continua respondendo.
  *Validação:* `docker compose pause db`, então em paralelo por 60s um laço `curl localhost:8000/ready`
  a cada 10s e outro `curl -m 2 localhost:8000/health` a cada 10s → **100% dos `/health` retornam 200
  dentro de 2s**. Se falhar, elevar `GUNICORN_THREADS` (Open Question do design) e repetir antes de
  seguir para a seção 7.

## 7. Manifesto Kubernetes

- [x] 7.1 Adicionar `READINESS_DB_TIMEOUT_SECONDS: "5"` e `GUNICORN_THREADS` (valor validado em 6.5) ao
  `ConfigMap encontros-tech` em `k8s/manifesto.yaml`.
  *Validação:* `grep -A3 READINESS_DB_TIMEOUT_SECONDS k8s/manifesto.yaml`
- [x] 7.2 Trocar a `readinessProbe` do container `app` de `httpGet /` para `httpGet /ready` e a
  `livenessProbe` de `tcpSocket 8000` para `httpGet /health`, com os valores de temporização de D7
  (`readiness`: timeout 6, period 10, failureThreshold 3, initialDelay 5; `liveness`: timeout 2,
  period 10, failureThreshold 3, initialDelay 10).
  *Validação:* `kubectl apply --dry-run=server -f k8s/manifesto.yaml` → sem erro
- [x] 7.3 Conferir a desigualdade de temporização de R2.3: `periodSeconds > timeoutSeconds > teto do app`.
  *Validação:* `grep -B2 -A8 "readinessProbe" k8s/manifesto.yaml` → `10 > 6 > 5`
- [x] 7.4 Atualizar a linha de Observabilidade dos RNFs em `docs/trd.md`, que hoje registra as probes
  provisórias como dívida conhecida, para refletir o estado implementado (consultar, não reescrever o
  restante do TRD).
  *Validação:* `grep -n "readinessProbe httpGet /" docs/trd.md` → sem resultado

## 8. GATE de cluster — critérios de aceite do PRD

- [x] 8.1 Aplicar o manifesto e confirmar que o pod fica `Ready`.
  *Validação:* `kubectl apply -f k8s/manifesto.yaml && kubectl rollout status deploy/encontros-tech -n encontros-tech`
- [x] 8.2 **CA3 + CA9** — derrubar o banco e confirmar saída da rotação **sem reinício**, com o corpo
  de diagnóstico chegando ao orquestrador.
  *Validação:* `kubectl scale statefulset/<postgres> --replicas=0 -n encontros-tech`, então
  `kubectl get endpoints encontros-tech -n encontros-tech` → sem endpoints prontos;
  `kubectl get pod -n encontros-tech -o jsonpath='{.items[*].status.containerStatuses[*].restartCount}'` → inalterado;
  `kubectl describe pod ... | grep -i readiness` → falha por `503`, **não** por `timeout`
- [x] 8.3 **CA4** — religar o banco e confirmar readmissão automática à rotação, sem reinício.
  *Validação:* `kubectl scale statefulset/<postgres> --replicas=1 -n encontros-tech` e reconferir
  `kubectl get endpoints` + `restartCount`
- [x] 8.4 **CA5** — subir a aplicação com o banco previamente indisponível.
  *Validação:* com o `StatefulSet` do Postgres em 0 réplicas,
  `kubectl rollout restart deploy/encontros-tech -n encontros-tech` → pod em `Running` `0/1 Ready`
  (não `CrashLoopBackOff`); ao religar o banco, torna-se `1/1 Ready` sem reinício
- [x] 8.5 **CA6 + CA7** — confirmar que as consultas não alteram dados de negócio e que o corpo em
  falha não vaza informação sensível.
  *Validação:* comparar `GET /api/events/` antes e depois de N consultas às probes → idêntico;
  inspecionar o corpo de `/ready` em 503 → sem host, porta, usuário, senha, string de conexão ou
  stack trace
