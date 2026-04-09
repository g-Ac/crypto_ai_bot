# Auditoria de Fees — 08/04/2026

## Paper Trader
- Fee: 0.08% round-trip
- Definida em: `paper_trader.py:199` — `ROUND_TRIP_FEE_PCT = 0.08`
- Aplicada em: `paper_trader.py:207` — `pnl_pct -= ROUND_TRIP_FEE_PCT`
- Momento: PnL final (apos calcular pnl bruto, antes de registrar)
- Consistente com backtest: Sim (backtest.py:18 usa mesmo 0.08%)

## Agent Trader (trade_agents.py)
- Fee: 0.08% round-trip
- Definida em: `trade_agents.py:42` — `ROUND_TRIP_FEE_PCT = 0.08`
- Aplicada em: `trade_agents.py:699` — `pnl_pct -= ROUND_TRIP_FEE_PCT`
- Momento: PnL final (desconto unico no fechamento)
- Consistente com backtest: Sim (backtest.py usa mesmo valor e momento)

## Scalping Trader (scalping_trader.py)
- Fee: 0.04% por leg (= 0.08% round-trip total)
- **NAO usa constante centralizada** — valores hardcoded
- Aplicada em dois momentos:
  1. TP1 parcial (50%): `scalping_trader.py:390,449` — `pos["tp1_pnl_pct"] -= 0.04` (meia fee, 1 leg)
  2. Fechamento final: `scalping_trader.py:491-492`:
     - Se TP1 ja hit: `fee_pct = 0.04` (s o 1 leg restante, pois TP1 ja pagou a outra)
     - Se TP1 nao hit: `fee_pct = 0.08` (round-trip completo)
- Momento: PnL por evento (parcial no TP1, restante no close)
- Consistente com backtest_scalping.py: **PARCIALMENTE**
  - Backtest usa `ROUND_TRIP_FEE_PCT = 0.08%` descontado de uma vez no `calculate_pnl()`
  - Live desconta em duas partes (0.04% no TP1 + 0.04% no close)
  - Total e igual (0.08%), mas o momento e diferente

## Pump Trader (pump_trader.py)
- Fee: 0.08% round-trip
- Definida em: `pump_trader.py:24` — `ROUND_TRIP_FEE_PCT = 0.08`
- Aplicada em: `pump_trader.py:269` — `pnl_pct -= ROUND_TRIP_FEE_PCT`
- Momento: PnL final (desconto unico no fechamento)
- Consistente com backtest: Sim (backtest_pump.py:35 e :247,:309)

## Backtests
- `backtest.py:18` — 0.08% round-trip, descontado em cada trade no PnL final
- `backtest_scalping.py:42-43` — 0.04% por lado = 0.08% total, descontado via `calculate_pnl()` no PnL liquido
- `backtest_pump.py:35` — 0.08% round-trip, descontado no PnL de cada exit

## Inconsistencias Encontradas

1. **Scalping fees hardcoded**: O scalping_trader.py usa `0.04` hardcoded em 4 lugares (linhas 390, 449, 491) em vez de referenciar uma constante. Se a fee mudar, precisaria atualizar em multiplos lugares.

2. **Scalping backtest vs live — momento do desconto**: 
   - Live: desconta 0.04% no TP1, depois 0.04% no close (total 0.08%)
   - Backtest: desconta 0.08% de uma vez no calculate_pnl() para cada evento de saida
   - Impacto: no backtest com saida parcial, a fee de 0.08% e aplicada TANTO no TP1 quanto no TP2, o que **over-charges** fees no backtest. No live, cada leg paga 0.04%.
   - **ESTE E UM BUG**: O backtest_scalping cobra 0.08% no TP1 (50% da posicao) + 0.08% no TP2 (50%), totalizando 0.08% efetivo. MAS a funcao calculate_pnl aplica fee_pct ao raw_pnl inteiro multiplicado por leverage, e apos multiplicar pela fracao. A formula no backtest e: `net_pnl_pct = (raw_pnl_pct * leverage) - fee_pct - slippage_pct`. Isso subtrai 0.08% fixo do PnL ja alavancado, o que e correto se fee e sobre o notional. Live tambem desconta de pnl_pct diretamente. Comparaveis, porem a semantica difere ligeiramente.

3. **Nenhum sistema usa fee na ENTRADA** — todos descontam na saida/P&L. Isso e correto para paper trading (sem fee real na entrada).

## Recomendacao

1. Extrair `ROUND_TRIP_FEE_PCT = 0.08` para `config.py` como constante central
2. No scalping_trader.py, usar `ROUND_TRIP_FEE_PCT / 2` em vez de 0.04 hardcoded
3. Revisar se o backtest_scalping aplica fee corretamente em saidas parciais
