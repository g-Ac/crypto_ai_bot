"""Livro-Razão / Carteira de apostas — VIEW derivada do journal (NUNCA escreve journal).

Duas responsabilidades, ambas funções puras:
  build_book(recs, hoje) -> estado por hipótese (chave = spec_signature).
  allocate(dist_by_label) -> pesos de alocação cauda-aware (downside-Kelly fracionado).

Regra-mãe: o journal.jsonl é a única fonte de verdade congelada. Aqui só se LÊ e deriva —
o estado da carteira é 100% reconstruível do journal via spec_signature (cada assinatura
tem no máx. 1 descoberta + 1 confirmação, garantido pela topologia gerador/confirmador).
NÃO prevê preço: allocate DIMENSIONA edges já medidos, não projeta retorno.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from research.gerador_prereg import catalogo as cat

CONF_PREFIX = "CONF-"
CARTEIRA_DEFAULT = Path(__file__).resolve().parent / "carteira.json"

# alocação (spec SPEC_LIVRO_RAZAO §5) — cauda-aware, conservadora
N0 = 30        # meia-vida da evidência: n=30 -> shrink 0.5, n=90 -> 0.75
LAMBDA = 1.0   # força da penalidade de cauda (dd == mu -> tail_factor 0.5)
W_CAP = 0.25   # peso MÁXIMO de um edge isolado (tail_factor e shrink só reduzem a partir daí)


# ───────────────────────── build_book ─────────────────────────
def _is_conf(rec) -> bool:
    return str(rec.get("batch_id", "")).startswith(CONF_PREFIX)


def _pos(x) -> bool:
    return isinstance(x, (int, float)) and x > 0


def _num(x):
    return x if isinstance(x, (int, float)) else None


def _fwd(rec) -> dict:
    """Resumo (só-leitura) de um forward já julgado, extraído do verdict."""
    v = rec.get("verdict") or {}
    return {"batch_id": rec.get("batch_id"), "n": v.get("n"),
            "expectancy_net_bps": v.get("expectancy_net_bps"),
            "p_value": v.get("p_value"), "passes_fdr": v.get("passes_fdr")}


def _frozen_ou_forward(rec, hoje_ts) -> str:
    """frozen antes do corte; em_forward depois do corte e antes do marco."""
    if hoje_ts is None:
        return "frozen"
    corte = rec.get("forward", {}).get("corte_ts")
    return "em_forward" if isinstance(corte, int) and corte <= hoje_ts else "frozen"


def _estado(sig, disc, conf, hoje_ts) -> dict:
    entry = {"label": sig,
             "disc_id": disc.get("id") if disc else None,
             "conf_id": conf.get("id") if conf else None,
             "forwards": []}

    if disc is None:                       # confirmação órfã (não deveria ocorrer)
        entry["estado"] = "orfa_confirmacao"
        return entry

    dv = disc.get("verdict")
    if dv:
        entry["forwards"].append(_fwd(disc))

    # descoberta ainda não julgada
    if disc.get("status") != "judged" or dv is None:
        entry["estado"] = _frozen_ou_forward(disc, hoje_ts)
        return entry

    # descoberta julgada, mas não é candidata -> terminal
    n_min = disc.get("forward", {}).get("n_min", 30)
    if not dv.get("is_candidato"):
        n = _num(dv.get("n"))
        entry["estado"] = "dado_insuficiente" if (n is not None and n < n_min) else "rejeitada"
        return entry

    # descoberta é candidata -> depende da confirmação
    if conf is None:
        entry["estado"] = "candidata"
        return entry

    cv = conf.get("verdict")
    if cv:
        entry["forwards"].append(_fwd(conf))
    if conf.get("status") != "judged" or cv is None:
        entry["estado"] = "em_confirmacao"
        return entry

    # confirmação julgada -> aplica a régua (§4): candidata na confirmação E sinal consistente
    cn_min = conf.get("forward", {}).get("n_min", 30)
    cn = _num(cv.get("n"))
    if cn is not None and cn < cn_min:
        entry["estado"] = "dado_insuf_conf"
    elif cv.get("is_candidato") and _pos(dv.get("expectancy_net_bps")) and _pos(cv.get("expectancy_net_bps")):
        entry["estado"] = "na_carteira"     # provisório; render confirma pooled>0 com os trades reais
    else:
        entry["estado"] = "rejeitada_conf"
    return entry


def build_book(recs, hoje_ts=None) -> dict:
    """Reducer PURO: agrupa recs por spec_signature e deriva o estado de cada
    hipótese a partir de {descoberta, confirmação?} e seus verdicts. hoje_ts (epoch,
    opcional) distingue frozen de em_forward. Não escreve nada."""
    groups: dict = {}
    for r in recs:
        sig = cat.spec_signature(r["spec"])
        g = groups.setdefault(sig, {"disc": None, "conf": None})
        g["conf" if _is_conf(r) else "disc"] = r
    return {sig: _estado(sig, g["disc"], g["conf"], hoje_ts)
            for sig, g in groups.items()}


def labels_por_estado(book, estado) -> list:
    return [lab for lab, e in book.items() if e["estado"] == estado]


# ───────────────────────── allocate ─────────────────────────
def _alloc_one(ret_net_bps) -> dict:
    """Peso de UM membro (SPEC §5). Fator-cauda SATURANTE — adotado da lente 'gestor de
    portfólio' do brainstorm sobre o mu/dd² minimalista, que degenerava ao teto para qualquer
    edge realista (dd² minúsculo em frações de trade -> kelly explode -> w=teto sempre, cauda e
    evidência inertes; pego pela revisão adversarial 2026-07-08).
    w = W_CAP · tail_factor · shrink, sempre em [0, W_CAP]:
      tail_factor = mu / (mu + LAMBDA·dd)  -> saturante em (0,1]; cauda gorda encolhe a aposta;
      shrink      = n / (n + N0)           -> força da evidência (mais trades -> aposta maior).
    ret_net_bps: retornos líquidos por trade (bps)."""
    r = [x / 1e4 for x in ret_net_bps]     # fração por trade
    n = len(r)
    if n == 0:
        return {"n": 0, "w": 0.0, "motivo": "sem trades"}
    mu = sum(r) / n
    dd = math.sqrt(sum(min(x, 0.0) ** 2 for x in r) / n)   # downside deviation
    shrink = n / (n + N0)
    tail = 0.0
    if mu <= 0:                            # VETO: mata "mediana+ com média−" (veneno do VRP)
        w, motivo = 0.0, "mu<=0 (veto de cauda)"
    else:
        tail = mu / (mu + LAMBDA * dd)     # dd=0 -> 1 (sem perdas); cauda gorda -> ->0
        w, motivo = W_CAP * tail * shrink, "ok"
    # ruin-guard: um único trade apaga o pnl cumulativo do edge -> cauda domina
    if mu > 0 and abs(min(r)) > mu * n:
        w, motivo = 0.0, "ruin-guard (cauda domina)"
    return {"n": n, "mu_bps": round(mu * 1e4, 3), "dd_bps": round(dd * 1e4, 3),
            "shrink": round(shrink, 4), "tail_factor": round(tail, 4),
            "w": round(w, 6), "motivo": motivo}


def allocate(dist_by_label) -> dict:
    """dist_by_label: {label: [ret_net_bps, ...]}. Retorna {hipoteses, sleeve_total, caixa}.
    Normaliza o sleeve (soma <= 1); caixa é o resto (posição válida — sem alavancagem)."""
    raw = {lab: _alloc_one(rets) for lab, rets in dist_by_label.items()}
    soma_w = sum(a["w"] for a in raw.values())
    scale = (1.0 / soma_w) if soma_w > 1.0 else 1.0
    total = 0.0
    for a in raw.values():
        a["alloc_weight"] = round(a["w"] * scale, 6)
        total += a["alloc_weight"]
    for a in raw.values():
        a["alloc_pct"] = round(a["alloc_weight"] / total, 4) if total > 0 else 0.0
    return {"hipoteses": raw, "sleeve_total": round(total, 6),
            "caixa": round(max(0.0, 1.0 - total), 6)}


# ───────────────────────── render (snapshot derivado) ─────────────────────────
def _forward(panels, corte_ts) -> dict:
    """Só o dado a partir do corte (forward-only). Espelha colhedor._forward_panels."""
    out = {}
    for s, df in panels.items():
        f = df[df.index >= corte_ts]
        if len(f) > 0:
            out[s] = f
    return out


def render(recs, panels, hoje_ts=None, agora_iso=None, hoje_str=None) -> dict:
    """Snapshot DERIVADO (nunca lido de volta como verdade). Para cada membro na_carteira,
    re-mede o track record pooled via build_trades sobre TODO o forward desde o corte da
    descoberta (uma passada contínua, sem concatenar janelas) e aloca. panels reais no marco,
    sintéticos nos testes. NÃO escreve journal."""
    book = build_book(recs, hoje_ts)
    disc_by_sig = {cat.spec_signature(r["spec"]): r for r in recs if not _is_conf(r)}

    dist = {}
    for lab in labels_por_estado(book, "na_carteira"):
        disc = disc_by_sig.get(lab)
        if disc is None:
            continue
        fwd = _forward(panels, disc["forward"]["corte_ts"])
        trades = cat.build_trades(disc["spec"], fwd)
        dist[lab] = [float(x) for x in trades["ret_net_bps"]]
    alloc = allocate(dist)

    hipoteses = []
    for lab, e in book.items():
        estado = e["estado"]
        item = {"label": lab, "estado": estado, "forwards": e["forwards"]}
        if lab in alloc["hipoteses"]:
            a = alloc["hipoteses"][lab]
            item["alloc"] = a
            # Finaliza o gate pooled>0 (SPEC §4 regra 2): na_carteira exige expectancy pooled
            # positivo (medido contínuo desde corte1). mu_bps<=0 ou sem trades = falhou a
            # confirmação pooled -> rejeitada_conf (terminal, entra no cemitério). Ruin-guard
            # (mu>0) NÃO rebaixa: passou o pooled; só o sizing zerou por risco de cauda.
            if estado == "na_carteira" and a.get("mu_bps", 0.0) <= 0:
                item["estado"] = "rejeitada_conf"
        hipoteses.append(item)
    hipoteses.sort(key=lambda h: (h.get("alloc", {}).get("alloc_weight", -1)), reverse=True)
    return {"gerado_em": agora_iso, "hoje": hoje_str, "derived": True,
            "hipoteses": hipoteses, "sleeve_total": alloc["sleeve_total"],
            "caixa": alloc["caixa"]}


def render_e_grava(journal_path=None, out_path=CARTEIRA_DEFAULT, panels=None, agora=None) -> dict:
    """Lê o journal, deriva a carteira, grava carteira.json. Só carrega panels reais se
    houver ao menos 1 membro na_carteira (evita ler 85k linhas para carteira vazia)."""
    from research.gerador_prereg import colhedor
    if agora is None:
        agora = datetime.now(timezone.utc)
    journal_path = journal_path or str(colhedor.JOURNAL_DEFAULT)
    recs = schema_read(journal_path)
    hoje_ts = int(agora.timestamp())
    if panels is None:
        book = build_book(recs, hoje_ts)
        if labels_por_estado(book, "na_carteira"):
            from research.exp100_screening import data as datamod
            panels = datamod.load_panel()
        else:
            panels = {}
    snap = render(recs, panels, hoje_ts=hoje_ts, agora_iso=agora.isoformat(),
                  hoje_str=agora.date().isoformat())
    Path(out_path).write_text(json.dumps(snap, indent=2, ensure_ascii=False, default=str))
    return snap


def schema_read(journal_path):
    from research.gerador_prereg import schema
    return schema.read_journal(journal_path)


def main():
    snap = render_e_grava()
    n_cart = sum(1 for h in snap["hipoteses"] if h["estado"] == "na_carteira")
    print(f"[livro-razao] {len(snap['hipoteses'])} hipoteses | {n_cart} na carteira | "
          f"sleeve {snap['sleeve_total']:.3f} | caixa {snap['caixa']:.3f}")
    for h in snap["hipoteses"]:
        est = h["estado"]
        extra = ""
        if "alloc" in h:
            extra = f"  w={h['alloc']['alloc_weight']:.3f} ({h['alloc']['motivo']})"
        print(f"  {est:18s} {h['label']}{extra}")


if __name__ == "__main__":
    main()
