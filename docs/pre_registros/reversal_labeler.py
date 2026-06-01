# reversal_labeler.py — Python 3.11, numpy + pandas. Puro, sem I/O.
import numpy as np
import pandas as pd


def label_reversals(price_series, regime_series=None, k=2.0, N=12,
                    vol_window=96, M=None, noise_k=0.1):
    """Rotula reversões: excursão adversa >= k*sigma contra a direção prévia em N candles.

    sigma = vol realizada local (trailing vol_window) escalada por sqrt(N), só passado.
    A excursão futura é o ALVO (uso de futuro intencional e correto).
    """
    if M is None:
        M = N
    price = pd.Series(price_series).astype(float).reset_index(drop=True)
    n = len(price)
    labels = np.zeros(n, dtype=bool)
    if n < max(vol_window, M) + N + 1:
        return labels

    logp = np.log(price.values)
    ret = np.diff(logp, prepend=logp[0])  # retorno log por candle

    # vol local trailing (exclui o candle corrente do desvio? usamos até t inclusive)
    vol_local = pd.Series(ret).rolling(vol_window).std(ddof=0).values  # por candle
    # direção prévia: retorno log acumulado nos M candles até t
    prior = logp - np.concatenate([np.full(M, np.nan), logp[:-M]])

    start = max(vol_window, M)
    end = n - N  # precisa de N candles à frente
    for t in range(start, end):
        sig = vol_local[t]
        if not np.isfinite(sig) or sig <= 0:
            continue
        sigN = sig * np.sqrt(N)
        d = prior[t]
        if not np.isfinite(d):
            continue
        # banda morta de direção
        if abs(d) < noise_k * sigN:
            continue
        future = logp[t + 1: t + N + 1] - logp[t]  # retornos log forward
        if d > 0:                       # subiu antes -> reversão é queda futura
            if future.min() <= -k * sigN:
                labels[t] = True
        else:                           # caiu antes -> reversão é alta futura
            if future.max() >= k * sigN:
                labels[t] = True
    return labels


def compute_baseline_rate(labels, regime_series):
    """Taxa incondicional de reversão por estrato de regime (ignora bordas não-rotuláveis)."""
    labels = np.asarray(labels, dtype=bool)
    reg = pd.Series(regime_series).reset_index(drop=True)
    out = {}
    # posições rotuláveis = onde regime é válido; bordas já vêm False mas
    # podem ser False legítimo -> usamos máscara de regime não-nulo como domínio.
    valid = reg.notna().values
    for r in reg[valid].unique():
        mask = (reg.values == r) & valid
        if mask.sum() == 0:
            continue
        out[str(r)] = float(labels[mask].mean())
    return out
