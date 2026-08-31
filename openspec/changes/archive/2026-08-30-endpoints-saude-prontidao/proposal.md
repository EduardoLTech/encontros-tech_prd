# Endpoints de saúde e prontidão

## Why

A aplicação não expõe nenhum sinal de saúde ou prontidão. O Kubernetes hoje usa a rota de negócio `/`
como readiness e um `tcpSocket` como liveness, de modo que não consegue distinguir "processo travado"
de "banco temporariamente fora" — e, pior, `src/main.py:21` executa `create_all` no import, fazendo o
processo **falhar no boot** quando o banco está indisponível, o que leva a CrashLoopBackOff com backoff
progressivo em vez de recuperação imediata.

O PRD-0001 (`docs/prds/PRD-0001-health-readiness.md`, revisão de 2026-08-30) define o comportamento
esperado em P1–P11 e I1–I7. Esta mudança o implementa.

## What Changes

**Aplicação**

- Novo endpoint `GET /health` — liveness. Responde 200 enquanto o processo estiver responsivo,
  **independentemente do estado do banco** (P1, P2, I3, R1).
- Novo endpoint `GET /ready` — readiness. Verifica a conectividade com o banco no momento da consulta
  (sem cache, I6) e responde 200 `{"status":"ready","checks":{"database":"ok"}}` ou 503
  `{"status":"not_ready","checks":{"database":"down"}}` (P3, P4, P11).
- **BREAKING (comportamento de boot):** a criação de schema deixa de ser bloqueante no import. O
  processo passa a concluir a inicialização mesmo com o banco fora, respondendo `/health` 200 e
  `/ready` 503, e converge para pronto sem reinício quando o banco volta (P7, P8, I4).
- Novo teto de tempo para a verificação de prontidão: **5 s por padrão**, parametrizável por variável
  de ambiente aplicada no deploy, com piso efetivo de 2 s (P9, P9.1, R2, R2.1, R2.2).
- Os endpoints são anônimos (R4), read-only (P10, I5) e não expõem dados de negócio, credenciais ou
  dados pessoais (R3).

**Manifesto Kubernetes** (`k8s/manifesto.yaml`)

- `readinessProbe` do container `app` deixa de apontar para `/` e passa a apontar para `/ready`.
- `livenessProbe` do container `app` deixa de ser `tcpSocket` e passa a ser `httpGet /health`.
- As probes passam a declarar explicitamente `timeoutSeconds`, `periodSeconds`, `failureThreshold` e
  `initialDelaySeconds`, respeitando `periodSeconds > timeoutSeconds > teto do app` (R2.3, P9.2). Hoje
  nenhum desses campos é declarado, o que faz as probes rodarem com `timeoutSeconds: 1` — menor que o
  teto de 5 s e, portanto, incompatível com o comportamento exigido.
- Nova entrada no `ConfigMap encontros-tech` para o teto de tempo da verificação.

**Configuração**

- A variável de ambiente do teto entra em `src/core/settings.py`, `.env.exemple`, `docker-compose.yml`
  e no `ConfigMap` do manifesto.

## Capabilities

### New Capabilities

- `saude-prontidao`: contrato observável dos sinais de vivacidade e prontidão — semântica de `/health`
  e `/ready`, corpo de diagnóstico, independência da liveness em relação ao banco, teto de tempo
  configurável da verificação, boot resiliente e convergência sem reinício.

### Modified Capabilities

- `implantacao-kubernetes`: o requisito **Sinais de saúde consumidos pelo orquestrador** é refinado.
  Ele exigia, de forma abstrata, "um sinal de prontidão" e "um sinal de vivacidade" — porque na época
  `/health` e `/ready` não existiam e o manifesto usava aproximações provisórias (`httpGet /` e
  `tcpSocket`). Agora passa a nomear os endpoints, proibir rota de negócio como probe e proibir socket
  TCP como sinal de vivacidade. Somam-se dois requisitos novos: a relação de temporização entre a
  janela de avaliação do orquestrador e o teto do app, e a declaração do teto na configuração do
  manifesto.

## Impact

**Código afetado**

| Arquivo | Natureza da mudança |
|---|---|
| `src/main.py` | `create_all` deixa de ser bloqueante no import; registro do novo blueprint |
| `src/core/database.py` | `create_engine` ganha parametrização de timeout (hoje usa defaults, sem timeout algum) |
| `src/core/settings.py` | nova configuração do teto de tempo |
| `src/routers/` | novo router para os sinais (não é rota de negócio) |
| `k8s/manifesto.yaml` | probes do container `app` (linhas ~234–240) e `ConfigMap` (linhas ~59–69) |
| `.env.exemple`, `docker-compose.yml` | documentação e paridade local da nova variável |

**Superfície pública.** Duas rotas novas, anônimas, sem versionamento de API. Não alteram nenhum
contrato existente da API de eventos.

**Dependências.** Nenhuma dependência nova. A verificação usa SQLAlchemy/`psycopg2-binary`, já
presentes em `src/requirements.txt`.

**ADRs e TRD.** Compatível com ADR 001 (containerização), ADR 002 (EKS) e ADR 003 (Postgres em
`StatefulSet` de uma réplica dentro do cluster) — nenhuma delas é reaberta. O ADR 003 é o que torna
esta mudança mais relevante: com o banco em uma única réplica dentro do cluster, reciclagem de nó e
rollout do `StatefulSet` produzem janelas de indisponibilidade rotineiras que hoje derrubam a aplicação.

### Impacto em disponibilidade / HA

**Ganhos.** É o objetivo da mudança: indisponibilidade do banco deixa de reiniciar a aplicação (I2) e
deixa de rotear tráfego para instâncias incapazes de servir (I1). O boot deixa de depender do banco
(I4), eliminando o CrashLoopBackOff — o modo de falha mais provável hoje, dado o ADR 003.

**Riscos introduzidos.**

1. **Starvation de workers (I7) — risco principal.** `GUNICORN_WORKERS: "2"` no `ConfigMap`, com
   workers *sync*: cada requisição ocupa um worker inteiro. Com o banco pendurado, verificações de até
   5 s podem ocupar ambos os workers e fazer `/health` deixar de ser atendido — convertendo uma falha
   de dependência em falha de liveness e, portanto, em reinício. Isso violaria I2/R1, exatamente o que
   a mudança existe para prevenir. Elevar o teto de 2 s para 5 s ampliou essa janela. **É a decisão
   central do `design.md`.**
2. **Detecção mais lenta.** Com `periodSeconds > timeoutSeconds > 5 s`, o tempo para tirar um pod da
   rotação passa a ser `failureThreshold × periodSeconds` — dezenas de segundos, contra poucos segundos
   hoje. Trade-off aceito em troca de tolerância a banco lento.
3. **Carga adicional no banco.** Cada verificação é um round-trip real (I6 proíbe cache), contra um
   Postgres de **uma única réplica**. A carga é `réplicas ÷ periodSeconds` de forma permanente.
4. **Readiness simultânea em todas as réplicas.** Se o banco cair, todas as réplicas ficam
   não-prontas ao mesmo tempo e o `Service` fica sem endpoints — comportamento correto e desejado
   (I1), mas significa indisponibilidade total do frontend durante a queda do banco, em vez das
   páginas de erro parciais de hoje. Mudança de comportamento visível ao usuário final.

### Blast radius

```
              ┌──────────────────────────────────────────────┐
              │ ALTO  — probes do manifesto                  │
              │ probe malconfigurada derruba TODAS as        │
              │ réplicas do Deployment simultaneamente       │
              ├──────────────────────────────────────────────┤
              │ MÉDIO — boot / create_all em src/main.py     │
              │ erro aqui impede a aplicação de subir        │
              ├──────────────────────────────────────────────┤
              │ MÉDIO — create_engine em database.py         │
              │ timeout mal aplicado afeta o tráfego de       │
              │ negócio, não só as probes                    │
              ├──────────────────────────────────────────────┤
              │ BAIXO — novos endpoints, settings, ConfigMap │
              │ código novo, aditivo, sem consumidores       │
              └──────────────────────────────────────────────┘
```

- **Escopo de infraestrutura:** namespace `encontros-tech` apenas. Não toca o `StatefulSet` do
  Postgres, o `Service`, o `Secret` nem o `ServiceAccount`.
- **Escopo de dados:** nenhum. A mudança é read-only quanto a dados de negócio (P10, I5). A única
  operação com efeito no schema é o `create_all`, que é reposicionado no tempo, não alterado em
  conteúdo.
- **Consumidores externos:** nenhum. As rotas são novas e o contrato da API de eventos não muda.
- **Pior caso realista:** `livenessProbe` apontando para um `/health` que, por starvation (risco 1),
  não responde sob banco fora → reinício em cascata de todas as réplicas durante um incidente de
  banco — estado **pior** que o atual. É precisamente o cenário que CA10 existe para barrar antes do
  merge.

### Plano de rollback

O rollback é limpo porque as duas metades são independentes e a de infraestrutura é reversível sem
build.

**Gatilhos.** Reinícios de pod durante indisponibilidade do banco (violação de I2/I7); `/ready`
retornando 503 com o banco comprovadamente saudável (falso-negativo); latência do tráfego de negócio
degradada após a parametrização de timeout no `create_engine`.

1. **Reverter só o manifesto (primeiro passo, ~1 min, sem rebuild).** Restaurar em
   `k8s/manifesto.yaml` a `readinessProbe: httpGet /` e a `livenessProbe: tcpSocket 8000`, remover os
   campos de temporização e aplicar. Os endpoints continuam publicados e inertes — nada os consulta.
   Isso desfaz 100% do risco de blast radius ALTO. O comportamento volta a ser exatamente o de hoje.
2. **Ajustar apenas o teto, sem reverter código.** Se o problema for a duração da verificação,
   alterar a variável no `ConfigMap` e fazer `kubectl rollout restart` — o piso é 2 s (R2.2), que era
   o valor original do PRD.
3. **Reverter a imagem.** `kubectl rollout undo deployment/encontros-tech -n encontros-tech`, voltando
   à tag anterior. Necessário apenas se o problema estiver no boot ou no `create_engine`.
4. **Reverter o repositório.** `git revert` do merge. Sem migração de dados envolvida, portanto sem
   passo de rollback de dados.

**Ponto sem retorno:** nenhum. A mudança não altera schema, não migra dados e não modifica contrato
consumido por terceiros.
