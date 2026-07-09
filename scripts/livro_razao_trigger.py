#!/usr/bin/env python3
"""Trigger do Livro-Razao. Roda diario via cron, DEPOIS do colhedor no marco.

Congela confirmacoes de candidatas (confirmador) e regenera carteira.json (livro_razao).
Idempotente. Falha NAO e silenciosa: alerta Telegram critico + exit 1 (licao da revisao).

Cron sugerido (diario 06:20 UTC, apos o colhedor as 06:10):
  20 6 * * *  /home/pi/crypto_ai_bot/.venv/bin/python /home/pi/crypto_ai_bot/scripts/livro_razao_trigger.py
"""
import sys
from datetime import datetime, timezone

ROOT = "/home/pi/crypto_ai_bot"
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _telegram_notifier(titulo, msg, critical):
    from telegram_notifier import send_system_alert
    send_system_alert(titulo, msg, critical=critical)


def run(journal_path=None, agora=None, notifier=None, panels=None, out_path=None):
    """Congela confirmacoes das candidatas + regenera a carteira. Parametrizavel p/ teste."""
    from research.gerador_prereg import colhedor, confirmador, livro_razao

    if agora is None:
        agora = datetime.now(timezone.utc)
    journal_path = journal_path or str(colhedor.JOURNAL_DEFAULT)

    novos = confirmador.freeze_confirmations(journal_path, agora=agora)

    kw = {"journal_path": journal_path, "agora": agora}
    if panels is not None:
        kw["panels"] = panels
    if out_path is not None:
        kw["out_path"] = out_path
    snap = livro_razao.render_e_grava(**kw)

    n_cart = sum(1 for h in snap["hipoteses"] if h["estado"] == "na_carteira")
    if notifier is not None and (novos or n_cart):
        msg = (f"Livro-razao atualizado.\n{len(novos)} confirmacao(oes) congelada(s).\n"
               f"{n_cart} na carteira, sleeve {snap['sleeve_total']:.3f}.")
        try:
            notifier("Livro-Razao", msg, False)
        except Exception as e:
            print(f"[livro-razao] notificacao falhou: {e}")

    print(f"[livro-razao] {len(novos)} confirmacoes congeladas, {n_cart} na carteira")
    return {"confirmacoes": novos, "n_carteira": n_cart, "snap": snap}


def main():
    try:
        run(notifier=_telegram_notifier)
    except Exception as e:
        print(f"[livro-razao] ERRO FATAL: {e}")
        try:
            _telegram_notifier("Livro-Razao FALHOU",
                               f"Excecao ao atualizar o livro-razao: {e}", True)
        except Exception as e2:
            print(f"[livro-razao] alerta de falha tambem falhou: {e2}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
