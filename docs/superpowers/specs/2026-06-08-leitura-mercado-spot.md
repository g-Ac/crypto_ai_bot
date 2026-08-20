# Spec — Leitura de Mercado pro Spot (`/mercado`)

- **Data:** 2026-06-08
- **Status:** 🟡 DESIGN aprovado no brainstorm — **NÃO implementado**. Retomar em sessão dedicada (TDD, módulo por módulo).
- **Escopo:** ferramenta de **leitura** (apoio à decisão manual de spot do Gabriel). **Não toca momentum/v1.1, não coleta dado novo, não opera.**
- **Origem:** brainstorm 2026-06-08 (sessão do fix de buckets). Gabriel faz trade spot manual e quer ancorar decisões nos dados que já coleta.

## Problema (3 dores priorizadas pelo Gabriel)
1. **Risco-on ou off?** — falta termômetro de regime (tendência/vol/sentimento).
2. **Onde tá a pressão?** — não enxerga em tempo útil onde tá liquidando/squeezando por moeda.
3. **Opero no feeling** — quer ancorar entrada/saída em dado antes de operar.

As três colapsam em **dois instrumentos de leitura**. A dor 3 é o que os dois curam.

## Decisões acordadas
| Eixo | Decisão |
|---|---|
| Cadência | **Sob demanda (pull)** — sem alertas/thresholds no MVP (evita virar pseudo-sinal). |
| Canal | **Telegram primeiro**; painel web = fase 2. |
| Forma | **`/mercado`** (macro) + **`/mercado <SYM>`** (zoom por moeda). |
| Princípio | **Mostra componentes, não veredito.** Nada de score "RISCO-ON" mastigado (caixa-preta = porta do drift). |
| Universo | os **14 símbolos** já coletados. |

## Não-objetivos (YAGNI / guarda anti-drift)
- ❌ Painel web (fase 2, só depois do Telegram validar o conteúdo).
- ❌ Alertas proativos (só se a leitura sob demanda provar que falta).
- ❌ **Qualquer agente / "equipe de agentes" / análise LLM.** Esse é o padrão que já virou teatro no MedPresence e que o Gabriel pediu pra sinalizar como drift de "automação pra gerar retorno". Um único *analista* (resumo LLM sob demanda) só se cogita **muito depois**, como camada fina sobre a leitura, e após o cooling-off de 7d. **Não é parte deste MVP.**

## Os dois instrumentos

### 1. Termômetro de regime (macro, risco-on/off)
Componentes lado a lado (sem veredito):
- **Tendência:** retorno 24h / 7d dos majors (`k_prices.close_price`).
- **Volatilidade:** range médio (high-low) recente (`k_prices`).
- **Pressão compradora:** taker buy ratio (`k_prices.taker_buy_base/quote`).
- **Sentimento/crowding:** LSR (`k_ratios.long_short_ratio`), funding (`k_funding_rates`), basis (`k_basis.basis_rate`).
- **Alavancagem:** tendência de OI (`k_open_interest.sum_open_interest`).

### 2. Mapa de pressão (liquidações por moeda)
- Liquidações 24h por moeda: notional total, **split por lado** (`side`), nº eventos (`k_liquidations`).
- Direção = a "cascata assinada": longs liquidados (cascata pra baixo) vs shorts liquidados (squeeze pra cima).
- Cruzar com OI (subiu/caiu) e LSR.
- **Ranking** "o que tá pegando fogo" por notional.

### `/mercado <SYM>` (zoom)
Tudo da moeda num lugar: ret 24h/7d, LSR top/global, funding, basis, tendência OI, liquidações 24h (split lado).

## Fontes de dados (todas em `runtime/baseline/bot.db`, coleta VIVA)
| Tabela | Colunas-chave | Símbolos | Notas |
|---|---|---|---|
| `k_liquidations` | symbol, **event_ts (epoch MS)**, side (BUY/SELL), qty, price, notional, collected_at (epoch s) | 12 c/ eventos | **side a confirmar:** BUY = short liquidado (forçado a comprar) / SELL = long liquidado. Fonte Bybit. |
| `k_ratios` | symbol, bucket_ts (epoch s), source, long_short_ratio, long_account, short_account | 14 | múltiplas linhas/bucket via `source` (global vs top traders) — separar na query. |
| `k_prices` | symbol, bucket_ts (epoch s), open/close/high/low_price, volume, taker_buy_base, taker_buy_quote | 14 | hourly. |
| `k_funding_rates` | symbol, funding_time, funding_rate, mark_price | 14 | **funding_time formato a confirmar** (preview saiu vazio com filtro por MAX — provável ms ou granularidade 8h). |
| `k_basis` | symbol, bucket_ts (epoch s), basis, basis_rate, index_price, futures_price | 14 | |
| `k_open_interest` | symbol, bucket_ts (epoch s), sum_open_interest, sum_open_interest_value | 14 | |

**14 símbolos:** BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, ADAUSDT, AVAXUSDT, LINKUSDT, LTCUSDT, TRXUSDT, SUIUSDT, HYPEUSDT, 1000PEPEUSDT.

## Arquitetura
- **`market_read.py`** (novo): funções puras de leitura (recebem `conn`, retornam dicts) + formatação (recebem dicts, retornam string Telegram). Testável isolado.
  - `read_regime(conn) -> dict`, `read_pressure(conn, hours=24) -> list`, `read_symbol(conn, symbol) -> dict`.
  - `format_macro(...) -> str`, `format_symbol(...) -> str`.
- **`telegram_commands.py`**: handler `/mercado [SYM]` chamando o módulo acima. Reusa a conexão do projeto (`database.py` / `runtime_config`).
- Sem schema novo, sem migration, sem alteração no loop principal.

## Preview real (08/jun ~15:25 UTC — evidência de que o dado sustenta)
Ret 24h: BTC +3.56% · ETH +4.20% · SOL +3.83%.
Pressão 24h (liquidações, % = lado dominante):

| Moeda | Total | Lado dominante | Eventos |
|---|---|---|---|
| BTC | $1.37M | longs 74% | 206 |
| ETH | $1.06M | longs 93% | 89 |
| XRP | $239k | longs 60% | 56 |
| SOL | $178k | longs 80% | 80 |
| HYPE | $89k | longs 94% | 121 |

Leitura: preço verde no dia, mas alavancagem **comprada** foi limpa (cascata de longs) — a nuance que cura o "feeling".

### Queries validadas (pra acelerar a impl)
```sql
-- Pressão 24h por moeda
SELECT symbol,
  ROUND(SUM(CASE WHEN side='BUY' THEN notional ELSE 0 END)) shorts_liq_usd,
  ROUND(SUM(CASE WHEN side='SELL' THEN notional ELSE 0 END)) longs_liq_usd,
  COUNT(*) ev
FROM k_liquidations
WHERE event_ts > (SELECT MAX(event_ts) FROM k_liquidations) - 86400000   -- event_ts em MS
GROUP BY symbol HAVING SUM(notional)>0 ORDER BY SUM(notional) DESC;

-- Retorno 24h (bucket_ts em s, hourly -> rn=25)
WITH px AS (SELECT symbol, close_price, ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY bucket_ts DESC) rn FROM k_prices)
SELECT symbol, ROUND(100.0*(MAX(CASE WHEN rn=1 THEN close_price END)/MAX(CASE WHEN rn=25 THEN close_price END)-1),2) ret24h
FROM px WHERE rn IN (1,25) GROUP BY symbol;
```

## Riscos / guardas a lembrar na impl
- **Semântica do `side`** das liquidações: confirmar BUY=short-liq antes de rotular "longs vs shorts" no output (rótulo errado inverte a leitura).
- **Timestamps mistos:** `event_ts` em ms; `bucket_ts`/`collected_at` em s; `funding_time` a confirmar. Padronizar conversões.
- **`k_ratios` múltiplas linhas/bucket** por `source` — filtrar/rotular.
- **Não deixar virar sinal:** sem "compre/venda", sem score-veredito, sem alerta automático no MVP.

## Próximo passo (sessão dedicada)
1. `writing-plans` a partir desta spec → plano TDD.
2. Implementar `market_read.py` (red→green por função), depois o handler Telegram.
3. Validar com 1 chamada real (`feedback_test_external_apis_early`) antes de empilhar.
4. Só então cogitar fase 2 (painel web).
