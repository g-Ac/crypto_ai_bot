# Spec — Aba Paper no Trade Desk (Fatia 4 — diário paper que mede)

- **Data:** 2026-06-10
- **Status:** ✅ DESIGN aprovado no brainstorm (2 rodadas + mockup visual) — pronto pra plano TDD da sub-fatia 4a.
- **Escopo:** diário de trades paper **manuais** do Gabriel: registra a tese ANTES do resultado, acompanha automaticamente até stop/alvo, e espelha onde a leitura dele funciona. **A ferramenta mede o trader; nunca opina sobre o trade.**
- **Origem:** Fatia "Paper manual" da Fase A (spec `2026-06-08-raiox-trades-design.md`), redefinida no brainstorm de 2026-06-10. Pedido original do Gabriel ("me mostrar melhores regiões/momentos/direções") foi espelhado: dica sem edge validado é teatro — **"melhores regiões e momentos" emergem dos dados DELE no espelho**, não de sinal da ferramenta.

## Decisões do brainstorm

| Eixo | Decisão |
|---|---|
| Cena de uso | **Diário paper que mede** + painel de condições visível no registro ("validador" = espelho estatístico dos próprios trades, não selo de aprovação). |
| Canal | **Só web** (aba Paper no Trade Desk). Sem Telegram nesta fatia. |
| Ciclo de vida | **Tese imutável**: registrou, travou. Fecha sozinho em stop/alvo; fechar manual antecipado permitido; **void até 10 min** após criação (anula fat-finger, fora da estatística, fica no banco). Sem edição de níveis, nunca. |
| Entrada | **A mercado** (preço atual ±0,5%). Ordem pendente = v2. |
| Símbolos | **13 símbolos** (`PAPER_SYMBOLS` = `SUPPORTED_MARKET_SYMBOLS` menos `1000PEPEUSDT`, que não existe na API spot — toda a infra de preço do paper é spot: validação, tracker, gráfico). BTC/ETH no topo do select. *(Decisão 2026-06-11, durante implementação.)* |
| Direção | `long` e `short` (short = tese não executável em spot, mas leitura mensurável; rotulado "short (tese)" no UI). |
| Carimbo | Snapshot **cru** do `market_read` gravado no INSERT (invisível não: o painel mostra a mesma leitura formatada). Forward-only por construção. |
| Fees | **0,1% taker spot por lado** (0,2 pp por round-trip) desde o dia 1; espelho mostra bruto e net. |
| Guarda estatística | Breakdown só mostra números com **n≥10** por célula; abaixo disso, "amostra insuficiente". Buckets de condição **congelados nesta spec** (anti stealth-backtest). |
| Benchmark | Equity paper vs **buy & hold de BTC** no mesmo período (régua anti-regime), com nota de que as bases diferem (soma de retornos % vs retorno contínuo). |

## Não-objetivos (YAGNI / guarda anti-drift)

- ❌ Score/semáforo/recomendação/"trade aprovado" — painel de condições é **descritivo** (mesmo tradutor do `/mercado`); teste automatizado anti-sinal.
- ❌ Ordem pendente/limite (v2), gestão ativa (mover stop, parciais — v2 com audit trail), checklist pessoal de regras (ideia anotada pra v2).
- ❌ Alertas proativos, replay/simulador histórico (evolução futura, fora desta fatia), LLM.
- ❌ Sizing/capital: 1 trade = 1 unidade de retorno %. Mede **leitura**, não gestão de capital.
- ❌ Coletor novo, mudança em `market_read.py`/`mercado_data.py`/motor do bot, mudança em tabelas existentes.

## Arquitetura

Molde das Fatias 1-3: **backend puro testável + rota fina + template server-side**.

### Tabela nova `paper_manual_trades`

⚠️ Nome NÃO é `paper_trades` — essa tabela legada já existe (paper_trader.py desativado).

```sql
CREATE TABLE IF NOT EXISTS paper_manual_trades (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at       INTEGER NOT NULL,            -- epoch s, relógio do SERVIDOR
  symbol           TEXT NOT NULL,
  direction        TEXT NOT NULL CHECK(direction IN ('long','short')),
  entry_price      REAL NOT NULL,
  stop_price       REAL NOT NULL,
  target_price     REAL NOT NULL,
  thesis           TEXT NOT NULL,               -- obrigatória, não vazia
  tags             TEXT,                        -- csv lowercase normalizado ("pullback,zona-liq")
  context_snapshot TEXT,                        -- JSON cru (ver Carimbo)
  status           TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed','void')),
  exit_reason      TEXT CHECK(exit_reason IN ('stop','target','manual')),
  exit_price       REAL,
  exit_ts          INTEGER,
  mfe_price        REAL,                        -- extremo favorável (high p/ long, low p/ short)
  mae_price        REAL,                        -- extremo adverso
  last_checked_ts  INTEGER,                     -- open_time do último candle 15m processado
  void_reason      TEXT
);
```

### `paper_data.py` (novo módulo, funções puras)

Padrão `raiox_data`/`mercado_data`: recebe `conn` / `get_candles_fn` / `now_s` injetáveis.

- `create_trade(conn, get_candles_fn, now_s, form) -> dict | erros` — valida e insere com carimbo.
- Validações: símbolo ∈ `SUPPORTED_MARKET_SYMBOLS`; tese não vazia; long ⇒ stop < entry < target, short ⇒ target < entry < stop; `entry_price` dentro de **±0,5%** do close do último candle 15m **fechado**; preço indisponível (API fora) ⇒ **registro bloqueado** com mensagem.
- `void_trade(conn, now_s, trade_id, reason)` — só se `status='open'` e `now_s - created_at <= 600`; backend valida (UI esconde o botão fora da janela, mas o servidor é a verdade).
- `close_manual(conn, get_candles_fn, now_s, trade_id)` — `exit_price` = close do último candle 15m fechado; `exit_reason='manual'`.
- `list_trades(conn, now_s) -> dict` — abertos (com MFE/MAE %, idade, flag janela-void) + fechados recentes.
- `espelho_view(conn, now_s) -> dict` — sub-fatia 4b (ver Espelho).
- `registro_view(conn, now_s, symbol) -> dict` — dados da página de registro; painel de condições reusa `mercado_data.symbol_view(conn, symbol, now_s)` + frescor (view formatada; o carimbo grava o cru — mesmo banco hourly, não precisa ser atômico).

### Carimbo (`context_snapshot`, JSON)

Dados **crus** (números, não strings formatadas), pra derivar buckets depois sem parsing:

```json
{
  "schema_version": 1,
  "regime": <market_read.read_regime(conn)>,
  "symbol": <market_read.read_symbol(conn, sym)>,
  "pressure_symbol": <entrada do símbolo em read_pressure(conn, 24)> | null,
  "freshness": <market_read.read_freshness(conn, now)>
}
```

Leitura de carimbo que falhar ⇒ campo `null` (registro NÃO bloqueia por carimbo; só por preço). Dado stale grava assim mesmo — `freshness` carrega as flags e o espelho pode filtrar.

### `scripts/paper_tracker.py` (cron */15, padrão k_collector)

CLI idempotente com `flock` (mesma receita do k_collector). A cada execução, para cada trade `open`:

1. Busca candles 15m **fechados** do símbolo via `market.get_candles` desde `max(last_checked_ts+900, primeiro boundary)` — **primeiro candle válido = open_time ≥ ceil(created_at/900)·900** (o candle parcial do momento do registro não conta: contém movimento pré-registro; limitação simétrica e documentada).
2. Varre em ordem cronológica, por candle:
   - atualiza `mfe_price`/`mae_price` (long: high/low; short: low/high);
   - long: `low ≤ stop` ⇒ fecha no stop; `high ≥ target` ⇒ fecha no alvo (short invertido);
   - **stop E alvo no mesmo candle ⇒ assume stop** (pessimista, padrão do lab);
   - **gap**: candle abre além do nível ⇒ `exit_price` = **open** do candle (fill honesto), não o nível;
   - `exit_ts` = open_time do candle do toque.
3. Atualiza `last_checked_ts`; cron atrasado/Pi reiniciado ⇒ na volta varre desde o último check, nenhum toque se perde; reprocessar é no-op (idempotente).
4. Símbolo sem dados/API fora ⇒ mantém aberto, loga; a página mostra idade do último check (frescor do tracker).

### Rotas em `dashboard_server.py` (finas, padrão raiox)

```
GET  /raiox/paper                 → registro_view + render paper.html (active_page="paper")
GET  /raiox/paper?symbol=<SYM>    → mesmo, com símbolo selecionado (normalize_symbol; inválido → BTCUSDT)
POST /raiox/paper/criar           → create_trade; sucesso → redirect; erro → re-render com mensagem
POST /raiox/paper/<id>/anular     → void_trade
POST /raiox/paper/<id>/fechar     → close_manual
GET  /raiox/paper/espelho         → espelho_view + render paper_espelho.html   [sub-fatia 4b]
```

- POSTs protegidos pelo **Basic Auth existente** (`DASHBOARD_USER`/`PASS`), como os POSTs atuais do dashboard.
- Conexão `db._get_conn()` + `try/finally close` (padrão).
- Gráfico de candles: **reusa `/api/raiox/candles`**; se a validação atual restringir a BTC/ETH, **estender pros 14** via `SUPPORTED_MARKET_SYMBOLS` (única mudança em código existente além do nav — verificar no plano).

### Frontend

- `templates/paper.html` + `templates/paper_espelho.html` (4b), estendendo `base.html`; macros reusam `_mercado_macros.html` onde couber (lição Jinja: spans dentro de macro, nunca concatenados).
- `static/js/paper.js`: gráfico lightweight-charts (mesmo componente local do Raio-X), modo "clique no gráfico preenche o nível selecionado" (entrada azul/stop vermelho/alvo verde como price lines), R:R calculado ao digitar, countdown do void. Sem lib nova, sem CDN.
- Nav: item **Paper** nos 2 blocos do `base.html`.
- Layout conforme mockup aprovado: gráfico + form lado a lado; painel "condições agora" (com aviso "será gravado junto com a tese"); lista de abertos com anular/fechar.

## Espelho (sub-fatia 4b)

- **Cards**: trades fechados (n), winrate, PF **net**, expectancy média (net, pp), máx drawdown da equity, vs buy & hold BTC (pp). Janela do B&H: do `created_at` do primeiro trade fechado ao `exit_ts` do último, com closes 15m da mesma fonte de candles.
- **Equity**: soma cumulativa de `net_pnl_pct` por trade fechado, ordenada por `exit_ts` (peso igual; sem sizing).
- **PnL**: long bruto = `(exit-entry)/entry·100`; short invertido; **net = bruto − 0,2 pp**.
- **Breakdown** (linhas = condição; colunas = n, PF net, expectancy; célula com **n<10 ⇒ "amostra insuficiente"**). Buckets **congelados**:
  - símbolo; direção; cada tag;
  - **funding** do símbolo na entrada: `>0` / `<0` / n-d;
  - **LSR** (`global_account`) na entrada: `>1` / `<1` / n-d;
  - **pressão de liquidação relativa à direção**: a favor = (long ∧ squeeze de shorts) ∨ (short ∧ cascata de longs); contra = oposto; neutro = equilibrado/pouco volume/n-d — derivada do `pressure_symbol` cru com os mesmos thresholds do `_pressure_label`;
  - **regime BTC na entrada** (do carimbo `regime`): ret 24h BTC `> +1%` = alta, `< −1%` = baixa, senão lateral.
- **Detalhe de trade**: clique abre painel estilo Raio-X — gráfico com níveis e caminho, tese escrita, carimbo da época traduzido ("como o mercado estava"), resultado, MFE/MAE.
- Rodapé fixo: "descreve o teu histórico — não é recomendação".

## Testes (TDD; suite atual 1041 passed permanece verde)

- **paper_data**: validações (níveis × direção, tolerância ±0,5%, símbolo inválido, tese vazia); criação grava carimbo cru + flags stale; carimbo falho ⇒ null sem bloquear; preço indisponível ⇒ bloqueia; void dentro/fora da janela; close manual; list.
- **paper_tracker**: toque stop, toque alvo, candle ambíguo ⇒ stop, gap ⇒ open, MFE/MAE, primeiro candle = boundary pós-registro, idempotência (rodar 2× = no-op), multi-trades, símbolo sem dados.
- **espelho**: PF/expectancy net (fee 0,2 pp), equity ordenada, célula n<10 ⇒ "amostra insuficiente", buckets derivados do carimbo (incl. pressão relativa à direção), trade void fora de tudo.
- **endpoints**: 200, POST sem auth ⇒ 401 (quando auth configurada), `class="positive"` presente e `&lt;span` ausente (anti-escape Jinja), **anti-sinal com lista própria do paper**: a `FORBIDDEN_SIGNAL_WORDS` do `/mercado` inclui "entrada/alvo/stop", que lá seriam a ferramenta sugerindo — mas no paper são o vocabulário do FORMULÁRIO onde o usuário declara os próprios níveis. A lista do paper proíbe recomendação/imperativo ("compre", "comprar", "venda", "vender", "sinal", "longar", "shortar", "recomend", "oportunidade") e mantém a guarda real: a ferramenta nunca opina. *(Decisão 2026-06-11.)*

## Sub-fatias e processo

- **4a**: tabela + `paper_data` (criar/validar/anular/fechar/listar) + tracker + cron + página de registro completa + nav + testes. Usável sozinha (lista de fechados crua já aparece).
- **4b**: espelho (`espelho_view` + página + detalhe de trade).
- Cada sub-fatia: plano TDD → implementação → validação visual com checklist na instância 5055 → **commit só com OK explícito do Gabriel**.
- Expectativa registrada: o espelho engorda com semanas/meses de uso disciplinado (n≥30 pra leitura inicial séria); sem pressa, alinhado ao 80/20.
