# Historico de Trades do Agent Trader

Data da auditoria: 2026-04-08

## Nota sobre "12 trades"

A contagem de "12 trades" do usuario inclui trades de TODAS as instancias do bot (bot.db principal + runtime/v2 + runtime/baseline). Na realidade, o banco principal (bot.db) tem **11 registros** e o agent_state.json mostra **4 trades fechados** (2W/2L = 50% WR, nao 0%).

As instancias runtime/v2 e runtime/baseline tem trades ABERTOS que nunca fecharam (posicoes orfas).

---

## Trades Fechados (bot.db) - 4 trades com resultado

### Trade 1: DOGEUSDT LONG -> LOSS (-0.57%)
| Campo | Valor |
|-------|-------|
| Abertura | 2026-03-25 02:32:08 |
| Fechamento | 2026-03-25 22:59:14 |
| Duracao | ~20.5 horas |
| Entry | 0.09621 |
| Exit | 0.09566 |
| SL | 0.095248 / TP | 0.098134 |
| Motivo saida | opposite_signal |
| Confidence Haiku | 100 |
| P&L | -0.57% (-$11.43) |
| Observacao | Saiu por sinal oposto, nao atingiu SL nem TP. Confidence 100 = Haiku totalmente confiante num trade que perdeu. |

### Trade 2: BTCUSDT LONG -> WIN (+0.24%)
| Campo | Valor |
|-------|-------|
| Abertura | 2026-03-25 02:08:25 |
| Fechamento | 2026-03-25 23:11:13 |
| Duracao | ~21 horas |
| Entry | 70982.88 |
| Exit | 71153.35 |
| SL | 68853.39 / TP | 75241.85 |
| Motivo saida | opposite_signal |
| Confidence Haiku | 100 |
| P&L | +0.24% (+$4.80) |
| Observacao | "Ganhou" mas P&L minimo (+0.24%) vs TP de +6%. Saiu por opposite_signal muito cedo. |

### Trade 3: ETHUSDT LONG -> LOSS (-0.58%)
| Campo | Valor |
|-------|-------|
| Abertura | 2026-03-25 02:45:31 |
| Fechamento | 2026-03-25 23:11:13 |
| Duracao | ~20.4 horas |
| Entry | 2173.13 |
| Exit | 2160.53 |
| SL | 2107.94 / TP | 2303.52 |
| Motivo saida | opposite_signal |
| Confidence Haiku | 100 |
| P&L | -0.58% (-$11.60) |
| Observacao | Mesmo padrao: Confidence 100, saiu por sinal oposto com prejuizo pequeno. |

### Trade 4: DOGEUSDT SHORT -> WIN (+2.00%)
| Campo | Valor |
|-------|-------|
| Abertura | 2026-03-25 22:59:18 |
| Fechamento | 2026-03-26 02:50:08 |
| Duracao | ~3.8 horas |
| Entry | 0.09566 |
| Exit | 0.09322 (TP hit) |
| SL | 0.096617 / TP | 0.093747 |
| Motivo saida | take_profit |
| Confidence Haiku | 92 |
| P&L | +2.00% (+$39.95) |
| Observacao | UNICO trade que atingiu TP. Ironicamente, confidence 92 (menor que os outros 100s). |

---

## Posicoes Abertas (Orfas) - bot.db / agent_state.json

### BTCUSDT SHORT (aberto desde 2026-03-25 23:11:17)
- Entry: 71153.35 | SL: 73287.95 | TP: 66884.15
- Confidence: 92
- **13 dias aberto sem fechar** - provavel SL hit (BTC hoje ~$80K+)

### ETHUSDT SHORT (aberto desde 2026-03-25 23:11:20)
- Entry: 2160.53 | SL: 2225.35 | TP: 2030.90
- Confidence: 100
- **13 dias aberto sem fechar** - SL certamente ultrapassado

### XRPUSDT SHORT (aberto desde 2026-03-26 03:26:20)
- Entry: 1.3883 | SL: 1.4161 | TP: 1.3328
- Confidence: 100
- **13 dias aberto sem fechar** - provavelmente stopped out

---

## Posicoes Orfas em runtime/v2 (capital: $285.71)

3 LONGs abertos desde 2026-03-31 + 1 SHORT, nenhum fechado (total_trades: 0).
Capital caiu de $10K para $285.71 (nao explicado pelo DB — possivel bug de state).

---

## Posicoes Orfas em runtime/baseline

3 LONGs abertos desde 2026-03-31, nenhum fechado (total_trades: 0).

---

## Resumo por Trade

| # | Symbol | Direcao | Conf. | Saida | P&L % | Problema |
|---|--------|---------|-------|-------|-------|----------|
| 1 | DOGE | LONG | 100 | opposite_signal | -0.57 | Overconfident, saida prematura |
| 2 | BTC | LONG | 100 | opposite_signal | +0.24 | Win minimo, nao atingiu TP |
| 3 | ETH | LONG | 100 | opposite_signal | -0.58 | Overconfident, saida prematura |
| 4 | DOGE | SHORT | 92 | take_profit | +2.00 | OK - unico TP hit |
| 5* | BTC | SHORT | 92 | ABERTO 13d | ??? | Orfa, SL certamente ultrapassado |
| 6* | ETH | SHORT | 100 | ABERTO 13d | ??? | Orfa, SL certamente ultrapassado |
| 7* | XRP | SHORT | 100 | ABERTO 13d | ??? | Orfa, SL certamente ultrapassado |

*Posicoes orfas que o bot parou de monitorar (provavelmente quando mudou para runtime/v2).

**Performance real considerando orfas: 1W/2L dos fechados + 3 SL provavies das orfas = ~1W/5L = 17% WR**
