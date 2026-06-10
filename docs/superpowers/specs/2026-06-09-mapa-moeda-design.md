# Mapa da Moeda — Design (App Web, Fatia 2)

**Data:** 2026-06-09 · **Rev:** 1
**Status:** 🟡 DESIGN — aguardando review do Gabriel antes de virar plano TDD.
**Origem:** brainstorm 2026-06-09, após a Fatia 1 (Raio-X) validada. Ver `2026-06-08-raiox-trades-design.md` e memória `project_app_web_trade_desk`.

## Contexto e enquadramento

Segunda fatia do Trade Desk (**Fase A** — visualizar/validar o que o bot **já faz**, sem estratégia nova). A Fatia 1 (Raio-X) disseca **um** trade por vez; esta fatia dá a visão **macro**: a moeda inteira com **todos** os trades marcados, pra treinar o olho a ver padrão (agrupamentos, contexto de regime, onde o bot acerta/erra).

**Guarda anti-drift:** é **descritivo do passado** do bot. Não gera sinal, não recomenda, não projeta, não mexe no bot.

## Objetivo

Ver uma moeda (BTC **ou** ETH) "de longe", com cada trade do bot momentum plotado como entrada+saída coloridas por resultado. Clicar num trade abre o **Raio-X de 15m que já existe** (drill-down). Macro pra padrão, clique pra detalhe.

## Decisões do brainstorm (fechadas)

| Tema | Decisão |
|---|---|
| Resolução macro vs. detalhe | **Macro + clique→Raio-X**: mapa "de longe", drill-down reusa a Fatia 1 |
| Moeda | Seletor **BTC / ETH** (uma por vez) |
| Período | **Todo o histórico de trades da moeda** (1º trade → agora). Sem seletor de período no MVP — zoom/pan nativo basta |
| Timeframe | **4h default** (≈324 velas p/ 54 dias) + seletor **1d** |
| Marcação | Entrada (seta na direção: ▲ LONG / ▼ SHORT) + saída (marcador), **ambos coloridos pelo resultado net** |
| Cores | 🟢 ganho (net>0) · 🔴 perda (net≤0) · 🟠 **fee comeu** (bruto>0 e net≤0) |
| Interação | Clique no marcador → Raio-X do trade via deep-link `/raiox/?trade=<id>` |
| Onde mora | **Nova rota `/raiox/mapa`** no dashboard Flask; reusa `/api/raiox/candles` |
| Gráfico | **lightweight-charts** local (lib já servida pela Fatia 1, sem CDN) |

> O resultado por cor já embute, de forma visual, o "filtro fee" pedido — sem precisar de filtro/ranking. ("Fee comeu" é ~5% dos trades — 8 de 149 —, então é destaque pontual, não o foco.)

## Arquitetura

Reusa `dashboard_server.py` (Flask), `raiox_data.py` (leitura pura) e `market`/`database`/`runtime_config`. Adiciona overlay de trades + página/endpoint sob `/raiox/mapa`.

**Camadas:**
1. **`raiox_data.py` (Python puro, testável)** — adiciona `_classify_result()` e `trades_overlay(conn, symbol)`. Reusa `_pnl_of`, `_to_epoch_s`, `MOMENTUM_INTERVAL_MIN` e a **mesma estimativa de `entry_time`** da Fatia 1 (`entry ≈ timestamp − duration_candles × 15min`). Sem Flask, sem rede.
2. **Endpoints Flask** em `dashboard_server.py` — rotas finas.
3. **Frontend** — `templates/mapa.html` + `static/js/mapa.js`, vanilla JS, reusa a lib local. `setMarkers()` + clique.
4. **Deep-link** — pequeno hook em `static/js/raiox.js`: ao carregar com `?trade=<id>`, abre direto o detalhe daquele trade.

**Endpoints:**
| Rota | Método | Retorna |
|---|---|---|
| `/raiox/mapa` | GET | Página HTML |
| `/api/raiox/mapa?symbol=` | GET | Overlay: todos os trades da moeda como pontos de plotagem |
| `/api/raiox/candles` (reuso) | GET | Candles OHLC (já valida symbol/interval/start/end e escala TF) |

(GET sem auth, padrão das `/api/*` atuais.)

## Fontes de dados

**`momentum_trades`** (mesma tabela da Fatia 1): `id`, `timestamp` (fechamento, ISO+tz), `symbol`, `direction`, `regime`, `entry_price`, `exit_price`, `duration_candles`, `mfe_pct`, `mae_pct`, `net_pnl_pct`, `pnl_pct`.

**`entry_time` é ESTIMADO** (banco não grava hora de entrada) — idêntico à Fatia 1; o marcador de entrada é aproximado e isso é coerente com a visão "de longe".

### `trades_overlay(conn, symbol)` — shape de retorno

```json
{
  "ok": true,
  "symbol": "ETHUSDT",
  "trades": [
    {
      "id": 149, "direction": "SHORT",
      "entry_time_s": 1780996105, "entry_price": 1678.02,
      "exit_time_s": 1780997905, "exit_price": 1668.16,
      "result": "win", "pnl_pct": 0.49, "pnl_source": "net_pnl_pct"
    }
  ]
}
```

### `_classify_result(pnl_net, pnl_bruto) -> "win" | "loss" | "fee_ate"`

- `win` — `pnl_net > 0`
- `fee_ate` — `pnl_bruto > 0 and pnl_net <= 0`
- `loss` — caso contrário (`pnl_net <= 0` sem ter sido positivo no bruto)

(`pnl_net` = `net_pnl_pct`; `pnl_bruto` = `pnl_pct`.)

## Comportamento da tela (`/raiox/mapa`)

1. Estado inicial: moeda **BTC**, TF **4h**.
2. Busca o overlay (`/api/raiox/mapa?symbol=BTCUSDT`) e os candles (`/api/raiox/candles?symbol=BTCUSDT&interval=4h&start=<1º entry−margem>&end=<agora>`).
3. Plota candles; monta os marcadores (entradas + saídas), **ordenados por tempo crescente** (exigência do lightweight-charts), e aplica `setMarkers()`.
   - Entrada: `time=entry_time_s`, shape `arrowUp` (LONG) / `arrowDown` (SHORT), cor pelo resultado.
   - Saída: `time=exit_time_s`, shape `circle`, cor pelo resultado, `text` = `pnl_pct%`.
4. **Clique** (`subscribeClick`): acha o trade cujo entrada/saída está mais próximo do tempo clicado (dentro de uma tolerância); navega pra `/raiox/?trade=<id>`. Clique longe de qualquer trade: ignora.
5. Trocar **moeda** ou **TF**: recarrega overlay + candles.

## Erros / edge cases

- **Moeda sem trades:** overlay vazio → mapa mostra só candles, sem marcadores; não quebra.
- **Símbolo inválido** (`/api/raiox/mapa`): **400** estruturado (`{ok:false, error:"symbol_invalido"}`).
- **Binance fora:** candles falham (502, já tratado na Fatia 1); a tela avisa e não quebra.
- **Janela > 1000 velas no TF pedido:** `/api/raiox/candles` já escala o TF sozinho e devolve `effective_interval`; o mapa plota no efetivo.
- **Marcador entre velas** (ex.: entrada às 13:30 num gráfico 4h): o lightweight-charts ancora na vela mais próxima — aproximado, coerente com a visão macro.

## Testes (TDD)

**Backend (`raiox_data.py`) — unitário, sem rede:**
- `_classify_result`: `win` (net>0), `loss` (net≤0 e bruto≤0), `fee_ate` (bruto>0 e net≤0); borda `net==0`.
- `trades_overlay(conn, symbol)`: filtra pelo símbolo; campos e tempos corretos (entrada estimada < saída); classificação por trade; ordem; **lista vazia** se sem trades.
- **Anti-sinal:** mantém a guarda — nenhum texto do overlay (ex.: rótulo de `pnl`) contém frase de ação proibida (`FORBIDDEN_ACTION_PHRASES` já existe).

**Endpoints Flask — fumaça, sem banco real:** SQLite temp com `momentum_trades`. `/api/raiox/mapa` → `ok:true` + chaves; `symbol` inválido → 400.

**Frontend:** validação manual objetiva (gráfico é visual) — checklist abaixo.

## Não-objetivos (YAGNI)

- **Sem** linha ligando entrada↔saída (poluição; o par vive no Raio-X).
- **Sem** SL/TP no mapa (vive no Raio-X).
- **Sem** estatística agregada, ranking, "melhores/piores", contadores na tela.
- **Sem** seletor de período custom (zoom/pan nativo basta).
- **Sem** TF abaixo de 4h no mapa (o detalhe fino é o Raio-X).
- Ativos além de BTC/ETH. Qualquer sinal/recomendação/score. WebSocket.
- **Sem CDN**, **sem** alterar `market.py` nem schema do banco, **sem** tocar bot/main/momentum.

## Frontend — detalhes

- Reusa `static/js/lightweight-charts.standalone.production.js` (v4.2.0 local — já presente).
- **Nav:** adicionar item "Mapa" em `templates/base.html`, junto de "Raio-X".
- `mapa.js`: vanilla JS, igual ao `raiox.js`. Marcadores via `series.setMarkers(sorted)`; clique via `chart.subscribeClick`.
- Deep-link: `raiox.js` lê `?trade=<id>` no load e abre o detalhe (hoje só abre via clique no feed).

## Checklist de validação real (final, objetivo)

- [ ] `http://<host>:PORT/raiox/mapa` carrega; seletores de moeda e TF presentes
- [ ] candles aparecem cobrindo o histórico todo da moeda
- [ ] marcadores de entrada/saída aparecem; cores corretas (conferir 1 ganho, 1 perda, 1 *fee comeu*)
- [ ] clique num marcador abre o Raio-X **do trade certo**
- [ ] trocar BTC↔ETH recarrega
- [ ] moeda/intervalo sem dados não quebra a tela
- [ ] console do navegador sem erro JS
- [ ] `/api/raiox/mapa?symbol=BTCUSDT` → `ok:true` com N trades; `symbol` inválido → 400

## Sequência de construção (visão; detalhe no plano)

1. `raiox_data.py`: `_classify_result` + `trades_overlay` (+ testes, incl. anti-sinal).
2. Endpoints Flask `/raiox/mapa` + `/api/raiox/mapa` (+ teste de fumaça).
3. Frontend: `mapa.html` + `mapa.js` — candles + marcadores.
4. Clique → deep-link Raio-X (+ hook `?trade=` no `raiox.js`).
5. Seletor de moeda + TF.
6. Validação real (checklist).

## Arquivos (caminhos)

| Arquivo | Ação |
|---|---|
| `docs/superpowers/specs/2026-06-09-mapa-moeda-design.md` | **novo** (esta spec) |
| `raiox_data.py` | **modifica** — `_classify_result`, `trades_overlay` |
| `dashboard_server.py` | **modifica** — rotas `/raiox/mapa` e `/api/raiox/mapa` |
| `templates/mapa.html` | **novo** |
| `static/js/mapa.js` | **novo** |
| `templates/base.html` | **modifica** — item "Mapa" na nav |
| `static/js/raiox.js` | **modifica** — deep-link `?trade=<id>` |
| `static/js/lightweight-charts.standalone.production.js` | **reusa** (já existe) |
| `tests/test_raiox_data.py` | **modifica** — testes de `trades_overlay`/`_classify_result` |
| `tests/test_raiox_endpoints.py` | **modifica** — teste do `/api/raiox/mapa` |

## Regras duras (do Gabriel)

- Não mexer no bot/main/estratégia momentum; não tocar `/pip/`.
- Não criar sinal, recomendação ou score. Não alterar schema do banco nem `market.py`.
- Sem CDN — lightweight-charts local, versão fixa.
- Backend puro em `raiox_data.py`, testável sem Flask; Flask só rotas finas.
- TDD red-green. **Sem commits automáticos.**
