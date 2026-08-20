#!/usr/bin/env python3
"""Trigger idempotente do Juiz Forward.

Pré-registro CONGELADO: vault context/decisoes/2026-06-17-juiz-forward-prereg.md.
Roda diário via cron; dispara o juiz UMA vez quando hoje >= MARCO, depois trava na flag
(robusto a reboot do Pi sem RTC). NÃO altera a régua — só executa o que já foi congelado.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

MARCO = datetime(2026, 8, 1, tzinfo=timezone.utc)
FLAG = Path("/home/pi/crypto_ai_bot/runtime/juiz_forward.done")
ROOT = "/home/pi/crypto_ai_bot"

sys.path.insert(0, ROOT)


def main():
    agora = datetime.now(timezone.utc)
    if agora < MARCO:
        print(f"[juiz-forward] ainda não é hora (marco {MARCO.date()}, hoje {agora.date()})")
        return
    if FLAG.exists():
        print("[juiz-forward] já rodou (flag existe); nada a fazer")
        return

    from research.juiz_forward import judge
    p = judge.judge()
    FLAG.write_text(
        f"{agora.isoformat()} veredito={p['veredito']} "
        f"candidatos={p['n_candidatos']} dias={p['dias_forward']}\n"
    )
    msg = (f"Veredito: <b>{p['veredito']}</b>\n"
           f"{p['dias_forward']}d forward · {p['n_simbolos']} símbolos · "
           f"{p['n_candidatos']} candidato(s) de {p['n_elegiveis']} células.\n"
           f"Pré-registro 2026-06-17. Chama o Claude pra interpretar o resultado.json.")
    try:
        from telegram_notifier import send_system_alert
        send_system_alert("Juiz Forward EXP-100/101/102", msg,
                          critical=(p["n_candidatos"] > 0))
    except Exception as e:  # notificação é best-effort; o resultado já está salvo
        print(f"[juiz-forward] notificacao falhou: {e}")
    print(f"[juiz-forward] RODOU: {p['veredito']} ({p['n_candidatos']} candidatos)")


if __name__ == "__main__":
    main()
