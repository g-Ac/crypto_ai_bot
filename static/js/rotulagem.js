// Rotulagem cega — um trade por vez, candles ATE a entrada (resultado escondido).
// Captura gostei/nao + 4 pistas + palpite de saida (clique no grafico), grava, avanca.
// Reusa lightweight-charts 4.2.0 (mesmo motor do raiox.js). Sem lib nova.
(function () {
  "use strict";
  var R = { chart: null, series: null, current: null, guess: null, guessLine: null, supLines: [], busy: false };
  var q = function (s) { return document.querySelector(s); };
  var COL = { up: "#46ff9a", down: "#ff6b6b", sup: "#5fe3c8", pivot: "#f0b90b", guess: "#cfd8d0" };
  var CUES = ["empurrao", "nivel", "direcao", "recuo"];

  function initChart() {
    R.chart = LightweightCharts.createChart(q("#rot-chart"), {
      height: 420,
      layout: { background: { color: "#0a120a" }, textColor: "#8fe6b3" },
      grid: { vertLines: { color: "#13251a" }, horzLines: { color: "#13251a" } },
      timeScale: { timeVisible: true, borderColor: "#1d3a24" },
      rightPriceScale: { borderColor: "#1d3a24" },
    });
    R.series = R.chart.addCandlestickSeries({
      upColor: COL.up, downColor: COL.down, wickUpColor: COL.up, wickDownColor: COL.down, borderVisible: false,
    });
    R.chart.subscribeClick(function (param) {
      if (!param.point || !R.series) return;
      var price = R.series.coordinateToPrice(param.point.y);
      if (price == null || !isFinite(price) || price <= 0) return;
      R.guess = Number(price.toPrecision(6));
      if (R.guessLine) { try { R.series.removePriceLine(R.guessLine); } catch (e) {} }
      R.guessLine = R.series.createPriceLine({ price: R.guess, color: COL.guess, lineWidth: 1, lineStyle: 0, title: "saída" });
      q("#rot-guess").textContent = "sairia em " + R.guess;
    });
  }

  function plot(d) {
    R.series.setData(d.candles || []);
    var markers = [{
      time: d.entry_time_s,
      position: d.direction === "LONG" ? "belowBar" : "aboveBar",
      color: COL.up, shape: d.direction === "LONG" ? "arrowUp" : "arrowDown", text: "entrada",
    }];
    ((d.swings && d.swings.lows) || []).forEach(function (p) {
      markers.push({ time: p.time, position: "belowBar", color: COL.pivot, shape: "circle" });
    });
    ((d.swings && d.swings.highs) || []).forEach(function (p) {
      markers.push({ time: p.time, position: "aboveBar", color: COL.pivot, shape: "circle" });
    });
    markers.sort(function (a, b) { return a.time - b.time; });
    R.series.setMarkers(markers);
    R.supLines.forEach(function (l) { try { R.series.removePriceLine(l); } catch (e) {} });
    R.supLines = (d.supports || []).map(function (lv) {
      return R.series.createPriceLine({ price: lv.price, color: COL.sup, lineWidth: 1, lineStyle: 2, title: "suporte" });
    });
    R.chart.timeScale().fitContent();
  }

  function resetPanel() {
    CUES.forEach(function (c) { q("#cue-" + c).checked = false; });
    R.guess = null;
    if (R.guessLine) { try { R.series.removePriceLine(R.guessLine); } catch (e) {} R.guessLine = null; }
    q("#rot-guess").textContent = "sem palpite de saída";
  }

  function showProgress(p) {
    if (!p) return;
    q("#rot-prog").textContent = p.done + " de " + p.total + " rotulados";
    q("#rot-barfill").style.width = (p.total ? (p.done / p.total * 100) : 0) + "%";
  }

  async function loadNext() {
    R.busy = true;
    var d;
    try { d = await (await fetch("/api/rotulagem/next")).json(); }
    catch (e) { q("#rot-meta").textContent = "erro de rede: " + e.message; R.busy = false; return; }
    if (!d.ok) {
      if (d.error === "binance_unavailable") { q("#rot-meta").textContent = "Binance indisponível — nova tentativa em 4s"; setTimeout(loadNext, 4000); return; }
      q("#rot-meta").textContent = "erro: " + (d.message || d.error); R.busy = false; return;
    }
    showProgress(d.progress);
    if (d.done) {
      q("#rot-panel").style.display = "none";
      q("#rot-chart").style.display = "none";
      q("#rot-meta").textContent = "lote completo";
      q("#rot-done").style.display = "block";
      R.busy = false;
      return;
    }
    R.current = d;
    resetPanel();
    var meta = q("#rot-meta");
    meta.textContent = d.symbol + " · ";
    var dirEl = document.createElement("span");
    dirEl.className = d.direction === "LONG" ? "long" : "short";
    dirEl.textContent = d.direction;
    var idEl = document.createElement("span");
    idEl.className = "rot-trade-id";
    idEl.textContent = " #" + d.trade_id;
    meta.appendChild(dirEl);
    meta.appendChild(idEl);
    plot(d);
    R.busy = false;
  }

  async function submit(verdict) {
    if (R.busy || !R.current) return;
    R.busy = true;
    var cues = {};
    CUES.forEach(function (c) { cues[c] = q("#cue-" + c).checked; });
    var body = { trade_id: R.current.trade_id, verdict: verdict, cues: cues, exit_price_guess: R.guess };
    try {
      var res = await (await fetch("/api/rotulagem/label", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      })).json();
      if (!res.ok) { alert("erro ao gravar: " + ((res.errors || []).join(", ") || res.error)); R.busy = false; return; }
    } catch (e) { alert("falha de rede: " + e.message); R.busy = false; return; }
    loadNext();
  }

  if (!q("#rot-chart")) return;
  if (typeof LightweightCharts === "undefined") { q("#rot-meta").textContent = "lib de gráfico não carregou"; return; }
  initChart();
  q("#btn-like").onclick = function () { submit("gostei"); };
  q("#btn-nope").onclick = function () { submit("nao"); };
  document.addEventListener("keydown", function (e) {
    if (e.target && /input|textarea/i.test(e.target.tagName)) return;
    if (e.key === "g" || e.key === "G") submit("gostei");
    else if (e.key === "n" || e.key === "N") submit("nao");
    else if (e.key >= "1" && e.key <= "4") { var c = q("#cue-" + CUES[+e.key - 1]); if (c) c.checked = !c.checked; }
  });
  loadNext();
})();
