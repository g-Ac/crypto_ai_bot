#!/usr/bin/env python3
"""Trigger idempotente do Colhedor de Pré-Registros.

Espelha scripts/juiz_forward_trigger.py. Roda diário via cron. Quando há pré-registro
`frozen` com marco vencido, dispara o colhedor (que é idempotente: `judged` nunca
re-julga) e notifica o Telegram. Robusto a reboot do Pi (o estado vive no journal,
não num relógio). NÃO altera régua congelada — só executa o que já foi travado.

Cron sugerido (diário 06:10 UTC):
  10 6 * * *  cd /home/pi/crypto_ai_bot && .venv/bin/python scripts/gerador_prereg_trigger.py
"""
import sys
from datetime import datetime, timezone

ROOT = "/home/pi/crypto_ai_bot"
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _telegram_notifier(titulo, msg, critical):
    from telegram_notifier import send_system_alert
    send_system_alert(titulo, msg, critical=critical)


def run(journal_path=None, panels=None, hoje=None, out_path=None, notifier=None):
    """Decide se roda o colhedor e notifica. Parametrizável p/ teste (panels sintético,
    hoje fixo, notifier mock). Retorna dict com {'ran': bool, ...}."""
    from research.gerador_prereg import colhedor, schema

    journal_path = journal_path or str(colhedor.JOURNAL_DEFAULT)
    hoje = hoje or datetime.now(timezone.utc).date()

    recs = schema.read_journal(journal_path)
    pend = [r for r in recs if r["status"] == "frozen"
            and colhedor._parse_marco(r["forward"]["marco"]) <= hoje]
    if not pend:
        print(f"[gerador-prereg] nada vencido (hoje {hoje}); nada a fazer")
        return {"ran": False, "reason": "nada vencido", "n_pendentes": 0}

    kw = {"journal_path": journal_path, "hoje": hoje}
    if out_path is not None:
        kw["out_path"] = out_path
    if panels is not None:
        kw["panels"] = panels
        kw["load"] = False
    p = colhedor.colher(**kw)

    if p["n_julgados"] > 0 and notifier is not None:
        linhas = [f"{b}: {i['veredito']} ({i['n_candidatos']}/{i['n_julgados']} cand, "
                  f"{i['dias_forward']}d)" for b, i in p["batches"].items()]
        msg = ("Colhedor de pré-registros rodou.\n" + "\n".join(linhas) +
               f"\n{len(p['candidatos'])} candidato(s). Chama o Claude pra ler o resultado.json.")
        try:
            notifier("Colhedor Pré-Registros", msg, len(p["candidatos"]) > 0)
        except Exception as e:   # notificação é best-effort; o resultado já está salvo
            print(f"[gerador-prereg] notificacao falhou: {e}")

    print(f"[gerador-prereg] RODOU: {p['n_julgados']} julgados, "
          f"{len(p['candidatos'])} candidatos")
    return {"ran": True, "payload": p}


def main():
    """Falha do colhedor no marco NÃO pode ser silenciosa: alerta crítico no Telegram
    e exit != 0 (o resultado só existe se colher() completou)."""
    try:
        run(notifier=_telegram_notifier)
    except Exception as e:
        print(f"[gerador-prereg] ERRO FATAL: {e}")
        try:
            _telegram_notifier(
                "Colhedor Pré-Registros FALHOU",
                f"Exceção ao rodar o colhedor no marco: {e}\n"
                "O journal NÃO foi julgado. Verificar logs/gerador_prereg.log e re-rodar.",
                True,
            )
        except Exception as e2:
            print(f"[gerador-prereg] alerta de falha tambem falhou: {e2}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
