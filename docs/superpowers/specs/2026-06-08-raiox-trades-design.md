# Raio-X dos Trades — Design (App Web, Fatia 1)

**Data:** 2026-06-08 · **Rev:** 2 (incorpora revisão técnica do Gabriel)
**Status:** 🟢 DESIGN aprovado com ajustes — pronto pra virar plano TDD.
**Origem:** brainstorm 2026-06-08 (após `/mercado` em produção). Ver memória `project_app_web_trade_desk`.

## Contexto e enquadramento

App web pra apoiar o **swing manual** do Gabriel. Construção **faseada**:
- **Fase A** — visualizar/validar o que o bot **já faz** (sem estratégia nova). 4 fatias: **(1) Raio-X** ← *esta spec*, (2) Termômetro, (3) Paper manual, (4) Estruturas ao vivo.
- **Fase B** — dados do `/mercado` viram ideias **só como pesquisa**, nunca sinal. Depois, com cooling-off.

**Esta spec cobre apenas a Fatia 1 (Raio-X).** Guarda anti-drift: a ferramenta **mostra e ensina a ler**; não gera sinal, não recomenda ação, não mexe no bot.

## Objetivo

Ver cada trade do bot (momentum, BTC/ETH) como **radiografia** no gráfico — onde entrou, stop/alvo, caminho do preço, onde "quebrou", MFE/MAE — pra treinar o olho e ter referência. Inclui acompanhar a **posição aberta ao vivo**.

## Decisões do brainstorm (fechadas)

| Tema | Decisão |
|---|---|
| Fonte das ordens | Trades do bot momentum (BTC/ETH), já no banco |
| Timeframe | Candles **15m** + **seletor** 15m/1h/4h/1d |
| Telas | **Feed** (lista) → clica → **Raio-X** (gráfico do trade) |
| Ao vivo | Posição aberta atualiza por polling (~30s) |
| Onde mora | **Nova página no dashboard Flask existente**; não toca `/pip/` nem bot |
| Gráfico | **lightweight-charts** standalone, **versão fixa servida localmente** (sem CDN) |

## Arquitetura

Reusa `dashboard_server.py` (Flask) e `database`/`market`/`runtime_config`. Adiciona página + endpoints sob `/raiox`.

**Camadas:**
1. **`raiox_data.py` (raiz, Python puro, testável)** — funções com **dependências explícitas** (recebem `conn`, `state_path`, `get_candles_fn`). Sem Flask, sem rede embutida na leitura de banco/state.
2. **Endpoints Flask** em `dashboard_server.py` — rotas finas que chamam `raiox_data.py`.
3. **Frontend** — `templates/raiox.html` + `static/js/raiox.js` + `static/js/lightweight-charts.standalone.js` (lib local, versão fixa). Vanilla JS, como o resto do dashboard.

**Endpoints:**
| Rota | Método | Retorna |
|---|---|---|
| `/raiox/` | GET | Página HTML |
| `/api/raiox/trades` | GET | Trades fechados (resumo) + posição aberta (sem PnL atual) |
| `/api/raiox/trade/<id>` | GET | Detalhe de 1 trade fechado pra plotar |
| `/api/raiox/candles` | GET | Candles OHLC (`?symbol=&interval=&start=&end=`) |

(GET sem auth, padrão das `/api/*` atuais.)

## Fontes de dados (confirmadas no banco)

**Trades fechados — `momentum_trades`:** `id`, `timestamp` (ISO+tz; é o **fechamento**), `symbol`, `direction`, `regime`, `entry_price`, `sl_price`, `tp1_price`, `tp2_price`, `exit_price`, `exit_reason`, `duration_candles`, `mfe_pct`, `mae_pct`, `net_pnl_pct`, `pnl_pct`.

**Posição aberta — `momentum_state.json`** (path via `runtime_config`): `positions[symbol] = {entry_price, sl_price, tp1_price, tp2_price, direction, open_time ('YYYY-MM-DD HH:MM:SS' UTC), candles_elapsed, mfe_pct, mae_pct, regime, position_size_usd}`.

**Candles — `market.get_candles(symbol, interval, limit)`** (Binance spot klines). ⚠️ **A função atual só aceita `limit`, não `start`/`end`.** Não será alterada. Ver wrapper abaixo.

### Mapeamentos e regras de dados

- **entry_time é ESTIMADO:** o banco não grava hora de entrada nos trades fechados. `entry_time ≈ timestamp − duration_candles × 15min`; `exit_time = timestamp`. `trade_detail` retorna `entry_time_estimated: true`; o frontend/resumo **rotula** "entrada estimada (fechamento − duração)". Sem fingir precisão cirúrgica.
- **PnL com fonte explícita:** usar `net_pnl_pct` se existir e não-null; senão `pnl_pct`. Retornar `pnl_source: "net_pnl_pct" | "pnl_pct"`.
- **Posição aberta sem rede:** `open_position(state_path)` só lê o JSON (puro). O feed devolve a posição **sem PnL atual**; o **frontend** calcula o PnL ao vivo quando `/api/raiox/candles` trouxer o último `close`.
- **Timestamps mistos:** trade (ISO+tz) vs state (sem tz) → normalizar tudo pra **epoch UTC (segundos)** numa função única.

### Wrapper de candles (resolve o start/end sem mexer no market.py)

`fetch_candles(symbol, interval, start_ts, end_ts, get_candles_fn=market.get_candles) -> dict`:
1. Calcula quantas velas cobrem `[start − margem, end + margem]` (margem default **20 velas**).
2. **Limite duro 1000 velas/request.** Se a janela (de `start` até agora, pois `get_candles` traz as mais recentes) não couber em 1000 velas do `interval` pedido, **escala o TF**: 15m → 1h → 4h → 1d, escolhendo o menor TF cujo range caiba em ≤1000. O TF efetivamente usado vai em `effective_interval`.
3. Se nem em 1d couber → erro estruturado (`error: "janela_muito_longa"`).
4. Chama `get_candles_fn(symbol, effective_interval, limit)` e **filtra** pro range.
5. `get_candles_fn` é injetável → testável sem rede.

## Endpoint `/api/raiox/candles` — validação rígida

- `symbol` ∈ {`BTCUSDT`, `ETHUSDT`} (MVP); senão **400**.
- `interval` ∈ {`15m`, `1h`, `4h`, `1d`}; senão **400**.
- `start`/`end` em **epoch segundos**; se `start >= end` → **400**.
- Binance falha/timeout → **502/503**.
- **Erro:** `{"ok": false, "error": "<code>", "message": "<humano>"}`
- **Sucesso:** `{"ok": true, "symbol": "ETHUSDT", "interval": "15m", "effective_interval": "15m", "candles": [...]}`

## Comportamento das telas

### Tela 1 — Feed (`/raiox/`)
- **Posição aberta** no topo (se houver): símbolo, direção, preço de entrada, botão "ver ao vivo". (PnL atual aparece depois que o gráfico carrega o último close.)
- **Trades fechados** abaixo, mais recente primeiro: símbolo · direção · resultado (com `pnl_source`) · ícone do `exit_reason` (🟢 tp / 🔴 sl / ⏱️ timeout) · data. Linha clicável → Raio-X.
- Paginação simples (ex: 50/vez).

### Tela 2 — Raio-X (ao clicar)
- Gráfico de candles, janela `[entry_time − margem, exit_time + margem]`.
- **Linhas:** entrada (verde), stop (vermelho), TP1/TP2 (azul).
- **Marcadores:** seta de entrada (em `entry_time`, rotulada "estimada"); seta de saída (em `exit_time`, com `exit_reason`).
- **Seletor de TF:** 15m · 1h · 4h · 1d (recarrega candles; linhas permanecem; mostra `effective_interval` se escalou).
- **Resumo factual** abaixo: duração (velas + tempo), resultado % (+fonte), **MFE/MAE em texto** ("chegou a +0.37% a favor antes de virar"), regime na entrada. Linguagem descritiva.

### Ao vivo (posição aberta)
- Mesmo gráfico com entrada/stop/alvo; **preço atual** por polling (~30s) recarregando o último candle; PnL calculado no frontend. Sem WebSocket no MVP.

## Erros / edge cases

- **Trade antigo sem velas finas:** wrapper escala o TF e o frontend mostra "janela longa: em 1h/4h/1d".
- **Binance fora:** `/candles` retorna erro estruturado; frontend avisa e **mantém linhas/resumo** (vêm do banco).
- **Sem posição aberta:** feed só fechados; tela não quebra.
- **Símbolo fora de BTC/ETH:** não ocorre no MVP; endpoint rejeita com 400.

## Testes (TDD)

**Backend (`raiox_data.py`) — unitário, deps explícitas:**
- `list_trades(conn, state_path)` → fechados (ordem, campos, ícone, `pnl_source`) + posição aberta.
- `trade_detail(conn, id)` → preços + `entry_time`/`exit_time` + `entry_time_estimated` (testar cálculo e normalização de tz).
- `fetch_candles(..., get_candles_fn=fake)` → cálculo de limit, **escala de TF**, filtro por range, erro de janela longa — **sem rede** (fake injetado).
- `open_position(state_path)` → parse do state (formato de tempo próprio; sem rede); caso sem posição.
- **Teste anti-sinal (nuance do Raio-X):** o texto factual/resumo NÃO pode conter **frases de ação** — `compre`, `comprar`, `venda agora`, `vender agora`, `sinal`, `recomendado`, `operação sugerida`, `longar`, `shortar`. **PERMITIDO:** `entrada`, `stop`, `alvo` (legítimos aqui, diferente do `/mercado`).

**Endpoints Flask — fumaça, sem banco real:** SQLite temp com `momentum_trades` + `momentum_state.json` temp, via monkeypatch de `DB_FILE`/path (ou deps explícitas). Conferir `ok:true` e chaves; `/candles` com `get_candles` fake; casos de erro retornam 400/502 estruturados.

**Frontend:** validação manual objetiva (gráfico é visual) — ver checklist abaixo.

## Não-objetivos (YAGNI)

- Termômetro/semáforo (Fatia 2), paper manual (Fatia 3), estruturas (Fatia 4).
- **Frontend sem:** ranking, filtro por regime/símbolo, "melhores/piores", estatística agregada, comentário automático. Só a radiografia.
- WebSocket/streaming (polling basta). Ativos além de BTC/ETH. Qualquer sinal/recomendação.
- **Sem CDN** (lib local). Sem alterar `market.py` nem schema do banco.

## Frontend — detalhes

- **lightweight-charts:** baixar build *standalone production* de **versão fixa** (ex: `v4.x`), salvar em `static/js/`, registrar a versão num comentário no HTML/JS. Não improvisar CDN.
- **Nav:** adicionar item "Raio-X" em `templates/base.html` (junto de Dashboard/Analytics/Equity/System). Não tocar no `/pip/`.

## Checklist de validação real (final, objetivo)

- [ ] abrir `http://localhost:5000/raiox/` — feed carrega
- [ ] trade fechado recente abre o Raio-X
- [ ] candles aparecem; linhas entry/SL/TP aparecem; marcador de saída aparece
- [ ] seletor 1h/4h/1d recarrega (mostra `effective_interval` se escalou)
- [ ] posição aberta: botão "ver ao vivo" funciona e PnL aparece após candle
- [ ] sem posição aberta: tela não quebra
- [ ] console do navegador sem erro JS
- [ ] `/api/raiox/trades` → `ok:true`; `/api/raiox/trade/<id>` → tempos e preços; `/api/raiox/candles` → candles ou erro estruturado

## Sequência de construção (visão; detalhe no plano)

1. `raiox_data.py`: normalização de tempo + `list_trades` + `trade_detail` + `open_position` (+ testes, incl. anti-sinal).
2. `raiox_data.py`: `fetch_candles` (wrapper + escala TF + filtro) com `get_candles` fake (+ testes).
3. Endpoints Flask + testes de fumaça (DB/state temp).
4. Frontend: feed.
5. Frontend: gráfico + raio-x (linhas/marcadores/resumo) + seletor TF.
6. Ao vivo (polling posição aberta).
7. Validação real (checklist acima).

## Regras duras pro plano/implementação (do Gabriel)

- Não mexer no bot/main/estratégia momentum; não mexer no `/pip/`.
- Não criar sinal, recomendação ou score. Não alterar schema do banco.
- Sem CDN — lightweight-charts servido localmente, versão fixa.
- Backend puro em `raiox_data.py`, testável sem Flask; Flask só rotas finas.
- Candles com validação de symbol/interval/start/end e limite máximo; **não alterar `market.py`** (usar wrapper/fallback).
- `entry_time` de trade fechado é **estimado** e tratado como tal.
- PnL usa `net_pnl_pct` com fallback `pnl_pct` (+ `pnl_source`).
- TDD red-green. **Sem commits automáticos.**
