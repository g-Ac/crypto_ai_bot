# Paper Readiness Framework — Momentum Pullback v1.1

Framework de governanca para a fase de paper trading da estrategia Momentum Pullback v1.1 (B1).

---

## 1. Objetivo e Filosofia

### Objetivo

Definir criterios objetivos que a estrategia Momentum Pullback v1.1 precisa cumprir antes, durante e ao final da fase de paper trading. Separar a decisao de governanca ("merece paper?") da decisao de implementacao ("como plugar no sistema?").

A aprovacao para paper trading nao implica aprovacao para operacao real. Paper e uma etapa intermediaria de validacao operacional e comportamental.

### Filosofia

Defensiva. O backtest/research ja provou edge suficiente para justificar observacao adicional. O paper precisa provar que esse edge sobrevive fora do laboratorio. Primeiro validamos estabilidade, aderencia ao research e seguranca operacional; depois avaliamos se o edge observado e suficiente para justificar continuidade.

### Principios

1. **Nao quebrar** vem antes de dar lucro
2. **Aderencia ao research** vem antes de performance absoluta
3. **Paper mede, nao otimiza** — se a estrategia precisa mudar, volta para research
4. **Baseline congelada** — a v1.1 avaliada em paper permanece congelada, salvo correcoes operacionais permitidas por este framework

---

## 2. Pre-requisitos e Capital

### Pre-requisitos para entrar em paper

- Validacao de robustez concluida e aprovada (3/3 PASS — feito em 2026-04-15)
- Params v1.1 congelados em `momentum/config.py` (sl_floor=0.5%, param_version="momentum-pullback-v1.1")
- Integracao tecnica funcional: executor de paper operacional, logging, auditoria, circuit breaker ativo
- Smoke test limpo (ver abaixo)
- Aprovacao explicita do operador/dono do projeto para inicio do paper oficial

### Capital paper

- Inicial: **US$ 1.000**
- Se houver distorcao operacional por sizing minimo (arredondamento em BTC/ETH), pode subir para **US$ 2.000**. Registrar como desvio controlado (Classe 2)
- Simbolos: **BTCUSDT, ETHUSDT** (mesmos do research)
- Max posicoes simultaneas: **1** (alinhado com a spec v1 aprovada)

### Smoke test (pre-paper)

Duracao: 24-48h. Nao conta como paper oficial. Trades executados durante o smoke test nao contam para a amostra oficial nem para avaliacao dos checkpoints.

Checklist objetivo:

- [ ] Decision log sendo gravado corretamente
- [ ] Trades paper abrindo e fechando corretamente
- [ ] Regime bloqueado realmente nao entra
- [ ] SL/TP/timeout batem com a spec v1.1
- [ ] Circuit breaker responde
- [ ] Sem erro repetido em log
- [ ] Sem divergencia entre decisao gravada e execucao

So apos smoke test limpo e aprovacao explicita do operador, o relogio do paper comeca a contar.

---

## 3. Checkpoints de Avaliacao

Os checkpoints sao mecanismos de governanca e nao substituem kill conditions, auditoria operacional ou julgamento prudente diante de comportamento anomalo. Kill conditions tem precedencia sobre qualquer zona de checkpoint.

### Checkpoint 1 — Sanidade

**Quando**: minimo de **30 dias corridos** E minimo de **80 trades fechados** (vale o requisito mais lento).

Pergunta central: "ela esta se comportando de forma aceitavel fora do laboratorio?"

| Zona | PF | WR | ER | Condicoes adicionais |
|---|---|---|---|---|
| **PASS** | >= 0.95 | >= 48% | >= 0.90 | Sem anomalias. SL hit rate, timeout % e comportamento por regime reconheciveis vs. research |
| **WATCH** | 0.85–0.95 | 45–48% | 0.80–0.90 | Comportamento geral coerente, sem bug, sem anomalia |
| **FAIL** | < 0.85 | < 45% | < 0.80 | Ou divergencia forte do research. Ou kill condition ativa |

Acoes:
- **PASS** → continua ate CP2, monitoramento normal
- **WATCH** → continua ate CP2, mas com revisao semanal obrigatoria e atencao redobrada. WATCH no CP1 significa continuidade cautelosa para coleta adicional de evidencia, nao aprovacao implicita. Se degradar em direcao a FAIL, nao espera CP2
- **FAIL** → paper encerrado. Estrategia volta para research. Dados preservados para analise

Referencia do research (para contexto, nao como regra mecanica):
- Blocos mensais: PF 1.03–1.48, WR 52.9–57.3%
- Holdout adverso: PF 0.72, WR 48.3%
- Paper na zona WATCH esta entre o holdout e o pior bloco. Paper na zona FAIL esta pior que o holdout

### Checkpoint 2 — Credibilidade

**Quando**: minimo de **60 dias corridos** E minimo de **150 trades fechados**.

A regua sobe. Pergunta central: "alem de estavel, ela continua boa o suficiente para merecer respeito?"

| Zona | PF | WR | ER | Condicoes adicionais |
|---|---|---|---|---|
| **PASS** | >= 1.00 | >= 50% | >= 0.95 | Drawdown controlado. Sem anomalias. Regime e exits coerentes com research |
| **WATCH** | 0.90–1.00 | 47–50% | 0.85–0.95 | Sem anomalias graves. Explicacao plausivel de regime/periodo |
| **FAIL** | < 0.90 | < 47% | < 0.85 | Ou divergencia forte. Ou kill condition |

Acoes:
- **PASS** → paper bem-sucedido. Libera abertura formal da decisao sobre proxima fase (nao libera live automaticamente). Decisao sobre proxima fase requer aprovacao explicita do operador
- **WATCH** → extensao do paper por mais 30 dias + 80 trades, com regua de CP2. Maximo uma extensao. Desfechos apos extensao:
  - PASS → paper bem-sucedido
  - WATCH → inconclusivo encerrado
  - FAIL → encerrado, volta research
- **FAIL** → paper encerrado. Volta para research

Apos uma extensao, o resultado obrigatoriamente se resolve como PASS, FAIL ou INCONCLUSIVO encerrado.

### Metricas complementares (ambos os checkpoints)

Avaliadas sem piso numerico fixo, mas divergencia forte e sinal de alerta:
- SL hit rate por regime
- Timeout % por regime
- Distribuicao de exits (SL / TP1 / TP2 / timeout)
- Breakdown TRENDING vs WEAK_TREND
- Sequencias de loss (padrao vs. anomalo)

### Definicao de "divergencia forte"

Pelo menos 2 destes sinais simultaneamente:
- Timeout % mais de **15pp** acima do research (ex: research ~35%, paper >50%)
- SL hit rate mais de **15pp** acima do research (ex: research ~25%, paper >40%)
- Comportamento por regime descaracterizado (ex: WEAK_TREND perde edge que era dominante no research)
- Distribuicao de exits irreconhecivel vs. research
- WR cai mais de **10pp** abaixo do pior bloco do research

---

## 4. Kill Conditions

Kill conditions sao independentes dos checkpoints e tem precedencia sobre qualquer zona. Se uma kill condition e acionada, o paper para — mesmo que as metricas agregadas parecam aceitaveis.

Kill conditions interrompem o paper independentemente do status do checkpoint. Anomalias operacionais geram pausa imediata; encerramento definitivo depende da natureza e repetibilidade da falha.

### Kill imediato — problema operacional ou risco inaceitavel

#### A. Anomalia operacional / violacao da spec

Qualquer uma destas aciona **pausa imediata**:
- Trade em regime bloqueado (fora de TRENDING / WEAK_TREND)
- SL ou TP calculado fora da logica da spec v1.1
- Posicao duplicada sem permissao
- Sizing fora da regra
- Entrada sem confirmacao de pullback valida
- Log inconsistente ou impossivel de auditar
- Decisao gravada sem correspondencia com a execucao

Acao: pausa imediata do paper. Investigar causa.
- Se bug operacional (Classe 1): corrigir, novo smoke test, e retomar
- Se falha logica da estrategia: encerrar paper
- Se anomalia se repetir apos correcao: encerrar paper

#### B. Drawdown acumulado

Calculado sobre **high-water mark** do capital paper (nao sobre capital inicial).

| Nivel | Drawdown (HWM) | Acao |
|---|---|---|
| Warning | >= 8% | Alerta. Revisao do estado |
| Review | >= 10% | Revisao obrigatoria. Avaliar se causa e regime adverso ou problema sistemico |
| Kill | >= 12% | Paper encerrado |
| Teto absoluto | 15% | Kill incondicional, mesmo que o review de 12% tenha decidido continuar por motivo justificado |

### Kill por evidencia — estrategia nao confirma o research

#### C. PF muito ruim com amostra minima

| PF | Amostra | Acao |
|---|---|---|
| < 0.70 | >= 40 trades | Kill forte. Estrategia nao presta neste mercado |
| 0.70–0.90 | >= 40 trades | Observacao apertada. Se nao recuperar ate CP1, e FAIL |

Este kill pode acionar **antes do CP1** — basta atingir 40 trades.

#### D. Divergencia extrema do research

Ver definicao de "divergencia forte" na Secao 3.

Acao: revisao obrigatoria. Se nao houver causa externa clara (ex: evento macro extremo, halt de exchange), encerrar paper.

#### E. Sequencia de losses — circuit breaker, nao kill automatico

| Losses consecutivos | Acao |
|---|---|
| 5 | Pausa automatica. Revisao do estado |
| 8 | Auditoria forte. Verificar se ha anomalia ou se e variancia normal |
| 10 | Kill candidate — encerrar se combinado com pelo menos 1 outro sinal (DD elevado, PF em queda, divergencia) |

Sequencia de losses sozinha nao mata. Mas 10 losses + outro sinal ruim = kill.

---

## 5. Classes de Mudanca Durante o Paper

Paper mede, nao otimiza. A baseline v1.1 permanece congelada. Se a estrategia precisa mudar para funcionar, ela nao esta pronta — volta para research.

### Classe 1 — Permitida (correcao operacional)

Mudancas que nao alteram o comportamento da estrategia. Podem ser feitas sem aprovacao previa, mas devem ser registradas no log de operacao do paper.

Exemplos:
- Bugfix de execucao, logging, persistencia, integracao
- Correcao de timezone/timestamp
- Fix de calculo que claramente contraria a spec aprovada (ex: SL calculado ao contrario)
- Melhoria de observabilidade (novos logs, metricas, dashboard)
- Fix de scheduler ou ciclo de execucao

Registro obrigatorio:
- O que mudou
- Impacto esperado (nenhum na estrategia / apenas operacional / corrige divergencia spec-implementacao)
- Data

Criterio: a mudanca corrige um desvio entre a implementacao e a spec, nao altera a spec.

### Classe 2 — Permitida com registro de desvio controlado

Mudancas operacionais minimas que nao alteram a logica da estrategia, mas ajustam o paper para representar melhor a execucao real. Requerem aprovacao explicita e ficam documentadas como desvio.

Exemplos:
- Ajuste de sizing minimo por distorcao de capital (1K → 2K)
- Arredondamento de tamanho de ordem
- Tolerancia tecnica de execucao no paper executor

Registro obrigatorio:
- O que mudou
- Por que mudou
- Que nao altera a logica da estrategia
- Data e aprovacao

Desvios controlados nao reiniciam automaticamente o paper, mas devem ficar claramente marcados no periodo em que ocorreram para interpretacao correta dos checkpoints.

### Classe 3 — Proibida durante o paper

Qualquer mudanca que altere o comportamento da estrategia. Se necessaria, o paper e encerrado e a estrategia volta para research como nova versao.

Lista explicita (nao exaustiva):
- EMAs (fast/slow)
- Regime gate
- Pullback range (min/max %)
- Confirmacao (logica de reentrada)
- sl_floor_pct
- Timeout (candles)
- TP1 / TP2 (fator, multiplicador)
- Filtros de entrada ou saida
- Sessoes permitidas
- Restricao direcional (long-only / short-only)
- Qualquer parametro de `MomentumConfig`

**Regra de ouro**: se a mudanca faria o backtest gerar resultados diferentes, e Classe 3.

**Na duvida entre Classe 2 e Classe 3, a mudanca deve ser tratada como Classe 3 ate justificativa em contrario.**

---

## 6. Resultado do Paper e Proxima Fase

### 1. Paper bem-sucedido (CP2 = PASS)

A estrategia provou estabilidade operacional e manteve edge suficiente por 60+ dias e 150+ trades.

Paper bem-sucedido libera apenas a abertura formal da decisao sobre a proxima fase. Nao libera operacao real automaticamente.

Liberado:
- Discussao formal sobre proxima fase (escala de capital, live com sizing minimo, ou extensao de observacao)
- Analise aprofundada dos dados de paper para informar decisao

Nao liberado:
- Operacao real automatica
- Qualquer acao sem aprovacao explicita do operador

### 2. Paper inconclusivo (CP2 = WATCH apos extensao)

A estrategia nao falhou, mas tambem nao convenceu. Dados insuficientes ou metricas em zona cinzenta apos 90 dias e 230+ trades.

Apos uma extensao, o resultado obrigatoriamente se resolve como PASS, FAIL ou INCONCLUSIVO encerrado. Nao e permitido estender indefinidamente.

Opcoes:
- Encerrar paper e preservar dados para analise futura
- Abrir nova rodada de research para investigar por que nao convergiu

### 3. Paper reprovado (FAIL em CP1 ou CP2)

A estrategia nao confirmou o edge do research fora do laboratorio.

Acao:
- Paper encerrado
- Dados preservados integralmente
- Estrategia volta para research. Pode gerar v1.2 ou ser descontinuada
- Analise post-mortem obrigatoria: o que divergiu, por que, o que isso ensina

### 4. Paper encerrado por kill condition

Algo quebrou ou o risco ficou inaceitavel antes de qualquer checkpoint.

Acao:
- Mesma do FAIL, com enfase na investigacao da causa raiz
- Se kill foi por anomalia operacional corrigivel (Classe 1), o paper pode ser reiniciado do zero apos correcao e novo smoke test. Um reinicio apos kill operacional e tratado como nova execucao de paper, com novo periodo, novos contadores e nova trilha de evidencia

### Regra transversal

Em qualquer desfecho, os dados de paper sao preservados integralmente. Nunca apagar trades, decisoes ou logs do periodo de paper — sao evidencia para decisoes futuras.

O encerramento do paper, por qualquer motivo, nunca invalida os dados coletados; ele apenas encerra aquela execucao como evidencia governavel.

---

## 7. Apendice Tecnico

> **Este apendice e apenas referencia tecnica para futura integracao. Ele nao autoriza implementacao automatica do bloco de integracao. Implementacao requer aprovacao explicita em sessao separada.**

O apendice descreve apenas a trilha minima de integracao para paper, preservando a baseline Momentum Pullback v1.1 sem alteracoes de logica.

### O que ja existe no codebase

| Componente | Status | Onde |
|---|---|---|
| Signal evaluator | Pronto, congelado v1.1 | `momentum/momentum_trader.py` → `evaluate_momentum_pullback()` |
| Config congelada | Pronta | `momentum/config.py` → `MomentumConfig` |
| Research runner | Pronto (backtest/research) | `momentum/research_runner.py` → `run_research_cycle()` |
| Research DB | Pronta (schema separado) | `momentum/research_db.py` |
| Swing/Pullback detection | Pronto | `momentum/swing_detector.py`, `momentum/pullback_detector.py` |
| State management pattern | Reutilizavel | `risk_manager.py` (JSON atomico, thread-safe) |
| Circuit breaker | Reutilizavel, generico por sistema | `daily_report.py` → `enforce_circuit_breaker()` |
| Proactive alerts | Reutilizavel, extensivel | `proactive_alerts.py` |
| Runtime isolation (BOT_ID) | Pronto | `runtime_config.py` |
| Candle fetch multi-TF | Pronto | `market.py`, `scalping_data.py` |
| Regime detection | Pronto | `htf.py` |
| Telegram notifications | Pronto | `telegram_notifier.py` |
| Audit helpers | Pronto | `audit_helpers.py`, `audit_data.py` |
| ATR calculation | Pronto | `risk_manager.py` |

### O que falta construir

**Obrigatorio para paper:**

1. **Paper executor** — modulo que transforma sinais do `evaluate_momentum_pullback()` em posicoes paper com gestao de SL/TP/timeout. Padrao: `paper_trader.py` e `scalping_trader.py` como referencia
2. **State file** — `momentum_state.json` em `runtime/<BOT_ID>/`. Capital, posicoes, cooldowns, contadores
3. **Database tables** — `momentum_trades` e `momentum_decisions` em `bot.db`. Esquema alinhado com o audit framework existente (scalping como modelo)
4. **Integracao no main.py** — bloco momentum no loop principal, com circuit breaker, pausa, e Telegram. Mesmo padrao do scalping (linhas 273-311)
5. **Config e env vars** — `MOMENTUM_TRADER_ENABLED`, `MOMENTUM_INITIAL_CAPITAL`, `MOMENTUM_SYMBOLS` em `config.py` e `runtime_config.py`

**Pode vir depois (nao bloqueia paper):**

6. **Dashboard** — extensao de `/api/trades`, `/api/status` e funil de decisoes para momentum

### Riscos tecnicos

- **Ciclo de 15m vs 5m**: main.py roda em ciclo de 5 minutos, momentum usa candles de 15m. Precisa decidir: rodar a cada ciclo (checando se candle 15m fechou) ou rodar em ciclo proprio
- **Posicao timeout**: timeout de 16 candles (4h) precisa de tracking persistente entre ciclos — o state file resolve, mas precisa de logica de contagem
- **Capital de US$ 1.000**: verificar se sizing minimo em BTC/ETH gera ordem viavel ou se precisa ajuste (Classe 2)

### Ordem sugerida de implementacao (quando for a hora)

1. Config + env vars + state file
2. Database tables + insert functions
3. Paper executor (core: entrada, SL/TP, timeout, saida)
4. Integracao no main.py + circuit breaker
5. Smoke test
6. Dashboard (pode ser paralelo ou posterior)

---

## 8. Quick-Reference Operacional

> Referencia rapida derivada do documento mestre. Nao e fonte de verdade — em caso de duvida, consultar as secoes anteriores.

### Pode entrar em paper?

- [ ] Robustez v1.0 vs v1.1 aprovada (3/3 PASS)
- [ ] Baseline v1.1 congelada em `momentum/config.py`
- [ ] Executor de paper funcional
- [ ] Logging, auditoria e circuit breaker ativos
- [ ] Smoke test 24-48h limpo (decisions logadas, SL/TP corretos, regime gate respeitado, timeout funcional, circuit breaker responde, sem erros repetidos, sem divergencia decisao-execucao)
- [ ] Aprovacao explicita do operador para inicio oficial
- [ ] Capital: US$ 1.000 (ate US$ 2.000 se distorcao de sizing, como desvio Classe 2)
- [ ] Simbolos: BTCUSDT, ETHUSDT | Max posicoes: 1

### Checkpoints

| | CP1 — Sanidade | CP2 — Credibilidade |
|---|---|---|
| **Quando** | 30 dias + 80 trades | 60 dias + 150 trades |
| **PASS** | PF>=0.95, WR>=48%, ER>=0.90 | PF>=1.00, WR>=50%, ER>=0.95 |
| **WATCH** | PF 0.85-0.95, WR 45-48%, ER 0.80-0.90 | PF 0.90-1.00, WR 47-50%, ER 0.85-0.95 |
| **FAIL** | PF<0.85, WR<45%, ER<0.80 | PF<0.90, WR<47%, ER<0.85 |
| **Acao PASS** | Continua ate CP2 | Paper bem-sucedido. Libera apenas discussao formal da proxima fase (nao libera live automaticamente) |
| **Acao WATCH** | Continua com revisao semanal | Extensao +30d/+80t (max 1). Depois: PASS, FAIL ou encerrado |
| **Acao FAIL** | Paper encerrado. Volta research | Paper encerrado. Volta research |

### Kill conditions

| Trigger | Tipo | Acao |
|---|---|---|
| Anomalia operacional / violacao spec | Imediato | Pausa. Se bug Classe 1: corrigir e retomar. Se falha logica: encerrar |
| Drawdown >= 8% (HWM) | Warning | Alerta + revisao |
| Drawdown >= 10% (HWM) | Review | Revisao obrigatoria |
| Drawdown >= 12% (HWM) | Kill | Paper encerrado |
| Drawdown >= 15% (HWM) | Kill absoluto | Incondicional |
| PF < 0.70 apos 40+ trades | Evidencia | Kill forte |
| Divergencia forte (2+ sinais) | Evidencia | Revisao obrigatoria. Sem causa externa → encerrar |
| 5 losses consecutivos | Circuit breaker | Pausa + revisao |
| 8 losses consecutivos | Circuit breaker | Auditoria forte |
| 10 losses + outro sinal | Kill candidate | Encerrar |

### Mudancas durante paper

| Classe | Pode? | Exemplo | Registro |
|---|---|---|---|
| 1 — Operacional | Sim | Bugfix, logging, persistencia | Log com impacto esperado |
| 2 — Desvio controlado | Com aprovacao | Sizing minimo, arredondamento | Aprovacao + docs. Nao reinicia CP, mas fica marcado |
| 3 — Estrategia | Nao | EMAs, SL, TP, regime, filtros | Encerra paper. Nova versao via research |

Na duvida entre Classe 2 e 3: tratar como Classe 3.

### Fluxograma de decisao

```
Deploy paper → Smoke test 24-48h
  |
  +-- Anomalia no smoke test? → Fix e repetir
  '-- Limpo → Aprovacao do operador → Paper oficial comeca
       |
       +-- Kill condition acionada? → Pausa ou encerramento (ver tabela)
       |
       +-- Atingiu 30d + 80 trades? → Avaliar CP1
       |     +-- PASS → continua
       |     +-- WATCH → continua com revisao semanal
       |     '-- FAIL → encerra, volta research
       |
       '-- Atingiu 60d + 150 trades? → Avaliar CP2
             +-- PASS → paper bem-sucedido (abre discussao proxima fase)
             +-- WATCH → extensao +30d/+80t (max 1)
             |     +-- PASS → bem-sucedido
             |     +-- WATCH → inconclusivo encerrado
             |     '-- FAIL → encerrado
             '-- FAIL → encerra, volta research
```
