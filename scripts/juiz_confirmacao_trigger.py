#!/usr/bin/env python3
"""Trigger idempotente da Confirmação do Juiz (2º forward dos candidatos EXP-100).

Pré-registro CONGELADO em research/juiz_forward/confirmacao_prereg.json (marco lá
dentro). Roda diário via cron; dispara UMA vez quando hoje >= marco, depois trava na
flag (robusto a reboot do Pi sem RTC). NÃO altera a régua — só executa o congelado.
Falha é BARULHENTA: pré-registro sumido ou exceção no julgamento alertam no Telegram
e NÃO gravam a flag (re-tenta e re-alerta a cada dia até alguém consertar).
"""
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = "/home/pi/crypto_ai_bot"
PREREG = Path(ROOT) / "research/juiz_forward/confirmacao_prereg.json"
FLAG = Path(ROOT) / "runtime/juiz_confirmacao.done"
PINNED_PREREG_SHA256 = "5ff3d8dd98a88c95d9044dcea02605ef6ff389e23ef1bd28a2d35aca3044c390"

sys.path.insert(0, ROOT)


def _notify(title, msg, critical=False):
    try:
        from telegram_notifier import send_system_alert
        send_system_alert(title, msg, critical=critical)
    except Exception as e:  # notificação é best-effort; o resultado já está salvo
        print(f"[juiz-confirmacao] notificacao falhou: {e}")


def run(prereg_path=PREREG, flag_path=FLAG, panels=None, hoje=None,
        out_path=None, notifier=_notify, expected_prereg_sha256=None):
    """Decide rodar + notifica. panels/hoje/out_path injetáveis p/ teste."""
    if hoje is None:
        hoje = datetime.now(timezone.utc).date()

    prereg_path = Path(prereg_path)
    if not prereg_path.exists():
        notifier("Confirmação Juiz — PRÉ-REGISTRO SUMIU",
                 f"{prereg_path} não existe; a confirmação dos candidatos EXP-100 "
                 f"não será julgada. Restaurar do git/backup.", critical=True)
        print(f"[juiz-confirmacao] ERRO: pré-registro ausente ({prereg_path})")
        return {"ran": False, "motivo": "prereg_ausente"}

    if expected_prereg_sha256 is None and prereg_path.resolve() == PREREG.resolve():
        expected_prereg_sha256 = PINNED_PREREG_SHA256
    actual_sha256 = hashlib.sha256(prereg_path.read_bytes()).hexdigest()
    if expected_prereg_sha256 and actual_sha256 != expected_prereg_sha256:
        notifier("Confirmação Juiz — PRÉ-REGISTRO ADULTERADO",
                 f"SHA256 mudou: esperado {expected_prereg_sha256}, atual "
                 f"{actual_sha256}. Julgamento bloqueado; flag NÃO gravada.", critical=True)
        print("[juiz-confirmacao] ERRO: hash do pré-registro divergiu")
        return {"ran": False, "motivo": "prereg_adulterado"}

    marco = date.fromisoformat(json.loads(prereg_path.read_text())["marco"])
    if hoje < marco:
        print(f"[juiz-confirmacao] ainda não é hora (marco {marco}, hoje {hoje})")
        return {"ran": False, "motivo": "antes_do_marco"}

    flag_path = Path(flag_path)
    if flag_path.exists():
        print("[juiz-confirmacao] já rodou (flag existe); nada a fazer")
        return {"ran": False, "motivo": "flag"}

    from research.juiz_forward import confirmacao
    kwargs = {"prereg_path": prereg_path, "panels": panels}
    if out_path is not None:
        kwargs["out_path"] = out_path
    try:
        p = confirmacao.confirmar(**kwargs)
    except Exception as e:
        notifier("Confirmação Juiz — FALHOU",
                 f"Julgamento da confirmação quebrou: {e}. Flag NÃO gravada; "
                 f"re-tento amanhã. Investigar.", critical=True)
        raise

    flag_path.write_text(
        f"{datetime.now(timezone.utc).isoformat()} veredito={p['veredito']} "
        f"confirmadas={p['n_confirmadas']} dias={p['dias_forward']}\n"
    )
    drift = ("\n⚠️ DRIFT DE CÓDIGO desde o congelamento: "
             + ", ".join(p["code_drift"])) if p["code_drift"] else ""
    msg = (f"Veredito: <b>{p['veredito']}</b>\n"
           f"{p['dias_forward']}d forward · {p['n_confirmadas']} de "
           f"{len(p['cells'])} célula(s) confirmada(s).{drift}\n"
           f"2º forward dos candidatos do Juiz 2026-08-01. "
           f"Chama o Claude pra interpretar o confirmacao_resultado.json.")
    notifier("Confirmação Juiz EXP-100", msg, critical=(p["n_confirmadas"] > 0))
    print(f"[juiz-confirmacao] RODOU: {p['veredito']} ({p['n_confirmadas']} confirmadas)")
    return {"ran": True, "payload": p}


if __name__ == "__main__":
    run()
