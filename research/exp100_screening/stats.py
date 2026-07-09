"""EXP-100 — correção de multiplicidade (Benjamini-Hochberg FDR).

Com 120 células no grid, ~5% rejeitariam H0 por puro acaso a alpha=0.05.
BH controla a *taxa de falsa descoberta* (FDR) — fração esperada de falsos
positivos entre os rejeitados. q=0.10 = aceito que ~10% dos "candidatos"
sejam ruído. Sem isso, o screening fabrica GO. Ver mini-moldura 2026-06-17.
"""
from __future__ import annotations

import numpy as np


def benjamini_hochberg(pvals, q=0.10):
    """Máscara booleana de quais hipóteses rejeitam H0 sob FDR <= q.

    pvals: sequência de p-values (mesma ordem das hipóteses).
    Retorna np.ndarray[bool] alinhado a pvals.
    """
    p = np.asarray(pvals, dtype=float)
    m = len(p)
    if m == 0:
        return np.zeros(0, dtype=bool)
    order = np.argsort(p)
    ranked = p[order]
    thresh = q * (np.arange(1, m + 1) / m)
    passed = ranked <= thresh
    if not passed.any():
        return np.zeros(m, dtype=bool)
    # maior posto i cujo p_(i) <= (i/m)*q define o ponto de corte
    k = np.max(np.where(passed)[0])
    crit = ranked[k]
    return p <= crit
