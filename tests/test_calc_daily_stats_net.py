"""calc_daily_stats deve reportar o PnL LIQUIDO (net) quando disponivel, nao o bruto —
para o headline (daily report + /performance do telegram) nao confundir lucro com prejuizo."""
import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from daily_report import calc_daily_stats  # noqa: E402


def _t(pnl, net=None, usd=None, net_usd=None):
    d = {"pnl_pct": pnl, "pnl_usd": usd if usd is not None else pnl * 10, "exit_reason": "tp1"}
    if net is not None:
        d["net_pnl_pct"] = net
        d["net_pnl_usd"] = net_usd if net_usd is not None else net * 10
    return d


def test_usa_net_quando_disponivel():
    # gross +2.0, net -0.1 (fee comeu tudo) -> headline deve ser NEGATIVO
    trades = [_t(1.0, net=-0.05), _t(1.0, net=-0.05)]
    s = calc_daily_stats(trades)
    assert s["pnl_pct"] == -0.1          # LIQUIDO, nao +2.0
    assert s["gross_pnl_pct"] == 2.0     # bruto exposto à parte
    assert s["is_net"] is True


def test_win_loss_pela_realidade_liquida():
    # trade bruto-positivo mas liquido-negativo conta como PERDA
    s = calc_daily_stats([_t(0.4, net=-0.1)])
    assert s["wins"] == 0 and s["losses"] == 1


def test_fallback_pro_gross_sem_net():
    # rows antigas sem net -> usa gross (backward-compat)
    s = calc_daily_stats([_t(1.5), _t(-0.5)])
    assert s["pnl_pct"] == 1.0 and s["is_net"] is False


def test_vazio_tem_chaves_novas():
    s = calc_daily_stats([])
    assert s["pnl_pct"] == 0 and s["gross_pnl_pct"] == 0 and s["is_net"] is False


def test_ignora_trades_abertos():
    trades = [_t(1.0, net=0.5), {"pnl_pct": 99, "exit_reason": "open"}]
    s = calc_daily_stats(trades)
    assert s["count"] == 1 and s["pnl_pct"] == 0.5
