"""Mesa (automacao deterministica) — as MAOS da mesa, sem LLM.

Fronteira honesta (SPEC_LIVRO_RAZAO Bloco 2): o SELETOR deterministico roda sozinho no Pi;
o GERADOR criativo fica pluggable. Este modulo e so o gate deterministico de congelamento:
  - recusa signature MORTA (cemiterio: rejeitada/rejeitada_conf) — tese ja refutada no forward;
  - recusa signature ja registrada (dedup vs journal);
  - recusa primitiva fora do catalogo.
A GERACAO de mecanismo/primitiva nova e o scoring anti-beta NAO sao automatizados no Pi
(llama.cpp desativado; agente autonomo regeneraria becos). Ficam human/Claude drop-file em
propostas/. NENHUM agente preve preco: a mesa so gera REGUAS ex-ante; o mercado julga no marco.
"""
from __future__ import annotations

from research.gerador_prereg import catalogo as cat
from research.gerador_prereg import livro_razao as lr

# estados terminais por veredito que constituem o cemiterio (nunca re-congelar a identica).
# dado_insuficiente NAO entra: e re-dimensionavel por decisao HUMANA (protocolo NOTA).
ESTADOS_MORTOS = {"rejeitada", "rejeitada_conf"}


def cemiterio(recs) -> set:
    """Signatures MORTAS (refutadas no forward). A mesa recusa re-congela-las."""
    book = lr.build_book(recs)
    return {lab for lab, e in book.items() if e["estado"] in ESTADOS_MORTOS}


def signatures_no_journal(recs) -> set:
    return {cat.spec_signature(r["spec"]) for r in recs}


def pode_congelar(spec, recs) -> tuple:
    """(ok: bool, motivo: str). Gate deterministico antes de qualquer freeze:
    catalogo -> cemiterio -> dedup. Ordem importa: cemiterio antes de dedup para dar o
    motivo mais informativo quando a signature morta tambem ja esta no journal."""
    signal = spec.get("signal")
    if signal not in cat.SIGNALS:
        return False, f"primitiva fora do catalogo: {signal}"
    sig = cat.spec_signature(spec)
    if sig in cemiterio(recs):
        return False, "signature no cemiterio (tese ja refutada no forward)"
    if sig in signatures_no_journal(recs):
        return False, "signature ja registrada (dedup)"
    return True, "ok"
