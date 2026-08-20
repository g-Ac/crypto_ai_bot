# EXP-014 — Trend-following diario (BTC/ETH/SOL)

_Teste final. Parametros congelados: ADX>25, ATR14, stop 2*ATR, trailing 3*ATR. Custo 0.10% round-trip. Inconclusivo = NO-GO._


## BTCUSDT  (n=28 estacoes, 14L/14S)
- **A1 liquido:** ret bruto +12.1% / liquido +9.3% | PF 1.14 | win 12/28
- **A2 vs aleatorio:** PF real percentil **74%** do null (med 0.81) NAO bate (>=90 exigido)
- **A3 vs buy-and-hold:** estrategia +9.3% vs B&H +3.7% -> BATE
- **A4 concentracao:** top-1 = 25% do lucro, top-2 = 40% 
- **A5 bootstrap IC95 do PF:** [0.36, 3.19] cruza 1.0 (inconclusivo)

## ETHUSDT  (n=28 estacoes, 15L/13S)
- **A1 liquido:** ret bruto +69.5% / liquido +66.7% | PF 2.16 | win 13/28
- **A2 vs aleatorio:** PF real percentil **96%** do null (med 0.78) BATE
- **A3 vs buy-and-hold:** estrategia +66.7% vs B&H -47.4% -> BATE
- **A4 concentracao:** top-1 = 29% do lucro, top-2 = 49% 
- **A5 bootstrap IC95 do PF:** [0.65, 6.16] cruza 1.0 (inconclusivo)

## SOLUSDT  (n=23 estacoes, 12L/11S)
- **A1 liquido:** ret bruto +11.6% / liquido +9.3% | PF 1.09 | win 7/23
- **A2 vs aleatorio:** PF real percentil **51%** do null (med 1.08) NAO bate (>=90 exigido)
- **A3 vs buy-and-hold:** estrategia +9.3% vs B&H -50.6% -> BATE
- **A4 concentracao:** top-1 = 34% do lucro, top-2 = 64% (FRAGIL: 1-2 trades carregam)
- **A5 bootstrap IC95 do PF:** [0.19, 3.05] cruza 1.0 (inconclusivo)

---
## Veredito (GO so se as 4: liquido+, bate-aleatorio, bate-B&H, nao-concentrado)
- BTCUSDT: liq+ alea- bnh+ conc+ IC-cruza1(inconclusivo)  ->  **NO-GO (inconclusivo)**
- ETHUSDT: liq+ alea+ bnh+ conc+ IC-cruza1(inconclusivo)  ->  **NO-GO (inconclusivo)**
- SOLUSDT: liq+ alea- bnh+ conc- IC-cruza1(inconclusivo)  ->  **NO-GO (inconclusivo)**

**Pooled** (n=79, correlacionado): PF 1.37, IC95 [0.69, 2.48] cruza 1.0

## LINHA BTC/ETH/SOL: **NO-GO — FECHADA**
Inconclusivo/morno foi pre-selado como NO-GO. ~25 estacoes/simbolo (correlacionadas) nao distinguem edge de drift+saida com confianca.
