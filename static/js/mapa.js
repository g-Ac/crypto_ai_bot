// Mapa da Moeda — todos os trades do momentum plotados no histórico.
// Reusa /api/raiox/mapa (overlay) e /api/raiox/candles (OHLC). lightweight-charts 4.2.0 local.
const MP = {
  chart: null, series: null,
  symbol: "BTCUSDT", tf: "4h",
  trades: [], tfEffSec: 14400,
  gen: 0,
};
const COLORS = { win: "#26a69a", loss: "#ef5350", fee_ate: "#ff9800" };
const SYMBOLS = ["BTCUSDT", "ETHUSDT"];
const TFS = ["4h", "1d"];
const TF_SEC = { "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400 };
const MARGIN_S = 2 * 86400;       // margem antes do 1º trade
const FALLBACK_DAYS = 30;         // janela quando a moeda não tem trades
const q = (s) => document.querySelector(s);  // "q" e nao "$": base.html ja declara const $ no escopo global

function initChart() {
  MP.chart = LightweightCharts.createChart(q("#chart"), {
    height: 520,
    layout: { background: { color: "#0d0d0d" }, textColor: "#ccc" },
    grid: { vertLines: { color: "#1c1c1c" }, horzLines: { color: "#1c1c1c" } },
    timeScale: { timeVisible: true },
  });
  MP.series = MP.chart.addCandlestickSeries();
  MP.chart.subscribeClick(onChartClick);
  q("#symbol-buttons").innerHTML = SYMBOLS.map(s =>
    `<button data-symbol="${s}">${s.replace("USDT", "")}</button>`).join(" ");
  q("#symbol-buttons").querySelectorAll("button").forEach(b =>
    b.onclick = () => { MP.symbol = b.dataset.symbol; reload(); });
  q("#tf-buttons").innerHTML = TFS.map(t => `<button data-tf="${t}">${t}</button>`).join(" ");
  q("#tf-buttons").querySelectorAll("button").forEach(b =>
    b.onclick = () => { MP.tf = b.dataset.tf; reload(); });
}

function setStatus(msg) { q("#mapa-status").textContent = msg; }

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
  const g = ++MP.gen;
  setStatus("carregando…");
  const ro = await fetch(`/api/raiox/mapa?symbol=${MP.symbol}`);
  const ov = await ro.json();
  if (g !== MP.gen) return;  // resposta velha: outro load() ja comecou
  if (!ov.ok) { setStatus(`erro no overlay: ${ov.error}`); return; }
  MP.trades = ov.trades;
  const now = Math.floor(Date.now() / 1000);
  const start = MP.trades.length
    ? Math.min(...MP.trades.map(t => t.entry_time_s)) - MARGIN_S
    : now - FALLBACK_DAYS * 86400;
  const rc = await fetch(`/api/raiox/candles?symbol=${MP.symbol}&interval=${MP.tf}&start=${start}&end=${now}`);
  const cd = await rc.json();
  if (g !== MP.gen) return;  // resposta velha: outro load() ja comecou
  if (!cd.ok) { setStatus(`candles indisponíveis: ${cd.message || cd.error}`); return; }
  MP.series.setData(cd.candles);
  MP.series.setMarkers(markersOf(MP.trades));
  MP.chart.timeScale().fitContent();
  MP.tfEffSec = TF_SEC[cd.effective_interval] || TF_SEC[MP.tf];
  let msg = `${MP.symbol} · ${MP.trades.length} trades · TF ${cd.effective_interval}`;
  if (cd.effective_interval !== MP.tf) msg += " (janela longa: TF escalado)";
  if (!MP.trades.length) msg += " · sem trades desta moeda";
  setStatus(msg);
}

function reload() {
  load().catch(() => setStatus("erro ao carregar — tente de novo"));
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
reload();
