"""
Helpers para instrumentacao de auditoria operacional.

Fornece funcoes utilitarias para preencher campos do trade_audit_log
e signal_decision_log que nao existiam antes no pipeline.
"""
import logging
import subprocess
from datetime import datetime, timezone

logger = logging.getLogger("audit_helpers")

# Cache do git sha (nao muda durante o runtime)
_GIT_SHA: str | None = None


def get_git_sha() -> str:
    """Retorna o SHA curto do commit atual (cached)."""
    global _GIT_SHA
    if _GIT_SHA is not None:
        return _GIT_SHA
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        _GIT_SHA = result.stdout.strip() or "unknown"
    except Exception:
        _GIT_SHA = "unknown"
    return _GIT_SHA


def get_param_version() -> str:
    """Retorna versao dos parametros do ScalpingConfig.

    Por enquanto usa git_sha como proxy. Quando tivermos
    versionamento explicito de parametros, trocar aqui.
    """
    return f"cfg_{get_git_sha()}"


def get_session_bucket(ts: datetime | None = None) -> str:
    """Classifica a hora UTC em sessao de mercado.

    Asia:   00:00-08:00 UTC
    Europe: 08:00-13:00 UTC
    US:     13:00-21:00 UTC
    Dead:   21:00-00:00 UTC
    """
    if ts is None:
        ts = datetime.now(timezone.utc)
    h = ts.hour
    if 0 <= h < 8:
        return "asia"
    elif 8 <= h < 13:
        return "europe"
    elif 13 <= h < 21:
        return "us"
    else:
        return "dead"


def get_hour_bucket(ts: datetime | None = None) -> int:
    """Retorna hora UTC (0-23)."""
    if ts is None:
        ts = datetime.now(timezone.utc)
    return ts.hour


def get_weekday_bucket(ts: datetime | None = None) -> int:
    """Retorna dia da semana (0=Monday, 6=Sunday)."""
    if ts is None:
        ts = datetime.now(timezone.utc)
    return ts.weekday()


def get_event_bucket() -> str:
    """Retorna bucket de evento. Placeholder — sem integracao com calendario macro ainda."""
    return "none"


def get_asset_bucket(symbol: str) -> str:
    """Classifica ativo em bucket padronizado."""
    s = symbol.upper()
    if "BTC" in s:
        return "btc"
    elif "ETH" in s:
        return "eth"
    elif any(x in s for x in ["BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "DOT", "MATIC", "LINK"]):
        return "majors"
    else:
        return "alts"


def calc_slippage_bps(expected: float, realized: float, direction: str) -> float:
    """Calcula slippage em basis points.

    Slippage positivo = pior que esperado (custo).
    Para LONG entry: realized > expected = slippage positivo.
    Para SHORT entry: realized < expected = slippage positivo.
    Para exit, inverter.
    """
    if expected <= 0:
        return 0.0
    diff_pct = ((realized - expected) / expected) * 10000  # bps
    if direction == "LONG":
        return round(diff_pct, 2)  # positive = worse for long entry
    else:
        return round(-diff_pct, 2)  # positive = worse for short entry


def calc_gross_pnl(entry_price: float, exit_price: float, direction: str,
                   position_size_usd: float) -> tuple[float, float]:
    """Calcula PnL bruto (sem fees/custos).

    Returns:
        (gross_pnl_pct, gross_pnl_usd)
    """
    if entry_price <= 0:
        return 0.0, 0.0
    if direction == "LONG":
        pct = ((exit_price - entry_price) / entry_price) * 100
    else:
        pct = ((entry_price - exit_price) / entry_price) * 100
    usd = position_size_usd * (pct / 100)
    return round(pct, 4), round(usd, 2)


def calc_total_cost_bps(fee_entry_bps: float, fee_exit_bps: float,
                        funding_cost_bps: float = 0.0,
                        other_cost_bps: float = 0.0) -> float:
    """Soma total dos custos em bps."""
    return round(fee_entry_bps + fee_exit_bps + funding_cost_bps + other_cost_bps, 2)
