"""
Offline Validation Auditor.

Reads existing bot data (SQLite + state files) and generates a structured
report about whether each trading system shows edge or is just churning.

Usage:
    python validation_auditor.py --days 30
    python validation_auditor.py --days 30 --stdout
    python validation_auditor.py --days 90 --output-dir runtime/baseline
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import (
    PAPER_INITIAL_CAPITAL,
    AGENT_INITIAL_CAPITAL,
    PUMP_INITIAL_CAPITAL,
    SCALPING_INITIAL_CAPITAL,
)


# ── LOCAL RUNTIME RESOLUTION (side-effect-free) ─────────────────────────────
# Mirrors the values from runtime_config.py but without creating directories,
# writing manifests, or any other I/O at import time.

_APP_DIR = Path(__file__).resolve().parent


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
    return normalized.strip("-._").lower() or "baseline"


def _git_short(args: list[str]) -> str:
    try:
        r = subprocess.run(
            ["git", *args], cwd=str(_APP_DIR),
            capture_output=True, text=True, timeout=3, check=False,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


BOT_ID = _slugify(os.getenv("BOT_ID", "baseline"))
_RUNTIME_BASE = Path(os.getenv("BOT_RUNTIME_BASE_DIR", str(_APP_DIR / "runtime")))
RUNTIME_DIR = _RUNTIME_BASE / BOT_ID
DB_FILE = str(RUNTIME_DIR / "bot.db")
_git_sha = os.getenv("BOT_GIT_SHA", _git_short(["rev-parse", "--short", "HEAD"]) or "unknown")
VERSION_TAG = os.getenv("BOT_VERSION_TAG", f"{BOT_ID}:{_git_sha}")


# ── LAZY IMPORTS (avoid triggering runtime_config side effects at load) ──────
# database.py and scalping_research.py transitively import runtime_config.py,
# which creates directories and writes runtime_manifest.json.  We defer those
# imports so that `import validation_auditor` is completely side-effect-free.

_db_module = None
_scorer_fn = None


def _db():
    """Return the database module (imported lazily on first call)."""
    global _db_module
    if _db_module is None:
        import database
        _db_module = database
    return _db_module


def _compute_scorer(days: int = 30, limit: int = 5000) -> dict:
    """Call compute_scalping_scorer_report (imported lazily on first call)."""
    global _scorer_fn
    if _scorer_fn is None:
        from scalping_research import compute_scalping_scorer_report
        _scorer_fn = compute_scalping_scorer_report
    return _scorer_fn(days=days, limit=limit)


# ── SYSTEM CONFIG ────────────────────────────────────────────────────────────

SYSTEMS = {
    "paper":    {"table": "paper_trades",    "initial_capital": PAPER_INITIAL_CAPITAL},
    "agent":    {"table": "agent_trades",    "initial_capital": AGENT_INITIAL_CAPITAL},
    "pump":     {"table": "pump_trades",     "initial_capital": PUMP_INITIAL_CAPITAL},
    "scalping": {"table": "scalping_trades", "initial_capital": SCALPING_INITIAL_CAPITAL},
}


# ── TRADE HELPERS ────────────────────────────────────────────────────────────

def _closed_trades(trades: list) -> list:
    """Keep only closed trades with realised PnL."""
    return [
        t for t in trades
        if t.get("exit_reason") != "open" and t.get("pnl_pct") is not None
    ]


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _compute_stats(trades: list) -> dict:
    """Compute aggregate stats from a list of closed trades.

    Mirrors the shape returned by db.get_all_time_stats but computed
    locally so the auditor uses one single trade list as source of truth.
    """
    if not trades:
        return {
            "total_trades": 0, "win_rate": 0, "avg_pnl_pct": 0,
            "largest_win": 0, "largest_loss": 0, "profit_factor": 0,
            "max_drawdown_pct": 0,
        }

    wins = [t for t in trades if _safe_float(t.get("pnl_pct")) > 0]
    losses = [t for t in trades if _safe_float(t.get("pnl_pct")) < 0]
    total = len(trades)
    win_rate = (len(wins) / total * 100) if total else 0

    sum_wins = sum(_safe_float(t.get("pnl_usd")) for t in wins)
    sum_losses = abs(sum(_safe_float(t.get("pnl_usd")) for t in losses))
    profit_factor = (
        (sum_wins / sum_losses) if sum_losses > 0
        else (99.0 if sum_wins > 0 else 0)
    )

    all_pnl = [_safe_float(t.get("pnl_pct")) for t in trades]
    largest_win = max(all_pnl) if all_pnl else 0
    largest_loss = min(all_pnl) if all_pnl else 0
    avg_pnl = sum(all_pnl) / len(all_pnl) if all_pnl else 0

    # Max drawdown from capital_after series
    max_dd = 0.0
    capitals = [_safe_float(t.get("capital_after")) for t in trades if t.get("capital_after")]
    if capitals:
        peak = capitals[0]
        for c in capitals:
            if c > peak:
                peak = c
            dd = ((peak - c) / peak * 100) if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

    return {
        "total_trades": total,
        "win_rate": round(win_rate, 1),
        "avg_pnl_pct": round(avg_pnl, 2),
        "largest_win": round(largest_win, 2),
        "largest_loss": round(largest_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_dd, 2),
    }


# ── EXPECTANCY & CHURN ───────────────────────────────────────────────────────

def _compute_expectancy(trades: list, audit_days: int = 30) -> dict:
    """Expectancy, avg win/loss, trades per day, churn ratio.

    ``audit_days`` is the full audit window (--days).  trades_per_day is
    computed over that window so it reflects activity vs inactivity, not
    just density on days that happened to have trades.
    """
    if not trades:
        return {
            "expectancy_pct": 0, "avg_win_pct": 0, "avg_loss_pct": 0,
            "win_count": 0, "loss_count": 0, "trades_per_day": 0,
            "total_pnl_pct": 0, "churn_ratio": None,
        }

    wins = [t for t in trades if _safe_float(t.get("pnl_pct")) > 0]
    losses = [t for t in trades if _safe_float(t.get("pnl_pct")) < 0]

    avg_win = (
        sum(_safe_float(t["pnl_pct"]) for t in wins) / len(wins)
        if wins else 0
    )
    avg_loss = (
        abs(sum(_safe_float(t["pnl_pct"]) for t in losses) / len(losses))
        if losses else 0
    )

    wr = len(wins) / len(trades)
    expectancy = (wr * avg_win) - ((1 - wr) * avg_loss)

    # Trades per day — uses the full audit window, not just days with trades
    span_days = max(audit_days, 1)
    trades_per_day = len(trades) / span_days

    total_pnl_pct = sum(_safe_float(t.get("pnl_pct")) for t in trades)

    # Churn ratio: trades per unit of absolute PnL.  Higher = more spinning.
    if abs(total_pnl_pct) > 0.01:
        churn_ratio = round(len(trades) / abs(total_pnl_pct), 2)
    else:
        churn_ratio = None  # effectively infinite

    return {
        "expectancy_pct": round(expectancy, 4),
        "avg_win_pct": round(avg_win, 4),
        "avg_loss_pct": round(avg_loss, 4),
        "win_count": len(wins),
        "loss_count": len(losses),
        "trades_per_day": round(trades_per_day, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "churn_ratio": churn_ratio,
    }


# ── CONCENTRATION ────────────────────────────────────────────────────────────

def _concentration_check(trades: list) -> dict:
    """Check if positive returns are concentrated in a few trades."""
    win_pnls = sorted(
        [_safe_float(t["pnl_pct"]) for t in trades if _safe_float(t.get("pnl_pct")) > 0],
        reverse=True,
    )
    if len(win_pnls) < 3:
        return {"concentrated": False, "top_trade_share_pct": 0}

    total_win = sum(win_pnls)
    top_share = (win_pnls[0] / total_win * 100) if total_win > 0 else 0

    return {
        "concentrated": top_share > 50 and len(win_pnls) >= 5,
        "top_trade_share_pct": round(top_share, 1),
    }


# ── VERDICT HEURISTICS ───────────────────────────────────────────────────────
#
#  H1  Profit factor perto de 1 (0.8 - 1.2)
#  H2  Expectancy baixa ou negativa (|exp| <= 0.15  ou  exp < -0.15)
#  H3  Drawdown desproporcional ao retorno acumulado
#  H4  Retorno concentrado em poucos trades
#  H5  Churn alto (muitos trades por % de PnL)
#  H6  Edge negativo (profit factor < 1)
#
#  Verdicts:
#    insufficient_data  — < 10 trades fechados
#    promising          — WR > 55%, PF > 1.5, exp > 0.1, 0 sinais de patinacao
#    patinando          — 2+ sinais de patinacao
#    watch              — demais casos

def _compute_verdict(stats: dict, exp: dict, conc: dict) -> tuple[str, list[str]]:
    """Determine operational verdict using explicit heuristics."""
    alerts: list[str] = []
    total = stats["total_trades"]

    if total < 10:
        return "insufficient_data", ["Menos de 10 trades fechados no periodo"]

    win_rate = stats["win_rate"]
    pf = stats["profit_factor"]
    max_dd = stats["max_drawdown_pct"]
    expectancy = exp["expectancy_pct"]
    total_pnl = exp["total_pnl_pct"]

    spin = 0  # counter of patinacao signals

    # H1: profit factor ~ 1
    if 0.8 <= pf <= 1.2:
        spin += 1
        alerts.append(f"[H1] Profit factor perto de 1 ({pf:.2f})")

    # H2: low / negative expectancy
    if -0.15 <= expectancy <= 0.15:
        spin += 1
        alerts.append(f"[H2] Expectancy muito baixa ({expectancy:+.4f}%)")
    elif expectancy < -0.15:
        spin += 1
        alerts.append(f"[H2] Expectancy negativa ({expectancy:+.4f}%)")

    # H3: drawdown > return
    if max_dd > 3 and abs(total_pnl) < max_dd:
        spin += 1
        alerts.append(
            f"[H3] Drawdown ({max_dd:.1f}%) maior que retorno "
            f"acumulado ({total_pnl:+.1f}%)"
        )

    # H4: concentrated returns
    if conc["concentrated"]:
        alerts.append(
            f"[H4] Retorno concentrado: melhor trade = "
            f"{conc['top_trade_share_pct']:.0f}% dos ganhos"
        )

    # H5: high churn
    if exp["churn_ratio"] is not None and exp["churn_ratio"] > 50:
        spin += 1
        alerts.append(f"[H5] Churn alto: {exp['churn_ratio']:.0f} trades por % de PnL")
    elif exp["churn_ratio"] is None and total >= 10:
        spin += 1
        alerts.append("[H5] PnL liquido ~0 com volume de trades significativo")

    # H6: negative edge
    if pf < 1.0:
        spin += 1
        alerts.append(f"[H6] Edge negativo: profit factor {pf:.2f}")

    # --- decision ---
    if win_rate > 55 and pf > 1.5 and expectancy > 0.1 and spin == 0:
        return "promising", alerts

    if spin >= 2:
        return "patinando", alerts

    return "watch", alerts


# ── SYSTEM AUDIT ─────────────────────────────────────────────────────────────

def _audit_system(table: str, days: int, initial_capital: float) -> dict:
    """Full audit for one trading system.

    All derived metrics (expectancy, churn, concentration, total_pnl_usd,
    verdict) are computed from the **same complete set** of closed trades
    returned by get_closed_trades_in_period (no artificial LIMIT).
    get_all_time_stats and get_stats_by_symbol use the same temporal
    window so the report is internally consistent.
    """
    trades = _db().get_closed_trades_in_period(table, days=days)
    by_symbol = _db().get_stats_by_symbol(table, days=days)

    # Compute stats from the same trade list (single source of truth)
    stats = _compute_stats(trades)

    exp = _compute_expectancy(trades, audit_days=days)
    conc = _concentration_check(trades)
    verdict, alerts = _compute_verdict(stats, exp, conc)

    total_pnl_usd = sum(_safe_float(t.get("pnl_usd")) for t in trades)

    return {
        "verdict": verdict,
        "metrics": {
            **stats,
            "total_pnl_usd": round(total_pnl_usd, 2),
            "initial_capital": initial_capital,
        },
        "expectancy": exp,
        "concentration": conc,
        "by_symbol": by_symbol,
        "alerts": alerts,
    }


# ── AI SUMMARY ───────────────────────────────────────────────────────────────

def _audit_ai_global(days: int) -> dict:
    """Read-only global summary of ALL AI decisions (every system)."""
    return _db().get_ai_decisions_summary(days=days)


def _audit_ai_for_system(days: int, system: str) -> dict:
    """Read-only summary of AI decisions filtered to one desk."""
    return _db().get_ai_decisions_summary(days=days, system=system)


# ── SCALPING RESEARCH ────────────────────────────────────────────────────────

def _audit_scalping_research(days: int) -> dict:
    """Leverage existing scalping research functions (read-only)."""
    funnel = _db().get_scalping_funnel_stats(days=days)

    try:
        scorer = _compute_scorer(days=days)
    except Exception:
        scorer = {}

    return {
        "funnel": funnel,
        "outcomes_summary": {
            "labels_considered": scorer.get("labels_considered", 0),
            "summary": scorer.get("summary", {}),
            "top_promising": scorer.get("top_promising", [])[:5],
            "top_avoid": scorer.get("top_avoid", [])[:5],
        },
    }


# ── PORTFOLIO ────────────────────────────────────────────────────────────────

def _portfolio_summary(systems: dict) -> dict:
    """Aggregate portfolio-level metrics."""
    total_trades = 0
    total_pnl_usd = 0.0
    verdicts = {}

    for name, data in systems.items():
        total_trades += data["metrics"]["total_trades"]
        total_pnl_usd += data["metrics"].get("total_pnl_usd", 0)
        verdicts[name] = data["verdict"]

    return {
        "total_trades": total_trades,
        "total_pnl_usd": round(total_pnl_usd, 2),
        "verdicts": verdicts,
        "systems_patinando": sum(1 for v in verdicts.values() if v == "patinando"),
        "systems_promising": sum(1 for v in verdicts.values() if v == "promising"),
    }


# ── RECOMMENDATIONS ─────────────────────────────────────────────────────────

def _generate_recommendations(systems: dict, ai_summary: dict) -> list[str]:
    recs: list[str] = []

    for name, data in systems.items():
        v = data["verdict"]
        if v == "patinando":
            recs.append(
                f"[{name}] Sistema patinando — revisar se vale manter "
                f"ativo ou precisa ajuste de parametros"
            )
        elif v == "insufficient_data":
            recs.append(
                f"[{name}] Dados insuficientes — aguardar mais trades "
                f"antes de concluir"
            )

    ai_total = ai_summary.get("total", 0)
    if ai_total > 0:
        fb_rate = ai_summary["fallbacks"] / ai_total * 100
        if fb_rate > 10:
            recs.append(
                f"[ai] Taxa de fallback alta ({fb_rate:.0f}%) — "
                f"verificar estabilidade da API"
            )
        pf_rate = ai_summary["parse_failures"] / ai_total * 100
        if pf_rate > 5:
            recs.append(
                f"[ai] Taxa de parse failure ({pf_rate:.0f}%) — "
                f"verificar formato do prompt"
            )

    if not recs:
        recs.append("Nenhuma acao urgente identificada")

    return recs


# ── TOP ALERTS ───────────────────────────────────────────────────────────────

def _collect_top_alerts(systems: dict) -> list[dict]:
    all_alerts: list[dict] = []
    for name, data in systems.items():
        for alert in data.get("alerts", []):
            all_alerts.append({
                "system": name, "alert": alert, "verdict": data["verdict"],
            })
    all_alerts.sort(
        key=lambda a: (a["verdict"] != "patinando", a["verdict"] != "watch")
    )
    return all_alerts[:10]


# ── MARKDOWN ─────────────────────────────────────────────────────────────────

def _generate_markdown(report: dict) -> str:
    lines: list[str] = []
    days = report["days"]
    ps = report["portfolio_summary"]

    lines.append("# Strategy Validation Report")
    lines.append("")
    lines.append(f"Gerado em: {report['generated_at']}")
    lines.append(f"Periodo: ultimos {days} dias")
    lines.append(
        f"Runtime: {report['runtime']['bot_id']} "
        f"({report['runtime']['version_tag']})"
    )
    lines.append("")

    # ── executive summary ──
    lines.append("## Resumo Executivo")
    lines.append("")
    lines.append(f"- Total de trades fechados: {ps['total_trades']}")
    lines.append(f"- PnL total: ${ps['total_pnl_usd']:+.2f}")
    lines.append(f"- Sistemas promissores: {ps['systems_promising']}")
    lines.append(f"- Sistemas patinando: {ps['systems_patinando']}")
    lines.append("")
    lines.append("| Sistema | Veredito |")
    lines.append("|---------|----------|")
    for sys_name, verdict in ps["verdicts"].items():
        lines.append(f"| {sys_name} | **{verdict}** |")
    lines.append("")

    # ── global AI summary ──
    ai_g = report.get("ai_summary_global", {})
    if ai_g.get("total", 0) > 0:
        lines.append("## Camada de IA (Global)")
        lines.append("")
        lines.append("| Metrica | Valor |")
        lines.append("|---------|-------|")
        lines.append(f"| Decisoes totais | {ai_g['total']} |")
        lines.append(
            f"| Aprovacoes | {ai_g['approvals']} "
            f"({ai_g['approval_rate']}%) |"
        )
        lines.append(f"| Fallbacks | {ai_g['fallbacks']} |")
        lines.append(f"| Parse failures | {ai_g['parse_failures']} |")
        lines.append(f"| Confianca media | {ai_g['avg_confidence']} |")
        lines.append(f"| Latencia media | {ai_g['avg_latency_ms']}ms |")
        by_sys = ai_g.get("by_system", {})
        if by_sys:
            s_str = ", ".join(f"{k}({v})" for k, v in by_sys.items())
            lines.append(f"| Por sistema | {s_str} |")
        versions = ai_g.get("by_prompt_version", {})
        if versions:
            v_str = ", ".join(f"{k}({v})" for k, v in versions.items())
            lines.append(f"| Versoes de prompt | {v_str} |")
        lines.append("")

    # ── system by system ──
    for sys_name, data in report["systems"].items():
        m = data["metrics"]
        exp = data.get("expectancy", {})

        lines.append(f"## {sys_name.upper()}")
        lines.append("")
        lines.append(f"**Veredito: {data['verdict']}**")
        lines.append("")
        lines.append("| Metrica | Valor |")
        lines.append("|---------|-------|")
        lines.append(f"| Trades | {m['total_trades']} |")
        lines.append(f"| Win Rate | {m['win_rate']}% |")
        lines.append(f"| Avg PnL | {m['avg_pnl_pct']}% |")
        lines.append(f"| PnL Total | ${m.get('total_pnl_usd', 0):+.2f} |")
        lines.append(f"| Profit Factor | {m['profit_factor']} |")
        lines.append(f"| Max Drawdown | {m['max_drawdown_pct']}% |")
        lines.append(f"| Melhor Trade | {m['largest_win']}% |")
        lines.append(f"| Pior Trade | {m['largest_loss']}% |")
        lines.append(f"| Expectancy | {exp.get('expectancy_pct', 0):+.4f}% |")
        lines.append(f"| Avg Win | {exp.get('avg_win_pct', 0):+.4f}% |")
        lines.append(f"| Avg Loss | {exp.get('avg_loss_pct', 0):+.4f}% |")
        lines.append(f"| Trades/dia | {exp.get('trades_per_day', 0)} |")
        cr = exp.get("churn_ratio")
        lines.append(f"| Churn Ratio | {cr if cr is not None else 'inf (PnL ~0)'} |")
        lines.append("")

        # per-symbol
        if data.get("by_symbol"):
            lines.append("**Por simbolo:**")
            lines.append("")
            lines.append(
                "| Simbolo | Trades | Wins | Losses | PnL USD | Avg PnL % |"
            )
            lines.append(
                "|---------|--------|------|--------|---------|-----------|"
            )
            for s in data["by_symbol"]:
                lines.append(
                    f"| {s['symbol']} | {s['trades']} | {s['wins']} "
                    f"| {s['losses']} | ${s['total_pnl']:+.2f} "
                    f"| {s['avg_pnl_pct']}% |"
                )
            lines.append("")

        # AI summary (agent-filtered)
        if sys_name == "agent" and "ai_summary" in data:
            ai = data["ai_summary"]
            lines.append("**Camada de IA (desk agent):**")
            lines.append("")
            lines.append("| Metrica | Valor |")
            lines.append("|---------|-------|")
            lines.append(f"| Decisoes totais | {ai.get('total', 0)} |")
            lines.append(
                f"| Aprovacoes | {ai.get('approvals', 0)} "
                f"({ai.get('approval_rate', 0)}%) |"
            )
            lines.append(f"| Fallbacks | {ai.get('fallbacks', 0)} |")
            lines.append(f"| Parse failures | {ai.get('parse_failures', 0)} |")
            lines.append(f"| Confianca media | {ai.get('avg_confidence', 0)} |")
            lines.append(
                f"| Latencia media | {ai.get('avg_latency_ms', 0)}ms |"
            )
            versions = ai.get("by_prompt_version", {})
            if versions:
                v_str = ", ".join(f"{k}({v})" for k, v in versions.items())
                lines.append(f"| Versoes de prompt | {v_str} |")
            lines.append("")

        # scalping research
        if sys_name == "scalping" and "research" in data:
            research = data["research"]
            funnel = research.get("funnel", {})
            outcomes = research.get("outcomes_summary", {})

            if funnel:
                lines.append("**Funil de decisoes:**")
                lines.append("")
                lines.append(f"- Total de ciclos: {funnel.get('total', 0)}")
                for k, v in funnel.get("breakdown", {}).items():
                    lines.append(f"  - {k}: {v}")
                lines.append("")

            if outcomes.get("top_promising"):
                lines.append("**Setups promissores (top 5):**")
                lines.append("")
                for s in outcomes["top_promising"]:
                    lines.append(
                        f"- {s['setup_key']} — score {s['edge_score']}, "
                        f"WR {s['win_rate']}%, n={s['complete_actionable']}"
                    )
                lines.append("")

            if outcomes.get("top_avoid"):
                lines.append("**Setups para evitar (top 5):**")
                lines.append("")
                for s in outcomes["top_avoid"]:
                    lines.append(
                        f"- {s['setup_key']} — score {s['edge_score']}, "
                        f"WR {s['win_rate']}%, n={s['complete_actionable']}"
                    )
                lines.append("")

        # alerts
        if data.get("alerts"):
            lines.append("**Alertas:**")
            lines.append("")
            for alert in data["alerts"]:
                lines.append(f"- {alert}")
            lines.append("")

    # ── edge signals ──
    lines.append("## Sinais de Edge")
    lines.append("")
    promising = [
        n for n, d in report["systems"].items() if d["verdict"] == "promising"
    ]
    if promising:
        for n in promising:
            m = report["systems"][n]["metrics"]
            lines.append(
                f"- **{n}**: WR {m['win_rate']}%, PF {m['profit_factor']}, "
                f"PnL ${m.get('total_pnl_usd', 0):+.2f}"
            )
    else:
        lines.append("- Nenhum sistema com edge claro no periodo")
    lines.append("")

    # ── spinning signals ──
    lines.append("## Sinais de Patinacao")
    lines.append("")
    patinando = [
        n for n, d in report["systems"].items() if d["verdict"] == "patinando"
    ]
    if patinando:
        for n in patinando:
            al = report["systems"][n]["alerts"]
            lines.append(f"- **{n}**: {'; '.join(al[:3])}")
    else:
        lines.append("- Nenhum sistema classificado como patinando")
    lines.append("")

    # ── recommendations ──
    lines.append("## Proximos Passos Sugeridos")
    lines.append("")
    for rec in report.get("recommendations", []):
        lines.append(f"- {rec}")
    lines.append("")

    return "\n".join(lines)


# ── MAIN RUNNER ──────────────────────────────────────────────────────────────

def run_audit(days: int = 30, output_dir: str | None = None) -> dict:
    """Run the full validation audit.  Returns report + file paths.

    This is a read-only tool: it never creates tables, alters schema, or
    writes to the database.

    Raises:
        FileNotFoundError: if the database file does not exist.
    """
    if not Path(DB_FILE).exists():
        raise FileNotFoundError(
            f"Banco nao encontrado em {DB_FILE}. "
            f"O bot precisa ter rodado pelo menos uma vez."
        )

    if output_dir is None:
        output_dir = str(RUNTIME_DIR)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # audit each system
    systems = {}
    for name, cfg in SYSTEMS.items():
        systems[name] = _audit_system(cfg["table"], days, cfg["initial_capital"])

    # AI summaries: global (all desks) + agent-only
    ai_summary_global = _audit_ai_global(days)
    ai_summary_agent = _audit_ai_for_system(days, system="agent")
    systems["agent"]["ai_summary"] = ai_summary_agent

    # scalping research (attach to scalping)
    systems["scalping"]["research"] = _audit_scalping_research(days)

    # portfolio
    portfolio = _portfolio_summary(systems)

    # recommendations (use global AI summary for cross-system alerts)
    recommendations = _generate_recommendations(systems, ai_summary_global)

    # top alerts
    top_alerts = _collect_top_alerts(systems)

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "days": days,
        "runtime": {"bot_id": BOT_ID, "version_tag": VERSION_TAG},
        "systems": systems,
        "ai_summary_global": ai_summary_global,
        "portfolio_summary": portfolio,
        "top_alerts": top_alerts,
        "recommendations": recommendations,
    }

    # save JSON
    json_path = str(Path(output_dir) / "strategy_validation_report.json")
    Path(json_path).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    # save Markdown
    md_content = _generate_markdown(report)
    md_path = str(Path(output_dir) / "strategy_validation_report.md")
    Path(md_path).write_text(md_content, encoding="utf-8")

    return {"report": report, "files": {"json": json_path, "md": md_path}}


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Offline Validation Auditor")
    parser.add_argument(
        "--days", type=int, default=30,
        help="Periodo em dias (default: 30)",
    )
    parser.add_argument(
        "--stdout", action="store_true",
        help="Imprimir Markdown no stdout",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Diretorio de saida (default: runtime/<bot_id>)",
    )
    args = parser.parse_args()

    try:
        result = run_audit(days=args.days, output_dir=args.output_dir)
    except FileNotFoundError as exc:
        print(f"  [AUDITOR] {exc}")
        sys.exit(1)

    report = result["report"]

    print(f"Audit concluido: {report['generated_at']}")
    print(f"Periodo: {args.days} dias")
    print()

    for name, data in report["systems"].items():
        m = data["metrics"]
        print(
            f"  {name:10s} | {data['verdict']:18s} | "
            f"trades={m['total_trades']:4d} | "
            f"WR={m['win_rate']:5.1f}% | "
            f"PF={m['profit_factor']:5.2f} | "
            f"PnL=${m.get('total_pnl_usd', 0):+8.2f}"
        )

    print()
    print(f"JSON: {result['files']['json']}")
    print(f"MD:   {result['files']['md']}")

    if args.stdout:
        print()
        print("=" * 60)
        print(_generate_markdown(report))


if __name__ == "__main__":
    main()
