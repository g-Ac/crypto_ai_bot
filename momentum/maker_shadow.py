"""Sombra maker-fill do v1.1 (docs/pre_registros/PREREG_maker_fill_v11.md, §4).

Simula a politica de execucao maker sobre os MESMOS sinais executados pelo
paper executor — funcao pura, sem DB nem rede — usada tanto pelo replay
retroativo (Fase R) quanto pelo coletor forward (Fase F). Nao toca a
estrategia nem o executor.

Regras travadas no pre-registro (nao renegociar aqui):
- Limit post-only ao preco de entrada real, valida por 2 candles 15m; fill
  estrito (strict-through): tocar exato nao preenche; preco de fill = limit.
- Candle de fill avalia SO o SL (o preco veio contra para preencher);
  TPs apenas a partir do candle seguinte, com o runner do baseline
  (check_exit: SL > TP2 > TP1 > timeout).
- Timeout ancorado no candle do sinal N com a mesma contagem do executor
  real (check no candle N+k usa duration=k-1; dispara quando >= 16).
- Fees: entrada maker 0.02; TP maker 0.02; SL/timeout taker 0.05.
- Non-fill: PnL da politica = 0 (ordem cancelada nao paga fee).

Semantica da entrada (adendo v1.2 do pre-registro): o executor decide no 1o
ciclo de 5min de um candle 15m novo, com entry_price = preco PARCIAL desse
candle N (nao um close finalizado). A serie `candles` da simulacao comeca,
portanto, no proprio N: a limit vive o resto de N e o candle N+1 (~30min,
a intencao economica selada de "2 candles 15m"). Usar low/high completos de
N inclui os primeiros minutos pre-sinal — vies otimista declarado, coberto
pelo piso alto e pelo carater kill-only da Fase R.
"""
from __future__ import annotations

from typing import Any, Dict, List

from momentum.research_runner import check_exit

MAKER_FEE_RATE = 0.02   # %/lado — congelado no selo do pre-registro
TAKER_FEE_RATE = 0.05   # %/lado — fee canonica do lab (CONSTITUTION)
FILL_WINDOW_CANDLES = 2
TIMEOUT_CANDLES = 16


def _pnl(is_long: bool, entry: float, exit_price: float) -> float:
    if is_long:
        return (exit_price - entry) / entry * 100
    return (entry - exit_price) / entry * 100


def simulate_maker_trade(
    *,
    direction: str,
    entry_price: float,
    sl_price: float,
    tp1_price: float,
    tp2_price: float,
    candles: List[Dict[str, float]],
    fill_window: int = FILL_WINDOW_CANDLES,
    timeout_candles: int = TIMEOUT_CANDLES,
    maker_fee_rate: float = MAKER_FEE_RATE,
    taker_fee_rate: float = TAKER_FEE_RATE,
) -> Dict[str, Any]:
    """Aplica a regra de execucao maker a um trade pareado do baseline.

    Args:
        candles: serie 15m a partir do candle do sinal N, INCLUSIVE (o sinal
            dispara dentro de N; a limit vive o resto de N e o N+1).
            Cada item: high/low/close.

    Returns:
        dict com filled, fill_candle (1-based, None se no_fill), exit_reason
        (no_fill | sl_hit | tp1_hit | tp2_hit | timeout | breakeven |
        incomplete), exit_price, gross_pnl_pct, entry_fee_rate,
        exit_fee_rate, net_pnl_pct, mfe_pct, mae_pct, duration_candles.
        "incomplete" = fill aconteceu mas a serie acabou sem exit (trade
        recente / Fase F em andamento); excluido do julgamento.
    """
    is_long = direction == "LONG"

    def _done(filled, fill_idx, reason, exit_price, gross,
              entry_fee, exit_fee, mfe, mae, duration):
        return {
            "filled": filled,
            "fill_candle": fill_idx,
            "exit_reason": reason,
            "exit_price": exit_price,
            "gross_pnl_pct": round(gross, 4),
            "entry_fee_rate": entry_fee,
            "exit_fee_rate": exit_fee,
            "net_pnl_pct": round(gross - (entry_fee + exit_fee), 4),
            "mfe_pct": round(mfe, 4),
            "mae_pct": round(mae, 4),
            "duration_candles": duration,
        }

    # --- Fill da entrada: strict-through dentro da janela ---
    fill_idx = None  # 1-based: C+1 = 1
    for i in range(min(fill_window, len(candles))):
        candle = candles[i]
        through = (candle["low"] < entry_price) if is_long \
            else (candle["high"] > entry_price)
        if through:
            fill_idx = i + 1
            break

    if fill_idx is None:
        return _done(False, None, "no_fill", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)

    # --- Candle de fill: avalia SO o SL ---
    fill_candle = candles[fill_idx - 1]
    if is_long:
        mfe = (fill_candle["high"] - entry_price) / entry_price * 100
        mae = (fill_candle["low"] - entry_price) / entry_price * 100
        sl_on_fill = fill_candle["low"] <= sl_price
    else:
        mfe = (entry_price - fill_candle["low"]) / entry_price * 100
        mae = (entry_price - fill_candle["high"]) / entry_price * 100
        sl_on_fill = fill_candle["high"] >= sl_price
    mfe = max(mfe, 0.0)
    mae = min(mae, 0.0)

    if sl_on_fill:
        gross = _pnl(is_long, entry_price, sl_price)
        return _done(True, fill_idx, "sl_hit", sl_price, gross,
                     maker_fee_rate, taker_fee_rate, mfe, mae, fill_idx - 1)

    # --- Candles seguintes: runner do baseline ---
    for k in range(fill_idx + 1, len(candles) + 1):
        candle = candles[k - 1]
        result = check_exit(
            direction=direction,
            entry_price=entry_price,
            sl_price=sl_price,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
            candle_high=candle["high"],
            candle_low=candle["low"],
            candle_close=candle["close"],
            current_mfe=mfe,
            current_mae=mae,
            duration_candles=k - 1,  # contagem do executor: candle C+k -> k-1
            timeout_candles=timeout_candles,
            breakeven_trigger_pct=0.0,
        )
        mfe = result["mfe_pct"]
        mae = result["mae_pct"]
        if result["closed"]:
            reason = result["exit_reason"]
            exit_fee = maker_fee_rate if reason in ("tp1_hit", "tp2_hit") \
                else taker_fee_rate
            return _done(True, fill_idx, reason, result["exit_price"],
                         result["pnl_pct"], maker_fee_rate, exit_fee,
                         mfe, mae, k - 1)

    return _done(True, fill_idx, "incomplete", 0.0, 0.0, 0.0, 0.0,
                 mfe, mae, len(candles))


_M15_MS = 15 * 60 * 1000


def locate_signal_candle(
    klines: List[Dict[str, Any]],
    idx_by_open_ms: Dict[int, int],
    close_ts_ms: int,
    duration_candles: int,
    entry_price: float,
    search_radius: int = 14,
) -> tuple[int | None, int | None]:
    """Localiza o indice do candle do sinal N de um trade fechado.

    Semantica real do executor (adendo do pre-registro): o sinal dispara no
    1o ciclo de 5min de um candle 15m NOVO, com entry_price = preco parcial
    desse candle N — logo entry_price esta contido no range final [low, high]
    de N. Estimativa temporal: open(N) = floor15(t_close) - duration*15m;
    estruturalmente o offset correto e 0 ou -1 (ordem check/incremento do
    executor); gaps de ciclo (downtime) subcontam duration e empurram N para
    offsets mais negativos.

    Busca do offset 0 para tras, retornando o primeiro candle que contem o
    entry_price. Retorna (indice, offset) ou (None, None). O offset deve ser
    reportado: ancoras com offset < -1 sao recuperacao de gap (mais fracas).
    """
    est_n_open = (close_ts_ms // _M15_MS) * _M15_MS - duration_candles * _M15_MS

    for off in range(0, -(search_radius + 1), -1):
        i = idx_by_open_ms.get(est_n_open + off * _M15_MS)
        if i is None:
            continue
        if klines[i]["low"] <= entry_price <= klines[i]["high"]:
            return i, off
    return None, None


def summarize_policy(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Agrega a politica maker conforme a semantica selada no pre-registro.

    - "incomplete" e excluido de tudo (so contado em n_incomplete).
    - PnL total: no_fill conta 0 (politica nao operou aquele sinal).
    - PF: SO dos PnLs executados — zeros sao neutros por definicao, entao
      o PF NAO pune selecao adversa (criterios 3-4 do pre-registro punem).
    - PF indefinido (sem perdas ou sem ganhos executados) retorna None:
      "PF indefinido nao aprova".
    """
    valid = [r for r in rows if r["exit_reason"] != "incomplete"]
    n_incomplete = len(rows) - len(valid)
    filled = [r for r in valid if r["filled"]]

    wins = sum(r["net_pnl_pct"] for r in filled if r["net_pnl_pct"] > 0)
    losses = sum(-r["net_pnl_pct"] for r in filled if r["net_pnl_pct"] < 0)
    pf = round(wins / losses, 4) if (wins > 0 and losses > 0) else None

    return {
        "n_trades": len(valid),
        "n_filled": len(filled),
        "n_incomplete": n_incomplete,
        "fill_rate": round(len(filled) / len(valid), 4) if valid else None,
        "total_net_pct": round(sum(r["net_pnl_pct"] for r in valid), 4),
        "pf_executados": pf,
    }
