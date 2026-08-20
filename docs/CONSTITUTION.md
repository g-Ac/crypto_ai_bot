# Constituição do crypto_ai_bot

> **O crypto_ai_bot é um laboratório forward-only para encontrar estrutura de mercado
> que pague custo real — sem precisar prever direção. Não é fonte de renda. Só vira
> executor quando uma hipótese provar edge líquido robusto fora do backtest.**

Adotada em 2026-06-09. Consolida decisões já em vigor: alocação 80/20 (2026-05-13),
lab de descoberta vs defesa de estratégia (2026-05-27) e reorientação
estrutura-que-paga (2026-06-01). Emendas só por commit explícito — nunca no meio
de uma análise.

## Princípios

1. **Capturar estrutura que paga, sem precisar prever direção.** A virada madura do
   projeto foi sair de "prever direção" para "capturar estrutura que paga sem prever".
2. O bot é laboratório, não fonte de renda. Renda real vem de fora dele (80/20).
3. O objetivo atual é aprendizado confiável. Sucesso se mede em veredictos
   confiáveis por unidade de tempo e custo — não em PnL paper.
4. Matar hipótese ruim rápido e barato é vitória.
5. A primeira pergunta é sempre: **"quanto posso perder se estiver errado?"**
6. Edge bruto sem edge líquido é inválido. Toda estratégia paga custo real.
7. Sizing otimiza distribuição; sizing não cria edge.
8. Resultado limpo vale mais que resultado conveniente. GO sem robustez é NO-GO.

## Custo canônico

```text
fee canônica       = 0.05% por lado (taker real Binance USDT-M Futures VIP 0)
round-trip         = 0.10% = 10 bps
slippage           = 0 por enquanto — limitação conhecida e declarada, não modelada
                     (sem book/spread real, número inventado seria falsa precisão)
edge bruto sem net = inválido
```

Nota: `SINGLE_SIDE_FEE_PCT = 0.04` em `config.py` é a taxa taker antiga, mantida
por compatibilidade com dados históricos do scalping. Não usar em experimento novo.

## Leis do lab (critérios mínimos)

1. Pré-registro antes de tocar o dado. Escavação com IC/baseline já é quase-experimento.
2. Custo canônico embutido em toda métrica.
3. Margem mínima ≥ **50 bps/trade net** sobre baseline, salvo critério diferente
   fixado no pré-registro **antes** da análise.
4. n ≥ **30 por estrato** quando houver análise estratificada.
5. Lift **incremental ao regime**, não na média agregada (não renegociável).
6. Walk-forward obrigatório para qualquer filtro categórico (sessão/asset/regime).
7. Nenhum critério se relaxa durante a análise.
8. Backtest sem custo real é inválido.
9. PF é métrica auxiliar (floor sugerido: PF net ≥ 1.10); margem em bps/trade net
   é preferível em amostras pequenas. Winrate sozinho não prova edge.

## NO-GOs

**Mortos para sempre (lei estrutural):**
- Qualquer edge que precise ignorar fee/custo para parecer bom.
- Price-action em timeframe curto com stop apertado quando a anatomia fee/R mata a
  expectativa (rejeição a priori — não precisa rodar).
- Martingale, grid infinito, revenge trading, dobrar após loss.
- Alavancagem como "rescue" de estratégia sem edge.

**Mortos com dados** (não reabrir a mesma pergunta no mesmo dataset procurando GO —
detalhes em `docs/EXPERIMENT_REGISTRY.md`): PB25, BE50, session filter, hourly
sizing, breakout 5m, pair trading (EXP-004), micro-posição 1m/5m, router (EXP-006),
sinal de entrada (EXP-013), trend following diário (EXP-014), LSR vanilla (H3).
Reabertura exige mecanismo novo, dado forward novo ou hipótese diferente — sempre
com pré-registro formal.

### Cláusula de reabertura

Experimentos mortos não são reabertos por performance histórica, tuning ou melhoria
retrospectiva de métricas. Só reabrem se uma autópsia, dado novo out-of-sample ou
mudança estrutural de mercado identificar hipótese mecânica nova, não testada, com
plausibilidade quantificada de sobreviver a custo. Para estratégias com ciclo de
execução comparável ao caso pairs/stat-arb, a régua mínima é edge bruto a priori
≥ 2× o custo total de ciclo. Toda reabertura exige pré-registro e validação
forward-only.

**Pausados com condição (não são mortos):**
- EXP-005 universe expansion — pausado, não morto.
- Funding BTC (EXP-011) — NO-GO de margem (46.1 vs 50 bps); watchlist, 1º da fila
  pós-pausa, forward-only.
- R2 crowded squeeze — re-testar com janela limpa ~2026-07-13, se ainda fizer sentido.

## Live trading

Não-prioritário — não proibido para sempre. Live só pode existir com **todas** as
condições: edge líquido robusto com custo real embutido; walk-forward aprovado;
pré-registro respeitado; cooling-off mínimo de 7 dias entre decisão e ativação;
ativação manual explícita do operador. **Nunca por default. Nunca por restore.
Nunca por automação.**
