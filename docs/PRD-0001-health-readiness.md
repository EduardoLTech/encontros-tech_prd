# PRD — Health & Readiness Probes · Encontros Tech

**Feature:** Sinais de saúde (`/health`) e prontidão (`/ready`)
**Data:** 2026-07-12 · **Status:** Revisado — premissas confirmadas
**Escopo do documento:** comportamento e regra de negócio. Escolhas de implementação (biblioteca, comando de verificação do banco, configuração de probes, mecanismo de retry) são deliberadamente omitidas — pertencem ao ADR/TRD.

---

## 1. Contexto

**Produto.** Encontros Tech é uma aplicação de cadastro e listagem de eventos de tecnologia, destinada a rodar sob orquestração Kubernetes. A aplicação depende criticamente de um banco de dados relacional para servir qualquer funcionalidade de negócio (listar, criar, editar eventos).

**Estado atual.**
- Não existe nenhum sinal de saúde ou prontidão exposto pela aplicação.
- Quando o banco está indisponível em tempo de execução, as requisições de negócio retornam erro genérico (HTTP 500), mas o orquestrador **não tem como saber** que a instância não deveria receber tráfego — ele continua encaminhando requisições para uma instância incapaz de atendê-las.
- Quando o banco está indisponível no momento em que a aplicação sobe, o processo **falha no boot** e entra em ciclo de reinício.

**Problema de negócio.** Sem sinais distintos de "vivo" e "pronto", o orquestrador toma decisões erradas em dois momentos:
1. **Falha transitória do banco em runtime** → tráfego continua chegando a instâncias que não conseguem responder, degradando a experiência do usuário e poluindo métricas de erro.
2. **Banco indisponível no boot** → instâncias entram em ciclo de reinício com backoff progressivo, de modo que, quando o banco volta, a recuperação é lenta em vez de imediata.

O objetivo é permitir que o orquestrador (a) reinicie apenas instâncias genuinamente travadas e (b) remova da rotação de tráfego — sem reiniciar — instâncias temporariamente incapazes de servir, devolvendo-as ao tráfego automaticamente quando voltarem a poder atender.

---

## 2. Atores

| Ator | Papel nesta feature |
|---|---|
| **Kubernetes (kubelet)** | Consome os sinais periodicamente. Reinicia a instância se a liveness falhar; remove/readmite a instância na rotação de tráfego conforme a readiness. |
| **Processo da aplicação** | Expõe os sinais. Reporta seu próprio estado de vivacidade e sua capacidade atual de servir. |
| **Banco de dados** | Dependência crítica cuja disponibilidade determina a prontidão da aplicação. Não determina a vivacidade. |
| **Operador / SRE** | Consome o corpo detalhado das respostas para diagnóstico durante incidentes. |
| **Usuário final** | Beneficiário indireto: não deve ser roteado para instâncias incapazes de atender. |

---

## 3. Predicados verificáveis (Dado / Quando / Então)

**P1 — Liveness com processo saudável**
Dado que o processo da aplicação está em execução e responsivo,
Quando o ator Kubernetes consulta `/health`,
Então a resposta é HTTP 200 indicando estado "vivo".

**P2 — Liveness é independente do banco**
Dado que o banco de dados está indisponível,
Quando o ator Kubernetes consulta `/health`,
Então a resposta continua sendo HTTP 200 (o estado do banco não influencia a vivacidade).

**P3 — Readiness com banco disponível**
Dado que o banco de dados está alcançável e respondendo,
Quando o ator Kubernetes consulta `/ready`,
Então a resposta é HTTP 200 com corpo indicando prontidão e o resultado da verificação do banco como saudável.
Corpo: `{"status": "ready", "checks": {"database": "ok"}}`.

**P4 — Readiness com banco indisponível**
Dado que o banco de dados está inalcançável ou não responde,
Quando o ator Kubernetes consulta `/ready`,
Então a resposta é HTTP 503 com corpo indicando não-prontidão e o resultado da verificação do banco como não-saudável.
Corpo: `{"status": "not_ready", "checks": {"database": "down"}}`.

**P5 — Remoção da rotação de tráfego**
Dado que `/ready` está retornando 503 para uma instância,
Quando o Kubernetes avalia a prontidão dessa instância,
Então essa instância deixa de receber tráfego novo, sem que o processo seja reiniciado.

**P6 — Retorno automático à rotação**
Dado que uma instância estava fora da rotação por readiness em 503, e o banco volta a ficar disponível,
Quando `/ready` volta a retornar 200,
Então a instância é readmitida na rotação de tráfego automaticamente, sem intervenção manual e sem reinício.

**P7 — Boot com banco indisponível (graceful)**
Dado que o banco de dados está indisponível no momento em que a aplicação inicia,
Quando o processo sobe,
Então o processo conclui a inicialização e passa a responder `/health` com 200 e `/ready` com 503 — em vez de falhar o boot.

**P8 — Recuperação após boot degradado**
Dado que a aplicação subiu com o banco indisponível (P7),
Quando o banco fica disponível,
Então `/ready` passa a retornar 200 sem necessidade de reiniciar a aplicação.

**P9 — Verificação de prontidão é limitada no tempo**
Dado que o banco está inalcançável de forma a não responder,
Quando `/ready` é consultado,
Então a resposta é emitida em até 2 segundos, retornando 503, em vez de ficar pendurada aguardando o banco.

**P10 — Sinais não alteram estado**
Dado qualquer estado do sistema,
Quando `/health` ou `/ready` são consultados qualquer número de vezes,
Então nenhum dado de negócio é criado, alterado ou removido (as consultas são read-only e idempotentes).

**P11 — Detalhe de diagnóstico**
Dado que `/ready` retorna 503,
Quando um operador inspeciona o corpo da resposta,
Então o corpo identifica qual dependência verificada está não-saudável (atualmente, o banco), sem expor dados de negócio, credenciais ou informações pessoais.

---

## 4. Invariantes

- **I1.** Uma instância não-pronta (readiness em 503) nunca recebe tráfego novo.
- **I2.** A indisponibilidade de uma dependência externa (banco) nunca, por si só, provoca o reinício do processo.
- **I3.** Enquanto o processo estiver vivo e responsivo, `/health` sempre responde com sucesso, independentemente do estado do banco.
- **I4.** A indisponibilidade do banco nunca impede o processo de concluir seu boot.
- **I5.** A consulta aos sinais nunca modifica o estado de negócio.
- **I6.** O sinal de prontidão sempre reflete a capacidade **atual** de servir, avaliada no momento da consulta: se o banco está indisponível, `/ready` não pode reportar prontidão. Não se admite reportar prontidão com base em resultado defasado/reaproveitado.

---

## 5. Restrições (de negócio / comportamento)

- **R1.** A vivacidade não pode depender de nenhuma dependência externa — apenas do próprio processo. (Fazer o contrário transformaria uma falha transitória de dependência em reinícios em massa.)
- **R2.** A verificação de prontidão deve concluir dentro de um limite curto de tempo (teto de 2s), para não estourar a janela de avaliação do orquestrador.
- **R3.** As respostas de diagnóstico não podem expor dados de negócio, credenciais, segredos ou informações pessoais — apenas o estado das dependências verificadas.
- **R4.** Os sinais devem ser observáveis sem autenticação, para que o orquestrador os consulte livremente.
- **R5.** A prontidão considera atendida somente a dependência **banco de dados**. Nenhuma outra dependência é avaliada nesta feature (ver Fora do Escopo).

---

## 6. Fora do escopo (com justificativa)

- **F1. Configuração das probes no Kubernetes** (cadência, `initialDelay`, `failureThreshold`, `timeout`). *Porquê:* é parametrização de deployment/infra — decisão de ADR/TRD, não de produto.
- **F2. Mecanismo técnico de verificação do banco e de inicialização resiliente** (como o banco é sondado, como o schema é criado sem bloquear o boot, retries). *Porquê:* é "como", não "o quê" — pertence ao ADR/TRD. O PRD só exige o comportamento observável (P7, P9).
- **F3. Cache/reaproveitamento do resultado da verificação de prontidão entre consultas.** *Porquê:* é otimização de implementação; o PRD apenas limita a defasagem aceitável (I6).
- **F4. Verificação de outras dependências** (cache, filas, serviços externos). *Porquê:* a aplicação hoje só depende criticamente do banco; adicionar checks especulativos aumentaria a superfície de falso-negativo sem valor de negócio atual.
- **F5. Métricas, tracing e alertas sobre os endpoints de saúde.** *Porquê:* observabilidade já é tratada por outra trilha (Prometheus/logging) e não é objeto desta feature.
- **F6. Autenticação/autorização dos endpoints de saúde.** *Porquê:* fora do escopo desta feature; se necessário, será tratado separadamente (relaciona-se a R4).
- **F7. Distinção de saúde por worker em execução multiprocesso.** *Porquê:* granularidade de processo interno é detalhe de implementação de runtime; o contrato de negócio é por instância.

---

## 7. Critérios de aceite (observáveis)

A feature é considerada "pronta" quando **todos** os itens abaixo são demonstráveis:

- **CA1.** Com o banco disponível: `/health` → 200 e `/ready` → 200 com corpo detalhando o banco como saudável. *(P1, P3)*
- **CA2.** Derrubando o banco com a aplicação já no ar: `/health` permanece 200 e `/ready` passa a 503 com corpo detalhando o banco como não-saudável, em até 2s por resposta. *(P2, P4, P9)*
- **CA3.** Com `/ready` em 503, verifica-se que a instância deixou de receber tráfego novo e que o processo **não** foi reiniciado. *(P5, I1, I2)*
- **CA4.** Religando o banco: `/ready` volta a 200 e a instância é readmitida ao tráfego automaticamente, sem reinício nem intervenção manual. *(P6, P8)*
- **CA5.** Subindo a aplicação com o banco previamente indisponível: o processo completa o boot, `/health` responde 200 e `/ready` responde 503; ao disponibilizar o banco, `/ready` passa a 200 sem reinício. *(P7, P8, I4)*
- **CA6.** Consultando os endpoints repetidamente, nenhum evento é criado/alterado/removido no banco. *(P10, I5)*
- **CA7.** O corpo de `/ready` em falha identifica a dependência afetada sem vazar dados de negócio, credenciais ou informações pessoais. *(P11, R3)*

---

## Decisões confirmadas (2026-07-12)

- **Corpo JSON:** `{"status": "ready"|"not_ready", "checks": {"database": "ok"|"down"}}` (P3/P4).
- **Teto de tempo da verificação de prontidão:** 2s (P9/R2).
- **Prontidão sempre fresca:** avaliada no momento da consulta, sem reaproveitar resultado defasado (I6).
- **Endpoints sem autenticação** (R4).
