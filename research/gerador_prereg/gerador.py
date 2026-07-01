"""Gerador — congela UMA hipótese nova por execução (forward-only).

Percorre uma fila CURADA de teses a priori (cada uma com mecanismo claro, composta
só de primitivas do catálogo) e congela a primeira ainda não registrada. Determinístico
e reproduzível: dado o journal, a próxima escolha é fixa. NUNCA olha o dado forward —
só monta a régua ex-ante. O julgamento é do colhedor, no marco.

A fila é diversa de propósito (1 sinal distinto por entrada antes de repetir): mais
hipóteses parecidas só inflariam a multiplicidade que o BH-FDR tem de pagar.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from research.gerador_prereg import catalogo as cat
from research.gerador_prereg import schema
from research.gerador_prereg.colhedor import JOURNAL_DEFAULT

CAP_N_DEFAULT = 5   # "poucos e diversos" — MINI_MOLDURA 2026-06-18

# Fila curada: cada tese é falsificável e motivada por mecanismo. Ordem = diversidade
# (sinais distintos primeiro). O gerador congela a próxima não-registrada.
CANDIDATOS = [
    {"hypothesis": "Após 3 candles horários consecutivos na mesma direção, o movimento "
                   "reverte (líquido) no horizonte de 4h.",
     "signal": "sequencia_candles", "signal_params": {"n": 3, "modo": "reversao"},
     "filter": "nenhum", "filter_params": {}, "side": "auto", "bars": 4, "universe": "todos"},
    {"hypothesis": "Tocar e rejeitar a máxima/mínima de 24h sinaliza reversão local com "
                   "retorno líquido > 0 em 8h.",
     "signal": "reacao_nivel", "signal_params": {"win": 24},
     "filter": "nenhum", "filter_params": {}, "side": "auto", "bars": 8, "universe": "todos"},
    {"hypothesis": "Quando o funding cruza zero, o preço segue a nova direção do "
                   "posicionamento (líquido) em 24h.",
     "signal": "funding_flip", "signal_params": {},
     "filter": "nenhum", "filter_params": {}, "side": "auto", "bars": 24, "universe": "todos"},
    {"hypothesis": "Divergência forte OI×preço (4h) antecede continuação direcional "
                   "líquida em 8h.",
     "signal": "oi_preco_div", "signal_params": {"win": 4, "z": 1.0},
     "filter": "nenhum", "filter_params": {}, "side": "auto", "bars": 8, "universe": "todos"},
    {"hypothesis": "Em regime de vol alta, 4 candles na mesma direção têm continuação "
                   "líquida > 0 em 4h.",
     "signal": "sequencia_candles", "signal_params": {"n": 4, "modo": "continuacao"},
     "filter": "vol_regime", "filter_params": {"regime": "alta"}, "side": "auto",
     "bars": 4, "universe": "todos"},
    # EXP-liq — fronteira tick-level (side=BUY validado na Etapa 0; primitiva causal testada).
    {"hypothesis": "Pico de venda forçada (long liq, side=BUY) varrendo um fundo 4h válido, "
                   "seguido de rejeição (close volta pra dentro), reverte (long) em 24h.",
     "signal": "liquidacao_sweep_estrutural",
     "signal_params": {"pivot_side": 3, "lookback": 18, "p_pct": 90, "p_window": 30,
                       "reject_within": 2},
     "filter": "nenhum", "filter_params": {}, "side": "long", "bars": 24, "universe": "todos"},
    # EXP-liq #2 — discriminante da qualidade da queda (mecanismo distinto do sweep).
    {"hypothesis": "Queda de 4h com pico de venda forçada (long liq, side=BUY) alta reverte "
                   "(long) em 8h — o overshoot inelástico volta.",
     "signal": "liquidacao_discriminante",
     "signal_params": {"ret_pct": 20, "liq_pct": 75, "p_window": 30},
     "filter": "nenhum", "filter_params": {}, "side": "long", "bars": 8, "universe": "todos"},
]


def _spec_of(c):
    return {"signal": c["signal"], "signal_params": c["signal_params"],
            "filter": c["filter"], "filter_params": c["filter_params"],
            "side": c["side"], "exit": {"type": "horizonte", "bars": c["bars"]},
            "universe": c["universe"],
            "fee_bps_roundtrip": schema.FEE_BPS_ROUNDTRIP,
            "slippage_bps": schema.SLIPPAGE_BPS}


def _motivation(c):
    base = cat.SIGNALS[c["signal"]]["rationale"]
    if c["filter"] != "nenhum":
        base += f" · regime: {cat.FILTERS[c['filter']]['rationale']}"
    return base


def _corte_amanha(agora):
    """Meia-noite UTC do dia seguinte = corte forward estritamente futuro."""
    d = (agora + timedelta(days=1)).date()
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def gerar(journal_path=JOURNAL_DEFAULT, agora=None, batch_id=None,
          cap_n=CAP_N_DEFAULT, marco=schema.MARCO_DEFAULT):
    """Congela no máx. 1 pré-registro. Retorna ('REGISTERED', id) | ('SKIPPED', None)
    | ('BATCH_FULL', None)."""
    journal_path = str(journal_path)
    if agora is None:
        agora = datetime.now(timezone.utc)
    if batch_id is None:
        batch_id = f"B-{agora:%Y%m%d}"

    recs = schema.read_journal(journal_path)
    no_batch = sum(1 for r in recs if r["batch_id"] == batch_id)
    if no_batch >= cap_n:
        return ("BATCH_FULL", None)

    usadas = {cat.spec_signature(r["spec"]) for r in recs}
    for c in CANDIDATOS:
        spec = _spec_of(c)
        if cat.spec_signature(spec) in usadas:
            continue
        rec_id = f"PR-{agora:%Y%m%d}-{no_batch + 1:03d}"
        rec = schema.new_frozen(
            rec_id=rec_id, created_at=agora.isoformat(), batch_id=batch_id,
            n_no_batch=no_batch + 1, hypothesis=c["hypothesis"], motivation=_motivation(c),
            signal=c["signal"], signal_params=c["signal_params"],
            filter_name=c["filter"], filter_params=c["filter_params"], side=c["side"],
            bars=c["bars"], universe=c["universe"],
            corte_ts=_corte_amanha(agora), marco=marco)
        schema.append(journal_path, rec)
        return ("REGISTERED", rec_id)

    return ("SKIPPED", None)   # fila esgotada, nada novo a congelar


if __name__ == "__main__":
    status, rid = gerar()
    print(f"REGISTERED {rid}" if status == "REGISTERED" else status)
