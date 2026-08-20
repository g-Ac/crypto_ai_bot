# Etapa 0 — Validação da semântica do `side` em `k_liquidations`

**Status:** ✅ **RESOLVIDA 2026-07-01** — semântica validada empiricamente (Opção A, t±1h).
**Bloqueava:** PROP-20260701-01, PROP-20260701-02.
**Natureza:** diagnóstica — não olhou retorno futuro como sinal.

## 🎯 Veredito

O `side` no nosso dado é o **lado da POSIÇÃO liquidada**, **não o lado da ordem** — o **inverso**
da convenção Binance e do que a doc genérica sugere. Assinatura empírica (n=87.364, 94–97% limpa):

| `side` | ret 1h até o evento | média | %consistente | significado real |
|---|---|---|---|---|
| **BUY** | após **queda** | **−2,12%** | 97,3% | **LONG liquidado** — venda forçada |
| **SELL** | após **alta** | **+1,57%** | 93,8% | **SHORT liquidado** — compra forçada |

(top 10% por notional: mesma assinatura, 98,2% / 93,9% — ainda mais limpo.)

## 🔧 Mapa de normalização (correto)

```
side=BUY  → forced_long_liquidation    (venda forçada · pressão de venda · ocorre em QUEDAS)
side=SELL → forced_short_liquidation   (compra forçada · pressão de compra · ocorre em ALTAS)
```

> ⚠️ Isto é o **inverso** do mapa proposto na versão original desta Etapa 0 (que seguia a convenção
> Binance/ordem). O dado mandou.

## 🕵️ Causa raiz

O coletor (`scripts/liquidation_collector.py`) usa `bybit_liquidation_feed.py`, que assina o tópico
**`allLiquidation`** da Bybit. Nesse tópico, o campo `S` é o **lado da posição** (Bybit mudou a
convenção do tópico antigo `liquidation`). Mas o comentário em `bybit_liquidation_feed.py:11` ainda
diz *"lado da ORDEM"* — **desatualizado/errado**. O dado gravado está correto; o comentário é a
armadilha. Binance (`fstream`, feed alternativo bloqueado neste Pi) usa a convenção oposta — daí a
confusão.

## ✅ O que este veredito destrava e o que ainda falta

- **Destrava:** a semântica de `side` (gate `side_semantics_validation` resolvido).
- **Ainda pendente antes de virar catálogo:**
  1. corrigir o comentário errado em `bybit_liquidation_feed.py:11`;
  2. implementar a normalização (mapa acima) no store/schema;
  3. revisão humana do mecanismo das duas primitivas (com o `side` **BUY** = venda forçada).

## Protocolo usado (referência)

Opção A: `ret_ate_evento = price_do_evento / close(hora_anterior) − 1`, via `k_prices` horário;
agrupado por `side`; top-decil por notional como robustez. Script: `scratchpad/etapa0_side.py`.
