# PRD — Script de Seed de Eventos · Encontros Tech

**Feature:** Script standalone para popular a tabela `events` com um conjunto inicial de eventos
**Data:** 2026-07-12 · **Status:** Rascunho — aguardando revisão
**Escopo do documento:** comportamento e regra de negócio. Escolhas de implementação (linguagem/biblioteca de acesso ao banco, forma de conexão, mecanismo de `INSERT`, empacotamento do script, integração com pipeline de CI) são deliberadamente omitidas — pertencem ao ADR/TRD.

---

## 1. Contexto

**Produto.** Encontros Tech é uma aplicação de cadastro e listagem de eventos de tecnologia, apoiada em um banco de dados relacional cuja tabela `events` guarda os registros exibidos aos usuários.

**Estado atual.**
- A aplicação sobe com a tabela `events` **vazia** — não há nenhum evento inicial.
- O único meio de popular eventos hoje é disparar manualmente as requisições do arquivo `api-requests.http` (10 `POST` contra a API), o que exige a aplicação **no ar**, é manual, não é repetível de forma confiável e não é automatizável em pipeline.
- Esse arquivo carrega o campo `technologies`, que a aplicação atualmente **não persiste** (não existe coluna correspondente na tabela).

**Problema de negócio.** Sem um conjunto inicial de eventos, cada ambiente novo (dev local, CI/CD) nasce vazio, e o time depende de um passo manual e frágil para ter dados de trabalho. Isso torna demonstrações, testes de listagem/busca e validações de ambiente inconsistentes entre uma execução e outra.

**Objetivo.** Prover um **script de seed independente** que popule a tabela `events` com um conjunto conhecido e determinístico de eventos, executável fora do ciclo de vida da aplicação (depois que o banco existe e as migrations rodaram), de forma repetível e sem duplicar dados em reexecuções.

---

## 2. Atores

| Ator | Papel nesta feature |
|---|---|
| **Operador (dev / pipeline de CI)** | Dispara o script manualmente, após a criação do schema. É quem invoca a execução. |
| **Script de seed** | Executa a lógica: verifica o estado da tabela e insere (ou não) os eventos iniciais. É o sujeito desta feature. |
| **Banco de dados** | Guarda a tabela `events`. Já existe e já está migrado quando o script roda — o script **não** o cria nem altera seu schema. |
| **Aplicação (Encontros Tech)** | Consumidora dos dados semeados. Não participa da execução do seed, mas seus dados precisam ficar válidos para leitura por ela. |

---

## 3. Predicados verificáveis (Dado / Quando / Então)

**P1 — Semeadura em tabela vazia**
Dado que a tabela `events` existe e está vazia,
Quando o script de seed é executado,
Então o script insere o conjunto completo de eventos iniciais e conclui com sucesso.

**P2 — No-op em tabela já populada**
Dado que a tabela `events` já contém ao menos um registro,
Quando o script de seed é executado,
Então o script **não insere nenhum evento**, encerra com sucesso e registra em log que a semeadura foi ignorada por já haver dados.

**P3 — Idempotência entre execuções**
Dado que o script foi executado com sucesso ao menos uma vez sobre a tabela vazia,
Quando o script é executado novamente (uma ou mais vezes),
Então a quantidade e o conteúdo dos eventos permanecem os mesmos da primeira execução (nenhuma duplicata é criada).

**P4 — Conjunto conhecido e completo**
Dado o script executado sobre tabela vazia,
Quando a semeadura termina,
Então a tabela contém exatamente os eventos do catálogo inicial definido no próprio script (derivado do `api-requests.http`), sem itens a mais nem a menos.
*(premissa — confirme ou corrija: o catálogo inicial é composto pelos 10 eventos hoje presentes no `api-requests.http`.)*

**P5 — Campos persistidos por evento**
Dado um evento do catálogo inicial,
Quando ele é inserido,
Então são gravados os campos `title`, `description`, `date` e `location`; o campo `technologies` **não** é gravado (a tabela não o comporta atualmente).

**P6 — Datas relativas ao momento da execução**
Dado que o catálogo inicial define datas de eventos,
Quando o script é executado,
Então as datas gravadas são calculadas em relação ao instante da execução (não são valores fixos herdados do `api-requests.http`), de modo que os eventos semeados não fiquem no passado.
*(premissa — confirme ou corrija: os eventos devem cair no futuro em relação a "agora"; a distribuição relativa entre eles preserva a ordem/espaçamento aproximado do arquivo original.)*

**P7 — Token de edição único por evento**
Dado que a aplicação identifica cada evento por um token de edição único,
Quando um evento é semeado,
Então ele recebe um `edit_token` único e não-nulo, de forma que a aplicação consiga localizá-lo e editá-lo pelos fluxos existentes.

**P8 — Legibilidade pela aplicação**
Dado que o script concluiu a semeadura,
Quando a aplicação lista ou busca eventos,
Então todos os eventos semeados aparecem corretamente na listagem e na busca, sem erro de leitura por campo ausente ou inválido.

**P9 — Independência do ciclo de vida da aplicação**
Dado que a aplicação **não** está em execução, mas o banco existe e está migrado,
Quando o script de seed é executado,
Então ele conclui a semeadura com sucesso sem depender de a aplicação estar no ar.

**P10 — Pré-condição de schema ausente**
Dado que a tabela `events` **não** existe (migrations não executadas),
Quando o script de seed é executado,
Então o script encerra com falha explícita e mensagem clara indicando a pré-condição não atendida, **sem** criar ou alterar o schema.

**P11 — Falha de conexão ao banco**
Dado que o banco de dados está inalcançável,
Quando o script de seed é executado,
Então o script encerra com falha explícita e mensagem clara, sem deixar a tabela em estado parcialmente semeado.

**P12 — Atomicidade da semeadura**
Dado que a semeadura está em andamento sobre tabela vazia,
Quando ocorre um erro no meio da inserção do conjunto,
Então nenhum evento parcial permanece: ou todos os eventos do catálogo são inseridos, ou nenhum.

---

## 4. Invariantes

- **I1.** Uma execução do script sobre tabela **não vazia** nunca altera, insere ou remove registros.
- **I2.** Reexecuções sucessivas do script nunca produzem duplicatas nem divergência de conteúdo em relação à primeira semeadura bem-sucedida.
- **I3.** O script nunca cria nem altera o schema do banco — assume que a tabela `events` já existe.
- **I4.** Todo evento semeado tem `edit_token` único e não-nulo.
- **I5.** Nenhum evento semeado tem data no passado em relação ao instante da execução.
- **I6.** A tabela nunca fica em estado parcialmente semeado: a semeadura é tudo-ou-nada (I decorre de P12).
- **I7.** O script não depende de a aplicação estar em execução.

---

## 5. Restrições (de negócio / comportamento)

- **R1.** O script é **standalone** e autocontido: sua execução não faz parte do boot da aplicação e não é disparada por ele.
- **R2.** O catálogo de eventos iniciais é **fixo e definido no próprio script** (hardcoded), derivado do `api-requests.http` — não depende de arquivo externo de dados nem de entrada do operador.
- **R3.** A semeadura só ocorre quando a tabela está vazia; caso contrário, é no-op. (Evita duplicatas em ambientes já populados.)
- **R4.** O campo `technologies` não é semeado enquanto a tabela não o suportar. (Coerente com o schema atual.)
- **R5.** O script não é responsável por criar schema, rodar migrations nem subir a aplicação — esses são passos anteriores e externos.
- **R6.** O resultado da execução deve ser observável em log: se semeou (e quantos), ou se ignorou por já haver dados, ou se falhou e por quê.

---

## 6. Fora do escopo (com justificativa)

- **F1. Integração com a pipeline de CI/CD** (em que estágio o script é chamado, orquestração, gates). *Porquê:* será resolvido na construção do CI; aqui entregamos apenas o script executável isoladamente.
- **F2. Criação de schema / migrations.** *Porquê:* é passo anterior e de responsabilidade de outra trilha; o script assume o schema pronto (I3, P10).
- **F3. Disparo automático do seed no start da aplicação** (gancho de boot, flag de ambiente). *Porquê:* decidiu-se por um script standalone; acoplar ao boot reintroduz risco de rodar em produção e a cada restart.
- **F4. Persistência de `technologies`** (nova coluna, tabela associada ou model). *Porquê:* mudança de schema/modelo de dados que extrapola o objetivo do seed; enquanto não existir, o campo é ignorado (R4).
- **F5. Atualização/sincronização de eventos já existentes** (upsert, reconciliação). *Porquê:* a regra escolhida é "semear só se vazio"; atualizar dados existentes é outro comportamento, não pedido.
- **F6. Modo de reset/limpeza da tabela** (`--force`, truncate). *Porquê:* não solicitado e potencialmente destrutivo; se necessário, será tratado em feature própria.
- **F7. Parametrização do conjunto semeado** (quantidade, dataset alternativo, seleção por ambiente). *Porquê:* o catálogo é fixo e hardcoded por decisão explícita (R2).
- **F8. Escolha de tecnologia de acesso ao banco e formato de conexão.** *Porquê:* é "como", não "o quê" — pertence ao ADR/TRD. O PRD só exige o comportamento observável.

---

## 7. Critérios de aceite (observáveis)

A feature é considerada "pronta" quando **todos** os itens abaixo são demonstráveis:

- **CA1.** Com a tabela `events` vazia e migrada, executar o script insere exatamente o catálogo inicial e encerra com sucesso; a contagem final de eventos é igual ao tamanho do catálogo. *(P1, P4)*
- **CA2.** Executar o script uma segunda vez (com a tabela já populada) não altera a contagem nem o conteúdo, encerra com sucesso e registra em log que a semeadura foi ignorada. *(P2, P3, I1, I2)*
- **CA3.** Inspecionando os eventos semeados, cada um tem `title`, `description`, `date` e `location` preenchidos, e nenhum depende de `technologies`. *(P5)*
- **CA4.** Todas as datas dos eventos semeados são posteriores ao instante da execução. *(P6, I5)*
- **CA5.** Cada evento semeado tem um `edit_token` único e não-nulo, e é localizável/editável pelos fluxos existentes da aplicação. *(P7, I4)*
- **CA6.** Com a aplicação **desligada**, o script roda e semeia com sucesso; ao subir a aplicação depois, todos os eventos aparecem na listagem e na busca. *(P8, P9)*
- **CA7.** Executar o script sem a tabela `events` existir resulta em falha explícita com mensagem clara, sem que o schema seja criado ou alterado. *(P10, I3)*
- **CA8.** Executar o script com o banco inalcançável resulta em falha explícita, sem deixar a tabela parcialmente semeada. *(P11, P12, I6)*
- **CA9.** A saída de log de qualquer execução deixa claro o desfecho: semeou (quantos), ignorou (já havia dados) ou falhou (motivo). *(R6)*

---

## Premissas a confirmar

1. **Catálogo inicial = os 10 eventos do `api-requests.http`** (P4).
2. **Datas relativas ao "agora" caindo no futuro**, preservando a ordem/espaçamento aproximado do arquivo original (P6, I5).
3. **Comportamento em tabela não-vazia é no-op silencioso de dados** (apenas loga), não erro — reexecução deve encerrar com sucesso (P2).
