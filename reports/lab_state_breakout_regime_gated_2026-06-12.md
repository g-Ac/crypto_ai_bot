# Estado do laboratório — breakout regime-gated

Data/hora: 2026-06-12T01:44:24-03:00
Projeto: crypto_ai_bot
Status operacional: não alterar bot

## Resumo brutal

Progredimos em qualidade de hipótese, não em prova de edge.

Até agora, a linha `breakout_compression regime-gated` é o melhor começo novo porque:

- tem tese causal clara: compressão + rompimento + regime já direcional;
- usa componentes existentes do motor: BreakoutEngine5m, candles 5m, BB bandwidth, volume/body, regime em momentum_decisions;
- discovery ficou no limiar mínimo interessante: PF 1.20, net positivo, WR 45%;
- tem critério congelado de morte/GO;
- agora tem coleta forward automática a cada 12h.

Mas ainda não existe prova operacional:

- OOS filled atual: 0/30;
- verdict atual: DADO INSUFICIENTE;
- não autoriza ativar breakout;
- não autoriza mexer em thresholds.

## O que foi feito

### 1. EXP exit-on-trend_exhaustion

Arquivos:

- `reports/exp_exit_on_trend_exhaustion_criteria_2026-06-11.md`
- `reports/run_exp_exit_on_trend_exhaustion_oos.py`
- `reports/exp_exit_on_trend_exhaustion_oos_2026-06-11.md`
- `reports/exp_exit_on_trend_exhaustion_oos_2026-06-11.csv`

Resultado:

- OOS trades: 2;
- H1: DADO INSUFICIENTE;
- H2: DADO INSUFICIENTE.

Conclusão:

- Linha ainda viva só como coleta OOS;
- não alterar bot.

### 2. Shadow discovery: breakout compression cru

Arquivos:

- `reports/run_breakout_compression_shadow_2026_06_12.py`
- `reports/breakout_compression_shadow_2026-06-12.md`
- `reports/breakout_compression_shadow_2026-06-12.csv`

Resultado geral:

- filled: 31;
- rejected: 727;
- net_sum: -3.1279%;
- PF: 0.79;
- false_breakout: 67.7%.

Conclusão:

- Breakout cru é NO-GO operacional.
- Mas apareceu pista de regime:
  - TRENDING: +0.6822%, PF 1.18;
  - WEAK_TREND: +0.9508%, PF 1.22;
  - RANGING: -3.8715%, PF 0.00;
  - VOLATILE: -0.8894%, PF 0.66.

### 3. Autópsia: regime/follow-through/invalidação rápida

Arquivos:

- `reports/run_breakout_regime_followthrough_autopsy_2026_06_12.py`
- `reports/breakout_regime_followthrough_autopsy_2026-06-12.md`
- `reports/breakout_regime_followthrough_autopsy_2026-06-12.csv`

Resultado:

GOOD_REGIME = TRENDING + WEAK_TREND:

- n: 20;
- net: +1.6330%;
- PF: 1.20;
- WR: 45.0%;
- false_breakout: 55.0%.

BAD_REGIME = RANGING + VOLATILE:

- n: 11;
- net: -4.7609%;
- PF: 0.27;
- WR: 9.1%;
- false_breakout: 90.9%.

Conclusão:

- A pista que sobreviveu foi regime gate.
- Invalidação rápida piorou o universo GOOD_REGIME.
- O problema é evitar regime ruim, não sair mais rápido.

### 4. EXP congelado: breakout regime-gated shadow

Critério congelado:

- `reports/exp_breakout_regime_gated_criteria_2026-06-12.md`

Hash:

- `e5d942591a7f86cdb3d58e66a0e669a87f66fafe8450a47576318b7a34edbcbc`

Runner:

- `reports/run_exp_breakout_regime_gated_shadow_2026_06_12.py`

Outputs:

- `reports/exp_breakout_regime_gated_shadow_2026-06-12.md`
- `reports/exp_breakout_regime_gated_shadow_2026-06-12.csv`

Hipótese H1:

- usar o mesmo BreakoutEngine5m;
- aceitar só sinais em TRENDING ou WEAK_TREND;
- bloquear RANGING, VOLATILE, UNKNOWN;
- não mudar thresholds;
- não usar invalidação rápida;
- não alterar bot.

Discovery:

- raw signals: 765;
- eligible signals: 392;
- blocked_by_regime: 373;
- filled trades: 20;
- rejected_by_risk: 372;
- net: +1.6330%;
- PF: 1.20;
- WR: 45.0%;
- false_breakout: 55.0%;
- max_damage: -0.9507%.

OOS:

- raw signals: 3;
- eligible signal: 1;
- filled trades: 0;
- blocked_by_regime: 2;
- verdict: DADO INSUFICIENTE.

### 5. Coleta forward automática

Cron Hermes criado:

- job_id: `3b63e5000255`;
- name: `EXP breakout regime-gated watch`;
- schedule: every 12h;
- deliver: all;
- enabled: true.

O job:

1. roda `reports/run_exp_breakout_regime_gated_shadow_2026_06_12.py`;
2. lê `reports/exp_breakout_regime_gated_shadow_2026-06-12.md`;
3. entrega alerta curto com OOS filled/30, verdict, net/PF/false_breakout e status.

Mensagem obrigatória enquanto OOS < 30:

> DADO INSUFICIENTE — não alterar bot

## Decisão atual

Veredito técnico:

- Progresso real: SIM, na disciplina e na qualidade da hipótese.
- Prova de edge: NÃO, ainda não.
- Estamos patinando? Não exatamente. Antes estávamos em exploração ampla; agora temos uma hipótese forward falsificável.
- Risco principal: se empolgar com discovery e tunar antes de OOS.

## Linha vermelha

Até OOS >= 30 filled:

Permitido:

- rodar runner;
- ler relatório;
- receber alerta Telegram;
- verificar saúde do bot/regime;
- registrar progresso.

Proibido:

- ativar breakout;
- mudar BreakoutEngine5m;
- mudar volume/body/range/BB/lookback;
- fazer BTC-only/SHORT-only/ETH-off;
- adicionar invalidação rápida;
- mexer em Momentum Pullback por causa deste EXP.

## Critério de próximo avanço

Só avançar se OOS tiver:

- pelo menos 30 trades shadow preenchidos;
- PnL net > 0;
- PF net >= 1.20;
- WR >= 40%;
- false_breakout <= 60%;
- sem dano individual <= -1.25%;
- sem concentração excessiva em 1 trade, 1 dia ou 1 symbol_direction.

Se passar: mini-spec separada.
Se falhar: NO-GO e matar/pausar a linha.
Se não acumular: setup raro/rígido demais; investigar disponibilidade de sinal, não rentabilidade.
