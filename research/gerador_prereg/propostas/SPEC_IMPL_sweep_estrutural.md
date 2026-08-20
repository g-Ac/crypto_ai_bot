# Spec técnica de implementação — `sig_liquidacao_sweep_estrutural`

**Data:** 2026-07-01 · **Status:** rascunho para discussão (antes de codar)

> **DECISÕES FINAIS (aprovadas 2026-07-01, o que foi de fato implementado/congelado):**
> saída **24h** (`bars=24`, horas — não 32h) · gatilho **P90 rolling(30)** com `shift(1)`
> (decisão D final: rolling, NÃO o expanding do rascunho abaixo) · pivô confirmado 3/lado ·
> lookback 18 candles 4h. O texto abaixo é o rascunho histórico da discussão; onde divergir,
> vale este bloco (e, acima de tudo, o `journal.jsonl`).
**Regra de ouro:** a engine de medição (`exp100_screening/backtest.py`) fica **intocada**. Toda a
lógica nova é causal e testada. Nada vai pro journal até os testes de causalidade passarem.

## Como a engine funciona hoje (o que temos de respeitar)

- `data.load_panel()` → dict `symbol → DataFrame horário` (open/high/low/close/volume/ret_1h + lsr/oi/funding via merge causal). **Não tem liquidação.**
- `catalogo.build_trades(spec, panels)` → `signal_fn(panels, syms, **params)` → filtro → `dedupe_overlap` → `trade_returns`.
- `trade_returns(entries, panels, horizon_h)` → **`horizon_h` é em HORAS**: `exit_ts = entry_ts + horizon_h*3600`; entra/sai no `close` do bucket; exige que `entry_ts` **e** `exit_ts` existam no índice horário. Descarta trade sem barra de saída.

> **Consequência 1 (ajuste na spec):** como o exit é em horas e o param_space é `{4,8,24}`, a saída
> do caso-base vira **`horizonte=24` (24h)** em vez dos 32h que eu tinha posto. Fica **100% dentro
> da engine atual** (zero mudança em EXITS). 24h após a rejeição é um swing coerente. *(discutir)*

---

## Peça A — trazer a liquidação para os panels

`k_liquidations` não está no painel. Proposta: **estender `data.load_panel`** com uma coluna
horária nova, causal e aditiva:

```
liq_sell_notional[bucket]  =  SUM(notional) de k_liquidations com side='BUY'
                              (= venda forçada = LONG liquidado, ver Etapa 0)
                              agregado na hora [bucket, bucket+1h)
```

- **Por que `side='BUY'`:** validado na Etapa 0 — BUY = long liquidado = venda forçada.
- **Causal:** a soma da hora `t` só usa eventos com `event_ts ∈ [t, t+1h)`; nenhum futuro.
- **Aditivo/backward-compat:** EXP-100/101/102 e o juiz forward ignoram a coluna nova. ⚖️ **decisão:**
  estender o `load_panel` compartilhado (simples, 1 query a mais) **vs.** isolar num enricher só do
  gerador (não toca código do juiz). Recomendo estender — é análogo ao que já faz com OI/funding.

## Peça B — reamostrar 4h e alinhar a entrada (o ponto causal mais delicado)

A primitiva reamostra o painel horário → 4h **internamente**:
`open=first, high=max, low=min, close=last, liq_sell_notional=sum` (resample `4h`, label/closed à esquerda).

O sinal é detectado em candles de 4h, mas a **entrada é emitida num timestamp horário** (a engine é
horária). Alinhamento: o candle 4h de rótulo `T` cobre `[T, T+4h)`; seu `close` = close do bucket
horário `T+3h`. Então:

```
sinal confirma no candle 4h[T]  →  entry_ts = T + 3*3600   (bucket horário cujo close == close 4h)
                                    exit_ts  = entry_ts + 24*3600   (engine horária, 24h)
```

Isso mantém entrada e saída em buckets horários existentes, causal, sem tocar `trade_returns`.

## Peça C — a lógica da primitiva (causal)

Sobre o painel 4h, para cada candle:
1. **fundo válido** = pivô de fundo **confirmado**: `low[i] == min(low[i-3 .. i+3])`. Um pivô só é
   *conhecível* em `i+3` (precisa dos 3 candles à direita) → **só é usado como suporte a partir de `i+3`**.
2. **varredura** = `low[t] < low(pivô válido mais recente)` — o preço perfura o fundo.
3. **gatilho** = `liq_sell_notional_4h[t] ≥ P90` do **expanding causal** (percentil só do passado, `shift(1)`).
4. **rejeição** = `close` volta pra dentro (`> low(pivô)`) em **≤ 2 candles** desde a perfuração.
5. **entry** long no close do candle de rejeição → `entry_ts = T+3h` (Peça B).

⚖️ **decisão C:** pivô confirmado com lag de 3 (fiel à mini-moldura, "estrutura real") **vs.** nível
rolling-min simples (tipo `sig_reacao_nivel`, mais fácil mas é "nível", não "pivô"). Recomendo o pivô
confirmado — o lag de 3 é o que o torna causal e honesto.

## Peça D — warm-up do percentil no forward

O colhedor corta `_forward_panels` (só `bucket_ts ≥ corte`) **antes** de chamar a primitiva. Logo o
expanding-P90 começa do zero no forward — os primeiros dias têm percentil instável. ⚖️ **decisão D:**
(i) aceitar warm-up curto (o expanding estabiliza rápido; N≥30 e semanas de forward diluem) **vs.**
(ii) calibrar o P90 com histórico pré-corte (exige passar o pré-corte à primitiva — mais invasivo).
Recomendo (i) — mais simples e não fura o forward-only.

## Peça E — plano de testes de causalidade (TDD, escrever ANTES da primitiva)

`tests/test_gerador_liquidacao.py`:
1. **Sem look-ahead (teste-ouro):** truncar a série em `t` não muda nenhuma entry ≤ `t`.
2. **P90 expanding:** o percentil em `t` é idêntico com ou sem os dados `> t`.
3. **Pivô com lag:** um pivô em `i` não gera suporte usável antes de `i+3`.
4. **Alinhamento de entry:** `entry_ts` é bucket horário existente e `close(entry_ts) == close4h`.
5. **Rejeição ≤2 candles:** não dispara se a volta demora 3+ candles.
6. **Fixture sintética:** cenário montado à mão (fundo → varredura+liquidação → rejeição) dispara
   exatamente 1 entry, no timestamp esperado, direção +1.
7. **Agregação de liquidação:** `liq_sell_notional` só soma `side='BUY'` e só a hora corrente.

## Arquivos tocados

| arquivo | mudança |
|---|---|
| `research/exp100_screening/data.py` | +coluna `liq_sell_notional` no `load_panel` (aditivo) |
| `research/gerador_prereg/catalogo.py` | +`sig_liquidacao_sweep_estrutural` + helper resample 4h + registro em SIGNALS |
| `tests/test_gerador_liquidacao.py` | novo — os 7 testes acima |
| EXITS / `trade_returns` | **nada** (usa `horizonte=24` já existente) |

## Resumo das decisões a discutir

- **Ajuste:** saída 24h (não 32h) — fica dentro do param_space, engine intocada.
- **⚖️ A:** estender `load_panel` compartilhado vs enricher isolado. (rec: estender)
- **⚖️ C:** pivô confirmado (lag 3) vs nível rolling-min. (rec: pivô confirmado)
- **⚖️ D:** warm-up do P90 no forward vs calibrar com pré-corte. (rec: aceitar warm-up)
