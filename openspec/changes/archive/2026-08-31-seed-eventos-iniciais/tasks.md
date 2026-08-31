# Tarefas — Script de seed de eventos iniciais

> Referências: `specs/seed-dados-iniciais/spec.md` (o quê) e `design.md` (como, decisões D1–D12).
> Comandos assumem a raiz do repositório, salvo indicação.
>
> **A suíte roda a partir de `src/`**, não da raiz: `python -m pytest` insere o diretório atual no
> `sys.path`, e é assim que `core`, `models` e `scripts` se tornam importáveis. Rodar da raiz falha
> na coleção com `ModuleNotFoundError: No module named 'core'` — vale para os testes existentes
> também. Sem dependências de teste no host, use o container:
> `docker run --rm -v "/$(pwd)":/w -w //w/src python:3.12-slim sh -c "pip install -q -r requirements-dev.txt && python -m pytest tests/ -q"`

## 1. Estrutura do módulo

- [x] 1.1 Criar o pacote `src/scripts/` com `__init__.py` vazio (D10).
      **Validação:** `python -c "import pathlib; assert pathlib.Path('src/scripts/__init__.py').exists()"`
- [x] 1.2 Criar `src/scripts/seed_events.py` com o esqueleto do módulo: imports de
      `models.event.Event`, `core.database` (`engine`, `SessionLocal`), `core.logging`
      (`setup_logging`, `get_logger`) e `core.settings.settings`. **Não** importar `core.schema` (D1).
      **Validação:** `cd src && python -c "import scripts.seed_events"` (deve importar sem erro e sem
      abrir conexão)
- [x] 1.3 Confirmar que nenhum arquivo existente foi modificado até aqui.
      **Validação:** `git status --porcelain src/ | grep -v '^??'` — não deve retornar nada

## 2. Catálogo de eventos

- [x] 2.1 Definir a constante do catálogo com os 10 eventos do `api-requests.http`: `title`,
      `description`, `location` e a data original. **Não** transportar `technologies` (D11, R4/F4).
      **Validação:** `cd src && python -c "from scripts.seed_events import CATALOGO; print(len(CATALOGO))"` → `10`
- [x] 2.2 Adicionar comentário no módulo apontando `api-requests.http` como origem do catálogo e
      registrando que a duplicação é deliberada (D11, risco conhecido).
      **Validação:** revisão de código — comentário presente no topo da constante
- [x] 2.3 Escrever teste que confere título, descrição e local de cada entrada do catálogo contra os
      valores do `api-requests.http`, e que nenhuma entrada carrega chave `technologies`.
      **Validação:** `cd src && python -m pytest tests/scripts/test_seed_events.py -k catalogo -q`

## 3. Cálculo de datas (D3, D4)

- [x] 3.1 Implementar a função de deslocamento em bloco:
      `agora + MARGEM + (data_original − data_original_mais_antiga)`, com `agora` ingênuo em UTC via
      `agora_utc()` (D4). Definir `MARGEM` como constante nomeada do módulo.
      **Validação:** `cd src && python -m pytest tests/scripts/test_seed_events.py -k datas -q`
- [x] 3.2 Teste: com um `agora` fixo injetado, **todas** as 10 datas resultantes são estritamente
      posteriores a esse instante — inclusive a do evento mais antigo do catálogo (I5, P6).
      **Validação:** `cd src && python -m pytest tests/scripts/test_seed_events.py -k futuro -q`
- [x] 3.3 Teste: os deltas entre pares de eventos nas datas resultantes são idênticos aos deltas do
      catálogo original, e a ordem cronológica é preservada.
      **Validação:** `cd src && python -m pytest tests/scripts/test_seed_events.py -k espacamento -q`
- [x] 3.4 Teste: dois `agora` diferentes produzem conjuntos de datas diferentes, ambos no futuro.
      **Validação:** `cd src && python -m pytest tests/scripts/test_seed_events.py -k instantes -q`

## 4. Guardas de pré-condição (D1, D2, D7)

- [x] 4.1 Implementar a verificação de existência da tabela `events` via
      `sqlalchemy.inspect(engine).has_table("events")`, retornando falha explícita quando ausente,
      com mensagem que nomeia a pré-condição — sem emitir DDL (P10, I3).
      **Validação:** `cd src && python -m pytest tests/scripts/test_seed_events.py -k schema_ausente -q`
- [x] 4.2 Implementar a verificação de tabela vazia por existência (`LIMIT 1`), não por `COUNT(*)`
      (D7, P2/R3).
      **Validação:** `cd src && python -m pytest tests/scripts/test_seed_events.py -k vazia -q`
- [x] 4.3 Separar o tratamento de `OperationalError`/erros de driver (falha de conexão, P11) do caso
      "inspeção bem-sucedida, tabela inexistente" (P10), com mensagens distinguíveis (D2).
      **Validação:** `cd src && python -m pytest tests/scripts/test_seed_events.py -k conexao -q`
- [x] 4.4 Teste: em nenhum dos cenários — vazia, populada ou ausente — o script emite instrução de
      criação/alteração de schema, e `core.schema` nunca é importado.
      **Validação:** `cd src && python -m pytest tests/scripts/test_seed_events.py -k sem_ddl -q` e
      `grep -n "core.schema\|create_all\|ensure_schema" src/scripts/seed_events.py` (sem resultados)

## 5. Inserção e atomicidade (D5, D6)

- [x] 5.1 Implementar a inserção via ORM: construir objetos `Event` e persistir com uma sessão de
      `SessionLocal`, com **um único** `commit` ao final e `rollback` em qualquer exceção (P12, I6).
      **Validação:** `cd src && python -m pytest tests/scripts/test_seed_events.py -k insercao -q`
- [x] 5.2 Confirmar que `edit_token` não é atribuído manualmente — vem do `default` do modelo (D5,
      P7/I4).
      **Validação:** `grep -n "edit_token" src/scripts/seed_events.py` — nenhuma atribuição
- [x] 5.3 Teste: tokens dos 10 eventos são não-nulos e distintos entre si.
      **Validação:** `cd src && python -m pytest tests/scripts/test_seed_events.py -k token -q`
- [x] 5.4 Teste: exceção no meio do lote dispara `rollback` e nenhum `commit` parcial ocorre.
      **Validação:** `cd src && python -m pytest tests/scripts/test_seed_events.py -k atomicidade -q`
- [x] 5.5 Teste: no-op em tabela populada não abre transação de escrita nem chama `add`/`commit`.
      **Validação:** `cd src && python -m pytest tests/scripts/test_seed_events.py -k noop -q`

## 6. Observabilidade e ponto de entrada (D8, D9, D10)

- [x] 6.1 Chamar `setup_logging(...)` no ponto de entrada, antes de qualquer mensagem, com os valores
      de `settings` (D8 — sem isso as mensagens de R6 somem silenciosamente).
      **Validação:** `cd src && python -m pytest tests/scripts/test_seed_events.py -k logging -q`
- [x] 6.2 Registrar o destino do banco (host/base, **sem credenciais**) antes de escrever, para que o
      operador reconheça o ambiente (mitigação do risco principal do `design.md`).
      **Validação:** `cd src && python -m pytest tests/scripts/test_seed_events.py -k destino -q` — a mensagem não
      contém a senha da `DATABASE_URL`
- [x] 6.3 Emitir as três mensagens de desfecho: semeou (com a quantidade), ignorou (com o motivo),
      falhou (com o motivo, distinguindo P10 de P11) — R6.
      **Validação:** `cd src && python -m pytest tests/scripts/test_seed_events.py -k desfecho -q`
- [x] 6.4 Implementar `main()` sob `if __name__ == "__main__":` retornando código de saída `0` para
      semeou e para no-op, `1` para falha (D9).
      **Validação:** `cd src && python -m pytest tests/scripts/test_seed_events.py -k saida -q`

## 7. Gate de verificação

> Não prosseguir para a validação end-to-end enquanto este grupo não estiver inteiramente verde.

- [x] 7.1 Suíte completa passando, sem regressão nos testes existentes.
      **Validação:** `cd src && python -m pytest tests/ -q`
- [x] 7.2 Conferir a cobertura de cenários: cada `#### Scenario` de
      `specs/seed-dados-iniciais/spec.md` tem teste correspondente ou justificativa registrada de por
      que só é verificável end-to-end (grupos 8 e 9).
      **Validação:** revisão cruzada entre `spec.md` e `src/tests/scripts/` — lista de cenários sem
      cobertura deve estar vazia ou explicada
- [x] 7.3 Confirmar o escopo aditivo: nenhum arquivo pré-existente modificado, nenhuma dependência
      nova, `Dockerfile`/`k8s/`/`docker-compose.yml` intocados.
      **Validação:** `git status --porcelain` — apenas arquivos novos sob `src/scripts/`,
      `src/tests/scripts/` e `openspec/changes/seed-eventos-iniciais/`

## 8. Imagem e ambiente Docker

> **Atenção — armadilha do bind mount.** O `docker-compose.yml` monta `./src:/app`, então
> `docker compose exec app ...` executa o **código do host**, não o que está dentro da imagem. Uma
> validação feita só por `compose exec` **não prova** que o script foi empacotado. Por isso 8.3 e 8.4
> rodam a imagem sem o mount, via `docker run`.
>
> Comandos escritos para shell POSIX (Git Bash). Em PowerShell, troque `echo "exit=$?"` por
> `echo "exit=$LASTEXITCODE"` e `&&` por `;`.

- [x] 8.1 Construir a imagem com o script já incorporado, sem alterar o `Dockerfile` (D10 — o
      `COPY src/ /app/` existente deve bastar).
      **Validação:** `docker compose build app` conclui sem erro
- [x] 8.2 Confirmar que o `Dockerfile` **não** precisou de mudança para levar o script.
      **Validação:** `git status --porcelain Dockerfile` → sem saída
- [x] 8.3 **Prova de empacotamento:** o módulo do seed existe dentro da imagem, sem bind mount.
      **Validação:** `docker run --rm teclinux/encontros-tech-prd:1.0.0 ls -la /app/scripts/seed_events.py`
      e `docker run --rm teclinux/encontros-tech-prd:1.0.0 python -c "import scripts.seed_events; print('ok')"` → `ok`
- [x] 8.4 **Prova de execução como não-root (ADR 001):** o seed roda sob o usuário `app`, e o módulo é
      legível por ele.
      **Validação:** `docker run --rm teclinux/encontros-tech-prd:1.0.0 whoami` → `app`, e o comando de
      8.3 executa sem `PermissionError`
- [x] 8.5 Subir o ambiente limpo e aguardar a aplicação pronta.
      **Validação:** `docker compose down -v && docker compose up -d`, depois
      `curl -s -o /dev/null -w "%{http_code}" localhost:8000/ready` → `200`
- [x] 8.6 Confirmar o ponto de partida: schema criado pelo boot da aplicação, tabela `events` vazia.
      **Validação:** `docker compose exec db psql -U encontros_tech -d encontros_tech -c "\dt events"`
      (tabela presente) e `-c "SELECT count(*) FROM events;"` → `0`

## 9. Validação end-to-end em containers (CA1–CA9 do PRD-0002)

> Executar na ordem. Cada passo depende do estado deixado pelo anterior.

**Semeadura e uso pela aplicação**

- [x] 9.1 **CA1/CA9:** executar o seed com a tabela vazia; 10 eventos inseridos, saída `0`, log
      declarando quantos semeou e identificando o banco de destino sem credenciais.
      **Validação:** `docker compose exec app python -m scripts.seed_events; echo "exit=$?"` (→ `0`),
      a saída contém a contagem e o host do banco (sem senha), e
      `docker compose exec db psql -U encontros_tech -d encontros_tech -tAc "SELECT count(*) FROM events;"` → `10`
- [x] 9.2 **CA3/CA4/CA5 (dados):** campos preenchidos, todas as datas no futuro, tokens únicos e
      não-nulos.
      **Validação:** `docker compose exec db psql -U encontros_tech -d encontros_tech -c "SELECT count(*) FILTER (WHERE date <= now()) AS passado, count(*) FILTER (WHERE edit_token IS NULL) AS sem_token, count(*) FILTER (WHERE title IS NULL OR description IS NULL OR location IS NULL) AS campo_vazio, count(DISTINCT edit_token) AS tokens FROM events;"`
      → `passado=0`, `sem_token=0`, `campo_vazio=0`, `tokens=10`
- [x] 9.3 Conferir o espaçamento preservado (D3): os intervalos entre eventos consecutivos reproduzem
      os do `api-requests.http`, e a janela total é de ~55 dias.
      **Validação:** `docker compose exec db psql -U encontros_tech -d encontros_tech -c "SELECT title, date, date - lag(date) OVER (ORDER BY date) AS delta FROM events ORDER BY date;"`
      — deltas variados (não uniformes) e primeira data já à frente de `now()`
- [x] 9.4 **CA6 (uso real pela API):** os 10 eventos aparecem na listagem da API.
      **Validação:** `curl -s localhost:8000/api/events/ | python -c "import json,sys; d=json.load(sys.stdin); print(len(d))"` → `10`
      **Desbloqueada** pela change `corrigir-serializacao-api-eventos` (task 6.2). O bloqueio era o
      `GET /api/events/` respondendo **500** — `'Event' object has no attribute 'model_dump'`: o
      router chamava `model_dump()` sobre objetos **ORM**, não sobre o schema Pydantic que importa.
      Defeito pré-existente e independente do seed, endereçado em change próprio.
      **Observado:** `200` com `len = 10`
- [x] 9.5 **CA6 (busca):** a busca encontra eventos semeados por título, descrição e local.
      **Validação:** `curl -s "localhost:8000/api/events/?search=Python"` etc.
      **Desbloqueada** pela mesma change (task 6.3) — o handler de busca é o mesmo `read_events`.
      **Observado:** por título (`Python` → 1), por descrição (`deploy` → 1, ausente do título) e
      por local (`Rio de Janeiro` → 1, ausente de título e descrição)
- [x] 9.6 **CA6 (página HTML) — cobre P8 no lugar de 9.4/9.5:** a interface web renderiza os eventos
      semeados, não uma lista vazia. Este é o caminho de leitura que **funciona** hoje, e é por ele
      que a legibilidade pela aplicação fica demonstrada.
      **Validação:** `curl -s localhost:8000/ | grep -c "FastAPI\|Kubernetes\|Blockchain"` → maior que `0`
      **Observado:** 5/5 títulos conferidos presentes no HTML
- [x] 9.7 **CA5 (fluxo de edição por token):** um evento semeado é localizável e editável pelos fluxos
      existentes da aplicação.
      **Validação:** obter um token com
      `docker compose exec db psql -U encontros_tech -d encontros_tech -tAc "SELECT edit_token FROM events LIMIT 1;"`,
      então `curl -s localhost:8000/events/edit/<token>` → `200` renderizando o evento.
      **Observado:** 200 com o título do evento semeado no corpo. O caminho equivalente da API
      (`/api/events/by-token/<token>`) também responde `200` desde a change
      `corrigir-serializacao-api-eventos` (task 6.5).

**Idempotência e não-acoplamento ao boot**

- [x] 9.8 **CA2:** segunda execução do seed é no-op — contagem e conteúdo idênticos, saída `0`, log
      declarando que ignorou por já haver dados.
      **Validação:** salvar `docker compose exec db psql -U encontros_tech -d encontros_tech -tAc "SELECT id,title,date,edit_token FROM events ORDER BY id;" > /tmp/antes.txt`,
      rodar o seed de novo (saída `0`, log de no-op), repetir a consulta para `/tmp/depois.txt` e
      `diff /tmp/antes.txt /tmp/depois.txt` → sem diferenças
- [x] 9.9 Terceira e quarta execuções seguidas continuam no-op, sem duplicatas (I2).
      **Validação:** rodar o seed mais duas vezes; `SELECT count(*) FROM events;` → `10` a cada vez
- [x] 9.10 **P9 (boot não dispara o seed):** reiniciar o container da aplicação várias vezes não
      insere nem duplica eventos.
      **Validação:** `docker compose restart app` três vezes, aguardar `/ready` → `200` a cada uma, e
      `SELECT count(*) FROM events;` → `10` ao final
- [x] 9.11 **P9 complementar:** com a tabela **vazia**, subir a aplicação não semeia nada — o seed só
      ocorre por invocação explícita.
      **Validação:** `docker compose exec db psql -U encontros_tech -d encontros_tech -c "TRUNCATE events;"`,
      `docker compose restart app`, aguardar `/ready` → `200`, e `SELECT count(*) FROM events;` → `0`

**Independência do ciclo de vida da aplicação**

- [x] 9.12 **CA6 (aplicação desligada):** com o container da aplicação **parado** e o schema já
      existente, o seed roda em container avulso e conclui com sucesso.
      **Validação:** `docker compose stop app`, confirmar com `docker compose ps app` que não há
      container em execução, então
      `docker compose run --rm app python -m scripts.seed_events; echo "exit=$?"` (→ `0`) e
      `SELECT count(*) FROM events;` → `10`
- [x] 9.13 Subir a aplicação depois da semeadura feita com ela desligada; os eventos aparecem na
      listagem e na busca.
      **Validação:** `docker compose up -d app`, aguardar `/ready` → `200`, repetir 9.4 e 9.5

**Falhas explícitas**

- [x] 9.14 **CA7:** sem a tabela `events`, o seed falha com mensagem de pré-condição e **não** cria o
      schema.
      **Validação:** `docker compose stop app` (para o boot não recriar a tabela), depois
      `docker compose exec db psql -U encontros_tech -d encontros_tech -c "DROP TABLE events;"`,
      `docker compose run --rm app python -m scripts.seed_events; echo "exit=$?"` (→ `1`), a mensagem
      cita a tabela ausente como pré-condição, e
      `docker compose exec db psql -U encontros_tech -d encontros_tech -c "\dt events"` → tabela ainda
      ausente
- [x] 9.15 **CA8:** com o banco inalcançável, o seed falha com mensagem de **conexão** — textualmente
      distinta da de 9.14 — sem pendurar o processo.
      **Validação:** `docker compose stop db`, então
      `docker compose run --rm app python -m scripts.seed_events; echo "exit=$?"` (→ `1`) em torno do
      `connect_timeout` de 10 s (não indefinido); comparar a mensagem com a de 9.14 e confirmar que
      distinguem os dois casos (D2)
- [x] 9.16 Registrar o resultado das 16 verificações — comando, saída observada e veredito — no
      relatório de validação da mudança (`validacao.md`).
      **Validação:** revisão: todo CA de CA1 a CA9 tem ao menos uma linha correspondente

**Restauração**

- [x] 9.17 Devolver o ambiente ao estado limpo e funcional após os passos destrutivos.
      **Validação:** `docker compose down -v && docker compose up -d`, aguardar
      `curl -s -o /dev/null -w "%{http_code}" localhost:8000/ready` → `200` e
      `SELECT count(*) FROM events;` → `0`

## 10. Documentação

- [x] 10.1 Registrar `src/scripts/` na estrutura de pastas do TRD (`docs/trd.md`) e o comando de
      invocação do seed. Não reescrever outras seções; o modelo de dados **não** muda.
      **Validação:** `grep -n "scripts" docs/trd.md`
- [x] 10.2 Atualizar o PRD-0002 marcando as três premissas da seção "Premissas a confirmar" como
      confirmadas, referenciando as decisões D3 (datas) e a premissa de execução serializada.
      **Validação:** `grep -n "Premissas" docs/prds/PRD-0002-seed-eventos.md` e revisão do trecho
- [x] 10.3 Documentar no `README.md`, na seção de setup de ambiente, o comando de seed em containers
      (`docker compose exec app python -m scripts.seed_events`), a ressalva de que só semeia com a
      tabela vazia e a pré-condição de schema já criado.
      **Validação:** `grep -n "seed" README.md`
