# Breakout regime/follow-through autopsy

Status: DISCOVERY / READ-ONLY. Usa somente os 31 trades filled do shadow anterior; não altera bot.

- input: `/home/pi/crypto_ai_bot/reports/breakout_compression_shadow_2026-06-12.csv`
- output csv: `/home/pi/crypto_ai_bot/reports/breakout_regime_followthrough_autopsy_2026-06-12.csv`
- horizons: 1, 2, 3, 4, 8, 12 candles de 5m
- good_regime definido antes desta autópsia: TRENDING + WEAK_TREND

## Base por grupo

| grupo | n | net | avg | median | WR | PF | TP1% | false_breakout% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ALL | 31 | -3.1279% | -0.1009% | -0.5729% | 32.3% | 0.79 | 32.3% | 67.7% |
| GOOD_REGIME TRENDING+WEAK_TREND | 20 | +1.6330% | +0.0816% | -0.4631% | 45.0% | 1.20 | 45.0% | 55.0% |
| BAD_REGIME RANGING+VOLATILE | 11 | -4.7609% | -0.4328% | -0.6993% | 9.1% | 0.27 | 9.1% | 90.9% |
| WINNERS | 10 | +11.6538% | +1.1654% | +1.2369% | 100.0% | inf | 100.0% | 0.0% |
| LOSERS | 21 | -14.7817% | -0.7039% | -0.7612% | 0.0% | 0.00 | 0.0% | 100.0% |

## Early MFE/MAE: winners vs losers

| grupo | h | median MFE | median MAE | median MFE/TP1 | back_inside% | close_against% |
|---|---:|---:|---:|---:|---:|---:|
| GOOD_REGIME TRENDING+WEAK_TREND | 1 | 0.1712% | 0.1039% | 0.20 | 35.0% | 35.0% |
| GOOD_REGIME TRENDING+WEAK_TREND | 2 | 0.2733% | 0.1616% | 0.24 | 40.0% | 50.0% |
| GOOD_REGIME TRENDING+WEAK_TREND | 3 | 0.3115% | 0.2001% | 0.28 | 50.0% | 55.0% |
| GOOD_REGIME TRENDING+WEAK_TREND | 4 | 0.3156% | 0.2320% | 0.29 | 50.0% | 55.0% |
| GOOD_REGIME TRENDING+WEAK_TREND | 8 | 0.4981% | 0.3082% | 0.46 | 35.0% | 35.0% |
| GOOD_REGIME TRENDING+WEAK_TREND | 12 | 0.7095% | 0.4241% | 0.53 | 55.0% | 60.0% |
| BAD_REGIME RANGING+VOLATILE | 1 | 0.0951% | 0.1758% | 0.08 | 54.5% | 54.5% |
| BAD_REGIME RANGING+VOLATILE | 2 | 0.1641% | 0.3312% | 0.14 | 81.8% | 81.8% |
| BAD_REGIME RANGING+VOLATILE | 3 | 0.1641% | 0.4717% | 0.14 | 81.8% | 90.9% |
| BAD_REGIME RANGING+VOLATILE | 4 | 0.1641% | 0.4717% | 0.14 | 63.6% | 81.8% |
| BAD_REGIME RANGING+VOLATILE | 8 | 0.1641% | 0.4961% | 0.14 | 90.9% | 90.9% |
| BAD_REGIME RANGING+VOLATILE | 12 | 0.1641% | 0.5513% | 0.14 | 81.8% | 81.8% |
| WINNERS | 1 | 0.2899% | 0.1379% | 0.26 | 30.0% | 30.0% |
| WINNERS | 2 | 0.3260% | 0.1620% | 0.30 | 30.0% | 40.0% |
| WINNERS | 3 | 0.4438% | 0.2281% | 0.34 | 40.0% | 50.0% |
| WINNERS | 4 | 0.4474% | 0.2421% | 0.34 | 30.0% | 30.0% |
| WINNERS | 8 | 0.7841% | 0.2671% | 0.58 | 20.0% | 20.0% |
| WINNERS | 12 | 1.1451% | 0.3087% | 0.90 | 30.0% | 30.0% |
| LOSERS | 1 | 0.1509% | 0.1494% | 0.12 | 47.6% | 47.6% |
| LOSERS | 2 | 0.1989% | 0.2165% | 0.20 | 66.7% | 71.4% |
| LOSERS | 3 | 0.1989% | 0.2318% | 0.20 | 71.4% | 76.2% |
| LOSERS | 4 | 0.1989% | 0.2496% | 0.20 | 66.7% | 81.0% |
| LOSERS | 8 | 0.2851% | 0.4717% | 0.23 | 71.4% | 71.4% |
| LOSERS | 12 | 0.3157% | 0.5513% | 0.23 | 81.0% | 85.7% |

## Teste diagnóstico de invalidação rápida

Hipóteses simuladas só como diagnóstico: se no candle H o close voltou para dentro da consolidação, sair no close_H; ou se fechou contra a entrada, sair no close_H. Se a condição não ocorre, mantém o resultado real shadow.

| universo | regra | H | net | delta vs real | PF | WR |
|---|---|---:|---:|---:|---:|---:|
| ALL | back_inside | 1 | -1.9967% | +1.1312% | 0.82 | 22.6% |
| ALL | close_against | 1 | -1.9967% | +1.1312% | 0.82 | 22.6% |
| ALL | back_inside | 2 | -2.6378% | +0.4901% | 0.76 | 22.6% |
| ALL | close_against | 2 | -3.1298% | -0.0019% | 0.70 | 19.4% |
| ALL | back_inside | 3 | -4.5836% | -1.4557% | 0.60 | 19.4% |
| ALL | close_against | 3 | -4.7386% | -1.6107% | 0.57 | 16.1% |
| ALL | back_inside | 4 | -4.0158% | -0.8879% | 0.68 | 22.6% |
| ALL | close_against | 4 | -2.1497% | +0.9782% | 0.80 | 22.6% |
| GOOD_REGIME | back_inside | 1 | +0.6761% | -0.9569% | 1.10 | 30.0% |
| GOOD_REGIME | close_against | 1 | +0.6761% | -0.9569% | 1.10 | 30.0% |
| GOOD_REGIME | back_inside | 2 | -0.3940% | -2.0270% | 0.95 | 30.0% |
| GOOD_REGIME | close_against | 2 | -0.8860% | -2.5190% | 0.86 | 25.0% |
| GOOD_REGIME | back_inside | 3 | +0.8537% | -0.7793% | 1.14 | 30.0% |
| GOOD_REGIME | close_against | 3 | +0.1218% | -1.5112% | 1.02 | 25.0% |
| GOOD_REGIME | back_inside | 4 | +0.4147% | -1.2183% | 1.06 | 30.0% |
| GOOD_REGIME | close_against | 4 | +1.0993% | -0.5337% | 1.19 | 30.0% |
| BAD_REGIME | back_inside | 1 | -2.6728% | +2.0881% | 0.40 | 9.1% |
| BAD_REGIME | close_against | 1 | -2.6728% | +2.0881% | 0.40 | 9.1% |
| BAD_REGIME | back_inside | 2 | -2.2438% | +2.5171% | 0.44 | 9.1% |
| BAD_REGIME | close_against | 2 | -2.2438% | +2.5171% | 0.44 | 9.1% |
| BAD_REGIME | back_inside | 3 | -5.4373% | -0.6764% | 0.00 | 0.0% |
| BAD_REGIME | close_against | 3 | -4.8603% | -0.0994% | 0.00 | 0.0% |
| BAD_REGIME | back_inside | 4 | -4.4305% | +0.3304% | 0.28 | 9.1% |
| BAD_REGIME | close_against | 4 | -3.2490% | +1.5119% | 0.35 | 9.1% |

## Leitura fria

- Regime direcional continua sendo a única pista: GOOD_REGIME n=20 net=+1.6330% PF=1.20; BAD_REGIME n=11 net=-4.7609% PF=0.27.
- Porém a amostra é pequena e ainda discovery. Isso não autoriza bot.
- Se uma regra de invalidação rápida melhora o universo GOOD_REGIME sem depender do BAD_REGIME, ela pode virar EXP congelado. Se só melhora removendo RANGING/VOLATILE, o EXP correto é regime-gate, não microgerenciamento.
- Não alterar executor/bot com base neste relatório.

