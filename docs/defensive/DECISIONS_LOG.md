# DECISIONS LOG — Sistema de Trading Defensivo

**Inicio:** 2026-04-14

Registro de decisoes tecnicas e estrategicas. Cada entrada documenta o que foi decidido, por que, e quais alternativas foram descartadas.

---

## D1 — Terceira linha de edge, nao melhoria de pump/scalp

**Data:** 2026-04-14
**Contexto:** Bot existente tem pump (+78% PnL, depende de fat-tails, DD -47%) e scalping (quase inoperante, 6 trades em 8 dias). Gap: nao existe sistema que gere renda base com drawdown controlado.
**Decisao:** Criar terceiro subsistema com familia de edge diferente — deslocamento exagerado em contexto permissivo e retorno para valor. NAO tratar como "meio-termo" entre pump e scalp.
**Alternativa descartada:** Melhorar pump/scalp existentes. Rejeitado porque o edge de momentum/fat-tail tem fragilidade intrinseca que nao muda com tuning.
**Consequencia:** Novo namespace `defensive/` com isolamento forte.

---

## D2 — CFER como candidata principal (nao congelada)

**Data:** 2026-04-14
**Contexto:** 3 estrategias analisadas: CFER (Compression → Failed Expansion → Reversion), RAVR (Regime-Aware Value Reversion), AVDR (Anchored VWAP Displacement).
**Decisao:** CFER como candidata principal. Edge comportamental (traders presos) com menor risco de overfitting (padrao estrutural, ~5-6 parametros). Reutiliza ~85% da infra existente.
**Nao e decisao final:** CFER NAO esta congelada como vencedora. Backtest comparativo decide.
**Alternativa viva:** RAVR como benchmark obrigatorio no mesmo framework. Se RAVR (mais simples) performar igual, vence por simplicidade.
**Alternativa descartada:** AVDR — complexidade alta (multi-anchor VWAP, swing detection, tick data). Nao justifica para V1.

---

## D3 — RAVR como benchmark obrigatorio

**Data:** 2026-04-14
**Contexto:** Risco de apego a narrativa do CFER. A camada de trap pode ser complexidade sem retorno.
**Decisao:** RAVR roda nos mesmos periodos e com as mesmas metricas que CFER. Se RAVR >= CFER em PF e expectancy no periodo sobreposto, RAVR vence (mais simples = mais robusto). Empate tecnico (±10%): RAVR vence.
**Motivo:** Dados decidem, nao narrativa.

---

## D4 — Trap score como hipotese inicial, nao verdade

**Data:** 2026-04-14
**Contexto:** Pesos do trap scoring (OI: 35, Liq: 30, Crowding: 25, Basis: 15) foram definidos por logica qualitativa, nao por dados.
**Decisao:** Tratar pesos como hipotese. Validar por ablation no backtest com 7 variantes (baseline, trap simples, trap completa, sem OI, sem liq, sem secundarias, sem primarias).
**Criterio:** Se CFER_baseline performar igual a CFER_trap_full, a trap layer nao agrega e deve ser removida.
**Separacao:** Evidencias primarias (OI, Liquidation) podem confirmar sozinhas. Secundarias (Crowding, Basis) precisam de combinacao.

---

## D5 — Camada Enhanced precisa de ablation

**Data:** 2026-04-14
**Contexto:** CFER Enhanced depende de microestrutura que tem historico curto e pode nao estar disponivel em live.
**Decisao:** Backtest em duas camadas obrigatorias:
  - Baseline: OHLCV + BB + ATR + regime (periodo longo, 6-12m)
  - Enhanced: Baseline + trap scoring (periodo curto, limitado a dados de micro)
  Comparar no MESMO periodo sobreposto. Nunca comparar periodos de duracao diferente.
**Motivo:** Evitar conclusao errada por amostra desigual. Se Enhanced so tem 2 semanas de dados, comparar Baseline nesses mesmos 2 semanas.
**Feature dependency:** Sistema opera em degraded mode se dados de micro faltarem. Decision log registra o que estava disponivel vs faltando.

---

## D6 — Risco ultra-conservador na fase real 1

**Data:** 2026-04-14
**Contexto:** Capital inicial pequeno e precioso. Perda irrecuperavel no inicio inviabiliza o projeto.
**Decisao:**
  - 0.5% risk por trade (nao 1%)
  - 1 posicao por vez (nao 2)
  - Max daily loss: 1.5%
  - Cooldown apos 2 losses seguidos
  - Sem aumento de mao apos wins
  - Sem reentrada no mesmo lado apos stop (6 candles)
**Motivo:** Ultra-conservador no inicio. Escalar somente apos evidencia empirica (50 trades + PF > 1.5).
**Niveis de escalacao definidos:** V1 (0.5%) → V1.1 (0.75%) → V1.2 (1.0%) → V2 (1.5%).

---

## D7 — Win rate como metrica contextual, nao gate

**Data:** 2026-04-14
**Contexto:** Para estrategias de failed-breakout reversion, win rate pode ser "apenas ok" (50-55%) se RR e controle de perda compensarem. Colocar WR como hard gate pode rejeitar um sistema lucrativo.
**Decisao:** WR e metrica informativa (soft). Hard gates sao: PF, expectancy, DD, sample size, walk-forward consistency, regime stability, backtest-paper deviation.
**Motivo:** O que importa e expectancy (WR * avg_win - (1-WR) * avg_loss), nao WR isolado.

---

## D8 — Gates de paper/real ajustados para baixa frequencia

**Data:** 2026-04-14
**Contexto:** Frequencia esperada de 2-5 trades/semana. Gates originais de 30 trades em 4 semanas e 50 trades em 8 semanas eram agressivos demais.
**Decisao:**
  - Paper → Real: 4 semanas + 15 trades (realista para ~3 trades/semana)
  - Real → Escala: 8 semanas + 25 trades
  Se frequencia for menor que esperado, estender tempo (nao baixar trades).
**Motivo:** Coerencia entre seletividade da estrategia e criterios de validacao.

---

## D9 — Kill switches inegociaveis

**Data:** 2026-04-14
**Contexto:** Em live, dados podem falhar, exchange pode cair, regime pode mudar durante operacao.
**Decisao:** 3 kill switches que param o sistema imediatamente:
  1. Data Quality: dados stale/NaN/gap → pausa entradas
  2. Latency/Exchange: API timeout/erro → pausa entradas
  3. Regime Flip: regime muda durante posicao → fechamento imediato
**Motivo:** Risco de infraestrutura nao e risco de mercado. Nao operar no escuro.

---

## D10 — Integrar no repo existente com isolamento forte

**Data:** 2026-04-14
**Contexto:** Opcao entre repo separado e integracao. Auditoria mostrou que 80-85% da infra e reutilizavel (regime, microestrutura, risk, DB, audit, supervisor).
**Decisao:** Integrar com namespace `defensive/`, configs `DEFENSIVE_*`, tabelas proprias, state file proprio, backtest separado.
**Limite:** Se durante a implementacao a integracao forcar mudancas invasivas no pump/scalp, migrar para repo separado.
**Criterio de integracao saudavel:** modificacoes no codigo existente < 200 linhas.

---

## Template para novas decisoes

```
## D[N] — [Titulo curto]

**Data:** YYYY-MM-DD
**Contexto:** [Situacao que levou a decisao]
**Decisao:** [O que foi decidido]
**Alternativa descartada:** [O que foi considerado e rejeitado, e por que]
**Consequencia:** [O que muda no projeto por causa dessa decisao]
```

---

## D11 — CFER v0.1 declarada morta

**Data:** 2026-04-14
**Contexto:** Bloco 4.5 executou matriz completa: BTC+ETH, 6 meses (17.280 candles cada), 3 cenários (base, stress slippage, stress full), walk-forward 3 janelas. Resultado: **zero trades em todas as combinações**.
**Causa raiz:** Compressão e volume spike são mutuamente exclusivos no 15m. Auditoria com dados brutos mostrou:
- 609 candles com compressão ativa
- 7 vezes close saiu da BB durante compressão (1.1%)
- 0 vezes com volume spike (volume médio durante compressão: 0.62x, máximo: 1.20x)
- O padrão "compressão + breakout com volume + reclaim em 3 candles" não existe de forma operável no BTC/ETH 15m
**Decisao:** CFER v0.1 é inviável na forma atual. NO-GO para paper trading. NO-GO para Enhanced (se Baseline não gera amostra, trap score não salva nada).
**O que NÃO morreu:** O projeto, a infraestrutura, a possibilidade de v0.2 com design diferente, a alternativa RAVR.
**Próximo passo:** Uma tentativa de resgate (v0.2) com compressão como estado anterior + volume como confirmação secundária. Se v0.2 não gerar amostra razoável, pivotar para RAVR.

---

## D12 — CFER v0.2: separação temporal compressão/breakout

**Data:** 2026-04-14
**Contexto:** D11 mostrou que compressão e breakout são quase mutuamente exclusivos quando exigidos no mesmo candle. A ideia de failed breakout pode existir, mas a forma de detectar estava errada.
**Decisao:** v0.2 muda o modelo conceitual:
1. Compressão vira estado anterior — marcada numa janela de N candles antes do breakout
2. Breakout não exige compressão ativa no mesmo instante — basta que tenha havido compressão recente
3. Volume spike deixa de ser requisito obrigatório — vira confirmação secundária ou comparativo
4. Reclaim window expandida (3→6 candles)
**Kill criteria:** Se v0.2 gerar <20 trades em 6 meses para BTC+ETH, matamos a família CFER como motor principal e pivotamos para RAVR.
**Alternativa descartada:** Relaxar todos os parâmetros indiscriminadamente (viraria "qualquer toque na BB").

---

## D13 — CFER v0.2 morta: edge inexistente com amostra suficiente

**Data:** 2026-04-14
**Contexto:** v0.2 rodou com separação temporal (compression_memory_window=12, breakout_require_volume=False, breakout_reclaim_window=6). Bug de cooldown deadlock corrigido durante a execução (2 losses consecutivos bloqueavam para sempre).
**Resultado empirico:**
- BTC: 93 trades, PF=0.39, WR=24.7%, Max DD=18.7%, PnL=-17.9%
- ETH: 88 trades, PF=0.43, WR=30.7%, Max DD=21.4%, PnL=-20.6%
- Walk-forward: BTC 1/3 positivo (marginal), ETH 0/3
- Stress tests: deterioração adicional (PF→0.22-0.29)
**Causa raiz:** O padrão "close fora da BB após compressão recente + reclaim" NÃO tem edge no BTC/ETH 15m. WR ~28% precisaria de RR ≥ 2.6 para breakeven; o RR realizado fica muito abaixo.
**Decisao:** Família CFER declarada morta como motor principal. v0.1 morreu por falta de amostra (0 trades). v0.2 morreu por falta de edge (181 trades, tudo negativo).
**O que sobrevive:** Infraestrutura inteira (backtest engine, metrics, persistence, walk-forward, stress tests, data fetcher, report builder). Tudo reutilizável para próxima estratégia.
**Próximo passo:** Pivotar para RAVR ou nova estratégia usando o mesmo framework. RAVR precisa de path próprio no engine (atualmente apenas logga decisions, não executa trades).
**Alternativa descartada:** Tentar v0.3 com mais ajustes — 181 trades com PF<0.5 não é problema de parâmetros, é ausência fundamental de edge.

---

## D14 — Pivot para RAVR como motor principal V1

**Data:** 2026-04-14
**Contexto:** CFER morta (D11, D13). Infraestrutura sobreviveu. Gabriel decidiu pivot imediato para RAVR, sem inventar estratégia nova.
**Decisao:** RAVR promovida de benchmark para candidata principal V1.
**Design RAVR v1:**
1. Regime gate: só RANGING/WEAK_TREND
2. Referência de valor: VWAP rolling 24h (96 candles de 15m)
3. Sinal: z-score >= 2.0 (preço a 2+ desvios-padrão da VWAP)
4. Direção: contra o desvio (z>0 → SHORT, z<0 → LONG)
5. TP1: return-to-VWAP (parcial 50%, breakeven após)
6. TP2: extensão 50% além da VWAP
7. SL: ATR × 1.5 (estrutural)
8. Timeout: 12 candles (3h)
**Parâmetros congelados:** z=2.0, VWAP=24h, ATR×1.5, timeout=12. Sem tuning antes da primeira matriz.
**Avaliação em 2 fases:** (1) amostra suficiente? distribuição razoável? (2) só depois: PF, expectancy, DD, stress.
**Alternativa descartada:** CFER v0.3, microestrutura nova, 4ª estratégia — nenhuma justificada sem dados.
**Consequência:** ~80 linhas de código novo no engine (RAVR execution path). 100% da infra existente reutilizada.
