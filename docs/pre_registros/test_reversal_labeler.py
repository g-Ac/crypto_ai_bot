# test_reversal_labeler.py — roda standalone: `python test_reversal_labeler.py`
import numpy as np
import pandas as pd
from reversal_labeler import label_reversals, compute_baseline_rate


def test_reversao_clara_passa():
    # subida limpa e estável, depois colapso brusco >> 2 sigma
    n = 200
    rng = np.random.default_rng(0)
    base = np.cumsum(rng.normal(0.0, 0.001, n)) + 0.0005 * np.arange(n)  # leve alta + ruído baixo
    price = np.exp(base) * 100
    # injeta colapso de ~8% num candle perto do fim da zona rotulável
    crash_at = 150
    price[crash_at + 1:] *= 0.92
    labels = label_reversals(pd.Series(price), k=2.0, N=12, vol_window=96, M=12)
    # algum índice antes do crash, com prior de alta, deve marcar reversão
    assert labels[crash_at - 11: crash_at + 1].any(), "colapso de 8% após alta deveria marcar reversão"
    print("OK: reversão clara é rotulada")


def test_vol_normal_nao_passa():
    # random walk de baixa amplitude: poucas/nenhuma excursão > 2 sigma
    n = 400
    rng = np.random.default_rng(1)
    price = np.exp(np.cumsum(rng.normal(0.0, 0.002, n))) * 100
    labels = label_reversals(pd.Series(price), k=2.0, N=12, vol_window=96, M=12)
    rate = labels.mean()
    assert rate < 0.10, f"vol normal não deveria gerar taxa alta de reversão (got {rate:.3f})"
    print(f"OK: vol normal gera taxa baixa de reversão ({rate:.3f})")


def test_edge_regime_muda_no_meio():
    # rótulo é atribuído ao instante t (início), independente de o regime mudar dentro de (t, t+N].
    n = 200
    rng = np.random.default_rng(2)
    price = np.exp(np.cumsum(rng.normal(0.0, 0.001, n)) + 0.0005 * np.arange(n)) * 100
    price[150 + 1:] *= 0.90
    regime = pd.Series(["UP"] * 160 + ["DOWN"] * 40)  # muda em 160, depois do crash em 150
    labels = label_reversals(pd.Series(price), regime, k=2.0, N=12, vol_window=96, M=12)
    base = compute_baseline_rate(labels, regime)
    # determinístico e sem exceção; o rótulo do crash (t~150) cai no estrato UP (regime em t)
    assert "UP" in base and "DOWN" in base
    assert isinstance(base["UP"], float) and 0.0 <= base["UP"] <= 1.0
    print(f"OK: regime mudando no meio da janela é tratado deterministicamente {base}")


def test_anti_lookahead_sigma_so_passado():
    # se zerarmos toda a história futura após um ponto, sigma/dir em t<=ponto não muda
    n = 300
    rng = np.random.default_rng(3)
    price = np.exp(np.cumsum(rng.normal(0, 0.002, n))) * 100
    l_full = label_reversals(pd.Series(price), k=2.0, N=12, vol_window=96, M=12)
    cut = 200
    l_trunc = label_reversals(pd.Series(price[:cut]), k=2.0, N=12, vol_window=96, M=12)
    # rótulos em t < cut-N devem coincidir (sigma e dir só usam passado; alvo usa (t,t+N])
    comp = min(len(l_trunc), cut) - 12
    assert np.array_equal(l_full[:comp], l_trunc[:comp]), "rótulos não podem depender de dados após t+N"
    print("OK: sigma/direção usam só passado; rótulo estável sob truncamento futuro")


if __name__ == "__main__":
    test_reversao_clara_passa()
    test_vol_normal_nao_passa()
    test_edge_regime_muda_no_meio()
    test_anti_lookahead_sigma_so_passado()
    print("todos os testes do labeler passaram")
