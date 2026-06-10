// Raio-X dos Trades — frontend (vanilla). Le /api/raiox/* e plota com lightweight-charts 4.2.0.
const RX = {
  chart: null,
  candleSeries: null,
  priceLines: [],
  liveTimer: null,
  current: null,
  currentTf: "15m",
};
const q = (s) => document.querySelector(s);
const TF = ["15m", "1h", "4h", "1d"];

function fmtTime(s) {
  return new Date(s * 1000).toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

function initChart() {
  RX.chart = LightweightCharts.createChart(q("#chart"), {
    height: 420,
    layout: { background: { color: "#0d0d0d" }, textColor: "#ccc" },
    grid: { vertLines: { color: "#1c1c1c" }, horzLines: { color: "#1c1c1c" } },
    timeScale: { timeVisible: true },
  });
  RX.candleSeries = RX.chart.addCandlestickSeries();
  q("#tf-buttons").innerHTML = TF.map(t => `<button data-tf="${t}">${t}</button>`).join(" ");
  q("#tf-buttons").querySelectorAll("button").forEach(b =>
    b.onclick = () => RX.current && loadChart(RX.current, b.dataset.tf));
}

function clearLines() {
  RX.priceLines.forEach(l => RX.candleSeries.removePriceLine(l));
  RX.priceLines = [];
}

function addLine(price, color, title) {
  if (price == null) return;
  RX.priceLines.push(RX.candleSeries.createPriceLine({ price, color, lineWidth: 1, title }));
}

async function loadFeed() {
  const r = await fetch("/api/raiox/trades");
  const d = await r.json();
  if (!d.ok) return;
  const op = d.open;
  q("#open-pos").innerHTML = op
    ? `<div class="open-card">🟢 ABERTA: ${op.symbol} ${op.direction} · entrou ${op.entry_price}
        <button id="live-btn">ver ao vivo →</button></div>`
    : "<div>nenhuma posição aberta</div>";
  if (op) q("#live-btn").onclick = () => openLive(op);
  q("#trade-feed").innerHTML = d.closed.map(t =>
    `<li data-id="${t.id}" class="trade-row" style="cursor:pointer;margin:6px 0;padding:8px;border:1px solid #333;border-radius:6px">
      ${t.exit_icon} ${t.symbol} ${t.direction} · ${t.pnl_pct.toFixed(2)}% · ${t.exit_reason} · ${fmtTime(t.timestamp_s)}
    </li>`).join("");
  q("#trade-feed").querySelectorAll("li").forEach(li =>
    li.onclick = () => openTrade(li.dataset.id));
}

async function openTrade(id) {
  stopLive();
  const r = await fetch(`/api/raiox/trade/${id}`);
  const d = await r.json();
  if (!d.ok) return;
  RX.current = { kind: "closed", t: d.trade };
  q("#trade-summary").textContent = d.trade.summary;
  await loadChart(RX.current, "15m");
}

function openLive(op) {
  stopLive();
  RX.current = { kind: "open", t: op };
  q("#trade-summary").textContent = `${op.symbol} ${op.direction} · entrada ${op.entry_price} · ao vivo`;
  loadChart(RX.current, "15m");
  RX.liveTimer = setInterval(() => loadChart(RX.current, RX.currentTf), 30000);
}

function stopLive() {
  if (RX.liveTimer) {
    clearInterval(RX.liveTimer);
    RX.liveTimer = null;
  }
}

function setMarkers(ctx, t) {
  const entryTime = ctx.kind === "closed" ? t.entry_time_s : t.open_time_s;
  const markers = [{
    time: entryTime,
    position: t.direction === "LONG" ? "belowBar" : "aboveBar",
    color: "#26a69a",
    shape: t.direction === "LONG" ? "arrowUp" : "arrowDown",
    text: ctx.kind === "closed" ? "entrada estimada" : "entrada",
  }];
  if (ctx.kind === "closed") {
    markers.push({
      time: t.exit_time_s,
      position: t.direction === "LONG" ? "aboveBar" : "belowBar",
      color: "#ef5350",
      shape: "circle",
      text: t.exit_reason,
    });
  }
  RX.candleSeries.setMarkers(markers);
}

async function loadChart(ctx, tf) {
  RX.currentTf = tf;
  const t = ctx.t;
  const entry = ctx.kind === "closed" ? t.entry_time_s : t.open_time_s;
  const exit = ctx.kind === "closed" ? t.exit_time_s : Math.floor(Date.now() / 1000);
  const url = `/api/raiox/candles?symbol=${t.symbol}&interval=${tf}&start=${entry}&end=${exit}`;
  const r = await fetch(url);
  const d = await r.json();
  if (!d.ok) {
    q("#trade-summary").textContent += `\n(candles indisponíveis: ${d.message})`;
    return;
  }
  RX.candleSeries.setData(d.candles);
  RX.chart.timeScale().fitContent();
  clearLines();
  addLine(t.entry_price, "#26a69a", "entrada");
  addLine(t.sl_price, "#ef5350", "stop");
  addLine(t.tp1_price, "#42a5f5", "TP1");
  addLine(t.tp2_price, "#42a5f5", "TP2");
  setMarkers(ctx, t);
  if (ctx.kind === "open") {
    const last = d.candles[d.candles.length - 1];
    if (last) {
      const pnl = ((last.close - t.entry_price) / t.entry_price * 100) * (t.direction === "LONG" ? 1 : -1);
      q("#trade-summary").textContent =
        `${t.symbol} ${t.direction} · entrada ${t.entry_price} · agora ${last.close} · PnL ${pnl.toFixed(2)}% · ao vivo`;
    }
  }
  if (d.effective_interval !== tf) {
    q("#trade-summary").textContent += `\n(janela longa: mostrando em ${d.effective_interval})`;
  }
}

initChart();
loadFeed();
// deep-link: /raiox/?trade=<id> abre direto o detalhe (usado pelo mapa)
const deepId = new URLSearchParams(location.search).get("trade");
if (deepId && /^\d+$/.test(deepId)) openTrade(deepId);
