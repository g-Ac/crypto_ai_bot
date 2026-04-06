"""
Offline Trade Review Lab.

Revisa um trade individual com profundidade, montando contexto real
do banco e gerando revisao estruturada (JSON + Markdown).

Usage:
    python trade_review_lab.py --system agent --trade-id 123
    python trade_review_lab.py --system scalping --trade-id 456 --stdout
    python trade_review_lab.py --system pump --latest 1
    python trade_review_lab.py --system agent --symbol BTCUSDT --latest 1
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


# ── LOCAL RUNTIME RESOLUTION (side-effect-free) ─────────────────────────────
_APP_DIR = Path(__file__).resolve().parent


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
    return normalized.strip("-._").lower() or "baseline"


BOT_ID = _slugify(os.getenv("BOT_ID", "baseline"))
_RUNTIME_BASE = Path(os.getenv("BOT_RUNTIME_BASE_DIR", str(_APP_DIR / "runtime")))
RUNTIME_DIR = _RUNTIME_BASE / BOT_ID
DB_FILE = str(RUNTIME_DIR / "bot.db")


# ── LAZY IMPORTS ──────────────────────────────────────────────────────────────
_db_module = None


def _db():
    """Return the database module (imported lazily on first call)."""
    global _db_module
    if _db_module is None:
        import database
        _db_module = database
    return _db_module


# ── SYSTEM CONFIG ─────────────────────────────────────────────────────────────
SYSTEM_TABLES = {
    "paper": "paper_trades",
    "agent": "agent_trades",
    "pump": "pump_trades",
    "scalping": "scalping_trades",
}


# ── NORMALIZATION ─────────────────────────────────────────────────────────────

_VALID_CLASSIFICATIONS = frozenset({
    "good_trade_good_outcome",
    "good_trade_bad_outcome",
    "bad_trade_good_outcome",
    "bad_trade_bad_outcome",
    "unclear",
})

_VALID_CF_RESULTS = frozenset({"better", "same", "worse", "unclear"})

_MAX_LIST_LEN = 5


def _ensure_str_list(val, max_len: int = _MAX_LIST_LEN) -> list[str]:
    """Coerce a value to a list of strings, truncated."""
    if isinstance(val, str):
        return [val][:max_len]
    if isinstance(val, list):
        return [str(item) for item in val if item is not None][:max_len]
    return []


def _normalize_counterfactual(item) -> dict | None:
    """Normalize a single counterfactual entry. Returns None if unusable."""
    if not isinstance(item, dict):
        return None
    raw_plausible = item.get("plausible_at_the_time")
    if isinstance(raw_plausible, str):
        plausible = raw_plausible.lower() in ("true", "yes", "1")
    else:
        plausible = bool(raw_plausible) if raw_plausible is not None else False
    est_result = item.get("estimated_result", "unclear")
    if est_result not in _VALID_CF_RESULTS:
        est_result = "unclear"
    return {
        "scenario": str(item.get("scenario", "unclear")),
        "plausible_at_the_time": plausible,
        "estimated_result": est_result,
        "reason": str(item.get("reason", "")),
    }


def _normalize_trade_review(raw, context: dict) -> dict:
    """Normalize Claude's raw review into a consistent shape.

    Accepts any JSON-parsed value (dict, list, str, int, None).
    Non-dict inputs are converted to an empty dict so defaults apply.

    Fills defaults, validates types, truncates lists, and overwrites
    trade_identity with the actual trade data from context.
    """
    if not isinstance(raw, dict):
        raw = {}

    trade = context["target_trade"]
    system = context["system"]

    # trade_identity: always from real trade, never from Claude
    identity = {
        "system": system,
        "trade_id": trade.get("id"),
        "symbol": trade.get("symbol", "?"),
        "timestamp": trade.get("timestamp", "?"),
    }

    # classification
    classification = raw.get("classification", "unclear")
    if classification not in _VALID_CLASSIFICATIONS:
        classification = "unclear"

    # counterfactuals
    raw_cfs = raw.get("counterfactuals", [])
    if not isinstance(raw_cfs, list):
        raw_cfs = []
    counterfactuals = []
    for item in raw_cfs[:_MAX_LIST_LEN]:
        normalized = _normalize_counterfactual(item)
        if normalized:
            counterfactuals.append(normalized)

    # lesson
    lesson = raw.get("lesson", "")
    if not isinstance(lesson, str):
        lesson = str(lesson) if lesson is not None else ""

    # tags: handle string input
    raw_tags = raw.get("tags", [])
    if isinstance(raw_tags, str):
        raw_tags = [t.strip() for t in re.split(r"[,\s]+", raw_tags) if t.strip()]
    tags = _ensure_str_list(raw_tags)

    return {
        "trade_identity": identity,
        "classification": classification,
        "root_causes": _ensure_str_list(raw.get("root_causes", [])),
        "things_done_well": _ensure_str_list(raw.get("things_done_well", [])),
        "mistakes": _ensure_str_list(raw.get("mistakes", [])),
        "counterfactuals": counterfactuals,
        "lesson": lesson,
        "tags": tags,
    }


# ── TRADE LOOKUP ──────────────────────────────────────────────────────────────

def _find_trade(system: str, trade_id: int | None = None,
                symbol: str | None = None, latest: int = 0) -> dict | None:
    """Find a closed trade by ID or latest.

    The Trade Review Lab only reviews closed trades (exit_reason present).
    - --trade-id: fetches by ID, raises ValueError if the trade is still open.
    - --latest: searches among closed trades only.
    """
    table = SYSTEM_TABLES[system]

    if trade_id is not None:
        trade = _db().get_closed_trade_by_id(table, trade_id)
        if trade is None:
            # Distinguish "not found" from "found but open"
            raw = _db().get_trade_by_id(table, trade_id)
            if raw is not None:
                er = raw.get("exit_reason", "")
                raise ValueError(
                    f"Trade #{trade_id} em {system} ainda esta aberto "
                    f"(exit_reason={er!r}). O Trade Review Lab revisa "
                    f"apenas trades fechados."
                )
        return trade

    if latest > 0:
        if symbol:
            trades = _db().get_recent_closed_trades_by_symbol(
                table, symbol.upper(), limit=latest,
            )
        else:
            trades = _db().get_recent_closed_trades(table, limit=latest)
        idx = latest - 1
        return trades[idx] if idx < len(trades) else None

    return None


# ── CONTEXT COLLECTION ────────────────────────────────────────────────────────

def _collect_context(system: str, trade: dict) -> dict:
    """Build a rich context package around the target trade."""
    table = SYSTEM_TABLES[system]
    trade_ts = trade.get("timestamp", "")
    trade_symbol = trade.get("symbol", "")

    context: dict = {
        "target_trade": trade,
        "system": system,
        "table": table,
    }

    # Recent trades from the same system (last 20)
    try:
        recent = _db().get_recent_trades(table, limit=20)
        context["recent_system_trades"] = recent
    except Exception:
        context["recent_system_trades"] = []

    # Recent trades for the same symbol in same system
    try:
        context["recent_symbol_trades"] = _db().get_recent_trades_by_symbol(
            table, trade_symbol, limit=10,
        )
    except Exception:
        context["recent_symbol_trades"] = [
            t for t in context["recent_system_trades"]
            if t.get("symbol") == trade_symbol
        ][:10]

    # Performance stats for this symbol (30d)
    try:
        by_symbol = _db().get_stats_by_symbol(table, days=30)
        context["symbol_performance_30d"] = next(
            (s for s in by_symbol if s.get("symbol") == trade_symbol), None
        )
    except Exception:
        context["symbol_performance_30d"] = None

    # System-level stats (30d)
    try:
        context["system_stats_30d"] = _db().get_all_time_stats(table, days=30)
    except Exception:
        context["system_stats_30d"] = None

    # Enrichment: ai_decisions near the trade (for agent system)
    if system == "agent" and trade_ts:
        try:
            context["nearby_ai_decisions"] = _db().get_nearby_ai_decisions(
                trade_ts, symbol=trade_symbol, system=system,
                window_minutes=30, limit=10,
            )
        except Exception:
            context["nearby_ai_decisions"] = []

    # Enrichment: analysis_log near the trade
    if trade_ts:
        try:
            context["nearby_analysis_log"] = _db().get_nearby_records(
                "analysis_log", trade_ts, symbol=trade_symbol,
                window_minutes=30, limit=10,
            )
        except Exception:
            context["nearby_analysis_log"] = []

    # Enrichment: alerts near the trade
    if trade_ts:
        try:
            context["nearby_alerts"] = _db().get_nearby_records(
                "alerts", trade_ts, symbol=trade_symbol,
                window_minutes=60, limit=10,
            )
        except Exception:
            context["nearby_alerts"] = []

    # Enrichment: scalping-specific context
    if system == "scalping" and trade_ts:
        try:
            context["nearby_scalping_audit"] = _db().get_nearby_records(
                "scalping_audit_log", trade_ts, symbol=trade_symbol,
                window_minutes=30, limit=10,
            )
        except Exception:
            context["nearby_scalping_audit"] = []

        try:
            context["nearby_scalping_outcome_labels"] = _db().get_nearby_records(
                "scalping_outcome_labels", trade_ts, symbol=trade_symbol,
                window_minutes=60, limit=10,
                timestamp_col="audit_timestamp",
            )
        except Exception:
            context["nearby_scalping_outcome_labels"] = []

    return context


# ── REVIEW PROMPT ─────────────────────────────────────────────────────────────

def _format_context_section(title: str, data, max_items: int = 5) -> str:
    """Format a context section as Markdown with JSON."""
    if not data:
        return f"## {title}\n\nNenhum dado encontrado."
    if isinstance(data, list):
        data = data[:max_items]
    payload = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    return f"## {title}\n\n```json\n{payload}\n```"


def _build_trade_review_prompt(context: dict) -> str:
    """Build a strong anti-hindsight review prompt for Claude."""
    trade = context["target_trade"]
    system = context["system"]

    trade_json = json.dumps(trade, ensure_ascii=False, indent=2, default=str)

    sections = [
        f"## Trade Alvo\n\nSistema: {system}\n\n```json\n{trade_json}\n```",
    ]

    sections.append(_format_context_section(
        f"Trades Recentes do Mesmo Simbolo ({trade.get('symbol', '?')})",
        context.get("recent_symbol_trades"),
    ))
    sections.append(_format_context_section(
        "Performance do Simbolo (30 dias)",
        context.get("symbol_performance_30d"),
    ))
    sections.append(_format_context_section(
        "Stats do Sistema (30 dias)",
        context.get("system_stats_30d"),
    ))

    if context.get("nearby_ai_decisions"):
        sections.append(_format_context_section(
            "Decisoes de IA Proximas", context["nearby_ai_decisions"],
        ))

    if context.get("nearby_analysis_log"):
        sections.append(_format_context_section(
            "Analysis Log Proximo", context["nearby_analysis_log"],
        ))

    if context.get("nearby_alerts"):
        sections.append(_format_context_section(
            "Alertas Proximos", context["nearby_alerts"],
        ))

    if context.get("nearby_scalping_audit"):
        sections.append(_format_context_section(
            "Scalping Audit Log Proximo", context["nearby_scalping_audit"],
        ))

    if context.get("nearby_scalping_outcome_labels"):
        sections.append(_format_context_section(
            "Scalping Outcome Labels Proximos",
            context["nearby_scalping_outcome_labels"],
        ))

    context_block = "\n\n".join(sections)

    trade_id_val = trade.get("id", "null")
    symbol_val = trade.get("symbol", "?")
    ts_val = trade.get("timestamp", "?")

    prompt = f"""Voce e um revisor de trades de um desk de cripto automatizado. Sua funcao e revisar este trade com rigor e honestidade.

# REGRAS ABSOLUTAS

1. SEPARAR fatos observaveis no momento do trade vs leitura posterior com informacao futura.
2. NAO sugerir decisoes que seriam impossiveis sem informacao futura (hindsight magica).
3. NAO dizer "deveria ter esperado X subir" se nao havia sinal observavel de X na hora.
4. DIFERENCIAR claramente:
   - Boa ideia com mau resultado (trade correto que deu errado por azar ou volatilidade)
   - Ma ideia com bom resultado (trade ruim que deu certo por sorte)
   - Boa execucao (entrada, sizing, invalidacao corretas)
   - Execucao ruim (entrada tardia, sizing errado, invalidacao fraca)
   - Contexto ruim (mercado adverso, liquidez baixa)
   - Invalidacao fraca (SL mal posicionado, sem referencia tecnica)
   - Entrada tardia (sinais ja tinham passado)
5. Se faltar informacao para concluir algo, dizer "unclear" em vez de inventar.
6. Manter listas curtas e objetivas (3-5 itens no maximo por lista).
7. A licao deve ser uma frase curta e reutilizavel.

# CONTEXTO DO TRADE

{context_block}

# FORMATO DE RESPOSTA

Responda EXCLUSIVAMENTE com JSON valido, sem texto antes ou depois. Use este formato:

{{
  "trade_identity": {{
    "system": "{system}",
    "trade_id": {trade_id_val},
    "symbol": "{symbol_val}",
    "timestamp": "{ts_val}"
  }},
  "classification": "good_trade_good_outcome|good_trade_bad_outcome|bad_trade_good_outcome|bad_trade_bad_outcome|unclear",
  "root_causes": ["causa 1", "causa 2"],
  "things_done_well": ["acerto 1", "acerto 2"],
  "mistakes": ["erro 1"],
  "counterfactuals": [
    {{
      "scenario": "skip_trade|wait_confirmation|smaller_size|tighter_invalidation|wider_invalidation|exit_earlier|hold_longer",
      "plausible_at_the_time": true,
      "estimated_result": "better|same|worse|unclear",
      "reason": "explicacao curta"
    }}
  ],
  "lesson": "frase curta e reutilizavel",
  "tags": ["late_entry", "weak_invalidation", "good_rr", "bad_context", "correct_thesis", "wrong_timing"]
}}

IMPORTANTE: Responda apenas com o JSON. Sem markdown, sem comentarios, sem texto adicional."""

    return prompt


# ── CLAUDE INTEGRATION ────────────────────────────────────────────────────────

def _call_claude(prompt: str) -> dict | None:
    """Call Claude for qualitative review. Returns parsed JSON or None."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()

        # Handle case where Claude wraps in ```json ... ```
        if text.startswith("```"):
            lines = text.split("\n")
            json_lines = []
            inside = False
            for line in lines:
                if line.startswith("```") and not inside:
                    inside = True
                    continue
                elif line.startswith("```") and inside:
                    break
                elif inside:
                    json_lines.append(line)
            text = "\n".join(json_lines)

        return json.loads(text)
    except Exception as exc:
        print(f"  [REVIEW] Claude call failed: {exc}")
        return None


# ── OUTPUT GENERATION ─────────────────────────────────────────────────────────

def _generate_review_markdown(review: dict, trade: dict) -> str:
    """Generate a concise Markdown review from structured JSON."""
    lines: list[str] = []

    lines.append("# Trade Review")
    lines.append("")

    # Identity
    identity = review.get("trade_identity", {})
    lines.append("## Identidade")
    lines.append("")
    lines.append(f"- Sistema: {identity.get('system', '?')}")
    lines.append(f"- Trade ID: {identity.get('trade_id', '?')}")
    lines.append(f"- Simbolo: {identity.get('symbol', '?')}")
    lines.append(f"- Timestamp: {identity.get('timestamp', '?')}")
    lines.append(f"- Tipo: {trade.get('type', '?')}")
    lines.append(f"- Entrada: {trade.get('entry_price', '?')}")
    lines.append(f"- Saida: {trade.get('exit_price', '?')}")
    pnl_pct = trade.get("pnl_pct", "?")
    pnl_usd = trade.get("pnl_usd", "?")
    lines.append(f"- PnL: {pnl_pct}% (${pnl_usd})")
    lines.append(f"- Exit Reason: {trade.get('exit_reason', '?')}")
    lines.append("")

    # Classification
    lines.append("## Classificacao")
    lines.append("")
    lines.append(f"**{review.get('classification', 'unclear')}**")
    lines.append("")

    # What was visible at the time
    causes = review.get("root_causes", [])
    if causes:
        lines.append("## Causas Provaveis")
        lines.append("")
        for c in causes:
            lines.append(f"- {c}")
        lines.append("")

    # Things done well
    good = review.get("things_done_well", [])
    if good:
        lines.append("## Acertos")
        lines.append("")
        for g in good:
            lines.append(f"- {g}")
        lines.append("")

    # Mistakes
    mistakes = review.get("mistakes", [])
    if mistakes:
        lines.append("## Erros")
        lines.append("")
        for m in mistakes:
            lines.append(f"- {m}")
        lines.append("")

    # Counterfactuals
    cfs = review.get("counterfactuals", [])
    if cfs:
        lines.append("## Contra-Factuais Plausiveis")
        lines.append("")
        for cf in cfs:
            plausible = "sim" if cf.get("plausible_at_the_time") else "nao"
            lines.append(
                f"- **{cf.get('scenario', '?')}**: resultado estimado = "
                f"{cf.get('estimated_result', '?')} "
                f"(plausivel na hora: {plausible})"
            )
            if cf.get("reason"):
                lines.append(f"  - {cf['reason']}")
        lines.append("")

    # Lesson
    lesson = review.get("lesson", "")
    if lesson:
        lines.append("## Licao")
        lines.append("")
        lines.append(f"> {lesson}")
        lines.append("")

    # Tags
    tags = review.get("tags", [])
    if tags:
        lines.append("## Tags")
        lines.append("")
        lines.append(f"`{'` `'.join(tags)}`")
        lines.append("")

    return "\n".join(lines)


def _save_outputs(context: dict, prompt: str, review: dict | None,
                  output_dir: str) -> dict:
    """Save all output files and return paths."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}

    # Always save context
    ctx_path = str(Path(output_dir) / "trade_review_context.json")
    serializable = json.loads(json.dumps(context, ensure_ascii=False, default=str))
    Path(ctx_path).write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    files["context_json"] = ctx_path

    # Always save prompt
    prompt_path = str(Path(output_dir) / "trade_review_prompt.md")
    Path(prompt_path).write_text(prompt, encoding="utf-8")
    files["prompt_md"] = prompt_path

    trade = context["target_trade"]

    if review:
        # Full review from Claude
        report_json_path = str(Path(output_dir) / "trade_review_report.json")
        Path(report_json_path).write_text(
            json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        files["report_json"] = report_json_path

        report_md_path = str(Path(output_dir) / "trade_review_report.md")
        md_content = _generate_review_markdown(review, trade)
        Path(report_md_path).write_text(md_content, encoding="utf-8")
        files["report_md"] = report_md_path
    else:
        # Stub when Claude is not available
        stub = {
            "status": "context_only",
            "reason": "Claude not available or call failed",
            "trade_identity": {
                "system": context.get("system", "?"),
                "trade_id": trade.get("id"),
                "symbol": trade.get("symbol", "?"),
                "timestamp": trade.get("timestamp", "?"),
            },
        }
        stub_path = str(Path(output_dir) / "trade_review_report.json")
        Path(stub_path).write_text(
            json.dumps(stub, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        files["report_json_stub"] = stub_path

    return files


# ── MAIN RUNNER ───────────────────────────────────────────────────────────────

def run_review(system: str, trade_id: int | None = None,
               symbol: str | None = None, latest: int = 0,
               use_claude: bool = True) -> dict:
    """Run a trade review. Returns result dict with files and review.

    Raises:
        FileNotFoundError: if the database file does not exist.
        ValueError: if the trade is not found or system is invalid.
    """
    if not Path(DB_FILE).exists():
        raise FileNotFoundError(
            f"Banco nao encontrado em {DB_FILE}. "
            f"O bot precisa ter rodado pelo menos uma vez."
        )

    if system not in SYSTEM_TABLES:
        raise ValueError(
            f"Sistema invalido: {system}. "
            f"Use: {list(SYSTEM_TABLES.keys())}"
        )

    # Find the trade
    trade = _find_trade(system, trade_id=trade_id, symbol=symbol, latest=latest)
    if not trade:
        raise ValueError(
            f"Trade nao encontrado. system={system}, trade_id={trade_id}, "
            f"symbol={symbol}, latest={latest}"
        )

    actual_id = trade.get("id", "unknown")
    actual_ts = trade.get("timestamp", "unknown")
    ts_slug = (
        actual_ts.replace(" ", "_").replace(":", "-")
        if actual_ts != "unknown" else "unknown"
    )

    print(
        f"  [REVIEW] Trade encontrado: #{actual_id} "
        f"{trade.get('symbol', '?')} @ {actual_ts}"
    )

    # Collect context
    context = _collect_context(system, trade)

    # Report which sources were found
    sources: list[str] = [f"target_trade (id={actual_id})"]
    _source_keys = [
        ("recent_system_trades", "recent_system_trades"),
        ("recent_symbol_trades", "recent_symbol_trades"),
        ("symbol_performance_30d", "symbol_performance_30d"),
        ("system_stats_30d", "system_stats_30d"),
        ("nearby_ai_decisions", "nearby_ai_decisions"),
        ("nearby_analysis_log", "nearby_analysis_log"),
        ("nearby_alerts", "nearby_alerts"),
        ("nearby_scalping_audit", "nearby_scalping_audit"),
        ("nearby_scalping_outcome_labels", "nearby_scalping_outcome_labels"),
    ]
    for key, label in _source_keys:
        val = context.get(key)
        if val:
            if isinstance(val, list):
                sources.append(f"{label} ({len(val)})")
            else:
                sources.append(label)

    print(f"  [REVIEW] Fontes de contexto: {', '.join(sources)}")

    # Build prompt
    prompt = _build_trade_review_prompt(context)

    # Call Claude if available and requested
    review = None
    if use_claude:
        print("  [REVIEW] Chamando Claude para revisao qualitativa...")
        review = _call_claude(prompt)
        if review is not None:
            review = _normalize_trade_review(review, context)
            print("  [REVIEW] Revisao recebida e normalizada com sucesso.")
        else:
            print(
                "  [REVIEW] Claude indisponivel ou falhou. "
                "Gerando apenas contexto + prompt."
            )
    else:
        print("  [REVIEW] Claude desligado. Gerando apenas contexto + prompt.")

    # Output directory
    output_dir = str(
        RUNTIME_DIR / "trade_reviews" / f"{system}-{actual_id}-{ts_slug}"
    )

    # Save outputs
    files = _save_outputs(context, prompt, review, output_dir)

    return {
        "trade_id": actual_id,
        "system": system,
        "symbol": trade.get("symbol", "?"),
        "timestamp": actual_ts,
        "sources": sources,
        "review": review,
        "files": files,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Offline Trade Review Lab — "
            "revisa trades individuais com profundidade"
        ),
    )
    parser.add_argument(
        "--system", required=True,
        choices=["paper", "agent", "pump", "scalping"],
        help="Sistema de trading (obrigatorio)",
    )
    parser.add_argument(
        "--trade-id", type=int, default=None,
        help="ID do trade a revisar",
    )
    parser.add_argument(
        "--latest", type=int, default=0,
        help="Revisar o N-esimo trade mais recente (1 = mais recente)",
    )
    parser.add_argument(
        "--symbol", type=str, default=None,
        help="Filtrar por simbolo (ex: BTCUSDT)",
    )
    parser.add_argument(
        "--no-claude", action="store_true",
        help="Desabilitar chamada ao Claude",
    )
    parser.add_argument(
        "--stdout", action="store_true",
        help="Imprimir review/prompt no stdout",
    )
    args = parser.parse_args()

    if args.trade_id is None and args.latest <= 0:
        parser.error("Especifique --trade-id ou --latest")

    try:
        result = run_review(
            system=args.system,
            trade_id=args.trade_id,
            symbol=args.symbol,
            latest=args.latest,
            use_claude=not args.no_claude,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"  [REVIEW] {exc}")
        sys.exit(1)

    print()
    print(
        f"Trade Review: #{result['trade_id']} "
        f"{result['symbol']} ({result['system']})"
    )
    print(f"Timestamp: {result['timestamp']}")
    print()

    if result["review"]:
        print(
            f"Classificacao: "
            f"{result['review'].get('classification', 'unclear')}"
        )
        lesson = result["review"].get("lesson", "")
        if lesson:
            print(f"Licao: {lesson}")
        tags = result["review"].get("tags", [])
        if tags:
            print(f"Tags: {', '.join(tags)}")
    else:
        print("Status: context_only (sem revisao de Claude)")

    print()
    print("Arquivos gerados:")
    for label, path in result["files"].items():
        print(f"  {label}: {path}")

    if args.stdout:
        print()
        print("=" * 60)
        # Print the review markdown if available, else the prompt
        report_md = result["files"].get("report_md")
        prompt_md = result["files"].get("prompt_md")
        target = report_md or prompt_md
        if target and Path(target).exists():
            print(Path(target).read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
