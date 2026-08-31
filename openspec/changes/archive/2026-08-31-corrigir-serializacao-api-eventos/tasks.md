# Tarefas — Correção da serialização da API JSON de eventos

> Referências: `specs/api-eventos-json/spec.md` (o quê) e `design.md` (como, decisões D1–D6).
> Comandos assumem a raiz do repositório, salvo indicação.
>
> **A suíte roda a partir de `src/`**, não da raiz: `python -m pytest` insere o diretório atual no
> `sys.path`, e é assim que `core`, `routers` e `services` se tornam importáveis. Rodar da raiz
> falha na coleção com `ModuleNotFoundError: No module named 'core'`. Sem dependências de teste no
> host, use o container:
> `docker run --rm -v "/$(pwd)":/w -w //w/src python:3.12-slim sh -c "pip install -q -r requirements-dev.txt && python -m pytest tests/ -q"`

## 1. Reproduzir o defeito antes de corrigir

- [x] 1.1 Subir o ambiente limpo e semear eventos para ter o que listar.
      **Validação:** `docker compose up -d`, `curl -s -o /dev/null -w "%{http_code}" localhost:8000/ready` → `200`,
      `docker compose exec app python -m scripts.seed_events` → `exit=0` e
      `docker compose exec db psql -U encontros_tech -d encontros_tech -tAc "SELECT count(*) FROM events;"` → `10`
- [x] 1.2 **Registrar o estado de partida:** os quatro endpoints respondem `500`.
      **Validação:** `curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/api/events/` → `500`;
      idem para `POST /api/events/` com payload válido e `GET /api/events/by-token/<token>`
- [x] 1.3 **Confirmar a gravação-fantasma do `POST` (D5):** o 500 esconde uma escrita bem-sucedida.
      **Validação:** contar eventos, disparar um `POST` válido (→ `500`), contar de novo — a
      contagem **aumentou** em 1. Anotar o número para o passo 5.4.
- [x] 1.4 **Escrever o teste de regressão que falha agora** (D6): service mockado devolvendo um
      objeto **sem** `model_dump` (`SimpleNamespace` com os atributos do evento, como o ORM);
      espera-se `200` com o corpo correto.
      **Validação:** `cd src && python -m pytest tests/routers/test_api_router.py -k regressao -q` →
      **falha** com `'…' object has no attribute 'model_dump'`. Um teste que já passa aqui não está
      exercitando o defeito.

## 2. Conversão ORM → schema nos quatro handlers (D1, D2)

- [x] 2.1 Implementar a conversão em `read_events` (`GET /`): `Event.model_validate(obj)` por item,
      serializando com `model_dump(mode="json")` (D2). O `Event` usado é o de `schemas.event`, já
      importado no módulo.
      **Validação:** `cd src && python -m pytest tests/routers/test_api_router.py -k listagem -q`
- [x] 2.2 Implementar a conversão em `get_event_by_token` (`GET /by-token/<t>`).
      **Validação:** `cd src && python -m pytest tests/routers/test_api_router.py -k por_token -q`
- [x] 2.3 Implementar a conversão em `create_event` (`POST /`).
      **Validação:** `cd src && python -m pytest tests/routers/test_api_router.py -k criacao -q`
- [x] 2.4 Implementar a conversão em `update_event` (`PUT /by-token/<t>`).
      **Validação:** `cd src && python -m pytest tests/routers/test_api_router.py -k atualizacao -q`
- [x] 2.5 Confirmar que **nenhum** `model_dump()` é chamado sobre objeto do service sem conversão
      prévia.
      **Validação:** `grep -n "model_dump\|model_validate" src/routers/api_router.py` — todo
      `model_dump` é precedido de um `model_validate` no mesmo caminho
- [x] 2.6 Confirmar o escopo: nenhum arquivo além de `api_router.py` foi modificado.
      **Validação:** `git status --porcelain src/ | grep -v '^??'` → apenas
      `src/routers/api_router.py`

## 3. Tratamento de falhas (D4)

- [x] 3.1 Capturar `ValidationError` de conversão **antes** do `except ValueError` nos handlers de
      escrita, para que dado corrompido no banco não seja relatado como payload inválido do cliente
      (D4 — `ValidationError` é subclasse de `ValueError`).
      **Validação:** `cd src && python -m pytest tests/routers/test_api_router.py -k ordem_except -q`
- [x] 3.2 Registrar em log o `id` do registro que falhou na conversão, e responder `500` — nunca um
      corpo parcial apresentado como lista completa (D4).
      **Validação:** `cd src && python -m pytest tests/routers/test_api_router.py -k conversao_invalida -q`
- [x] 3.3 Teste: token inexistente devolve `404`, não `500`, nos dois endpoints por token.
      **Validação:** `cd src && python -m pytest tests/routers/test_api_router.py -k nao_encontrado -q`
- [x] 3.4 Teste: payload sem campo obrigatório, ou com `date` irreconhecível, devolve `400` e nada
      é criado nem alterado.
      **Validação:** `cd src && python -m pytest tests/routers/test_api_router.py -k payload_invalido -q`
- [x] 3.5 Teste: exceção do service devolve `500` sem vazar credencial nem stack trace no corpo, e
      a causa vai para o log.
      **Validação:** `cd src && python -m pytest tests/routers/test_api_router.py -k erro_interno -q`
- [x] 3.6 Confirmar que os `log_business_event` existentes continuam sendo emitidos nos quatro
      caminhos de sucesso — a observabilidade não regride.
      **Validação:** `cd src && python -m pytest tests/routers/test_api_router.py -k log -q`

## 4. Contrato de campos (D2, D3)

- [x] 4.1 Teste: o corpo de sucesso contém `id`, `title`, `description`, `date`, `location` e
      `edit_token`, nos quatro endpoints.
      **Validação:** `cd src && python -m pytest tests/routers/test_api_router.py -k campos -q`
- [x] 4.2 Teste: `date` sai em ISO 8601, e o valor de volta é o mesmo que entrou — não RFC 822 (D2).
      **Validação:** `cd src && python -m pytest tests/routers/test_api_router.py -k data_iso -q` — o
      corpo casa com `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}`, e **não** contém `GMT`
- [x] 4.3 Teste: `technologies` vem como `[]` na leitura e ecoa o valor recebido na escrita, sem
      persistir (D3).
      **Validação:** `cd src && python -m pytest tests/routers/test_api_router.py -k technologies -q`
- [x] 4.4 Teste: listagem de tabela vazia devolve `200` com `[]` — não `404` nem `500`.
      **Validação:** `cd src && python -m pytest tests/routers/test_api_router.py -k lista_vazia -q`
- [x] 4.5 Teste: busca por `search` devolve só os eventos correspondentes, no mesmo formato da
      listagem.
      **Validação:** `cd src && python -m pytest tests/routers/test_api_router.py -k busca -q`

## 5. Gate de verificação

> Não prosseguir para a validação end-to-end enquanto este grupo não estiver inteiramente verde.

- [x] 5.1 O teste de regressão de 1.4, que falhava antes da correção, agora passa.
      **Validação:** `cd src && python -m pytest tests/routers/test_api_router.py -k regressao -q` → passa
- [x] 5.2 Suíte completa passando, sem regressão nos testes existentes (77 antes desta mudança).
      **Validação:** `cd src && python -m pytest tests/ -q`
- [x] 5.3 Conferir a cobertura de cenários: cada `#### Scenario` de
      `specs/api-eventos-json/spec.md` tem teste correspondente ou justificativa registrada de por
      que só é verificável end-to-end (grupo 6).
      **Validação:** revisão cruzada entre `spec.md` e `src/tests/routers/test_api_router.py` — a
      lista de cenários sem cobertura deve estar vazia ou explicada
- [x] 5.4 Confirmar o escopo declarado: apenas `api_router.py` modificado, nenhuma dependência nova,
      `Dockerfile`/`k8s/`/`docker-compose.yml`/`main.py` intocados.
      **Validação:** `git status --porcelain` — apenas `src/routers/api_router.py` modificado e
      arquivos novos sob `src/tests/routers/` e `openspec/changes/corrigir-serializacao-api-eventos/`

## 6. Validação end-to-end em containers

> Executar na ordem, sobre o ambiente do grupo 1 com a imagem reconstruída.

- [x] 6.1 Reconstruir e subir com a correção.
      **Validação:** `docker compose build app && docker compose up -d`, depois
      `curl -s -o /dev/null -w "%{http_code}" localhost:8000/ready` → `200`
- [x] 6.2 **Desbloqueia 9.4 do `seed-eventos-iniciais` (CA6 — listagem):** os eventos semeados
      aparecem na listagem JSON.
      **Validação:** `curl -s localhost:8000/api/events/ | python -c "import json,sys; d=json.load(sys.stdin); print(len(d))"` → `10`
- [x] 6.3 **Desbloqueia 9.5 do `seed-eventos-iniciais` (CA6 — busca):** a busca encontra eventos
      semeados por título, descrição e local.
      **Validação:** `curl -s "localhost:8000/api/events/?search=Python"` devolve `200` com
      subconjunto não vazio; repetir com um termo presente só na descrição e outro só no local
- [x] 6.4 **`date` em ISO 8601 no ambiente real (D2).**
      **Validação:** `curl -s localhost:8000/api/events/ | grep -c "GMT"` → `0`, e o campo `date`
      casa com o padrão ISO
- [x] 6.5 **Ciclo completo de escrita:** `POST` cria e devolve `200` com o evento; o `edit_token`
      da resposta recupera o mesmo evento por `GET /by-token/<t>`; `PUT` atualiza e devolve os
      valores novos.
      **Validação:** executar os três `curl` em sequência, conferindo `id` e `edit_token` estáveis
      entre eles
- [x] 6.6 **Fim da gravação-fantasma (D5):** contagem antes e depois de um `POST` de sucesso sobe
      exatamente 1, e a resposta é `200` — não `500` sobre linha gravada.
      **Validação:** `SELECT count(*) FROM events;` antes e depois; comparar com o comportamento
      anotado em 1.3
- [x] 6.7 **`api-requests.http` volta a funcionar:** os 10 `POST` do arquivo executam com sucesso
      contra tabela vazia.
      **Validação:** `docker compose down -v && docker compose up -d`, aguardar `/ready` → `200`,
      disparar os `POST` do arquivo (REST Client ou `curl` equivalente) — todos `200` — e
      `curl -s localhost:8000/api/events/ | python -c "import json,sys; print(len(json.load(sys.stdin)))"` → `10`
- [x] 6.8 **Falhas explícitas no ambiente real:** token inexistente → `404`; payload sem `title` →
      `400`; banco parado → `500` sem vazar credencial.
      **Validação:** os três `curl` com `-w "%{http_code}"`; para o último,
      `docker compose stop db`, disparar `GET /api/events/`, conferir `500` e que o corpo não
      contém a senha da `DATABASE_URL`; `docker compose start db` ao final
- [x] 6.9 **Caminho HTML sem regressão:** a página inicial e a edição por token continuam
      funcionando como antes.
      **Validação:** `curl -s localhost:8000/ | grep -c "FastAPI\|Kubernetes\|Blockchain"` → maior
      que `0`, e `curl -s -o /dev/null -w "%{http_code}" localhost:8000/events/edit/<token>` → `200`
- [x] 6.10 Registrar o resultado das verificações — comando, saída observada e veredito — em
      `validacao.md` desta mudança.
      **Validação:** revisão: cada requisito de `specs/api-eventos-json/spec.md` tem ao menos uma
      linha correspondente
- [x] 6.11 Devolver o ambiente ao estado limpo após os passos destrutivos.
      **Validação:** `docker compose down -v && docker compose up -d`, aguardar
      `curl -s -o /dev/null -w "%{http_code}" localhost:8000/ready` → `200`

## 7. Fechamento do bloqueio e documentação

- [x] 7.1 Desmarcar o bloqueio das tarefas 9.4 e 9.5 em
      `openspec/changes/seed-eventos-iniciais/tasks.md`, marcando-as concluídas com referência a
      6.2 e 6.3 desta mudança.
      **Validação:** `grep -n "BLOQUEADA" openspec/changes/seed-eventos-iniciais/tasks.md` → sem
      resultados
- [x] 7.2 Atualizar `openspec/changes/seed-eventos-iniciais/validacao.md`: linhas 9.4/9.5 passam a
      ✅, CA6 deixa de ser "parcial" e a seção "Bloqueio conhecido" registra que foi resolvida por
      esta mudança.
      **Validação:** revisão do arquivo — a tabela de CAs não tem mais "✅ parcial"
- [x] 7.3 Registrar no TRD (`docs/trd.md`), na seção da API, que o formato de data das respostas é
      ISO 8601 (D2). Não reescrever outras seções; a arquitetura em camadas não muda.
      **Validação:** `grep -n "ISO 8601" docs/trd.md`
- [x] 7.4 Conferir que nenhum ADR foi reaberto ou alterado.
      **Validação:** `git status --porcelain docs/adrs/` → sem saída
