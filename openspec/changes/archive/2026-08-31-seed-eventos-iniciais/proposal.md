# Script de seed de eventos iniciais

## Why

A tabela `events` nasce vazia em todo ambiente novo. O único meio de populá-la hoje é disparar
manualmente os 10 `POST` do `api-requests.http` contra a API — o que exige a aplicação no ar, é
manual, não é repetível de forma confiável e não é automatizável em pipeline. Pior: as datas daquele
arquivo são de **2024**, ou seja, um seed literal já nasceria com todos os eventos no passado,
invisíveis na ordenação por data que `event_service.get_events` aplica.

Sem conjunto inicial, demonstrações, testes de listagem/busca e validações de ambiente ficam
inconsistentes entre uma execução e outra. O PRD-0002 (`docs/prds/PRD-0002-seed-eventos.md`) define o
comportamento esperado em P1–P12, I1–I7 e R1–R6. Esta mudança o implementa.

## What Changes

**Novo script standalone**

- Novo módulo executável de seed em `src/scripts/`, invocável fora do ciclo de vida da aplicação
  (`python -m scripts.seed_events`, a partir de `src/` ou de `/app` no container). **Não** é chamado
  pelo boot da aplicação e **não** é registrado como blueprint, comando Flask ou hook (R1, F3).
- **Catálogo hardcoded** dos 10 eventos derivados do `api-requests.http`, definido no próprio
  script — sem arquivo externo de dados e sem entrada do operador (R2, P4, F7).
- **Guarda de pré-condição:** se a tabela `events` não existir, o script encerra com **falha
  explícita** e mensagem clara, sem criar nem alterar schema (P10, I3). Ele nunca chama
  `ensure_schema` nem `create_all`.
- **Guarda de idempotência:** semeia apenas com a tabela vazia; havendo qualquer registro, é no-op
  que encerra com **sucesso** e registra em log que a semeadura foi ignorada (P2, P3, R3, I1, I2).
- **Datas recalculadas por deslocamento em bloco:** cada evento recebe
  `agora + (data_original_do_evento − data_original_do_primeiro_evento)`, preservando os intervalos
  reais entre os 10 eventos do arquivo (que variam de 5 a 15 dias) e garantindo que nenhum caia no
  passado (P6, I5).
- **`edit_token` por evento:** gerado pelo `default` do modelo ORM `Event`, único e não-nulo (P7, I4).
- **Atomicidade:** a inserção do catálogo inteiro ocorre em uma única transação — ou todos os 10
  eventos entram, ou nenhum (P12, I6).
- **`technologies` não é semeado**, coerente com o schema atual, que não tem coluna correspondente
  (P5, R4, F4).
- **Desfecho observável em log**: semeou (e quantos), ignorou (já havia dados) ou falhou (motivo),
  usando o `core.logging` já existente (R6).
- **Código de saída** distinguindo sucesso (semeou ou no-op) de falha (pré-condição não atendida,
  banco inalcançável), para que um pipeline futuro consiga fazer gate sobre ele.

**Testes**

- Novos testes em `src/tests/scripts/`, no mesmo estilo dos existentes (`unittest.mock` sobre o
  engine, sem banco real), cobrindo tabela vazia, tabela populada, tabela ausente, falha de conexão,
  atomicidade e o cálculo de datas.

**Premissas fixadas nesta mudança** (decididas na exploração, ver `design.md`)

- O schema é assumido pronto — a criação continua sendo responsabilidade de outra trilha (F2).
- A execução é assumida **serializada**: o script não é projetado para execução concorrente.
- O algoritmo de datas é o deslocamento em bloco descrito acima.

**Nada muda** na aplicação: nenhum endpoint, nenhum model, nenhum service, nenhum manifesto
Kubernetes, nenhuma variável de ambiente nova.

## Capabilities

### New Capabilities

- `seed-dados-iniciais`: contrato observável da semeadura de dados iniciais — condição de disparo
  (só em tabela vazia), idempotência entre execuções, atomicidade tudo-ou-nada, pré-condições de
  schema e de conectividade, independência do ciclo de vida da aplicação, forma do catálogo semeado
  (campos persistidos, unicidade do token, datas sempre futuras) e observabilidade do desfecho.

### Modified Capabilities

Nenhuma. O script é aditivo e não altera requisito de nenhuma capability existente:

- `empacotamento-container` — o script entra na imagem sem mudança no `Dockerfile`, que já faz
  `COPY src/ /app/`. Nenhum requisito de empacotamento muda.
- `saude-prontidao` — o seed não participa do boot nem das probes.
- `implantacao-kubernetes` — nenhum recurso, ConfigMap ou probe é tocado. A execução em cluster é um
  `kubectl exec` pontual, não um recurso versionado.
- `observabilidade` — o script não sobe servidor HTTP e não emite métricas Prometheus; seu desfecho
  é observado por log e código de saída.

## Impact

**Código afetado**

| Arquivo | Natureza da mudança |
|---|---|
| `src/scripts/__init__.py` | novo — pacote |
| `src/scripts/seed_events.py` | novo — catálogo, guardas, cálculo de datas, inserção e logs |
| `src/tests/scripts/` | novo — testes do script |

Nenhum arquivo existente é modificado. `models/event.py`, `core/database.py`, `core/logging.py` e
`core/schema.py` são **lidos/reusados**, não alterados.

**Superfície pública.** Nenhuma. Nenhuma rota nova, nenhum contrato de API tocado. A única superfície
nova é a linha de comando do script.

**Dependências.** Nenhuma nova. Usa SQLAlchemy e `psycopg2-binary`, já em `src/requirements.txt`.

**ADRs e TRD.** Compatível com ADR 001 (containerização), ADR 002 (plataforma) e ADR 003 (Postgres em
`StatefulSet` dentro do cluster) — nenhum é reaberto. O TRD ganha, no máximo, uma linha na estrutura
de pastas (`src/scripts/`); a seção de modelo de dados não muda, porque o schema não muda.

### Impacto em disponibilidade / HA

**Sobre a aplicação em execução: nenhum.** O script não faz parte do boot (R1, F3), não registra
rotas, não altera schema e não reinicia processo. Uma aplicação no ar durante a semeadura continua
servindo normalmente; os eventos simplesmente passam a aparecer na listagem.

**Riscos introduzidos.**

1. **Carga pontual no banco de réplica única.** Pelo ADR 003, o Postgres roda em um `StatefulSet` de
   uma réplica. O script abre uma conexão e faz 10 `INSERT` em uma transação — carga desprezível,
   mas concorre com o mesmo banco que serve o tráfego e as probes de prontidão. Não há risco prático
   de contenção nesta escala.
2. **Este é o primeiro caminho de escrita operacional do projeto.** Até aqui, todo artefato de
   operação era read-only (probes, métricas). O seed grava dados de negócio. A mitigação estrutural é
   R3 (só semeia em tabela vazia) — ver blast radius.
3. **Execução concorrente não é coberta.** A checagem "tabela vazia → semeia" é *check-then-act*. Dois
   operadores, ou dois jobs, rodando o script ao mesmo tempo contra uma tabela vazia poderiam ambos
   ver "vazia" e inserir, resultando em 20 eventos — e o schema não tem nenhuma constraint que
   barraria isso silenciosamente (não há `unique` em `title`). **Decisão explícita:** execução
   serializada é premissa desta mudança; concorrência fica fora de escopo. Está registrado como
   limitação conhecida no `design.md`, não como bug.

### Blast radius

```
              ┌──────────────────────────────────────────────┐
              │ MÉDIO — dados de negócio da tabela events    │
              │ único efeito real da mudança: 10 linhas      │
              │ inseridas. Contido por R3 (só se vazia).     │
              ├──────────────────────────────────────────────┤
              │ BAIXO — imagem do container                  │
              │ arquivos novos entram via COPY src/ já       │
              │ existente; não alteram o CMD nem o runtime   │
              ├──────────────────────────────────────────────┤
              │ NENHUM — aplicação em execução, probes,      │
              │ schema, manifesto, API, dependências         │
              └──────────────────────────────────────────────┘
```

- **Escopo de infraestrutura:** nenhum. Não toca `k8s/manifesto.yaml`, ConfigMap, Secret,
  Deployment, Service nem StatefulSet.
- **Escopo de schema:** nenhum, por invariante (I3). O script falha em vez de criar tabela.
- **Escopo de dados:** a tabela `events`, e **somente** quando ela está vazia.
- **Consumidores externos:** nenhum.
- **Pior caso realista:** rodar o script apontando para um banco de **produção que esteja vazio** —
  por exemplo, logo após um provisionamento, ou com `DATABASE_URL` do ambiente errado exportada no
  shell. R3 protege o banco populado, mas é justamente o banco vazio o estado em que o seed é mais
  perigoso e menos perceptível: 10 eventos fictícios entram em produção e ficam visíveis a usuários
  reais. A mitigação é operacional (o script loga a URL do banco — sem credenciais — antes de
  semear, para que o operador reconheça o alvo), não técnica.
- **Efeito colateral de longo prazo:** depois da primeira semeadura bem-sucedida, a tabela nunca
  mais está vazia, então toda execução futura é no-op. O script é, na prática, "de uso único por
  ambiente" — o que é exatamente o comportamento pedido (F5, F6).

### Plano de rollback

O rollback é trivial porque a mudança é aditiva em código e reversível em dados.

**Gatilhos.** Semeadura disparada contra o ambiente errado; catálogo com conteúdo indesejado; datas
calculadas de forma incorreta (eventos no passado, violando I5).

1. **Reverter o código (imediato, sem efeito colateral).** `git revert` do merge. Como nenhum arquivo
   existente é modificado e o script não é referenciado por nada — nem pelo boot, nem pelo
   `Dockerfile`, nem pelo manifesto —, remover os arquivos novos devolve o repositório exatamente ao
   estado anterior. Não há rebuild obrigatório: a imagem em execução simplesmente passa a conter um
   script que ninguém invoca.
2. **Reverter os dados semeados.** Os eventos semeados não carregam marcação que os distinga de
   eventos criados por usuários. Porém, por R3, a semeadura **só ocorre em tabela vazia** — logo, se
   ela ocorreu, todo registro anterior a ela é inexistente. O rollback de dados é:
   - se nenhum evento foi criado por usuários desde a semeadura: `DELETE FROM events;` devolve a
     tabela ao estado pré-seed;
   - se já houve criação de eventos reais: apagar seletivamente pelos `id` das 10 linhas semeadas
     (as de menor `id`, contíguas, registradas no log da execução).
3. **Sem passo de migração.** Não há schema a reverter (I3), nenhuma coluna criada, nenhum índice.

**Ponto sem retorno:** nenhum. O único efeito persistente são 10 linhas em uma tabela, removíveis por
`DELETE`. Como a semeadura só acontece em tabela vazia, não existe cenário em que o rollback destrua
dados que já existiam antes da mudança.
