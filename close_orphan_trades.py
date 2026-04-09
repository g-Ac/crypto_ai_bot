"""
Fecha trades orfaos do agent que ficaram abertos indefinidamente.

Busca preco atual via Binance, calcula P&L real, registra no banco,
e limpa o state. Seguro para rodar em paper mode.

Uso:
  python close_orphan_trades.py          # mostra o que vai fazer (dry run)
  python close_orphan_trades.py --execute  # executa de verdade
"""
import json
import sys
import requests
from datetime import datetime
from pathlib import Path

# Lazy imports to avoid side effects on import
from runtime_config import AGENT_STATE_FILE
from config import ROUND_TRIP_FEE_PCT
import database as db


def get_current_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch current prices from Binance."""
    try:
        resp = requests.get("https://api.binance.com/api/v3/ticker/price", timeout=5)
        resp.raise_for_status()
        all_prices = {item["symbol"]: float(item["price"]) for item in resp.json()}
        return {s: all_prices[s] for s in symbols if s in all_prices}
    except Exception as e:
        print(f"[ERRO] Falha ao buscar precos: {e}")
        return {}


def load_agent_state() -> dict:
    if not Path(AGENT_STATE_FILE).exists():
        return {}
    with open(AGENT_STATE_FILE, "r") as f:
        return json.load(f)


def save_agent_state(state: dict):
    import tempfile, os
    dir_name = os.path.dirname(os.path.abspath(AGENT_STATE_FILE))
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, suffix=".tmp") as f:
        f.write(json.dumps(state, indent=4, default=str))
        tmp_path = f.name
    os.replace(tmp_path, AGENT_STATE_FILE)


def main():
    execute = "--execute" in sys.argv
    db.init_db()

    state = load_agent_state()
    positions = state.get("positions", {})

    if not positions:
        print("Nenhuma posicao aberta no agent. Nada a fazer.")
        return

    symbols = list(positions.keys())
    prices = get_current_prices(symbols)

    if not prices:
        print("[ERRO] Nao conseguiu buscar precos. Abortando.")
        return

    print(f"\n{'='*60}")
    print(f"  AGENT ORPHAN TRADE CLOSER")
    print(f"  Mode: {'EXECUTE' if execute else 'DRY RUN'}")
    print(f"  Posicoes abertas: {len(positions)}")
    print(f"{'='*60}\n")

    trades_to_close = []

    for symbol, pos in positions.items():
        entry = pos["entry_price"]
        current = prices.get(symbol)
        if current is None:
            print(f"  [SKIP] {symbol} — preco nao encontrado")
            continue

        direction = pos["type"]
        if direction == "LONG":
            pnl_pct = ((current - entry) / entry) * 100
        else:
            pnl_pct = ((entry - current) / entry) * 100

        pnl_pct -= ROUND_TRIP_FEE_PCT
        position_size = pos.get("position_size_usd", 200)
        pnl_usd = position_size * (pnl_pct / 100)

        trade_data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol,
            "type": direction,
            "entry_price": entry,
            "sl_price": pos.get("sl_price"),
            "tp_price": pos.get("tp_price"),
            "position_size_usd": position_size,
            "exit_price": current,
            "pnl_pct": round(pnl_pct, 4),
            "pnl_usd": round(pnl_usd, 2),
            "exit_reason": "orphan_cleanup",
            "analyst_confidence": pos.get("analyst_confidence", 0),
            "capital_after": state.get("capital", 10000) + pnl_usd,
            "execution_mode": pos.get("execution_mode", "paper"),
            "recommended_mode": pos.get("recommended_mode", "paper"),
            "lifecycle_id": pos.get("lifecycle_id"),
        }
        trades_to_close.append((symbol, trade_data, pnl_pct, pnl_usd))

        status = "WIN" if pnl_pct > 0 else "LOSS"
        print(f"  {symbol} ({direction})")
        print(f"    Entry: {entry:.4f} -> Current: {current:.4f}")
        print(f"    P&L: {pnl_pct:+.2f}% (${pnl_usd:+.2f}) [{status}]")
        print()

    if not trades_to_close:
        print("Nenhum trade para fechar.")
        return

    total_pnl = sum(t[3] for t in trades_to_close)
    print(f"  Total P&L: ${total_pnl:+.2f}")
    print()

    if not execute:
        print("  [DRY RUN] Nenhuma alteracao feita.")
        print("  Para executar: python close_orphan_trades.py --execute")
        return

    # Execute: close all trades
    for symbol, trade_data, pnl_pct, pnl_usd in trades_to_close:
        # Update state
        state["capital"] += pnl_usd
        state["total_trades"] = state.get("total_trades", 0) + 1
        if pnl_pct > 0:
            state["wins"] = state.get("wins", 0) + 1
        else:
            state["losses"] = state.get("losses", 0) + 1

        state.setdefault("history", []).append({
            "symbol": symbol,
            "type": trade_data["type"],
            "pnl_pct": round(pnl_pct, 2),
        })

        # Update capital_after with running total
        trade_data["capital_after"] = round(state["capital"], 2)

        # Log to database
        try:
            db.insert_agent_trade(trade_data)
            print(f"  [OK] {symbol} fechado e registrado no banco")
        except Exception as e:
            print(f"  [ERRO] {symbol} falha ao gravar: {e}")

        # Remove from positions
        del state["positions"][symbol]

    # Keep only last 20 history entries
    state["history"] = state.get("history", [])[-20:]

    # Save state
    save_agent_state(state)
    print(f"\n  State salvo. Capital: ${state['capital']:.2f}")
    print(f"  Trades: {state['total_trades']} | W: {state['wins']} | L: {state['losses']}")
    print(f"  Posicoes abertas: {len(state.get('positions', {}))}")


if __name__ == "__main__":
    main()
