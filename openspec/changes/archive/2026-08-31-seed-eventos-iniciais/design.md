## Context

O PRD-0002 pede um script standalone que popule a tabela `events` com um catálogo conhecido, de
forma repetível e sem duplicar dados. O `proposal.md` descreve o quê e o porquê; este documento fixa
o como.

**Estado atual relevante.**

- `models/event.py` define `Event` com `title`, `description`, `date`, `location` e `edit_token`
  (`unique=True`, `default=lambda: str(uuid.uuid4())`). **Não há coluna `technologies`** — e
  `event_service.create_event` já traz o comentário de que o campo não é persistido.
- `core/database.py` expõe `engine` (negócio, `connect_timeout` de 10 s + keepalives TCP),
  `health_engine` (NullPool, teto curto de prontidão) e `SessionLocal`.
- `core/schema.py` expõe `prepare_schema`/`ensure_schema`, que criam o schema via `create_all` sob
  advisory lock. **É o único caminho que cria a tabela hoje**, e roda no import de `main.py`.
- `core/logging.py` separa `setup_logging` (que instala o handler em `stdout`) de `get_logger` (que
  apenas retorna um logger filho de `encontros-tech`).
- `pytest.ini` define `pythonpath = .`; os testes existentes vivem em `src/tests/**` e mockam o
  engine com `unittest.mock`, sem banco real.
- `Dockerfile` faz `COPY src/ /app/`, então qualquer módulo novo sob `src/` entra na imagem sem
  alteração de build.

**Restrições.** ADR 001 (container único, usuário não-root, `python:3.12-slim`), ADR 002 (plataforma)
e ADR 003 (Postgres em `StatefulSet` de réplica única dentro do cluster) são aceitos e não são
reabertos aqui. O TRD define a estrutura de pastas `src/` e a camada `core/database.py` como dona do
engine e da sessão — o script se encaixa nessa estrutura em vez de criar uma paralela.

**Tensão herdada.** O PRD assume, em P9, que o banco "existe e está migrado" com a aplicação
desligada. Hoje não existe mecanismo de migration separado do boot da aplicação: o schema só nasce
quando `main.py` é importado. Essa lacuna foi reconhecida na exploração e **deliberadamente não é
resolvida aqui** (ver D1 e Open Questions).

## Goals / Non-Goals

**Goals:**

- Um módulo executável, sem dependências novas, que semeia o catálogo de 10 eventos de forma atômica
  e idempotente.
- Distinguir com clareza os três desfechos — semeou, ignorou, falhou — em log e em código de saída.
- Distinguir as duas falhas possíveis entre si: schema ausente (P10) e banco inalcançável (P11).
- Reusar `models/event.py`, `core/database.py` e `core/logging.py` sem modificá-los.
- Testabilidade no mesmo estilo da suíte existente: mock do engine, sem banco real.

**Non-Goals:**

- Criar schema ou rodar migrations — proibido por I3 (F2).
- Disparar o seed no boot da aplicação (F3).
- Suporte a execução concorrente (premissa desta mudança).
- Upsert, reconciliação, modo `--force`, truncate ou parametrização do catálogo (F5, F6, F7).
- Persistir `technologies` (F4).
- Integração com pipeline de CI/CD (F1) — o script apenas oferece um código de saída utilizável.

## Decisions

### D1 — O script verifica a pré-condição de schema, nunca a satisfaz

**Decisão.** Antes de qualquer leitura ou escrita de negócio, o script verifica a existência da
tabela `events` via inspeção de metadados (`sqlalchemy.inspect(engine).has_table("events")`). Não
existindo, encerra em falha com mensagem que nomeia a pré-condição. Ele **não** importa
`core.schema`, **não** chama `ensure_schema` e **não** chama `create_all`.

**Alternativa considerada e rejeitada:** reusar `ensure_schema` para garantir a tabela antes de
semear. Eliminaria a dependência de um passo externo que hoje não é formalizado, mas violaria I3 e
apagaria a fronteira entre seed e migration — um script de dados passaria a ter autoridade sobre o
schema. Rejeitada explicitamente na exploração; a lacuna de migration fica registrada em Open
Questions, para uma trilha própria.

**Consequência operacional.** Na prática, hoje, "banco migrado" significa "a aplicação subiu ao menos
uma vez contra este banco". Isso é aceito como pré-condição do operador, não automatizado pelo script.

### D2 — Distinguir schema ausente de banco inalcançável

**Decisão.** As duas falhas produzem mensagens distintas. A ordem importa: a inspeção de metadados é
a primeira operação que toca o banco, então um banco inalcançável falha **ali**, com
`OperationalError`, antes de qualquer conclusão sobre a tabela. O tratamento separa os casos por tipo
de exceção — falha de conexão/driver é reportada como P11; ausência de tabela, detectada por
inspeção bem-sucedida que retorna `False`, é reportada como P10.

**Por que importa.** Sem essa separação, "tabela não encontrada" seria a mensagem exibida para um
banco fora do ar, mandando o operador investigar migrations quando o problema é rede ou credencial.
A spec exige explicitamente que as mensagens sejam distinguíveis.

### D3 — Datas por deslocamento em bloco, com âncora à frente do instante da execução

**Decisão.** Cada evento recebe:

```
data_semeada = agora + MARGEM + (data_original_do_evento − data_original_mais_antiga)
```

O catálogo guarda as datas originais do `api-requests.http`; o script calcula o delta de cada uma em
relação à **mais antiga do conjunto** (`2024-02-15T19:00`, o Workshop de FastAPI) e desloca tudo.

**Por que a `MARGEM` existe.** Sem ela, o evento mais antigo receberia exatamente `agora` — que já é
passado no instante em que a transação é confirmada, violando I5 por uma diferença de milissegundos.
A margem torna o primeiro evento estritamente futuro por construção, não por sorte de timing.

**Alternativa considerada e rejeitada:** distribuição uniforme em uma janela fixa
(`agora + i × janela/N`). Mais simples de calcular, mas perde a variação real de espaçamento do
catálogo original — os intervalos entre os 10 eventos vão de ~5 a ~15 dias, e achatá-los tornaria o
conjunto artificialmente regular, empobrecendo o dado de demonstração que é o propósito do seed.

**Consequência.** O conjunto semeado ocupa uma janela de ~55 dias a partir de `agora + MARGEM`,
espelhando a distribuição fevereiro–abril do arquivo original.

### D4 — Fuso e tipo da data: `datetime` ingênuo em UTC

**Decisão.** O `agora` é obtido como `datetime.utcnow()` (ingênuo, em UTC), coerente com o `default`
do modelo `Event.date` e com a coluna `DateTime` sem `timezone=True`.

**Por quê.** Misturar um `datetime` com fuso a uma coluna `DateTime` ingênua produziria comparações
incorretas na ordenação por data que `event_service.get_events` aplica. A escolha aqui é
**consistência com o schema existente**, não uma opinião sobre a melhor prática de fuso — corrigir o
modelo de tempo do projeto é outro assunto, fora do escopo deste seed.

### D5 — Inserção via ORM, em uma única transação

**Decisão.** O script constrói objetos `Event` e usa uma sessão do `SessionLocal`, com um único
`commit` ao final e `rollback` em qualquer exceção.

**Por quê.**

- **`edit_token` sai de graça e correto.** O token é gerado por `default=lambda: str(uuid.uuid4())`
  no **ORM**, não pelo banco. Uma inserção por SQL cru deixaria a coluna nula e violaria I4/P7 —
  armadilha real, já que a coluna não tem `server_default`.
- **Atomicidade (P12/I6) é o comportamento padrão** de uma transação com commit único: um erro no
  meio do lote não deixa resíduo.
- Reusa o mapeamento existente; se o modelo mudar, o script acompanha.

**Alternativa considerada e rejeitada:** `INSERT` em SQL cru via `text()`. Mais leve, mas exigiria
duplicar a geração de token e o conhecimento das colunas — dois lugares para errar, sem ganho nesta
escala (10 linhas).

### D6 — Engine de negócio, não o `health_engine`

**Decisão.** O script usa `engine`/`SessionLocal` de `core.database`.

**Por quê.** O `health_engine` existe para responder probes: `NullPool` e teto curto derivado de
`READINESS_DB_TIMEOUT_SECONDS`, calibrado para "não prender o kubelet". O engine de negócio tem
`connect_timeout` de 10 s e keepalives TCP — o suficiente para não pendurar o script contra um banco
congelado (exigência da spec), sem transformar uma latência normal em falha. Reusar o engine de
prontidão acoplaria o seed a um parâmetro cujo propósito é outro.

### D7 — Checagem de vazio por existência, não por contagem

**Decisão.** A condição "tabela vazia" é avaliada por uma consulta que para no primeiro registro
(`SELECT ... LIMIT 1`), não por `COUNT(*)`.

**Por quê.** O predicado é "existe algum registro?", e é isso que a consulta deve perguntar. Contra o
Postgres de réplica única do ADR 003, um `COUNT(*)` percorreria a tabela inteira para responder uma
pergunta booleana — irrelevante com 10 linhas, desnecessário sempre.

### D8 — O script configura o próprio logging

**Decisão.** O ponto de entrada chama `setup_logging(...)` antes de qualquer mensagem, usando os
valores de `settings`.

**Por quê.** `get_logger` devolve um filho de `encontros-tech`, que **só tem handler depois** que
`setup_logging` roda — e quem faz isso hoje é `main.py`. Um script que apenas chamasse `get_logger`
escreveria em um logger sem handler: as mensagens de desfecho exigidas por R6 sumiriam
silenciosamente, e o operador veria um processo mudo. É o tipo de falha que só aparece em produção,
por isso está fixada como decisão e coberta por cenário na spec.

### D9 — Códigos de saída: `0` para sucesso e no-op, `1` para falha

**Decisão.** Semeou → `0`. Ignorou por já haver dados → `0`. Falhou (schema ausente ou conexão) →
`1`. O script não distingue as falhas por código, apenas por mensagem.

**Por quê.** O no-op é um desfecho **esperado e correto** (P2, premissa 3 do PRD): um pipeline que
roda o seed a cada deploy não pode falhar porque o ambiente já estava semeado. Códigos distintos por
tipo de falha seriam especulação sobre um consumidor que ainda não existe — F1 mantém a integração
com CI fora de escopo, e o par sucesso/falha basta para um gate.

### D10 — Localização e forma de invocação

**Decisão.** `src/scripts/seed_events.py`, com `__init__.py`, executado como
`python -m scripts.seed_events` a partir de `src/` (ou de `/app`, no container). O módulo expõe
funções puras testáveis e um `main()` sob `if __name__ == "__main__":`.

**Por quê.** `src/scripts/` é a extensão natural da estrutura do TRD para código operacional que não
é `core`, `service` nem `router`. A invocação por `-m` alinha-se ao `pythonpath` que a aplicação já
usa dentro do container, sem manipulação de `sys.path` no próprio arquivo. Nenhuma mudança no
`Dockerfile` é necessária: `COPY src/ /app/` já leva o script junto.

**Invocação típica:**

| Ambiente | Comando |
|---|---|
| Local | `cd src && python -m scripts.seed_events` |
| Docker Compose | `docker compose exec app python -m scripts.seed_events` |
| Kubernetes | `kubectl exec -n encontros-tech deploy/encontros-tech -- python -m scripts.seed_events` |

### D11 — O catálogo é dado, não código

**Decisão.** As 10 entradas ficam em uma estrutura de dados constante no módulo (título, descrição,
local e data original), separada da lógica que calcula datas e insere. O campo `technologies` do
arquivo original **não** é transportado para a estrutura.

**Por quê.** Manter o catálogo como dado torna trivial verificar "são exatamente os 10 do
`api-requests.http`" em revisão e em teste. Omitir `technologies` desde a estrutura — em vez de
carregá-lo e ignorá-lo na inserção — evita sugerir que existe um caminho de persistência para ele
(R4/F4).

### D12 — Três exceções, não duas; e testes contra banco real onde o mock não alcança

**Decisão tomada durante a implementação**, a partir de duas descobertas.

**(a) `FalhaNaSemeadura` além de `BancoInalcancavel`.** D2 previa dois modos de falha — schema
ausente e banco inalcançável. Faltava um terceiro: erro de banco **já durante a inserção**, com a
conexão existindo. Pode ser perda de conexão no meio do lote ou violação de constraint. Rotular isso
como "banco inalcançável" mentiria para o operador. As três exceções (`PreCondicaoNaoAtendida`,
`BancoInalcancavel`, `FalhaNaSemeadura`) produzem mensagens distintas e todas mapeiam para saída `1`,
preservando D9.

**(b) O `default` do ORM só age no flush.** `Column(default=...)` é um default **de coluna aplicado
no INSERT**, não na construção do objeto: `Event(...).edit_token` é `None` até o flush. Com sessão
mockada não há flush, então nenhum teste de sessão simulada consegue observar a geração do token — a
invariante I4 ficaria sem verificação real. A suíte passou a ter duas camadas:

| Camada | Cobre |
|---|---|
| Sessão mockada (`unittest.mock`) | fluxo, guardas, no-op, mensagens, códigos de saída, caminhos de erro |
| SQLite em memória (`StaticPool`) | geração e unicidade do `edit_token` no flush, inserção real do catálogo, rollback efetivo, idempotência entre reexecuções, e o par `verificar_tabela`/`tabela_vazia` contra um banco de verdade |

A camada SQLite é um desvio consciente do "sem banco real" que o plano original sugeria: é a única
forma de verificar I4 e P12 sem subir Postgres, e exercita o caminho de código completo em vez de
afirmar sobre chamadas mockadas. O `create_all` do SQLite acontece **no teste**, nunca no script —
I3 permanece intacta.

## Risks / Trade-offs

**[Seed disparado contra o ambiente errado]** → É o risco de maior consequência. R3 protege bancos
já populados, mas um banco de produção **vazio** — recém-provisionado, ou alcançado por um
`DATABASE_URL` errado exportado no shell — seria semeado com 10 eventos fictícios visíveis a usuários
reais. Mitigação parcial e deliberadamente operacional: antes de escrever, o script loga o destino
(host/base, sem credenciais) para que o operador reconheça o alvo. Não há gate técnico; adicioná-lo
significaria um modo interativo ou uma flag de confirmação, ambos fora do escopo do PRD.

**[Check-then-act sob concorrência]** → Duas execuções simultâneas sobre a tabela vazia podem ambas
ver "vazia" e inserir, produzindo 20 eventos; nenhuma constraint do schema barraria isso (não há
`unique` em `title`). Mitigação escolhida: **nenhuma técnica** — execução serializada é premissa
declarada, registrada na spec como cenário de resultado não garantido. Se um dia o seed for para
dentro de um pipeline com jobs paralelos, o advisory lock do Postgres já usado em `core/schema.py` é
o caminho pronto para fechar a janela.

**[Datas relativas quebram determinismo literal]** → Duas execuções em instantes diferentes produzem
datas diferentes, então um teste não pode afirmar igualdade contra valores fixos. Mitigação: os
testes verificam **propriedades** — todas as datas no futuro, deltas entre eventos preservados, ordem
mantida — em vez de valores absolutos. É a leitura correta de I2, que fala em idempotência entre
reexecuções (onde nada é reinserido), não em reprodutibilidade entre ambientes.

**[Acoplamento ao `default` do ORM para o token]** → I4 depende de um `default` em Python, não de um
`server_default`. Se um dia alguém inserir eventos por SQL cru — em outro script, em uma migration —
o token virá nulo e o índice único não impedirá (nulos não colidem em Postgres). Mitigação neste
escopo: D5 mantém o seed no ORM e um teste afirma tokens não-nulos e distintos. Endurecer o schema é
outra mudança.

**[Catálogo hardcoded diverge do `api-requests.http`]** → São duas cópias da mesma lista; editar uma
não atualiza a outra. Mitigação: aceitar a duplicação (R2 exige o catálogo no script) e registrar em
comentário que o arquivo é a origem. Derivar em tempo de execução do `.http` seria parsear um formato
de cliente REST para popular um banco — frágil e fora do espírito de "autocontido".

**[Uso único por ambiente]** → Depois da primeira semeadura a tabela nunca mais está vazia, então
toda execução futura é no-op. É o comportamento pedido (F5/F6), mas significa que corrigir um
catálogo malformado exige intervenção manual em SQL. O plano de rollback do `proposal.md` cobre esse
caminho.

## Migration Plan

Não há migração de schema nem de dados. A implantação é a entrada dos arquivos novos no repositório e,
por consequência, na próxima imagem — sem rebuild obrigatório, porque nada em execução referencia o
script.

**Ordem de uso em um ambiente novo:** provisionar o banco → garantir o schema (hoje: subir a
aplicação ao menos uma vez) → executar o script → conferir a listagem.

**Rollback:** ver `proposal.md` — `git revert` para o código (aditivo, sem referências) e `DELETE`
seletivo para os dados, seguro por construção, já que a semeadura só ocorre em tabela vazia.

## Open Questions

1. **Quem migra o banco quando a aplicação não sobe?** Esta mudança assume o schema pronto (D1), mas
   o projeto não tem mecanismo de migration independente do boot de `main.py`. Enquanto isso não
   existir, P9 ("script roda com a aplicação desligada") só é satisfeito por bancos que já viram a
   aplicação subir. Merece trilha própria — Alembic, ou um comando de schema separado.
2. **`MARGEM` de quanto?** D3 exige que a margem exista e seja suficiente; o valor concreto (uma
   hora, um dia) é escolha de implementação. Um dia deixa o conjunto visivelmente "a partir de
   amanhã", o que costuma ler melhor em demonstração.
3. **O seed deve marcar seus próprios registros?** Hoje um evento semeado é indistinguível de um
   criado por usuário, o que torna o rollback de dados dependente de inspeção por `id`. Uma marcação
   resolveria, mas exigiria coluna nova — mudança de schema, vedada aqui por I3.
