# Mini-spec — Coletor Maker-Shadow Fase F (PREREG_maker_fill_v11)

**Data:** 2026-06-10 · **Status:** aprovado em conceito pelo Gabriel (3 invariantes); implementação TDD.
**Escopo:** medição forward shadow. NÃO altera estratégia, sizing, executor real nem params v1.1. Sombra nunca pode derrubar o executor (todo hook em try/except). Julgamento: critérios §6 do pré-registro, N≥80 ou 2026-07-31.

## Invariantes (do Gabriel, inegociáveis)

1. **Timestamp real do sinal.** A sombra nasce no instante em que `open_position` abre o trade taker real (`signal_ts = now`), com `entry_price_real`, `limit_price`, `candle_open_ts` (open do candle 15m em formação N) e `order_expiry_ts` (fim de N+1 = open(N)+30min).
2. **Nenhum dado anterior ao nascimento conta para fill.** O candle N (onde a ordem nasceu) NUNCA usa wick para fill — só ticks observados nos ciclos (close parcial a cada ~5min, sempre pós-nascimento). Candles que ABRIRAM após `signal_ts` (N+1) podem usar wick completo ao fechar. Forward é deliberadamente mais conservador que o replay (que usou low/high completos de N) — replay otimista + forward conservador encurralam a verdade.
3. **Marketability como diagnóstico.** No nascimento, snapshot REST `bookTicker`: `best_bid_at_signal`, `best_ask_at_signal`, `spread_bps`, `would_post` (LONG: limit < ask; SHORT: limit > bid), `post_only_reject_hypothetical = not would_post`. Falha de fetch → NULLs (nunca bloqueia). Não é critério de GO; é régua de honestidade do fill rate.

## Mecânica de fill/desfecho (espelha a regra selada §4)

- Fill estrito: tocar exato não preenche; preço de fill = limit. Fontes: `cycle_tick` (tick parcial < limit, válido até expiry) ou `next_candle_wick` (low/high do candle fechado que abriu pós-sinal).
- Expiry sem fill → `no_fill` (PnL política = 0). Ordem de avaliação no ciclo: wick do candle recém-fechado → tick corrente → expiry.
- Candle do fill avalia SÓ SL ao fechar (low/high completos — viés declarado, igual ao replay); seed de MFE/MAE nele.
- Candles seguintes fechados: `check_exit` do baseline (SL > TP2 > TP1 > timeout), `duration = k−1` com `k = (open(candle) − open(N))/15m`; timeout quando ≥ 16.
- Fees: entrada maker 0.02; TP maker 0.02; SL/timeout taker 0.05 (constantes de `maker_shadow.py`).

## Persistência

Tabela `momentum_maker_shadow` no `bot.db` (criada pelo coletor, `CREATE TABLE IF NOT EXISTS`): id, symbol, direction, signal_ts (ISO), candle_open_ts/expiry_ts/fill_candle_open_ts (epoch s), limit_price, sl/tp1/tp2, status (`pending → filled → closed` | `no_fill`), fill_ts, fill_source, exit_reason/exit_price/exit_ts, gross/net_pnl_pct, fees, mfe/mae, duration_candles, book snapshot (5 colunas), `taker_net_pnl_pct` (gravado no close do trade real — pareamento direto, sem join).

## Integração (3 hooks em `paper_executor.py`, todos try/except + flag `MOMENTUM_MAKER_SHADOW_ENABLED`)

1. `open_position` (sucesso) → `on_trade_opened(...)`; `pos["maker_shadow_id"] = shadow_id`.
2. Bloco de close em `check_open_positions` → `on_trade_closed(shadow_id, net_pnl_pct)`.
3. Loop Phase 1 por símbolo → `on_cycle(symbol, tick, now_candle_open, closed_candle?)`, com `closed_candle = iloc[-2]` só quando candle 15m novo foi detectado.

## Fora de escopo

Execução maker real; mudanças no v1.1; critérios novos; fila de descoberta (funding BTC segue 1º).
