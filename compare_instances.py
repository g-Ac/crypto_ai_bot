"""
Compara duas instancias do bot a partir dos runtimes isolados.

Uso:
    python compare_instances.py
    python compare_instances.py --left baseline --right v2 --format json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from config import PAPER_INITIAL_CAPITAL, AGENT_INITIAL_CAPITAL, PUMP_INITIAL_CAPITAL, SCALPING_INITIAL_CAPITAL
SYSTEM_ORDER = ["paper", "agent", "pump", "scalping"]
TRADE_TABLES = {
    "paper": "paper_trades",
    "agent": "agent_trades",
    "pump": "pump_trades",
}
STATE_FILES = {
    "paper": "paper_state.json",
    "agent": "agent_state.json",
    "pump": "pump_positions.json",
    "scalping": "scalping_state.json",
}
INITIAL_CAPITALS = {
    "paper": float(PAPER_INITIAL_CAPITAL),
    "agent": float(AGENT_INITIAL_CAPITAL),
    "pump": float(PUMP_INITIAL_CAPITAL),
    "scalping": float(SCALPING_INITIAL_CAPITAL),
}


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _query_rows(db_path: Path, query: str, params: tuple = ()) -> list[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def _calc_trade_stats(rows: list[dict]) -> dict:
    if not rows:
        return {"count": 0, "wins": 0, "losses": 0, "pnl_usd": 0.0, "pnl_pct": 0.0}

    pnl_usd = 0.0
    pnl_pct = 0.0
    wins = 0
    losses = 0
    for row in rows:
        row_pnl_usd = float(row.get("pnl_usd") or 0)
        row_pnl_pct = float(row.get("pnl_pct") or 0)
        pnl_usd += row_pnl_usd
        pnl_pct += row_pnl_pct
        if row_pnl_pct > 0:
            wins += 1
        elif row_pnl_pct < 0:
            losses += 1
    return {
        "count": len(rows),
        "wins": wins,
        "losses": losses,
        "pnl_usd": round(pnl_usd, 2),
        "pnl_pct": round(pnl_pct, 2),
    }


def _today_prefix() -> str:
    return date.today().isoformat()


def _get_today_trade_rows(db_path: Path, table: str) -> list[dict]:
    return _query_rows(
        db_path,
        f"SELECT * FROM {table} WHERE timestamp LIKE ?",
        (f"{_today_prefix()}%",),
    )


def _get_scalping_today_rows(runtime_dir: Path) -> list[dict]:
    state = _load_json(runtime_dir / STATE_FILES["scalping"], {})
    history = state.get("history", [])
    return [
        row for row in history
        if str(row.get("timestamp", "")).startswith(_today_prefix())
    ]


def _resolve_initial_capitals(manifest: dict) -> dict:
    manifest_initials = manifest.get("initial_capitals", {})
    resolved = {}
    for system in SYSTEM_ORDER:
        resolved[system] = float(manifest_initials.get(system, INITIAL_CAPITALS[system]))
    return resolved


def _get_capitals(runtime_dir: Path, initial_capitals: dict) -> dict:
    capitals = {}
    for system in SYSTEM_ORDER:
        state = _load_json(runtime_dir / STATE_FILES[system], {})
        capitals[system] = round(float(state.get("capital", initial_capitals[system])), 2)
    return capitals


def _get_scalping_funnel(db_path: Path, days: int) -> dict:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    breakdown_rows = _query_rows(
        db_path,
        """
        SELECT outcome, COUNT(*) AS count
        FROM scalping_decisions
        WHERE timestamp >= ?
        GROUP BY outcome
        ORDER BY outcome
        """,
        (cutoff,),
    )
    reason_rows = _query_rows(
        db_path,
        """
        SELECT outcome, reason, COUNT(*) AS count
        FROM scalping_decisions
        WHERE timestamp >= ? AND outcome != 'opened'
        GROUP BY outcome, reason
        ORDER BY count DESC, outcome ASC
        LIMIT 5
        """,
        (cutoff,),
    )
    breakdown = {row["outcome"]: int(row["count"]) for row in breakdown_rows}
    return {
        "total": sum(breakdown.values()),
        "breakdown": breakdown,
        "top_reasons": [
            {
                "outcome": row["outcome"],
                "reason": row["reason"],
                "count": int(row["count"]),
            }
            for row in reason_rows
        ],
    }


def _get_trade_table_counts(db_path: Path) -> dict:
    counts = {}
    for system, table in TRADE_TABLES.items():
        rows = _query_rows(db_path, f"SELECT COUNT(*) AS count FROM {table}")
        counts[system] = int(rows[0]["count"]) if rows else 0
    return counts


def _portfolio_value(capitals: dict) -> float:
    return round(sum(float(capitals.get(system, 0)) for system in SYSTEM_ORDER), 2)


def _portfolio_return(capitals: dict, initial_capitals: dict) -> float:
    initial = sum(initial_capitals.values())
    return round((_portfolio_value(capitals) - initial) / initial * 100, 2) if initial else 0.0


def build_snapshot(runtime_dir: Path, days: int) -> dict:
    manifest = _load_json(runtime_dir / "runtime_manifest.json", {})
    db_path = runtime_dir / "bot.db"
    initial_capitals = _resolve_initial_capitals(manifest)
    capitals = _get_capitals(runtime_dir, initial_capitals)
    today_stats = {}

    for system, table in TRADE_TABLES.items():
        today_stats[system] = _calc_trade_stats(_get_today_trade_rows(db_path, table))
    today_stats["scalping"] = _calc_trade_stats(_get_scalping_today_rows(runtime_dir))

    return {
        "identity": {
            "bot_id": manifest.get("bot_id", runtime_dir.name),
            "label": manifest.get("label", runtime_dir.name.upper()),
            "version_tag": manifest.get("version_tag", "unknown"),
            "git_sha": manifest.get("git_sha", "unknown"),
            "git_branch": manifest.get("git_branch", "unknown"),
            "git_commit_date": manifest.get("git_commit_date", "unknown"),
            "runtime_dir": str(runtime_dir),
            "written_at": manifest.get("written_at", "unknown"),
        },
        "capitals": capitals,
        "initial_capitals": initial_capitals,
        "portfolio": {
            "value": _portfolio_value(capitals),
            "ret_pct": _portfolio_return(capitals, initial_capitals),
        },
        "today": today_stats,
        "trade_table_counts": _get_trade_table_counts(db_path),
        "scalping_funnel": _get_scalping_funnel(db_path, days),
        "artifacts": {
            "db_exists": db_path.exists(),
            "manifest_exists": (runtime_dir / "runtime_manifest.json").exists(),
            "logs_dir_exists": (runtime_dir / "logs").exists(),
        },
    }


def _delta(right_value: float, left_value: float, digits: int = 2) -> float:
    return round(float(right_value) - float(left_value), digits)


def compare_snapshots(left: dict, right: dict) -> dict:
    comparison = {
        "generated_at": datetime.now().isoformat(),
        "left": left,
        "right": right,
        "delta": {
            "portfolio_value": _delta(right["portfolio"]["value"], left["portfolio"]["value"]),
            "portfolio_ret_pct": _delta(right["portfolio"]["ret_pct"], left["portfolio"]["ret_pct"]),
            "capitals": {},
            "today": {},
            "scalping_funnel": {},
        },
    }

    for system in SYSTEM_ORDER:
        comparison["delta"]["capitals"][system] = _delta(
            right["capitals"].get(system, 0),
            left["capitals"].get(system, 0),
        )
        comparison["delta"]["today"][system] = {
            "count": _delta(right["today"][system]["count"], left["today"][system]["count"], 0),
            "pnl_usd": _delta(right["today"][system]["pnl_usd"], left["today"][system]["pnl_usd"]),
            "pnl_pct": _delta(right["today"][system]["pnl_pct"], left["today"][system]["pnl_pct"]),
        }

    funnel_keys = sorted({
        *left["scalping_funnel"]["breakdown"].keys(),
        *right["scalping_funnel"]["breakdown"].keys(),
    })
    for key in funnel_keys:
        comparison["delta"]["scalping_funnel"][key] = _delta(
            right["scalping_funnel"]["breakdown"].get(key, 0),
            left["scalping_funnel"]["breakdown"].get(key, 0),
            0,
        )

    return comparison


def _fmt_number(value) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def render_markdown(report: dict) -> str:
    left = report["left"]
    right = report["right"]

    lines = [
        "# Comparacao de Instancias",
        "",
        f"Gerado em: `{report['generated_at']}`",
        f"Comparando `{left['identity']['bot_id']}` vs `{right['identity']['bot_id']}`",
        "",
        "## Identidade",
        "",
        "| Campo | Esquerda | Direita |",
        "|---|---:|---:|",
        f"| bot_id | {left['identity']['bot_id']} | {right['identity']['bot_id']} |",
        f"| version_tag | {left['identity']['version_tag']} | {right['identity']['version_tag']} |",
        f"| git_sha | {left['identity']['git_sha']} | {right['identity']['git_sha']} |",
        f"| branch | {left['identity']['git_branch']} | {right['identity']['git_branch']} |",
        "",
        "## Portfolio",
        "",
        "| Metrica | Esquerda | Direita | Delta (direita-esquerda) |",
        "|---|---:|---:|---:|",
        f"| Valor | {left['portfolio']['value']:.2f} | {right['portfolio']['value']:.2f} | {report['delta']['portfolio_value']:.2f} |",
        f"| Retorno % | {left['portfolio']['ret_pct']:.2f} | {right['portfolio']['ret_pct']:.2f} | {report['delta']['portfolio_ret_pct']:.2f} |",
        "",
        "## Capital por Sistema",
        "",
        "| Sistema | Esquerda | Direita | Delta |",
        "|---|---:|---:|---:|",
    ]

    for system in SYSTEM_ORDER:
        lines.append(
            f"| {system} | {left['capitals'][system]:.2f} | {right['capitals'][system]:.2f} | "
            f"{report['delta']['capitals'][system]:.2f} |"
        )

    lines.extend([
        "",
        "## Hoje",
        "",
        "| Sistema | Trades Esq | Trades Dir | Delta Trades | PnL USD Esq | PnL USD Dir | Delta USD |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])

    for system in SYSTEM_ORDER:
        left_today = left["today"][system]
        right_today = right["today"][system]
        delta_today = report["delta"]["today"][system]
        lines.append(
            f"| {system} | {left_today['count']} | {right_today['count']} | {int(delta_today['count'])} | "
            f"{left_today['pnl_usd']:.2f} | {right_today['pnl_usd']:.2f} | {delta_today['pnl_usd']:.2f} |"
        )

    funnel_keys = sorted({
        *left["scalping_funnel"]["breakdown"].keys(),
        *right["scalping_funnel"]["breakdown"].keys(),
    })
    lines.extend([
        "",
        "## Funil do Scalping",
        "",
        "| Outcome | Esquerda | Direita | Delta |",
        "|---|---:|---:|---:|",
    ])
    for key in funnel_keys:
        lines.append(
            f"| {key} | {left['scalping_funnel']['breakdown'].get(key, 0)} | "
            f"{right['scalping_funnel']['breakdown'].get(key, 0)} | "
            f"{int(report['delta']['scalping_funnel'].get(key, 0))} |"
        )

    if left["scalping_funnel"]["top_reasons"] or right["scalping_funnel"]["top_reasons"]:
        lines.extend(["", "## Top Motivos de Bloqueio", ""])
        if left["scalping_funnel"]["top_reasons"]:
            lines.append(f"Esquerda `{left['identity']['bot_id']}`:")
            for item in left["scalping_funnel"]["top_reasons"]:
                lines.append(f"- {item['outcome']}: {item['reason']} ({item['count']})")
            lines.append("")
        if right["scalping_funnel"]["top_reasons"]:
            lines.append(f"Direita `{right['identity']['bot_id']}`:")
            for item in right["scalping_funnel"]["top_reasons"]:
                lines.append(f"- {item['outcome']}: {item['reason']} ({item['count']})")

    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compara dois runtimes do bot.")
    parser.add_argument("--runtime-base-dir", default="runtime", help="Diretorio base dos runtimes")
    parser.add_argument("--left", default="baseline", help="Nome da instancia esquerda")
    parser.add_argument("--right", default="v2", help="Nome da instancia direita")
    parser.add_argument("--days", type=int, default=1, help="Janela de dias para o funil do scalping")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", default="", help="Arquivo opcional para salvar o resultado")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runtime_base_dir = Path(args.runtime_base_dir)
    left_dir = runtime_base_dir / args.left
    right_dir = runtime_base_dir / args.right

    if not left_dir.exists():
        raise SystemExit(f"Runtime nao encontrado: {left_dir}")
    if not right_dir.exists():
        raise SystemExit(f"Runtime nao encontrado: {right_dir}")

    report = compare_snapshots(
        build_snapshot(left_dir, args.days),
        build_snapshot(right_dir, args.days),
    )

    if args.format == "json":
        output = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    else:
        output = render_markdown(report)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
