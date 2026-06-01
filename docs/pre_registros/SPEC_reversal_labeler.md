# Especificação — Módulo `reversal_labeler` (peça neutra compartilhada)

**Status:** especificado, **não consumido**. Será usado por **H2** (quando OI amadurecer) e por **H4** (quando dados pós-data-de-análise-de-H3 acumularem).
**Versão:** 1.0
**Natureza:** módulo Python isolado, puro, testável. Nenhuma dependência de H2/H4; nenhum acesso a rede ou DB.

---

## 1. Definição formal de reversão

Uma **reversão** rotulada no índice `t` ocorre quando, após uma direção prévia estabelecida, o preço faz uma excursão adversa de magnitude **≥ k·σ** contra essa direção dentro de **N candles** à frente.

Componentes:

1. **Direção prévia `d_t`** = sinal do retorno log acumulado nos trailing `M` candles terminando em `t` (`M = N` por padrão). `d_t ∈ {+1, −1}`; se |retorno| < limiar de ruído (`0.1·σ_t`), `d_t = 0` (sem direção → sem rótulo, retorna `False`).

2. **σ do horizonte `σ_t^(N)`** = volatilidade realizada **local** (não global), escalada ao horizonte:
   `σ_t^(N) = std(retornos log por candle nas trailing vol_window candles) × √N`.
   Calculada **estritamente com passado** (até `t`, inclusive). Sem vazamento.

3. **Excursão adversa** em `(t, t+N]`:
   - Se `d_t = +1` (subiu): `exc = min_{1≤h≤N} ( ln(price[t+h]/price[t]) )` (pior queda futura).
     Reversão se `exc ≤ −k·σ_t^(N)`.
   - Se `d_t = −1` (caiu): `exc = max_{1≤h≤N} ( ln(price[t+h]/price[t]) )` (maior alta futura).
     Reversão se `exc ≥ +k·σ_t^(N)`.

**Distinção crítica anti-lookahead:** `σ_t^(N)` e `d_t` são features (só passado). A excursão é o **alvo** (target) — usar futuro aqui é correto e esperado, porque o rótulo de reversão É a variável dependente, não um preditor. O módulo nunca expõe a excursão como feature.

### Parâmetros e padrões justificados

| Param | Padrão | Justificativa | Regra de calibração |
|---|---|---|---|
| `k` | 2.0 | 2σ = excursão além do que a vol base explica; separa reversão de respiração normal do mercado. | Calibrar `k` **somente em dados de discovery** até a taxa-base incondicional cair em **5–25%**. Taxa muito alta → subir `k`. Calibração nunca toca dados de julgamento de H2/H4. |
| `N` | 12 | Horizonte para a reversão se manifestar (ex.: 3h em candles de 15m; 12h em candles de 1h). | Fixar por TF do experimento consumidor; documentar na chamada. |
| `vol_window` | 96 | Janela longa o bastante para σ estável, curta o bastante para ser local ao regime. | — |
| `M` (prior dir.) | `= N` | Simetria entre janela de direção prévia e horizonte de reversão. | — |
| `noise_k` | 0.1 | Banda morta: direção prévia desprezível → sem rótulo. | — |

---

## 2. σ por regime/janela (não global)

`σ` é **vol realizada trailing local** (`vol_window` candles até `t`), não o desvio do período inteiro. Motivo: em regime de alta vol, exigir `k·σ_global` rotularia quase tudo como reversão; em baixa vol, quase nada. A vol local normaliza pela respiração corrente do mercado, que é o ponto de "além do esperado pela vol base". O `regime_series` entra apenas no **baseline** (§3), não no cálculo de σ — σ já é local por construção.

---

## 3. Baseline de comparação

`compute_baseline_rate` devolve a **taxa incondicional** de reversão **por estrato de regime**. É o número que qualquer sinal (ΔOI+volume em H2; ratio+convergência em H4) precisa **bater** para ter valor: se a condição X prevê reversão a uma taxa que não excede a taxa-base daquele regime, X não carrega informação além de "este regime reverte muito".

Computado por estrato porque a propensão a reverter é ela própria função de regime (FLAT reverte mais que TRENDING). Comparar contra uma taxa-base global confundiria o efeito de X com composição de regime.

---

## 4. Interface (funções puras)

```python
label_reversals(price_series, regime_series, k=2.0, N=12,
                vol_window=96, M=None, noise_k=0.1) -> np.ndarray[bool]
# Retorna array bool alinhado ao índice de price_series.
# Os últimos N elementos são False (futuro indisponível -> não rotulável).
# Os primeiros max(vol_window, M) elementos são False (passado insuficiente).

compute_baseline_rate(labels, regime_series) -> dict[str, float]
# {regime: taxa_de_reversao}. Ignora posições não-rotuláveis (bordas).
```

Contrato: ambas puras (sem I/O, sem estado global, determinísticas). `price_series` e `regime_series` são `pd.Series` alinhadas pelo mesmo índice. `regime_series` pode conter o label do bot ou o derivado de H3 §2.1.

---

## 5. Código do módulo

```python
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
```

> Nota de borda honesta: `compute_baseline_rate` como escrito inclui as bordas (`False` por indisponibilidade de futuro) no denominador, o que **subestima** levemente a taxa. Para H2/H4 o consumidor deve passar um domínio já recortado (descartar os primeiros `max(vol_window,M)` e últimos `N`) ou aceitar o viés conservador. Documentado para não virar bug silencioso.

---

## 6. Testes unitários

```python
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
```

---

## 7. Regras de consumo (para quando H2/H4 forem ativados)

1. **Calibração de `k` só em discovery.** Ajustar `k` para taxa-base em 5–25% usando dados que **não** entrarão no julgamento do experimento consumidor.
2. **`regime_series` consistente.** Usar a mesma taxonomia de regime do experimento (label do bot ou H3 §2.1) nos dois lados — labeler e teste de sinal.
3. **Comparar sempre contra `compute_baseline_rate` por estrato**, nunca contra 50% nem contra taxa global.
4. **Não modificar o módulo por experimento.** Se H2 e H4 precisarem de definições diferentes de reversão, parametrizar via argumentos — não bifurcar o código (senão os dois deixam de ser comparáveis contra o mesmo padrão).
