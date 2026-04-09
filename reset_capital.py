#!/usr/bin/env python3
"""
reset_capital.py - Reset all trading systems to clean state with new capital.

Usage:
    python reset_capital.py --dry-run
    python reset_capital.py --execute
    python reset_capital.py --execute --capital '{"paper": 0, "agent": 500, "pump": 50, "scalping": 500}'
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime

# Ensure project dir is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from runtime_config import (
    PAPER_STATE_FILE,
    AGENT_STATE_FILE,
    PUMP_STATE_FILE,
    SCALPING_STATE_FILE,
    APP_DIR,
)
from database import (
    init_db,
    insert_paper_trade,
    insert_agent_trade,
    insert_pump_trade,
    insert_scalping_trade,
)
from market import get_candles

DEFAULT_CAPITAL = {
    "paper": 0,
    "agent": 500,
    "pump": 50,
    "scalping": 500,
}

SYSTEMS = {
    "paper": {
        "state_file": PAPER_STATE_FILE,
        "insert_fn": insert_paper_trade,
    },
    "agent": {
        "state_file": AGENT_STATE_FILE,
        "insert_fn": insert_agent_trade,
    },
    "pump": {
        "state_file": PUMP_STATE_FILE,
        "insert_fn": insert_pump_trade,
    },
    "scalping": {
        "state_file": SCALPING_STATE_FILE,
        "insert_fn": insert_scalping_trade,
    },
}


def get_current_price(symbol: str) -> float:
    """Fetch current price from Binance via 1m candle."""
    try:
        df = get_candles(symbol, "1m", 1)
        return float(df["close"].iloc[-1])
    except Exception as e:
        print(f"  WARNING: Could not fetch price for {symbol}: {e}")
        return 0.0


def load_state(filepath: str) -> dict:
    """Load JSON state file. Returns empty dict if missing or invalid."""
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"  File not found: {filepath}")
        return {}
    except json.JSONDecodeError as e:
        print(f"  Invalid JSON in {filepath}: {e}")
        return {}


def backup_states() -> str:
    """Backup all state files to timestamped directory. Returns backup path."""
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_dir = os.path.join(str(APP_DIR), "backups", f"state_backup_{ts}")
    os.makedirs(backup_dir, exist_ok=True)

    for name, cfg in SYSTEMS.items():
        src = cfg["state_file"]
        if os.path.exists(src):
            dst = os.path.join(backup_dir, f"{name}_{os.path.basename(src)}")
            shutil.copy2(src, dst)
            print(f"  Backed up: {name} -> {os.path.basename(dst)}")

    print(f"  Backup dir: {backup_dir}")
    return backup_dir


def close_positions(system_name: str, state: dict, insert_fn, new_capital: float, dry_run: bool) -> list:
    """Close open positions and record them in the database."""
    positions = state.get("positions", {})
    if not positions:
        return []

    closed = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for symbol, pos in positions.items():
        entry_price = pos.get("entry_price", 0)
        current_price = get_current_price(symbol)

        if current_price == 0:
            print(f"  SKIP {symbol}: could not get current price")
            continue

        pos_type = pos.get("type", pos.get("direction", "LONG"))

        if pos_type == "LONG":
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
        else:
            pnl_pct = ((entry_price - current_price) / entry_price) * 100

        position_size = pos.get("position_size_usd", state.get("capital", 0) * 0.15)
        pnl_usd = position_size * (pnl_pct / 100)

        print(f"  {symbol} {pos_type}: entry=${entry_price:.4f} -> now=${current_price:.4f} | "
              f"PnL: {pnl_pct:+.2f}% (${pnl_usd:+.2f})")

        trade_info = {
            "symbol": symbol,
            "type": pos_type,
            "entry_price": entry_price,
            "current_price": current_price,
            "pnl_pct": round(pnl_pct, 4),
            "pnl_usd": round(pnl_usd, 2),
        }

        if not dry_run:
            trade = {
                "timestamp": now,
                "symbol": symbol,
                "type": pos_type,
                "entry_price": entry_price,
                "exit_price": current_price,
                "pnl_pct": round(pnl_pct, 4),
                "pnl_usd": round(pnl_usd, 2),
                "exit_reason": "manual_reset",
                "capital_after": round(new_capital, 2),
            }

            if system_name == "paper":
                trade["sl_price"] = pos.get("sl_price")
                trade["tp_price"] = pos.get("tp_price")

            elif system_name == "agent":
                trade["sl_price"] = pos.get("sl_price", 0)
                trade["tp_price"] = pos.get("tp_price", 0)
                trade["position_size_usd"] = round(position_size, 2)
                trade["analyst_confidence"] = pos.get("analyst_confidence", 0)
                trade["execution_mode"] = pos.get("execution_mode", "paper")
                trade["lifecycle_id"] = pos.get("lifecycle_id", "")
                trade["recommended_mode"] = pos.get("recommended_mode", "paper")

            elif system_name == "pump":
                trade["duration_min"] = 0
                trade["peak_price"] = current_price

            elif system_name == "scalping":
                trade["sl_price"] = pos.get("sl_price")
                trade["tp_price"] = pos.get("tp_price")
                trade["position_size_usd"] = pos.get("position_size_usd")
                trade["leverage"] = pos.get("leverage", 1)
                trade["confluence_score"] = pos.get("confluence_score")
                trade["source"] = pos.get("source", "manual_reset")

            try:
                insert_fn(trade)
                print(f"    -> Recorded in {system_name}_trades")
            except Exception as e:
                print(f"    -> FAILED to record: {e}")

        closed.append(trade_info)

    return closed


def write_clean_state(filepath: str, capital: float, dry_run: bool):
    """Write a clean state file with the given capital."""
    clean = {
        "capital": capital,
        "positions": {},
        "cooldowns": {},
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "total_pnl": 0,
        "history": [],
    }

    if dry_run:
        print(f"  Would write: capital=${capital:.2f}, 0 positions, clean stats")
    else:
        dir_name = os.path.dirname(filepath) or "."
        with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False,
                                         suffix=".tmp", encoding="utf-8") as f:
            json.dump(clean, f, indent=4)
            tmp_path = f.name
        os.replace(tmp_path, filepath)
        print(f"  Written: capital=${capital:.2f}")


def main():
    parser = argparse.ArgumentParser(description="Reset trading systems to clean state")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--execute", action="store_true", help="Execute the reset")
    parser.add_argument("--capital", type=str, default=None,
                        help='Capital JSON, e.g. \'{"paper": 0, "agent": 500}\'')
    args = parser.parse_args()

    if not args.dry_run and not args.execute:
        parser.error("Must specify --dry-run or --execute")
    if args.dry_run and args.execute:
        parser.error("Cannot specify both --dry-run and --execute")

    capital = DEFAULT_CAPITAL.copy()
    if args.capital:
        try:
            custom = json.loads(args.capital)
            capital.update(custom)
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid --capital JSON: {e}")
            sys.exit(1)

    dry_run = args.dry_run
    mode = "DRY-RUN" if dry_run else "EXECUTE"

    print("=" * 60)
    print(f"  RESET CAPITAL - {mode}")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    print(f"\nTarget capital allocation:")
    for sys_name, amt in capital.items():
        status = "(PAUSED)" if amt == 0 else ""
        print(f"  {sys_name:10s}: ${amt:.2f} {status}")

    # Init database
    print("\nInitializing database...")
    init_db()

    # Phase 1: Read all current states
    print("\n" + "-" * 60)
    print("CURRENT STATE:")
    print("-" * 60)

    states = {}
    total_positions = 0
    for sys_name, cfg in SYSTEMS.items():
        state = load_state(cfg["state_file"])
        states[sys_name] = state
        n_pos = len(state.get("positions", {}))
        total_positions += n_pos
        print(f"\n  [{sys_name.upper()}]")
        if state:
            print(f"  Capital:   ${state.get('capital', 0):.2f}")
            print(f"  Positions: {n_pos}")
            print(f"  Trades:    {state.get('total_trades', 0)} "
                  f"(W:{state.get('wins', 0)} L:{state.get('losses', 0)})")
            for sym, pos in state.get("positions", {}).items():
                pt = pos.get("type", pos.get("direction", "?"))
                print(f"    - {sym} {pt} @ ${pos.get('entry_price', 0):.4f}")
        else:
            print(f"  No state file found")

    # Phase 2: Backup (execute mode only)
    if not dry_run:
        print(f"\n" + "-" * 60)
        print("BACKUP:")
        print("-" * 60)
        backup_states()

    # Phase 3: Close open positions
    if total_positions > 0:
        print(f"\n" + "-" * 60)
        print(f"CLOSING {total_positions} OPEN POSITION(S):")
        print("-" * 60)
        for sys_name, cfg in SYSTEMS.items():
            positions = states[sys_name].get("positions", {})
            if positions:
                print(f"\n  [{sys_name.upper()}] - {len(positions)} position(s)")
                close_positions(
                    sys_name, states[sys_name],
                    cfg["insert_fn"], capital[sys_name], dry_run
                )

    # Phase 4: Write clean states
    print(f"\n" + "-" * 60)
    print(f"{'WOULD WRITE' if dry_run else 'WRITING'} CLEAN STATES:")
    print("-" * 60)
    for sys_name, cfg in SYSTEMS.items():
        print(f"\n  [{sys_name.upper()}]")
        write_clean_state(cfg["state_file"], capital[sys_name], dry_run)

    # Summary
    print("\n" + "=" * 60)
    print(f"  RESET {'PREVIEW' if dry_run else 'COMPLETE'}")
    if not dry_run:
        total = sum(capital.values())
        print(f"  Total capital deployed: ${total:.2f}")
    print("=" * 60)

    if dry_run:
        print("\nNo changes were made. Run with --execute to apply.")


if __name__ == "__main__":
    main()
