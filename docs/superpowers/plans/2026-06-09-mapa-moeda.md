# Mapa da Moeda — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Página `/raiox/mapa` com todos os trades do momentum plotados sobre o histórico da moeda (BTC/ETH), coloridos por resultado net, com clique abrindo o Raio-X do trade.

**Architecture:** Backend puro em `raiox_data.py` (`_classify_result` + `trades_overlay`, sem Flask/rede), rotas finas em `dashboard_server.py`, frontend vanilla JS reusando a lib lightweight-charts local e o endpoint `/api/raiox/candles` já existente.

**Tech Stack:** Python 3.13 + Flask + SQLite (leitura), lightweight-charts 4.2.0 local, vanilla JS. Spec: `docs/superpowers/specs/2026-06-09-mapa-moeda-design.md`.

---

## Regras de execução (NÃO pular)

1. **Sem commits automáticos.** Regra dura do Gabriel (CLAUDE.md + spec). Nenhuma task commita. Ao fim de cada task o diff fica acumulado no working tree; commit só quando o Gabriel aprovar explicitamente. Os steps de "checkpoint" substituem os commits.
2. **Hook PostToolUse roda pytest sozinho** a cada Write/Edit em `.py`. NÃO rodar a suite manualmente — os steps "verificar red/green" significam: ler a saída do hook após salvar o arquivo. Red esperado = só os testes novos falham; green = suite inteira passa (~700 testes).
3. **Não tocar:** `market.py`, schema do banco, `momentum/`, `main.py`, `/pip/`. Sem CDN.
4. Working dir: `~/crypto_ai_bot`, branch `lab/trend-following-2026-06-02`.
5. Instância de validação: dashboard dev na porta 5055 (`DASHBOARD_PORT=5055 .venv/bin/python dashboard_server.py`), já no ar. Produção (5000, systemd) só é reiniciada após commit aprovado.

**Dados reais para conferência (banco `runtime/baseline/bot.db`, 2026-06-09):** 149 trades (80 BTC, 69 ETH), 82 win, 8 fee_ate, 0 `net_pnl_pct` NULL.

---

### Task 1: `_classify_result` em `raiox_data.py`

**Files:**
- Modify: `raiox_data.py` (após `_pnl_of`, ~linha 58)
- Test: `tests/test_raiox_data.py` (após `test_pnl_of_prefers_net`)

- [ ] **Step 1: Escrever os testes (red)**

Em `tests/test_raiox_data.py`, adicionar após `test_pnl_of_prefers_net` (linha ~100):

```python
def test_classify_result_win_loss_fee_ate():
    assert rx._classify_result(0.49, 0.59) == "win"      # net > 0
    assert rx._classify_result(-0.88, -0.78) == "loss"   # net <= 0, bruto <= 0
    assert rx._classify_result(-0.05, 0.05) == "fee_ate" # bruto > 0, net <= 0


def test_classify_result_bordas_zero():
    assert rx._classify_result(0.0, 0.10) == "fee_ate"   # net == 0 com bruto positivo: fee comeu
    assert rx._classify_result(0.0, 0.0) == "loss"       # tudo zero: loss
    assert rx._classify_result(0.01, 0.0) == "win"       # net positivo manda, mesmo bruto zero
```

- [ ] **Step 2: Confirmar red na saída do hook**

Esperado: os 2 testes novos falham com `AttributeError: module 'raiox_data' has no attribute '_classify_result'`. Todo o resto passa.

- [ ] **Step 3: Implementar mínimo**

Em `raiox_data.py`, adicionar após `_pnl_of` (linha ~58):

```python
def _classify_result(pnl_net: float, pnl_bruto: float) -> str:
    """Classifica o resultado do trade: win / loss / fee_ate (bruto positivo que a fee comeu)."""
    if pnl_net > 0:
        return "win"
    if pnl_bruto > 0:
        return "fee_ate"
    return "loss"
```

- [ ] **Step 4: Confirmar green na saída do hook**

Esperado: suite inteira passa.

- [ ] **Step 5: Checkpoint** — diff de `raiox_data.py` + `tests/test_raiox_data.py` acumulado. Sem commit.

---

### Task 2: `trades_overlay(conn, symbol)` em `raiox_data.py`

**Files:**
- Modify: `raiox_data.py` (após `trade_detail`, ~linha 164)
- Test: `tests/test_raiox_data.py` (após os testes da Task 1; reusa fixture `trades_conn` e helper `_ins` já existentes no arquivo)

- [ ] **Step 1: Escrever os testes (red)**

```python
def test_trades_overlay_filters_symbol_and_classifies(trades_conn):
    _ins(trades_conn, id=1, timestamp="2026-06-01T12:00:00+00:00", symbol="BTCUSDT",
         direction="LONG", entry_price=100000.0, exit_price=101000.0,
         duration_candles=4, pnl_pct=1.0, net_pnl_pct=0.9)        # win
    _ins(trades_conn, id=2, timestamp="2026-06-02T12:00:00+00:00", symbol="BTCUSDT",
         direction="SHORT", entry_price=101000.0, exit_price=102000.0,
         duration_candles=2, pnl_pct=-0.99, net_pnl_pct=-1.09)    # loss
    _ins(trades_conn, id=3, timestamp="2026-06-03T12:00:00+00:00", symbol="BTCUSDT",
         direction="LONG", entry_price=102000.0, exit_price=102050.0,
         duration_candles=8, pnl_pct=0.05, net_pnl_pct=-0.05)     # fee_ate
    _ins(trades_conn, id=4, timestamp="2026-06-04T12:00:00+00:00", symbol="ETHUSDT",
         direction="LONG", entry_price=1700.0, exit_price=1717.0,
         duration_candles=3, pnl_pct=1.0, net_pnl_pct=0.9)        # outro simbolo: fora
    out = rx.trades_overlay(trades_conn, "BTCUSDT")
    assert out["ok"] is True and out["symbol"] == "BTCUSDT"
    assert [t["id"] for t in out["trades"]] == [1, 2, 3]          # ordem temporal crescente
    assert [t["result"] for t in out["trades"]] == ["win", "loss", "fee_ate"]
    t1 = out["trades"][0]
    assert t1["exit_time_s"] == rx._to_epoch_s("2026-06-01T12:00:00+00:00")
    assert t1["entry_time_s"] == t1["exit_time_s"] - 4 * 15 * 60  # estimativa igual a do trade_detail
    assert t1["entry_time_s"] < t1["exit_time_s"]
    assert t1["direction"] == "LONG"
    assert t1["entry_price"] == 100000.0 and t1["exit_price"] == 101000.0
    assert t1["pnl_pct"] == 0.9 and t1["pnl_source"] == "net_pnl_pct"


def test_trades_overlay_empty_when_no_trades(trades_conn):
    out = rx.trades_overlay(trades_conn, "BTCUSDT")
    assert out["ok"] is True and out["symbol"] == "BTCUSDT"
    assert out["trades"] == []


def test_trades_overlay_net_null_classifica_pelo_bruto(trades_conn):
    _ins(trades_conn, id=1, timestamp="2026-06-01T12:00:00+00:00", symbol="BTCUSDT",
         direction="LONG", entry_price=100.0, exit_price=101.0,
         duration_candles=1, pnl_pct=1.0, net_pnl_pct=None)
    t = rx.trades_overlay(trades_conn, "BTCUSDT")["trades"][0]
    assert t["result"] == "win"            # sem net nao existe "fee_ate": classifica pelo bruto
    assert t["pnl_pct"] == 1.0 and t["pnl_source"] == "pnl_pct"


def test_trades_overlay_factual_no_action_words(trades_conn):
    _ins(trades_conn, id=1, timestamp="2026-06-01T12:00:00+00:00", symbol="BTCUSDT",
         direction="LONG", entry_price=100.0, exit_price=101.0,
         duration_candles=1, pnl_pct=1.0, net_pnl_pct=0.9)
    blob = _json.dumps(rx.trades_overlay(trades_conn, "BTCUSDT"), ensure_ascii=False).lower()
    for w in rx.FORBIDDEN_ACTION_PHRASES:
        assert w not in blob, f"overlay contem frase de acao: {w!r}"
```

(`_json` já está importado no topo do arquivo de teste.)

- [ ] **Step 2: Confirmar red na saída do hook**

Esperado: os 4 testes novos falham com `AttributeError: ... has no attribute 'trades_overlay'`.

- [ ] **Step 3: Implementar**

Em `raiox_data.py`, após `trade_detail` (linha ~164):

```python
def trades_overlay(conn, symbol: str) -> dict:
    """Todos os trades fechados de um simbolo como pontos de plotagem do mapa.

    entry_time_s e ESTIMADO (timestamp - duration_candles * 15min), igual ao trade_detail.
    Sem net_pnl_pct no row, classifica pelo bruto (nunca vira fee_ate).
    """
    rows = conn.execute(
        "SELECT id, timestamp, direction, entry_price, exit_price, "
        "duration_candles, pnl_pct, net_pnl_pct "
        "FROM momentum_trades WHERE symbol=? ORDER BY id ASC", (symbol,)
    ).fetchall()
    trades = []
    for r in rows:
        pnl, source = _pnl_of(r)
        exit_s = _to_epoch_s(r["timestamp"])
        dur = r["duration_candles"] or 0
        bruto = float(_row_get(r, "pnl_pct") or 0.0)
        net = _row_get(r, "net_pnl_pct")
        trades.append({
            "id": r["id"],
            "direction": r["direction"],
            "entry_time_s": exit_s - dur * MOMENTUM_INTERVAL_MIN * 60,
            "entry_price": r["entry_price"],
            "exit_time_s": exit_s,
            "exit_price": r["exit_price"],
            "result": _classify_result(float(net) if net is not None else bruto, bruto),
            "pnl_pct": pnl,
            "pnl_source": source,
        })
    return {"ok": True, "symbol": symbol, "trades": trades}
```

Nota: `ORDER BY id ASC` ⇒ ordem temporal crescente por símbolo (momentum tem 1 posição por símbolo por vez, então id cresce com o tempo dentro do símbolo).

- [ ] **Step 4: Confirmar green na saída do hook**

- [ ] **Step 5: Checkpoint** — backend puro completo. Sem commit.

---

### Task 3: endpoint `GET /api/raiox/mapa` em `dashboard_server.py`

**Files:**
- Modify: `dashboard_server.py` (após `api_raiox_candles`, ~linha 1584)
- Test: `tests/test_raiox_endpoints.py` (reusa fixture `client`, que insere 1 trade ETHUSDT id=1 com `pnl_pct=-0.78, net_pnl_pct=-0.88` ⇒ `loss`)

- [ ] **Step 1: Escrever os testes (red)**

Em `tests/test_raiox_endpoints.py`, ao final do arquivo:

```python
def test_api_mapa_ok(client):
    r = client.get("/api/raiox/mapa?symbol=ETHUSDT")
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True and d["symbol"] == "ETHUSDT"
    assert len(d["trades"]) == 1
    t = d["trades"][0]
    assert t["id"] == 1 and t["result"] == "loss"
    assert t["entry_time_s"] < t["exit_time_s"]
    assert t["pnl_source"] == "net_pnl_pct"


def test_api_mapa_symbol_sem_trades(client):
    r = client.get("/api/raiox/mapa?symbol=BTCUSDT")
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True and d["trades"] == []


def test_api_mapa_symbol_invalido(client):
    r = client.get("/api/raiox/mapa?symbol=DOGEUSDT")
    assert r.status_code == 400
    assert r.get_json()["error"] == "symbol_invalido"
```

- [ ] **Step 2: Confirmar red na saída do hook**

Esperado: os 3 testes falham com status 404 (rota não existe).

- [ ] **Step 3: Implementar a rota**

Em `dashboard_server.py`, inserir após a função `api_raiox_candles` (depois da linha ~1584, antes de `@app.route("/legacy")`):

```python
@app.route("/api/raiox/mapa")
def api_raiox_mapa():
    symbol = request.args.get("symbol", "")
    if symbol not in raiox_data.VALID_SYMBOLS:
        return jsonify({"ok": False, "error": "symbol_invalido", "message": "simbolo nao suportado"}), 400
    conn = db._get_conn()
    try:
        out = raiox_data.trades_overlay(conn, symbol)
    finally:
        conn.close()
    return jsonify(out)
```

(Mesmo padrão de `api_raiox_trades`: conexão via `db._get_conn()`, fecha no `finally`, GET sem auth.)

- [ ] **Step 4: Confirmar green na saída do hook**

- [ ] **Step 5: Checkpoint** — API do mapa completa. Sem commit.

---

### Task 4: página `/raiox/mapa` + `templates/mapa.html` + nav

**Files:**
- Modify: `dashboard_server.py` (junto da rota da Task 3)
- Create: `templates/mapa.html`
- Modify: `templates/base.html` (nav desktop ~linha 27 e nav mobile ~linha 65)
- Test: `tests/test_raiox_endpoints.py`

- [ ] **Step 1: Escrever o teste (red)**

Ao final de `tests/test_raiox_endpoints.py`:

```python
def test_mapa_page_renders(client):
    r = client.get("/raiox/mapa")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Mapa da Moeda" in html
    assert "mapa.js" in html
```

- [ ] **Step 2: Confirmar red na saída do hook** — falha com 404.

- [ ] **Step 3: Criar `templates/mapa.html`**

```html
{% extends "base.html" %}
{% block title %}Mapa{% endblock %}
{% block content %}
<!-- lightweight-charts 4.2.0 (local, sem CDN) -->
<script src="/static/js/lightweight-charts.standalone.production.js"></script>
<section class="card">
  <div class="card-header">
    <h1>🗺️ Mapa da Moeda</h1>
    <p>Todos os trades do momentum sobre o histórico. 🟢 ganho · 🔴 perda · 🟠 fee comeu · clique num marcador abre o Raio-X.</p>
  </div>
  <div style="display:flex;gap:16px;margin-bottom:8px;flex-wrap:wrap">
    <div id="symbol-buttons"></div>
    <div id="tf-buttons"></div>
  </div>
  <div id="chart" style="height:520px"></div>
  <div id="mapa-status" style="margin-top:8px"></div>
</section>
<script src="/static/js/mapa.js"></script>
{% endblock %}
```

- [ ] **Step 4: Adicionar a rota da página**

Em `dashboard_server.py`, logo antes de `api_raiox_mapa`:

```python
@app.route("/raiox/mapa")
def raiox_mapa_page():
    return render_template("mapa.html", active_page="mapa")
```

- [ ] **Step 5: Confirmar green na saída do hook**

(O teste passa mesmo sem `static/js/mapa.js` existir — o template só referencia o script; o arquivo vem na Task 5.)

- [ ] **Step 6: Nav — desktop e mobile em `templates/base.html`**

Na `ul.nav-links` (linha ~27), adicionar após o item Raio-X:

```html
            <li><a href="/raiox/mapa" {% if active_page == 'mapa' %}class="active"{% endif %}>Mapa</a></li>
```

Na `nav.mobile-nav` (linha ~65), adicionar após o item Raio-X:

```html
      <a href="/raiox/mapa" {% if active_page == 'mapa' %}class="active"{% endif %}>Mapa</a>
```

- [ ] **Step 7: Checkpoint** — página renderiza, nav nos 2 menus. Sem commit.

---

### Task 5: `static/js/mapa.js` — candles + marcadores + seletores

**Files:**
- Create: `static/js/mapa.js`

Sem teste automatizado (frontend visual — validação real na Task 7). Hook pytest não dispara em `.js`.

- [ ] **Step 1: Criar `static/js/mapa.js` completo**

```js
// Mapa da Moeda — todos os trades do momentum plotados no histórico.
// Reusa /api/raiox/mapa (overlay) e /api/raiox/candles (OHLC). lightweight-charts 4.2.0 local.
const MP = {
  chart: null, series: null,
  symbol: "BTCUSDT", tf: "4h",
  trades: [], tfEffSec: 14400,
};
const COLORS = { win: "#26a69a", loss: "#ef5350", fee_ate: "#ff9800" };
const SYMBOLS = ["BTCUSDT", "ETHUSDT"];
const TFS = ["4h", "1d"];
const TF_SEC = { "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400 };
const MARGIN_S = 2 * 86400;       // margem antes do 1º trade
const FALLBACK_DAYS = 30;         // janela quando a moeda não tem trades
const $ = (s) => document.querySelector(s);

function initChart() {
  MP.chart = LightweightCharts.createChart($("#chart"), {
    height: 520,
    layout: { background: { color: "#0d0d0d" }, textColor: "#ccc" },
    grid: { vertLines: { color: "#1c1c1c" }, horzLines: { color: "#1c1c1c" } },
    timeScale: { timeVisible: true },
  });
  MP.series = MP.chart.addCandlestickSeries();
  MP.chart.subscribeClick(onChartClick);
  $("#symbol-buttons").innerHTML = SYMBOLS.map(s =>
    `<button data-symbol="${s}">${s.replace("USDT", "")}</button>`).join(" ");
  $("#symbol-buttons").querySelectorAll("button").forEach(b =>
    b.onclick = () => { MP.symbol = b.dataset.symbol; load(); });
  $("#tf-buttons").innerHTML = TFS.map(t => `<button data-tf="${t}">${t}</button>`).join(" ");
  $("#tf-buttons").querySelectorAll("button").forEach(b =>
    b.onclick = () => { MP.tf = b.dataset.tf; load(); });
}

function status(msg) { $("#mapa-status").textContent = msg; }

function markersOf(trades) {
  const m = [];
  for (const t of trades) {
    const color = COLORS[t.result] || COLORS.loss;
    m.push({
      time: t.entry_time_s,
      position: t.direction === "LONG" ? "belowBar" : "aboveBar",
      shape: t.direction === "LONG" ? "arrowUp" : "arrowDown",
      color, id: "e" + t.id,
    });
    m.push({
      time: t.exit_time_s,
      position: t.direction === "LONG" ? "aboveBar" : "belowBar",
      shape: "circle", color, id: "x" + t.id,
      text: (t.pnl_pct >= 0 ? "+" : "") + t.pnl_pct.toFixed(2) + "%",
    });
  }
  return m.sort((a, b) => a.time - b.time);  // setMarkers exige ordem temporal crescente
}

async function load() {
  status("carregando…");
  const ro = await fetch(`/api/raiox/mapa?symbol=${MP.symbol}`);
  const ov = await ro.json();
  if (!ov.ok) { status(`erro no overlay: ${ov.error}`); return; }
  MP.trades = ov.trades;
  const now = Math.floor(Date.now() / 1000);
  const start = MP.trades.length
    ? Math.min(...MP.trades.map(t => t.entry_time_s)) - MARGIN_S
    : now - FALLBACK_DAYS * 86400;
  const rc = await fetch(`/api/raiox/candles?symbol=${MP.symbol}&interval=${MP.tf}&start=${start}&end=${now}`);
  const cd = await rc.json();
  if (!cd.ok) { status(`candles indisponíveis: ${cd.message || cd.error}`); return; }
  MP.series.setData(cd.candles);
  MP.series.setMarkers(markersOf(MP.trades));
  MP.chart.timeScale().fitContent();
  MP.tfEffSec = TF_SEC[cd.effective_interval] || TF_SEC[MP.tf];
  let msg = `${MP.symbol} · ${MP.trades.length} trades · TF ${cd.effective_interval}`;
  if (cd.effective_interval !== MP.tf) msg += " (janela longa: TF escalado)";
  if (!MP.trades.length) msg += " · sem trades desta moeda";
  status(msg);
}

function onChartClick(param) {
  // clique exatamente sobre um marcador: id "e<trade_id>" ou "x<trade_id>"
  if (param.hoveredObjectId) {
    window.location.href = "/raiox/?trade=" + String(param.hoveredObjectId).slice(1);
    return;
  }
  // clique perto: trade com entrada/saída mais próxima do tempo clicado (tolerância 2 velas)
  if (param.time === undefined || !MP.trades.length) return;
  const tol = 2 * MP.tfEffSec;
  let best = null, bestDist = Infinity;
  for (const t of MP.trades) {
    const d = Math.min(Math.abs(param.time - t.entry_time_s), Math.abs(param.time - t.exit_time_s));
    if (d < bestDist) { bestDist = d; best = t; }
  }
  if (best && bestDist <= tol) window.location.href = "/raiox/?trade=" + best.id;
}

initChart();
load();
```

Decisões embutidas (vindas da spec): marcadores ordenados por tempo (exigência do `setMarkers`); cores por `result`; saída com `text` = pnl; clique usa `hoveredObjectId` quando o cursor está sobre o marcador (preciso) com fallback por distância de tempo (tolerância 2 velas do TF efetivo); clique longe ignora; moeda sem trades mostra só candles dos últimos 30 dias; `effective_interval` respeitado quando o backend escala o TF.

- [ ] **Step 2: Smoke manual rápido**

```bash
curl -s "http://localhost:5055/raiox/mapa" | grep -c "mapa.js"   # esperado: 1
curl -s "http://localhost:5055/api/raiox/mapa?symbol=BTCUSDT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['ok'], len(d['trades']))"
# esperado: True 80
```

(Se a instância 5055 tiver sido iniciada antes destas mudanças, reiniciar antes: ver Task 7 Step 1.)

- [ ] **Step 3: Checkpoint** — mapa plota. Validação visual completa fica na Task 7. Sem commit.

---

### Task 6: deep-link `?trade=<id>` no Raio-X

**Files:**
- Modify: `static/js/raiox.js` (final do arquivo, linhas 139-140)

Sem teste automatizado (JS puro; comportamento coberto na validação real).

- [ ] **Step 1: Editar o final de `static/js/raiox.js`**

Hoje:

```js
initChart();
loadFeed();
```

Trocar por:

```js
initChart();
loadFeed();
// deep-link: /raiox/?trade=<id> abre direto o detalhe (usado pelo mapa)
const deepId = new URLSearchParams(location.search).get("trade");
if (deepId) openTrade(deepId);
```

(`openTrade` já existe e busca `/api/raiox/trade/<id>` por conta própria — não depende do feed; id inexistente retorna `ok:false` e é ignorado em silêncio, que é o comportamento atual do feed.)

- [ ] **Step 2: Smoke manual**

Abrir `http://<ip>:5055/raiox/?trade=1` no navegador: o detalhe do trade 1 deve carregar sozinho (summary + gráfico), sem precisar clicar no feed.

- [ ] **Step 3: Checkpoint** — ciclo mapa→raio-x fechado. Sem commit.

---

### Task 7: validação real (checklist da spec)

**Files:** nenhum novo — validação.

- [ ] **Step 1: Reiniciar a instância dev 5055 com o código novo**

```bash
fuser -k 5055/tcp 2>/dev/null || true   # mata so quem escuta na 5055 (pkill por env var nao acha; pkill por nome mataria o dashboard de producao)
cd ~/crypto_ai_bot && DASHBOARD_PORT=5055 nohup .venv/bin/python dashboard_server.py > /tmp/dash5055.log 2>&1 &
sleep 3 && curl -s http://localhost:5055/api/status >/dev/null && echo "5055 OK"
```

- [ ] **Step 2: API — fumaça com dados reais**

```bash
curl -s "http://localhost:5055/api/raiox/mapa?symbol=BTCUSDT" | python3 -c "
import sys, json; d = json.load(sys.stdin)
rs = [t['result'] for t in d['trades']]
print('ok:', d['ok'], '· trades:', len(rs), '· win:', rs.count('win'), '· loss:', rs.count('loss'), '· fee_ate:', rs.count('fee_ate'))"
# esperado: ok: True · trades: 80 e contagens coerentes (total geral: 82 win / 8 fee_ate em 149)
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:5055/api/raiox/mapa?symbol=DOGEUSDT"   # esperado: 400
```

Para achar 1 trade de cada cor pro check visual:

```bash
sqlite3 ~/crypto_ai_bot/runtime/baseline/bot.db "
SELECT id, symbol, CASE WHEN net_pnl_pct > 0 THEN 'win' WHEN pnl_pct > 0 THEN 'fee_ate' ELSE 'loss' END r
FROM momentum_trades GROUP BY r;"
```

- [ ] **Step 3: Checklist visual no navegador (Gabriel)** — `http://<ip-do-pi>:5055/raiox/mapa`

- [ ] `/raiox/mapa` carrega; seletores de moeda e TF presentes
- [ ] candles cobrem o histórico todo da moeda (1º trade → agora)
- [ ] marcadores de entrada/saída aparecem; cores corretas (conferir os 3 ids do Step 2: 1 win 🟢, 1 loss 🔴, 1 fee_ate 🟠)
- [ ] clique num marcador abre o Raio-X **do trade certo**
- [ ] trocar BTC↔ETH recarrega; trocar 4h↔1d recarrega
- [ ] item "Mapa" na nav (desktop e mobile), com estado ativo
- [ ] console do navegador sem erro JS

- [ ] **Step 4: Encerrar** — apresentar ao Gabriel o diff completo (`git diff` + `git status`) e o resultado do checklist. **Commit e restart do cryptobot (produção, porta 5000) só após aprovação explícita.**

---

## Fora de escopo (guardas da spec)

Sem linha entrada↔saída, sem SL/TP no mapa, sem agregados/ranking, sem seletor de período, sem TF < 4h, sem outros ativos, sem sinal/recomendação, sem CDN, sem tocar `market.py`/schema/bot.
