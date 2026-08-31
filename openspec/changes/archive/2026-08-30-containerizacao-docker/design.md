# Design — Containerização Docker

## Contexto

A ADR 001 já fixou o *quê*: imagem única multi-stage, base slim oficial do Python, usuário
não-root, mesmo servidor de aplicação (Gunicorn) em dev e prod, Compose com PostgreSQL para
desenvolvimento. Este documento registra as decisões de *como* que a ADR deixou em aberto e
que emergiram ao confrontar a decisão com o código existente.

```
        ┌──────────────────── docker-compose.yml ────────────────────┐
        │   ┌────────────────┐            ┌──────────────────┐       │
        │   │  app           │            │  db (postgres)   │       │
        │   │  imagem única  │──5432─────▶│  volume pgdata   │       │
        │   │  gunicorn      │  depends_on│  healthcheck:    │       │
        │   │  --reload poll │  (healthy) │  pg_isready      │       │
        │   │  USER não-root │            └──────────────────┘       │
        │   │  :8000         │                                       │
        │   └───────┬────────┘                                       │
        │           │ bind mount ./src ─▶ /app  (só em dev)          │
        └───────────┼────────────────────────────────────────────────┘
                    │
        ┌───────────▼─────────── Dockerfile (multi-stage) ───────────┐
        │  [builder]  python:3.12-slim, instala requirements.txt     │
        │                        │                                   │
        │                        ▼ copia só o resultado              │
        │  [runtime]  python:3.12-slim, USER app, sem cache de pip   │
        └────────────────────────────────────────────────────────────┘
```

## Decisões

### D1 — Base fixada em `python:3.12-slim`

O TRD (linha 11) diz "na mesma versão usada localmente". O ambiente local é **Python 3.14.3**,
o que traria consequências reais:

| | 3.14.3 | 3.12 |
|---|---|---|
| `psycopg2-binary` 2.9.10 | sem wheel cp314 → compila do sdist | wheel cp312 disponível |
| toolchain no builder | `gcc`, `libpq-dev`, `python3-dev` | desnecessário |
| Flask 3.0.0 / Werkzeug 3.0.1 | não testados nessa versão | contemporâneos |
| tempo de build | minutos | segundos |

**Decisão:** fixar `python:3.12-slim` e **corrigir a linha 11 do TRD**, que passa a nomear a
versão explicitamente em vez de referenciar "a versão local".

**Consequência aceita:** com todas as dependências em wheel, a justificativa que a ADR 001 deu
para o multi-stage ("absorve a compilação de dependências... inclusive quando não há artefatos
pré-compilados") deixa de se aplicar. O multi-stage **permanece** — continua a impedir que o
cache do pip e as dependências de teste cheguem à imagem final, e preserva a decisão caso uma
dependência futura precise compilar. Mas agora é higiene, não necessidade: o Dockerfile
resultante será mais simples do que a ADR sugere, e isso é esperado, não um erro.

### D2 — Boot acoplado ao banco: aceitar em dev, registrar em prod

`src/main.py:21` chama `Base.metadata.create_all(bind=engine)` **em tempo de import**. Com o
banco fora, o import falha, o worker morre e o Gunicorn reinicia em laço.

```
   BANCO FORA          BANCO OK
       │                  │
  create_all() ✗      create_all() ✓
       │                  │
  worker morre        app sobe
       │
  CrashLoopBackOff
```

Três posturas foram consideradas:

- **(a) Aceitar** — `depends_on: condition: service_healthy` resolve *em desenvolvimento*.
- **(b) Entrypoint com espera** — loop de `pg_isready` antes do `exec gunicorn`; resolveria
  também produção, mas insere comportamento que o PRD-0001 deliberadamente não especificou.
- **(c) Mover `create_all`** — sai do escopo "Docker" e entra em escopo de aplicação.

**Decisão: (a)**, coerente com a ADR 001, que já assume o trade-off ("a subida do container da
aplicação fica condicionada à prontidão do serviço de banco").

**Dívida explícita, não uma nota de rodapé:** em produção o problema permanece. O PRD-0001
existe justamente para evitar que instâncias entrem em ciclo de reinício quando o banco está
fora — e enquanto o boot puder morrer antes de servir qualquer requisição, o `/ready`, quando
implementado, ficará parcialmente sem efeito. O TRD já registra a criação de tabelas no boot
como dívida sem decisão (corrida entre réplicas); esta mudança **não a remove**.

### D3 — `gunicorn.conf.py` versionado

**Decisão:** um arquivo de configuração no repositório, com valores lidos de variáveis de
ambiente, em vez de flags no `CMD` e no Compose.

Sem ele, `workers`, `bind`, `--reload` e o hook de métricas viram flags duplicadas entre o
Dockerfile e o `docker-compose.yml` — e a paridade dev/prod que motivou a ADR 001 se dilui
justamente no ponto onde ela deveria ser visível. Com ele, dev e prod usam o mesmo arquivo e
diferem apenas por env.

### D4 — Recarga com `--reload-engine=poll`

O ambiente de desenvolvimento é **Windows 11 + Docker Desktop**. O watcher padrão do Gunicorn
depende de eventos de filesystem (inotify), que não atravessam de forma confiável o bind mount
a partir de NTFS:

```
  Windows NTFS ──▶ Docker Desktop VM ──▶ container
       │                                    │
   arquivo salvo                      inotify: silêncio
                                            │
                                      --reload nunca dispara
```

**Decisão:** `--reload-engine=poll` desde o início. Custa CPU ocioso; a alternativa é descobrir
na marra que salvar arquivo não recarrega nada.

### D5 — Split de dependências em dois arquivos

O TRD exige separar deps de runtime das de teste; hoje `pytest==8.3.4` está no mesmo
`src/requirements.txt`. Duas saídas foram consideradas:

```
  A) dois arquivos                 B) estágio de teste no Dockerfile
  ──────────────────               ────────────────────────────────
  requirements.txt                 builder ─┬─▶ runtime  (prod)
  requirements-dev.txt (+pytest)             └─▶ test  (+pytest)
```

**Decisão: (A)** — simples e explícito. (B) daria paridade maior (testes rodando na imagem
real), ao custo de um Dockerfile mais denso; fica disponível como evolução futura.

### D6 — Métricas Prometheus multiproc entram no escopo

O TRD promete "métricas Prometheus em diretório multiproc (`PROMETHEUS_MULTIPROC_DIR`)". O
código tem a variável e cria o diretório (`src/main.py:32`), mas `src/main.py:35` instancia
`PrometheusMetrics(app)` com o **registry padrão**. Sob Gunicorn multi-worker cada worker mantém
seu próprio registry em memória, e `/metrics` responde com os números de um worker sorteado.

Containerizar acrescenta três exigências próprias:

```
   PROMETHEUS_MULTIPROC_DIR
     ├─ gravável pelo USER não-root      ← imposto pela ADR 001
     ├─ limpo a cada start               ← senão, contadores fantasma de runs anteriores
     └─ a env var precisa existir ANTES do import de prometheus_client
```

**Decisão:** incluir no escopo. Sem isso o TRD continua prometendo um comportamento que não
acontece, e a promessa só seria desmentida no EKS, sob carga — o pior momento possível.
Implica alterar `src/main.py` e escrever o hook `child_exit` em `gunicorn.conf.py`.

### D7 — Layout dentro da imagem

Os imports da aplicação são planos (`from core.database import ...`, `from services import
event_service`), sem prefixo `src.`. Portanto o **conteúdo** de `src/` vira a raiz do `WORKDIR`,
e o comando é `gunicorn main:app`.

Isso descasa do `pytest.ini`, que mora na raiz do repositório com `pythonpath = .` e espera os
testes em `src/tests/`. Como (D5) manteve os testes fora da imagem de runtime, o descasamento
não bloqueia esta mudança — mas fica registrado como o obstáculo a resolver caso se queira
rodar `pytest` dentro do container no futuro (a opção (B) de D5).

## Riscos

| Risco | Mitigação |
|---|---|
| `create_all` derruba pods em produção durante failover do RDS | Fora do escopo por decisão (D2); registrado como dívida no TRD e na proposta |
| Polling do reloader consome CPU ocioso em dev | Aceito conscientemente (D4); ajustável por env se incomodar |
| Alteração em `main.py` para multiproc quebra as métricas atuais | Verificar `/metrics` com mais de um worker antes de fechar a mudança |
| `.env` vazar para a imagem | `.dockerignore` é item obrigatório, não opcional |
