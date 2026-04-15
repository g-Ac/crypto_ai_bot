#!/usr/bin/env python3
"""
diagnose_funnel.py — Diagnostico do funil de decisoes do scalping.

Usa dados do banco (scalping_decisions) para mostrar onde os sinais
estao sendo bloqueados. Funciona tanto como CLI quanto como modulo
importavel pelo dashboard.

Metricas:
  - Distribuicao por blocked_by (confluence, risk, cooldown, etc.)
  - Distribuicao por regime (TRENDING, RANGING, etc.)
  - Distribuicao por sessao (us, europe, asia, dead)
  - Taxa de passagem (blocked_by = 'none')
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database as db


def get_funnel_data(hours: int = 24) -> dict:
    """Retorna dados do funil de decisoes do scalping.

    Args:
        hours: janela de tempo (default 24h)

    Returns:
        dict com total_decisions, funnel (by blocked_by), by_regime, by_session
    """
    conn = db._get_conn()
    try:
        # Funil principal: blocked_by
        blocked_rows = conn.execute(
            "SELECT blocked_by, COUNT(*) as count "
            "FROM scalping_decisions "
            "WHERE timestamp > datetime('now', ?) "
            "GROUP BY blocked_by ORDER BY count DESC",
            (f"-{hours} hours",),
        ).fetchall()
        funnel = {(r["blocked_by"] or "none"): int(r["count"]) for r in blocked_rows}
        total = sum(funnel.values())

        # Por regime (decisions count)
        regime_rows = conn.execute(
            "SELECT market_regime, COUNT(*) as count "
            "FROM scalping_decisions "
            "WHERE timestamp > datetime('now', ?) "
            "GROUP BY market_regime ORDER BY count DESC",
            (f"-{hours} hours",),
        ).fetchall()
        regime_decisions = {(r["market_regime"] or "N/A"): int(r["count"]) for r in regime_rows}

        # Por regime (trade-level stats from scalping_trades)
        regime_trade_rows = conn.execute(
            "SELECT market_regime, COUNT(*) as trades, "
            "SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins, "
            "ROUND(SUM(pnl_pct), 4) as pnl "
            "FROM scalping_trades "
            "WHERE timestamp > datetime('now', ?) "
            "GROUP BY market_regime",
            (f"-{hours} hours",),
        ).fetchall()
        regime_trades = {(r["market_regime"] or "N/A"): {
            "trades": int(r["trades"]), "wins": int(r["wins"]), "pnl": float(r["pnl"] or 0)
        } for r in regime_trade_rows}

        # Merge: by_regime = {regime: {decisions, trades, wins, pnl}}
        all_regimes = set(regime_decisions) | set(regime_trades)
        by_regime = {}
        for regime in all_regimes:
            t = regime_trades.get(regime, {"trades": 0, "wins": 0, "pnl": 0})
            by_regime[regime] = {
                "decisions": regime_decisions.get(regime, 0),
                "trades": t["trades"],
                "wins": t["wins"],
                "pnl": t["pnl"],
            }

        # Por sessao (decisions count)
        session_rows = conn.execute(
            "SELECT session_bucket, COUNT(*) as count "
            "FROM scalping_decisions "
            "WHERE timestamp > datetime('now', ?) "
            "GROUP BY session_bucket ORDER BY count DESC",
            (f"-{hours} hours",),
        ).fetchall()
        session_decisions = {(r["session_bucket"] or "N/A"): int(r["count"]) for r in session_rows}

        # Por sessao (trade-level stats from scalping_trades)
        session_trade_rows = conn.execute(
            "SELECT session_bucket, COUNT(*) as trades, "
            "SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins, "
            "ROUND(SUM(pnl_pct), 4) as pnl "
            "FROM scalping_trades "
            "WHERE timestamp > datetime('now', ?) "
            "GROUP BY session_bucket",
            (f"-{hours} hours",),
        ).fetchall()
        session_trades = {(r["session_bucket"] or "N/A"): {
            "trades": int(r["trades"]), "wins": int(r["wins"]), "pnl": float(r["pnl"] or 0)
        } for r in session_trade_rows}

        # Merge: by_session = {session: {decisions, trades, wins, pnl}}
        all_sessions = set(session_decisions) | set(session_trades)
        by_session = {}
        for session in all_sessions:
            t = session_trades.get(session, {"trades": 0, "wins": 0, "pnl": 0})
            by_session[session] = {
                "decisions": session_decisions.get(session, 0),
                "trades": t["trades"],
                "wins": t["wins"],
                "pnl": t["pnl"],
            }

        # Por confluence_score
        score_rows = conn.execute(
            "SELECT confluence_score, COUNT(*) as count "
            "FROM scalping_decisions "
            "WHERE timestamp > datetime('now', ?) "
            "GROUP BY confluence_score ORDER BY confluence_score",
            (f"-{hours} hours",),
        ).fetchall()
        by_score = {str(r["confluence_score"] or 0): int(r["count"]) for r in score_rows}

        # Motivos mais frequentes de bloqueio
        reason_rows = conn.execute(
            "SELECT reason, COUNT(*) as count "
            "FROM scalping_decisions "
            "WHERE timestamp > datetime('now', ?) "
            "AND blocked_by != 'none' "
            "GROUP BY reason ORDER BY count DESC LIMIT 10",
            (f"-{hours} hours",),
        ).fetchall()
        top_reasons = [
            {"reason": r["reason"] or "?", "count": int(r["count"])}
            for r in reason_rows
        ]

        passed = funnel.get("none", 0)
        pass_rate = (passed / total * 100) if total > 0 else 0

        return {
            "period_hours": hours,
            "total_decisions": total,
            "passed": passed,
            "pass_rate_pct": round(pass_rate, 1),
            "funnel": funnel,
            "by_regime": by_regime,
            "by_session": by_session,
            "by_confluence_score": by_score,
            "top_block_reasons": top_reasons,
        }
    finally:
        conn.close()


def get_funnel_json(hours: int = 24) -> str:
    """Retorna funil como JSON string (para API)."""
    return json.dumps(get_funnel_data(hours), indent=2, ensure_ascii=False)


def print_funnel(hours: int = 24):
    """Imprime funil formatado no terminal."""
    data = get_funnel_data(hours)

    print(f"FUNIL DE DECISOES — ultimas {hours}h")
    print("=" * 55)
    print(f"  Total decisoes: {data['total_decisions']}")
    print(f"  Passaram:       {data['passed']} ({data['pass_rate_pct']:.1f}%)")
    print()

    # Blocked by
    print("  Bloqueado por:")
    for key, count in sorted(data["funnel"].items(), key=lambda x: -x[1]):
        pct = count / data["total_decisions"] * 100 if data["total_decisions"] else 0
        marker = " <--" if key == "none" else ""
        print(f"    {key:20s} {count:>5}  ({pct:5.1f}%){marker}")

    # By regime
    if data["by_regime"]:
        print()
        print("  Por regime:")
        for regime, count in data["by_regime"].items():
            print(f"    {regime:20s} {count:>5}")

    # By session
    if data["by_session"]:
        print()
        print("  Por sessao:")
        for session, count in data["by_session"].items():
            print(f"    {session:20s} {count:>5}")

    # Top reasons
    if data["top_block_reasons"]:
        print()
        print("  Top motivos de bloqueio:")
        for item in data["top_block_reasons"][:5]:
            reason = item["reason"][:60]
            print(f"    {item['count']:>4}x  {reason}")

    print(f"\n{'=' * 55}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Diagnostico do funil de scalping")
    parser.add_argument("--hours", type=int, default=24, help="Janela em horas")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    if args.json:
        print(get_funnel_json(args.hours))
    else:
        print_funnel(args.hours)


if __name__ == "__main__":
    main()
