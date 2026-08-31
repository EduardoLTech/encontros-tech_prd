# Design — Endpoints de saúde e prontidão

## Context

A aplicação é stateless, servida por Gunicorn em container não-root (ADR 001), implantada em EKS
(ADR 002) com o PostgreSQL rodando **dentro do cluster** como `StatefulSet` de réplica única com PVC
(ADR 003). O TRD registra as consequências disso: sem failover automático nem standby síncrono, a
perda do nó onde o pod do banco está agendado é indisponibilidade até reagendamento e remontagem do
volume. Ou seja, **janelas de indisponibilidade do banco são rotineiras nesta arquitetura**, não
excepcionais.

Estado atual relevante:

| Ponto | Situação | Consequência |
|---|---|---|
| `src/main.py:21` | `event_model.Base.metadata.create_all(bind=engine)` no import | banco fora no boot → processo não sobe → CrashLoopBackOff |
| `src/core/database.py:6` | `create_engine(settings.DATABASE_URL)` sem nenhum timeout | conexão pendurada não tem teto |
| `k8s/manifesto.yaml:234-240` | `readinessProbe httpGet /`, `livenessProbe tcpSocket 8000`, sem campos de temporização | probes rodam com `timeoutSeconds: 1` implícito; readiness usa rota de negócio |
| `ConfigMap`, `GUNICORN_WORKERS: "2"` | 2 workers **sync**; manifesto com 1 réplica | cada requisição ocupa um worker inteiro |

O TRD já antecipa esta mudança na linha de Observabilidade dos RNFs ("dívida conhecida: `/health` e
`/ready` (PRD-0001) não existem no código; a readiness real será `/ready` e a liveness `/health`
quando o PRD for implementado"). Este design não reabre nenhuma ADR — apenas concretiza essa dívida.

O documento existe porque a mudança não é a adição de duas rotas: ela mexe no caminho de boot, no
gerenciamento de conexões e no modelo de concorrência do servidor de aplicação.

## Goals / Non-Goals

**Goals:**

- Satisfazer os requisitos de `specs/saude-prontidao/` e `specs/implantacao-kubernetes/`.
- Garantir **I7** — a verificação de prontidão não pode, por consumo de capacidade, provocar falha de
  vivacidade. É o objetivo que define a maior parte das decisões abaixo.
- Tornar o teto de tempo da verificação um orçamento **real e total**, não um timeout de uma fase.
- Isolar a verificação do caminho de conexões do tráfego de negócio, nas duas direções.

**Non-Goals:**

- Reabrir ADR 002 ou ADR 003 — compute em EKS e banco em `StatefulSet` de réplica única permanecem.
- Resolver as dívidas de HA que o TRD já registra: réplica única de aplicação no manifesto,
  `topologySpreadConstraints` e pool de conexões externo (pgbouncer). Esta mudança deve ser correta
  com 1 réplica e continuar correta com N.
- Adicionar verificação de dependências além do banco (F4 do PRD).
- Métricas, tracing ou alertas sobre os endpoints (F5 do PRD).

## Decisions

### D1 — Router dedicado para os sinais, sem passar pela camada de serviço

Os endpoints ficam em um blueprint próprio (`src/routers/health_router.py`), registrado sem prefixo,
e chamam diretamente uma função de verificação em `src/core/database.py`.

**Por quê.** A arquitetura em camadas do projeto é `router → service → model`, e `services/` contém
regra de negócio (`event_service`). Um sinal de infraestrutura não é regra de negócio: passá-lo por
`services/` criaria uma camada vazia e sugeriria, erradamente, que o sinal tem semântica de domínio.
Mantê-lo em `core/` também deixa explícito que a verificação é sobre a **conexão**, não sobre eventos.

**Alternativas.** *Adicionar as rotas em `page_router`* — rejeitada: mistura sinal com negócio,
exatamente o acoplamento que a mudança existe para desfazer. *Criar um `health_service`* — rejeitada:
camada sem conteúdo.

### D2 — O teto de tempo é um orçamento total, aplicado por prazo (deadline), não por fase

A verificação registra um instante inicial e deriva os timeouts das fases a partir do **tempo
restante**:

```
  T = teto configurado (padrão 5.0s, piso 2.0s)

  t0 ─────────────────────────────────────────────────────────────▶ t0 + T
     │                                             │
     │◀────── connect_timeout ──────▶│             │
     │        max(2, floor(T))       │             │
     │                               │◀─ restante ─▶│
     │                               │  statement_timeout = T - decorrido
     │                               │
   abre conexão              executa SELECT 1
   (sem pool)
```

- `connect_timeout` (libpq) = `max(2, floor(T))`. Inteiro, porque libpq só aceita segundos inteiros.
- Após a conexão, o tempo restante do orçamento vira `statement_timeout` da sessão (em ms). Se o
  restante for ≤ 0, responde `down` sem executar a consulta.

**Por quê.** Somar timeouts independentes de cada fase faria o pior caso ser ~2×T, quebrando P9 e o
requisito de que o teto cobre a verificação inteira. O prazo garante pior caso ≤ `max(2, T)`.

**Por que o piso de 2s existe.** libpq eleva silenciosamente qualquer `connect_timeout` menor que 2
para 2. O piso da R2.2 não é escolha de produto: é essa limitação tornada explícita. Configurar 1s
produziria 2s de qualquer forma, sem o operador perceber.

**Alternativas.** *Só `connect_timeout`* — rejeitada: não protege a fase de consulta; um banco que
aceita conexão e não responde penduraria a verificação.

#### D2.1 — Correção após validação: prazo de tempo de parede por fora do driver

*Revisão durante a implementação.* A validação em container mostrou que os timeouts do driver **não
bastam**: o `connect_timeout` da libpq limita o connect TCP com precisão, mas **não cobre a resolução
de nome**.

```
  connect_timeout=2 · nome que não resolve   →  2,85s   ✗ estourou o teto
  connect_timeout=2 · IP blackhole            →  2,00s   ✓
  connect_timeout=5 · IP blackhole            →  5,01s   ✓
```

Como o `DATABASE_URL` sempre usa hostname — `db` no compose, o `Service` do Postgres no cluster —, o
pior caso real era `resolução DNS + teto`, e não `teto`. Isso não é cosmético: D7 dimensionou
`timeoutSeconds: 6` a partir do teto de 5s, de modo que um DNS lento faria o kubelet cortar a
tentativa antes da resposta, levando junto o corpo de diagnóstico — quebrando P9.2 e CA9 exatamente
no cenário em que o operador mais precisa dele.

**Decisão.** A verificação passa a rodar em um `ThreadPoolExecutor` dedicado, com
`future.result(timeout=teto)`. Isso dá um teto de **tempo de parede real**, cobrindo resolução de
nome, conexão e consulta. Os timeouts do driver permanecem como **limites internos**, para que a
thread não fique pendurada além do necessário.

Threads órfãs (as que estouraram o teto) terminam sozinhas quando a resolução ou a conexão falha, e
sua quantidade é limitada pela cadência das probes. Se o pool de verificação saturar, as consultas
seguintes respondem `down` de imediato — o que é correto: um pool saturado significa que o banco está
pendurado.

*Alternativa considerada:* resolver o host com `getaddrinfo` limitado e conectar por IP — rejeitada
por transferir para a aplicação a responsabilidade de múltiplos registros A, cache e verificação de
host. *Alternativa considerada:* afrouxar P9 para excluir o DNS do teto — rejeitada por exigir
alargar `timeoutSeconds` em D7 sem limite conhecido.

*Validação após a correção:* com o banco fora e teto de 2s, `/ready` responde 503 em 2,01s de forma
estável.

### D3 — Engine dedicado e sem pool para a verificação

A verificação usa um `Engine` próprio, distinto do engine de negócio, configurado com `NullPool` —
conexão aberta e fechada a cada verificação.

**Por quê.** Três razões, em ordem de peso:

1. **Evita falso-negativo por saturação.** Se a verificação disputasse o pool de negócio, um pico de
   tráfego legítimo esgotaria o pool e a readiness cairia — tirando o pod da rotação **por estar
   ocupado**, o que reduz capacidade justamente sob carga e realimenta o problema nas réplicas
   restantes. A readiness deve refletir a saúde do banco, não a fila da aplicação.
2. **Isola o blast radius dos timeouts.** A verificação precisa de timeouts curtos; o tráfego de
   negócio, não. Engines separados permitem parametrizar um sem alterar o outro — o `create_engine`
   de negócio permanece com seu comportamento atual.
3. **Satisfaz I6 estruturalmente.** Sem pool, não há conexão reaproveitada que possa estar
   silenciosamente morta desde antes do outage e mascarar o estado real.

**Custo.** Cada verificação é uma conexão nova ao Postgres. O TRD registra pressão sobre
`max_connections` (réplicas × workers, com pgbouncer pendente). Aqui o custo é limitado: a
concorrência máxima de verificações é **uma por réplica por período de probe** — com 1 réplica e
`periodSeconds: 10`, é desprezível; com 10 réplicas, ainda é uma conexão a cada 10s por réplica.

**Alternativas.** *Reutilizar `SessionLocal`* — rejeitada pelo item 1. *Engine dedicado com pool
persistente* — rejeitada pelo item 3.

#### D3.1 — Correção após validação: o engine de negócio também precisa de teto

*Revisão durante a implementação.* A decisão original — "o `create_engine` de negócio permanece com
seu comportamento atual" — mostrou-se o elo fraco de I7. Medição com o banco pendurado:

```
  GET /              →  ainda pendurada aos 30s (limite do medidor)
  GET /api/events/   →  ainda pendurada aos 30s
```

Sem timeout algum, cada requisição de negócio prende uma thread **indefinidamente**. Bastam 8 delas
(2 workers × 4 threads) para `/health` deixar de ser respondido — I7 violada **pelo tráfego de
negócio**, não pelas probes. O isolamento de D3 protegia a readiness do tráfego, mas não protegia a
vivacidade dele.

**Decisão.** O engine de negócio passa a ter `connect_timeout` e `pool_timeout` de 10s. Além disso,
ambos os engines ganham `tcp_user_timeout` e keepalives: o `connect_timeout` cobre apenas o handshake,
e um banco que aceitou a conexão e congelou deixaria o cliente esperando no `recv` para sempre. No
engine de verificação isso é o que impede a thread órfã de uma verificação estourada de pendurar
indefinidamente e saturar o executor.

**Trade-off aceito.** Mudança visível: uma rota de negócio contra um banco pendurado passa a
responder erro em ~10s em vez de travar. Isso é melhor sob todos os ângulos — o usuário recebe
resposta e a thread é devolvida.

*Validação após a correção:* rota de negócio responde 500 em 10,06s (antes: > 30s sem resposta).
Na cadência real das probes com o banco pendurado, `/health` respondeu 200 em 12/12 consultas, com
`restartCount` em 0.

**Limite conhecido.** Sob saturação — mais requisições concorrentes que threads disponíveis —
`/health` enfileira atrás delas. A diferença é que agora a espera é **limitada no tempo** (≤ 10s), e o
`failureThreshold: 3 × periodSeconds: 10` da liveness dá 30s de folga, de modo que uma saturação
transitória não gera reinício. Medição sob stress artificial (18 concorrentes para 8 slots): 4/8
consultas a `/health` enfileiraram além de 2s, sem nenhum reinício.

### D4 — Worker class `gthread` para satisfazer I7

`GUNICORN_WORKERS` permanece em 2, mas a classe de worker passa de `sync` para `gthread`, com threads
por worker configuradas em `gunicorn.conf.py`.

**O problema.** Com workers `sync`, cada requisição ocupa um worker inteiro. Com 2 workers e o banco
pendurado, duas verificações de 5s simultâneas ocupam ambos:

```
   sync, 2 workers                        gthread, 2 workers × N threads
   ──────────────────────                 ──────────────────────────────
   w1 ██████ /ready (5s, I/O bloq.)       w1 t1 ██████ /ready (bloqueada em I/O)
   w2 ██████ /ready (5s, I/O bloq.)          t2 ▪ /health  ◀── responde
   ── /health SEM WORKER ──               w2 t1 ██████ /ready
   → liveness falha → RESTART                t2 ▪ /health  ◀── responde
   ✗ viola I2 / I7                        ✓ I7 satisfeita
```

**Por quê `gthread` e não mais workers.** Elevar `GUNICORN_WORKERS` apenas desloca o limiar — n
verificações concorrentes ainda ocupam n workers — e custa memória: o TRD é explícito que os `t3.small`
têm 2 GB partilhados entre overhead do EKS e pods, e que o caminho de escala é adicionar nós, não
verticalizar. Threads compartilham o espaço de memória do worker e a espera aqui é **I/O puro** no
socket do Postgres, que libera o GIL. `/health` não faz I/O algum, então sempre encontra uma thread
disponível.

**Compatibilidade com a spec de observabilidade já arquivada.** As métricas Prometheus multiproc são
agregadas **por processo** (`PROMETHEUS_MULTIPROC_DIR`, `child_exit` em `gunicorn.conf.py`). Threads
vivem dentro do mesmo processo, portanto o número de arquivos multiproc e o ciclo de vida deles não
mudam — a mudança de worker class é transparente para aquele contrato.

**Segurança de thread.** A aplicação é stateless; `flask.g` é escopo de requisição, as sessões
SQLAlchemy são criadas por requisição via `get_db()`, e o engine de verificação é `NullPool`. Não há
estado mutável compartilhado introduzido por este design.

**Alternativas.** *Verificação em thread de background com resultado publicado* — **rejeitada por
I6**: publicaria prontidão a partir de resultado defasado, que o PRD proíbe explicitamente.
*Worker class assíncrona (`gevent`/`eventlet`)* — rejeitada: exigiria monkey-patching e revisão do
driver e do exporter Prometheus, desproporcional ao problema.

### D5 — Boot best-effort com reparo em background e lock consultivo

`create_all` sai do import. A preparação do schema passa a ser:

```
  boot ──▶ tenta preparar o schema (best-effort, com o mesmo teto de tempo)
            │
            ├── sucesso ──▶ segue; nada mais a fazer
            │
            └── falha ────▶ registra em log, NÃO interrompe o boot
                             │
                             └──▶ thread de reparo: backoff exponencial (1s → 30s),
                                  tenta até obter sucesso, sob pg_advisory_lock
```

**Por quê.** É a única das opções que satisfaz P7/I4 sem violar P10/I5 nem contrariar as ADRs:

- *`initContainer` que espera o banco* — **rejeitada**: reintroduz exatamente o boot bloqueante que P7
  elimina. O pod ficaria em `Init:0/1` e `/health` sequer responderia.
- *`Job` de migração separado* — **rejeitada**: a ADR 003 firma `k8s/manifesto.yaml` como arquivo único
  aplicável com um `kubectl apply`, na ordem de dependência dos recursos. Um `Job` introduz ordenação
  e sincronização de deploy que aquele contrato não comporta. Continua sendo o caminho correto quando
  houver ferramenta de migração de verdade — ver Open Questions.
- *DDL disparado dentro de `/ready`* — **rejeitada**: transforma um sinal declaradamente read-only
  (P10, I5) em operação com efeito colateral.

**Concorrência entre workers.** `create_all` já é idempotente (`checkfirst`), mas execuções
simultâneas podem colidir no catálogo. O `pg_advisory_lock` serializa a preparação entre workers e
entre réplicas, satisfazendo o cenário de preparação concorrente da spec sem exigir coordenação
externa.

### D6 — Configuração: `READINESS_DB_TIMEOUT_SECONDS`, tolerante a valor inválido

Declarada em `src/core/settings.py` como float, padrão `5.0`, com normalização: valores abaixo de 2
viram 2; valor não numérico ou negativo aplica o padrão e registra aviso.

**Por quê a tolerância.** `pydantic-settings` levantaria exceção na inicialização diante de um valor
malformado — o que faria um erro de digitação no `ConfigMap` derrubar o boot de todas as réplicas.
Isso reintroduziria, por outra porta, o modo de falha que I4 proíbe. Uma configuração inválida deve
degradar para o padrão, não impedir a aplicação de subir.

### D7 — Temporização das probes no manifesto

Com teto do app em 5s, e respeitando `periodSeconds > timeoutSeconds > teto` (R2.3):

| Campo | `readinessProbe` | `livenessProbe` |
|---|---|---|
| tipo | `httpGet /ready` | `httpGet /health` |
| `timeoutSeconds` | **6** | **2** |
| `periodSeconds` | **10** | **10** |
| `failureThreshold` | **3** | **3** |
| `initialDelaySeconds` | **5** | **10** |

**Por quê.** `timeoutSeconds: 6 > 5` garante que o 503 com corpo de diagnóstico chegue ao orquestrador
em vez de a tentativa morrer por timeout (P9.2, P11). `periodSeconds: 10 > 6` impede sobreposição de
avaliações. A liveness usa `timeoutSeconds: 2` porque `/health` não faz I/O — se não responde em 2s, o
processo está de fato comprometido; um valor generoso aqui atrasaria a detecção do que a liveness
existe para detectar. `initialDelaySeconds` maior na liveness que na readiness evita reinício durante
o arranque.

**Consequência aceita.** A remoção da rotação passa a levar `3 × 10 = 30s`, contra poucos segundos
hoje. É o custo de tolerar um banco lento sem oscilar (flapping) a rotação.

**`startupProbe`** foi considerada e dispensada: com D5, o boot deixa de depender do banco e é rápido
e previsível, então `initialDelaySeconds` basta.

### D8 — Sinais fora das métricas e do log de requisição

Os dois endpoints são marcados como não rastreados pelo exporter Prometheus e excluídos do middleware
de log de requisição de `src/main.py`.

**Por quê.** Uma probe a cada 10s por réplica × 2 endpoints gera tráfego constante que hoje seria
contabilizado como acesso HTTP e registrado em log a cada ciclo, afogando o sinal de negócio. Não é o
objeto de F5 (que trata de métricas *sobre* a saúde); é higiene do que já existe — e é a contrapartida
direta do ganho de tirar as probes da rota `/`.

## Risks / Trade-offs

- **[I7 não se sustentar sob carga real]** → `gthread` (D4) é a mitigação estrutural, mas o número de
  threads precisa ser validado, não presumido. **CA10 é gate de merge**: com o banco pendurado e as
  probes na cadência de D7 por período sustentado, `/health` deve continuar respondendo e a contagem
  de reinícios do pod deve permanecer zero. Se falhar, o número de threads sobe antes de qualquer
  outra mudança.
- **[Detecção 30s mais lenta]** → aceito conscientemente (D7). Mitigação disponível sem alterar código:
  baixar `periodSeconds`, respeitando a desigualdade de R2.3.
- **[Conexões novas a cada verificação pressionam `max_connections`]** → limitado pela cadência das
  probes (D3). O TRD já registra pgbouncer como mitigação pendente para o problema maior, do qual este
  é uma fração pequena.
- **[Indisponibilidade total do frontend durante queda do banco]** → com todas as réplicas
  não-prontas, o `Service` fica sem endpoints. É o comportamento **correto** por I1, mas é uma mudança
  visível: hoje o usuário vê página de erro, depois verá erro de conexão. Fora do escopo alterar isso;
  uma página de degradação seria feature à parte.
- **[Reparo de schema em background falhando silenciosamente]** → D5 registra cada tentativa em log
  com backoff visível; a instância permanece não-pronta enquanto o banco não estiver acessível, de modo
  que a falha é observável pela readiness, não apenas pelo log.
- **[`gthread` expondo condição de corrida latente]** → a aplicação é stateless e as sessões são por
  requisição (D4), mas é uma mudança de modelo de execução. A suíte em `src/tests/` roda como gate
  antes do deploy.

## Migration Plan

A mudança tem duas metades deliberadamente desacopláveis: **código** (endpoints inertes) e
**manifesto** (probes que passam a consumi-los). Só a segunda tem blast radius alto.

1. **Publicar o código com os endpoints.** Os endpoints existem, mas nada os consulta — as probes
   ainda apontam para `/` e `tcpSocket`. Risco praticamente nulo. Valida-se D5 nesta etapa: derrubar
   o banco e reiniciar o pod deve deixá-lo `Running` (hoje ficaria em CrashLoopBackOff).
2. **Verificar CA10 no ambiente de destino** com as probes ainda antigas, exercitando `/ready` e
   `/health` manualmente sob banco pendurado. É o gate de I7.
3. **Aplicar o manifesto** — probes novas e entrada do `ConfigMap`, em um único `kubectl apply`
   conforme ADR 003.
4. **Observar um ciclo completo:** derrubar o banco (`kubectl scale statefulset` para 0), confirmar
   readiness 503, saída da rotação e ausência de reinício; religar e confirmar readmissão automática.

**Rollback.** Detalhado no `proposal.md`. O ponto essencial: o passo 3 é reversível em ~1 minuto sem
rebuild — restaurar as probes antigas no manifesto e reaplicar desfaz todo o risco de blast radius
alto, deixando os endpoints publicados e inertes. Não há migração de dados e, portanto, não há ponto
sem retorno.

## Open Questions

- **Número de threads por worker em `gthread`.** A definir empiricamente contra CA10, considerando o
  limite de `500m` de CPU do container. Ponto de partida sugerido: 4.
- **Ferramenta de migração de schema.** `create_all` é aceitável hoje porque o modelo é único e
  aditivo. Quando houver migração destrutiva ou versionada (Alembic), a decisão D5 deve ser
  reavaliada em favor de um `Job` — e isso provavelmente exige uma ADR, por tocar o contrato de
  arquivo único da ADR 003.
- **Réplica única da aplicação.** O TRD registra como dívida conhecida que o manifesto implanta 1
  réplica. Com 1 réplica, I1 significa indisponibilidade total durante outage do banco. O design é
  correto para N réplicas, mas o benefício de HA só aparece quando essa dívida for paga — fora do
  escopo aqui.
- ~~**Baseline de specs.**~~ *Resolvido:* a suspeita de que `openspec/specs/` estivesse vazio era
  leitura equivocada de uma listagem truncada. As specs vivas existem
  (`empacotamento-container`, `implantacao-kubernetes`, `observabilidade`), e o delta de
  `implantacao-kubernetes` foi reescrito como `MODIFIED` do requisito de sinais de saúde já existente,
  em vez de `ADDED` duplicado.
