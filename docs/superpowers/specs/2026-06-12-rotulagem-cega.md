# Rotulagem cega — valida se o olho do Gabriel separa trade bom de ruído

**Data:** 2026-06-12 · **Status:** Fases 1-2 entregues (motor + tela). Fase 3 (revelação) pendente.

## Por quê

O momentum v1.1 executa pullback-continuação **mecanicamente** e morre no custo
(PF 1.32 bruto → 0.88 líquido em 158 trades). O Gabriel, olhando os trades plotados,
viu que **poucos são pullback de verdade; o resto é ruído** que entra e sai perdedor —
e que o discriminador é **contexto estrutural** (nível, "renovou máxima?") que o bot é cego.

Hipótese: o edge não está em *entrar* no pullback (o bot já faz e perde) — está na
**seleção**. Este experimento testa se o olho do Gabriel, cego ao resultado, separa os
vencedores dos perdedores.

## Método

1. Rotular os 158 `momentum_trades` **um a um, sem ver o resultado** — só o gráfico 15m
   até o instante da entrada, com fundos/suportes marcados.
2. Para cada trade: veredito **gostei / não** + as 4 pistas (empurrão · nível · direção ·
   recuo confirmou) + **palpite de saída** (clique no gráfico → preço).
3. Começar por um **piloto de ~30-40**, não os 158 de cara.
4. Na revelação (Fase 3): cruzar veredito × `net_pnl_pct` real.

## Invariante crítico — CEGUEIRA

`/api/rotulagem/next` **nunca** pode incluir `exit_reason`, `pnl`, `sl/tp`, `mfe/mae`,
`exit_time`. Se o olho vê o resultado, o cérebro inventa a regra óbvia (hindsight) e o
experimento morre. Travado em `tests/test_rotulagem_endpoints.py::test_next_nao_vaza_resultado`.

## Critério de leitura (Fase 3) — anti stealth-backtest

- **Sinal:** "gostei" tem `net_pnl` materialmente melhor que "não" **E** segura num split
  temporal (1ª metade vs 2ª metade dos rótulos). Só agregado não vale — walk-forward.
- **Nulo é resultado bom:** se o olho não separa, a conclusão é que o edge mora no contexto
  ainda não medido → instrumentar nível/estrutura no desk operacional (fase futura), não
  forçar um GO.
- A **saída** emerge dos `exit_price_guess` comparados ao MFE real — não se infere de média.

## Arquitetura

| Camada | Arquivo |
|---|---|
| Persistência dos rótulos (`blind_labels`) | `rotulagem_data.py` |
| Fundos/topos/suportes (geometria pura) | `rotulagem_levels.py` |
| Busca cega de candles (Binance REST, corte no entry) | `rotulagem_candles.py` |
| Endpoints `/rotulagem`, `/api/rotulagem/{next,label}` | `dashboard_server.py` |
| Tela | `templates/rotulagem.html` + `static/js/rotulagem.js` |

Fonte de OHLC: **Binance REST `/fapi/v1/klines`** com `endTime` no entry (o endpoint
`/api/raiox/candles` não serve — rebaixa 15m→4h no histórico e vaza o pós-entrada).

## Fora do escopo (fase futura)

Desk operacional ao vivo: marcação manual de zonas, DNA da moeda (volatilidade · regime ·
funding · correlação BTC · respeita-níveis), 1m/5m. Só depois que a rotulagem provar o olho.
