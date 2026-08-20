#!/usr/bin/env python3
"""Monitor automatico do momentum - manda relatorio fixado no Telegram.

Roda via cron 4x/dia. Zero API Anthropic, so SQL + Telegram API.
Cada execucao despina a mensagem anterior e fixa a nova, mantendo sempre
o relatorio mais recente fixado no chat.

Quando algo chama atencao, o usuario abre Claude e roda /monitor pra analise mais profunda.
"""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DB = PROJECT_ROOT / "runtime" / "baseline" / "bot.db"
PIN_STATE = PROJECT_ROOT / "runtime" / "baseline" / ".monitor_pinned_id.json"

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MOMENTUM_SYMBOLS = [s.strip() for s in os.getenv("MOMENTUM_SYMBOLS", "BTCUSDT,ETHUSDT").split(",") if s.strip()]

API = f"https://api.telegram.org/bot{TOKEN}"


def q(sql: str) -> list:
    conn = sqlite3.connect(str(DB))
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10).stdout.strip()


def fmt_pct(v: float | None, decimals: int = 2, plus: bool = True) -> str:
    if v is None:
        return "N/A"
    sign = "+" if plus and v >= 0 else ""
    return f"{sign}{v:.{decimals}f}%"


def trend_arrow(curr: float, baseline: float, threshold: float = 0.0) -> str:
    diff = curr - baseline
    if abs(diff) < threshold:
        return "→"
    return "↑" if diff > 0 else "↓"


def _pf(pnls: list[float]) -> float:
    """Profit factor = sum(wins) / |sum(losses)|. inf se so wins, 0 se so losses."""
    wins = sum(p for p in pnls if p > 0)
    losses = sum(p for p in pnls if p < 0)
    if losses < 0:
        return wins / abs(losses)
    return float("inf") if wins > 0 else 0.0


# Custo round-trip taker aplicado ao shadow: 0,05%/lado x2 = 0,10%, espelhando o
# fee REAL dos trades (MOMENTUM_PAPER_*_FEE_RATE=0.05). momentum_shadow_outcomes
# guarda pnl_pct GROSS, entao o custo e aplicado por outcome aqui antes de agregar.
# NAO usar SINGLE_SIDE_FEE_PCT=0.04 global (desatualizado) — ver project_momentum_fee_net.
SHADOW_ROUNDTRIP_FEE_PCT = 0.10


def _apply_fee(pnls: list[float], fee: float = SHADOW_ROUNDTRIP_FEE_PCT) -> list[float]:
    """Converte serie de PnL gross em net subtraindo o custo round-trip por trade."""
    return [p - fee for p in pnls]


def shadow_aggregate(pnls_gross: list[float], fee: float = SHADOW_ROUNDTRIP_FEE_PCT) -> dict:
    """Agrega outcomes shadow em metricas NET (avg/total/PF liquidos de fee).

    WR/contagem (wins) permanece em gross — winrate alto com PnL net negativo e
    justamente o sintoma a expor (o fee come a margem fina).
    """
    net = _apply_fee(pnls_gross, fee)
    n = len(net)
    return {
        "n": n,
        "wins": sum(1 for p in pnls_gross if p > 0),
        "avg": (sum(net) / n) if n else 0.0,
        "total": sum(net),
        "pf": _pf(net),
    }


def _fmt_pf(pf: float) -> str:
    if pf == float("inf"):
        return "inf"
    return f"{pf:.2f}"


def shadow_breakdown_lines(blocked_by: str = "max_positions", min_n: int = 20) -> list[str]:
    """Lines mostrando PF por symbol/direction/regime para um blocked_by.

    Retorna lista vazia se amostra < min_n (evita conclusoes em sample fraco).
    Hipotese refinada 2026-04-27: edge concentrado em subespacos; acompanhar
    evolucao por dimensao durante coleta shadow.
    """
    rows = q(
        f"""
        SELECT symbol, direction, regime, pnl_pct
        FROM momentum_shadow_outcomes
        WHERE blocked_by = '{blocked_by}' AND complete = 1
        """
    )
    if len(rows) < min_n:
        return []

    def by(idx: int) -> dict[str, tuple[float, int]]:
        groups: dict[str, list[float]] = {}
        for r in rows:
            k = r[idx] or "(none)"
            groups.setdefault(k, []).append(r[3])
        return {k: (_pf(_apply_fee(v)), len(v)) for k, v in groups.items()}

    def fmt(d: dict[str, tuple[float, int]]) -> str:
        return " | ".join(f"{k}={_fmt_pf(pf)}({n})" for k, (pf, n) in sorted(d.items()))

    return [
        f"  symbol:    {fmt(by(0))}",
        f"  direction: {fmt(by(1))}",
        f"  regime:    {fmt(by(2))}",
    ]


def build_report() -> str:
    # === 24h ===
    trades24 = q(
        """
        SELECT symbol, direction, exit_reason, pnl_pct, mfe_pct, mae_pct, net_pnl_pct
        FROM momentum_trades
        WHERE timestamp >= datetime('now','-24 hours') AND exit_price IS NOT NULL
        ORDER BY id DESC
        """
    )
    abertos = q("SELECT symbol, direction FROM momentum_trades WHERE exit_price IS NULL")
    funil = q(
        """
        SELECT blocked_by, COUNT(*) FROM momentum_decisions
        WHERE timestamp >= datetime('now','-24 hours') AND blocked_by != 'none'
        GROUP BY blocked_by ORDER BY COUNT(*) DESC LIMIT 5
        """
    )
    media_30d_row = q(
        """
        WITH dias AS (
          SELECT date(timestamp) as d, COUNT(*) as n
          FROM momentum_trades
          WHERE timestamp >= datetime('now','-30 days') AND exit_price IS NOT NULL
          GROUP BY d
        )
        SELECT COALESCE(ROUND(AVG(n),1),0), COALESCE(MIN(n),0), COALESCE(MAX(n),0) FROM dias
        """
    )
    media_30d, min_30d, max_30d = media_30d_row[0] if media_30d_row else (0, 0, 0)

    # === All-time ===
    alltime = q(
        """
        SELECT
          COUNT(*) as n,
          SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
          ROUND(SUM(net_pnl_pct), 2) as pnl_total,
          ROUND(MAX(net_pnl_pct), 2) as best,
          ROUND(MIN(net_pnl_pct), 2) as worst,
          MIN(date(timestamp)) as first_day,
          MAX(date(timestamp)) as last_day
        FROM momentum_trades WHERE exit_price IS NOT NULL
        """
    )
    at_n, at_wins, at_pnl, at_best, at_worst, at_first, at_last = alltime[0] if alltime else (0, 0, 0, 0, 0, "?", "?")
    at_wr = (at_wins / at_n * 100) if at_n else 0

    days_active_row = q(
        """
        SELECT COALESCE(julianday(MAX(date(timestamp))) - julianday(MIN(date(timestamp))) + 1, 0)
        FROM momentum_trades WHERE exit_price IS NOT NULL
        """
    )
    days_active = days_active_row[0][0] if days_active_row else 0
    trades_per_day_alltime = at_n / days_active if days_active > 0 else 0

    # === 7d vs 30d ===
    def window_stats(days: int) -> tuple[int, float, float, float]:
        row = q(
            f"""
            SELECT
              COUNT(*) as n,
              SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
              COALESCE(SUM(net_pnl_pct), 0) as pnl_sum
            FROM momentum_trades
            WHERE timestamp >= datetime('now','-{days} days') AND exit_price IS NOT NULL
            """
        )
        n, wins, pnl_sum = row[0] if row else (0, 0, 0)
        wr = (wins / n * 100) if n else 0
        pnl_per_day = pnl_sum / days if days else 0
        trades_per_day = n / days if days else 0
        return n, wr, pnl_per_day, trades_per_day

    n7, wr7, pnl_d7, tpd7 = window_stats(7)
    n30, wr30, pnl_d30, tpd30 = window_stats(30)

    # === Saude ===
    service = sh("systemctl is-active cryptobot") or "unknown"
    temp = sh("vcgencmd measure_temp 2>/dev/null").replace("temp=", "") or "N/A"
    ram_free = sh("free -m | awk 'NR==2 {print $7}'") or "?"
    disk_free = sh("df -h / | awk 'NR==2 {print $4}'") or "?"
    erros_n = sh(
        "journalctl -u cryptobot --since '12 hours ago' --no-pager 2>/dev/null "
        "| grep -iE 'error|exception|traceback' | grep -v DEBUG | wc -l"
    ) or "0"

    # === 24h aggregates ===
    n24 = len(trades24)
    wins24 = sum(1 for t in trades24 if (t[3] or 0) > 0)
    losses24 = n24 - wins24
    pnl24 = sum((t[6] or 0) for t in trades24)  # net_pnl_pct (index 6)
    exits24: dict[str, int] = {}
    for t in trades24:
        er = t[2] or "unknown"
        exits24[er] = exits24.get(er, 0) + 1
    exits_str = ", ".join(f"{k}={v}" for k, v in sorted(exits24.items(), key=lambda x: -x[1])) or "-"

    # === Pontos de atencao ===
    pontos = []

    # Losses com MFE alto (saida prematura?)
    losses_high_mfe = sum(
        1 for t in trades24 if (t[3] or 0) <= 0 and (t[4] or 0) > 0.5
    )
    if losses_high_mfe >= 2:
        pontos.append(f"{losses_high_mfe}/{losses24} losses tinham MFE>0.5% (analisar saida)")

    # Trades 24h vs media
    if n24 < max(1, media_30d * 0.5) and media_30d > 0:
        pontos.append(f"trades 24h ({n24}) abaixo de 50% da media 30d ({media_30d})")

    # Win rate em queda
    if n7 >= 5 and n30 >= 10 and (wr30 - wr7) > 15:
        pontos.append(f"WR em queda: 7d={wr7:.0f}% vs 30d={wr30:.0f}%")

    # PnL em queda
    if pnl_d30 > 0 and pnl_d7 < pnl_d30 * 0.5:
        pontos.append(f"PnL/dia em queda: 7d={pnl_d7:+.2f}% vs 30d={pnl_d30:+.2f}%")

    # Simbolos sem trade 7d
    simbolos_ativos_7d = q(
        """
        SELECT DISTINCT symbol FROM momentum_trades
        WHERE timestamp >= datetime('now','-7 days') AND exit_price IS NOT NULL
        """
    )
    ativos = {row[0] for row in simbolos_ativos_7d}
    parados = [s for s in MOMENTUM_SYMBOLS if s not in ativos]
    if parados:
        pontos.append(f"sem trade 7d: {', '.join(parados)}")

    # Erros
    if int(erros_n) > 0:
        primeira = sh(
            "journalctl -u cryptobot --since '12 hours ago' --no-pager 2>/dev/null "
            "| grep -iE 'error|exception|traceback' | grep -v DEBUG | head -1"
        )[:120]
        pontos.append(f"{erros_n} erros 12h: {primeira or '?'}")

    # Servico
    if service != "active":
        pontos.append(f"servico {service} (esperado: active)")

    # === Tendencias com setas ===
    arrow_wr = trend_arrow(wr7, wr30, threshold=5)
    arrow_pnl = trend_arrow(pnl_d7, pnl_d30, threshold=0.05)
    arrow_tpd = trend_arrow(tpd7, tpd30, threshold=0.3)

    funil_str = "\n".join(f"  {b}: {n}" for b, n in funil) or "  (sem decisoes bloqueadas)"

    # === Shadow simulation (oportunidades bloqueadas que teriam dado X) ===
    # NET: momentum_shadow_outcomes guarda pnl_pct GROSS; o custo round-trip e
    # aplicado por outcome via shadow_aggregate (avg/total/PF ficam liquidos).
    shadow_raw = q(
        """
        SELECT blocked_by, pnl_pct
        FROM momentum_shadow_outcomes
        WHERE complete = 1
        """
    )
    if shadow_raw:
        by_block: dict[str, list[float]] = {}
        for bb, pnl in shadow_raw:
            by_block.setdefault(bb, []).append(pnl or 0.0)
        agg = {bb: shadow_aggregate(pnls) for bb, pnls in by_block.items()}
        shadow_lines = []
        for bb, s in sorted(agg.items(), key=lambda kv: -kv[1]["total"]):
            wr = (s["wins"] / s["n"] * 100) if s["n"] else 0
            shadow_lines.append(
                f"  {bb}: N={s['n']} WR={wr:.0f}% avg={s['avg']:+.3f}% total={s['total']:+.2f}%"
            )
            # Flag so dispara se o shadow for NET-lucrativo de verdade (avg liquido > custo)
            if bb != "none" and s["total"] > 1 and s["avg"] > 0.05:
                pontos.append(
                    f"shadow: {bb} bloqueou {s['n']} trades com edge NET +{s['avg']:.3f}%/trade ({s['total']:+.2f}% total)"
                )
        shadow_str = "\n".join(shadow_lines)
    else:
        shadow_str = "  (sem dados — rodar python shadow_simulator.py)"

    # Breakdown shadow max_positions por symbol/direction/regime
    # Hipotese refinada 2026-04-27: edge concentrado em subespacos
    breakdown_lines = shadow_breakdown_lines("max_positions", min_n=20)
    if breakdown_lines:
        breakdown_str = "\n".join(breakdown_lines)
    else:
        breakdown_str = "  (amostra < 20, aguardando coleta)"

    pontos_str = "\n".join(f"- {p}" for p in pontos) if pontos else "- nenhum (tudo dentro do esperado)"

    msg = f"""<b>📊 Monitor Momentum</b> | <code>{at_last}</code>

<b>━ SAUDE ━</b>
{service} | {temp} | RAM {ram_free}M | Disco {disk_free}

<b>━ TRADES 24h ━</b>
{n24} fechados | {len(abertos)} abertos | media 30d={media_30d}
WL: {wins24}W/{losses24}L ({(wins24/n24*100 if n24 else 0):.0f}%) | PnL net: {fmt_pct(pnl24)}
Exits: {exits_str}

<b>━ VISAO GERAL (all-time) ━</b>
Total: {at_n} trades em {days_active:.0f} dias
WR: {at_wr:.1f}% | PnL net acum.: {fmt_pct(at_pnl)}
Best: {fmt_pct(at_best)} | Worst: {fmt_pct(at_worst)} (net)
Trades/dia: {trades_per_day_alltime:.1f} (range {min_30d}-{max_30d} em 30d)

<b>━ TENDENCIA 7d vs 30d ━</b>
WR: 7d={wr7:.0f}% vs 30d={wr30:.0f}% {arrow_wr}
PnL net/dia: 7d={fmt_pct(pnl_d7)} vs 30d={fmt_pct(pnl_d30)} {arrow_pnl}
Trades/dia: 7d={tpd7:.1f} vs 30d={tpd30:.1f} {arrow_tpd}

<b>━ GARGALO 24h ━</b>
{funil_str}

<b>━ SHADOW (net · fee 0,10% round-trip) ━</b>
{shadow_str}

<b>━ SHADOW DEEP — max_positions por dimensao (PF net) ━</b>
{breakdown_str}

<b>━ PONTOS DE ATENCAO ━</b>
{pontos_str}

<i>Aprofundar: ssh pi → cd ~/crypto_ai_bot && claude → /monitor</i>"""
    return msg


def telegram_post(method: str, data: dict) -> dict:
    r = requests.post(f"{API}/{method}", data=data, timeout=10)
    return r.json()


def load_pinned_id() -> int | None:
    try:
        with open(PIN_STATE) as f:
            return json.load(f).get("message_id")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_pinned_id(message_id: int) -> None:
    PIN_STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(PIN_STATE, "w") as f:
        json.dump({"message_id": message_id}, f)


def send_and_pin(msg: str) -> bool:
    if not TOKEN or not CHAT_ID:
        print("ERRO: TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID nao configurados", file=sys.stderr)
        return False

    # Despinar mensagem anterior (se houver)
    old_id = load_pinned_id()
    if old_id:
        result = telegram_post("unpinChatMessage", {"chat_id": CHAT_ID, "message_id": old_id})
        if not result.get("ok"):
            print(f"Aviso: falha ao despinar {old_id}: {result.get('description', '?')}", file=sys.stderr)

    # Mandar nova
    result = telegram_post("sendMessage", {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })
    if not result.get("ok"):
        print(f"ERRO sendMessage: {result.get('description', '?')}", file=sys.stderr)
        return False
    new_id = result["result"]["message_id"]

    # Pinar nova (silent pra nao soar notificacao do pin)
    pin_result = telegram_post("pinChatMessage", {
        "chat_id": CHAT_ID,
        "message_id": new_id,
        "disable_notification": True,
    })
    if not pin_result.get("ok"):
        print(f"Aviso: falha ao pinar {new_id}: {pin_result.get('description', '?')}", file=sys.stderr)
        return False

    save_pinned_id(new_id)
    return True


def main() -> int:
    msg = build_report()
    if "--dry-run" in sys.argv:
        print(msg)
        return 0
    return 0 if send_and_pin(msg) else 1


if __name__ == "__main__":
    sys.exit(main())
