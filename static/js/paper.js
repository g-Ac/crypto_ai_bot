// Aba Paper — grafico com niveis clicaveis + R:R + countdown void.
// Reusa /api/raiox/candles (mesma fonte do Raio-X). Sem lib nova.
// data.candles consumido diretamente por series.setData (time = epoch seconds,
// shape ja pronto pelo endpoint — copiado do comportamento do raiox.js).

(function () {
  "use strict";

  var PP = {
    chart: null,
    series: null,
    lines: {},
    activeField: "f-entry",
    tf: "4h",
    gen: 0,
  };

  var TF_DAYS = { "15m": 7, "1h": 30, "4h": 60, "1d": 180 };

  var LINE_STYLE = {
    "f-entry":  { color: "#378ADD", title: "entrada",  lineStyle: 2 },
    "f-stop":   { color: "#E24B4A", title: "stop",     lineStyle: 2 },
    "f-target": { color: "#639922", title: "alvo",     lineStyle: 2 },
  };

  // ── Helpers ────────────────────────────────────────────────

  function pnum(el) {
    return parseFloat((el && el.value || "").replace(",", "."));
  }

  function pq(sel) {
    return document.querySelector(sel);
  }

  function chartEl() {
    return pq("#paper-chart");
  }

  function getSymbol() {
    var el = chartEl();
    return el ? el.dataset.symbol : null;
  }

  // ── Chart init ─────────────────────────────────────────────

  function initChart() {
    var el = chartEl();
    if (!el) return;

    // Mirror raiox.js exactly: same height/layout/grid/timeScale
    PP.chart = LightweightCharts.createChart(el, {
      height: 360,
      layout: {
        background: { color: "#0d0d0d" },
        textColor: "#ccc",
      },
      grid: {
        vertLines: { color: "#1c1c1c" },
        horzLines: { color: "#1c1c1c" },
      },
      timeScale: { timeVisible: true },
    });

    PP.series = PP.chart.addCandlestickSeries();

    // Click-to-fill: write coordinateToPrice into the active price field
    PP.chart.subscribeClick(function (param) {
      if (!param.point) return;
      if (!PP.series) return;
      var price = PP.series.coordinateToPrice(param.point.y);
      if (price == null || !isFinite(price) || price <= 0) return;
      var input = pq("#" + PP.activeField);
      if (!input) return;
      // Sensible precision: 6 significant figures (same as plan spec)
      input.value = Number(price.toPrecision(6));
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }

  // ── Candle loading ─────────────────────────────────────────

  function showChartError(msg) {
    var el = chartEl();
    if (!el) return;
    var existing = el.querySelector(".paper-chart-error");
    if (existing) existing.remove();
    var div = document.createElement("div");
    div.className = "paper-chart-error";
    div.textContent = "candles indisponiveis: " + msg;
    el.appendChild(div);
  }

  function clearChartError() {
    var el = chartEl();
    if (!el) return;
    var existing = el.querySelector(".paper-chart-error");
    if (existing) existing.remove();
  }

  function loadCandles() {
    var symbol = getSymbol();
    if (!symbol || !PP.series) return;
    var g = ++PP.gen;  // Fix 2: generation counter — stale responses bail early
    var end = Math.floor(Date.now() / 1000);
    var days = TF_DAYS[PP.tf] || 60;  // Fix 1: per-TF window
    var start = end - days * 86400;
    var url =
      "/api/raiox/candles?symbol=" + symbol +
      "&interval=" + PP.tf +
      "&start=" + start +
      "&end=" + end +
      "&margin=0";
    fetch(url)
      .then(function (res) {
        if (!res.ok) {
          throw new Error("HTTP " + res.status);
        }
        return res.json();
      })
      .then(function (data) {
        if (g !== PP.gen) return;  // Fix 2: stale response — a newer load() already ran
        if (!data.ok) {
          showChartError(data.message || "erro desconhecido");
          return;
        }
        clearChartError();
        // data.candles already shaped for LightweightCharts (time = epoch s)
        PP.series.setData(data.candles);
        if (data.candles.length) {
          PP.chart.timeScale().fitContent();
        }
        // Fix 1: sync UI when server escalated the TF (e.g. 15m→4h for long window)
        if (data.effective_interval && data.effective_interval !== PP.tf) {
          console.warn("paper.js: TF escalado pelo servidor de " + PP.tf + " para " + data.effective_interval);
          PP.tf = data.effective_interval;
          document.querySelectorAll(".paper-tfs button").forEach(function (b) {
            b.classList.remove("active");
            if (b.dataset.tf === PP.tf) b.classList.add("active");
          });
        }
      })
      .catch(function (err) {
        if (g !== PP.gen) return;  // Fix 2: stale error — don't overwrite a fresh success
        showChartError(err.message || String(err));
      });
  }

  // ── Price lines ────────────────────────────────────────────

  function refreshLine(fieldId) {
    if (!PP.series) return;
    // Remove existing line for this field
    if (PP.lines[fieldId]) {
      try { PP.series.removePriceLine(PP.lines[fieldId]); } catch (e) {}
      PP.lines[fieldId] = null;
    }
    var input = pq("#" + fieldId);
    if (!input) return;
    var v = pnum(input);  // Fix 4: comma-tolerant parsing
    if (!isFinite(v) || v <= 0) return;
    var st = LINE_STYLE[fieldId];
    PP.lines[fieldId] = PP.series.createPriceLine({
      price: v,
      color: st.color,
      lineWidth: 1,
      lineStyle: st.lineStyle,
      title: st.title,
      axisLabelVisible: true,
    });
  }

  // ── R:R display ────────────────────────────────────────────

  function refreshRR() {
    var out = pq("#rr-line");
    if (!out) return;
    var e = pnum(pq("#f-entry"));    // Fix 4: comma-tolerant parsing
    var s = pnum(pq("#f-stop"));
    var t = pnum(pq("#f-target"));
    if (![e, s, t].every(function (x) { return isFinite(x) && x > 0; }) || e === s) {
      out.textContent = "R:R —";
      return;
    }
    var risk   = Math.abs(e - s) / e * 100;
    var reward = Math.abs(t - e) / e * 100;
    if (risk < 1e-8) {
      out.textContent = "R:R —";
      return;
    }
    out.textContent =
      "risco " + risk.toFixed(1) + "% · " +
      "retorno " + reward.toFixed(1) + "% · " +
      "R:R 1 : " + (reward / risk).toFixed(1);
  }

  // ── Form wiring ────────────────────────────────────────────

  function initForm() {
    // Price fields: focus sets active; input updates line + R:R
    ["f-entry", "f-stop", "f-target"].forEach(function (id) {
      var input = pq("#" + id);
      if (!input) return;
      input.addEventListener("focus", function () {
        PP.activeField = id;
        // Fix 3: toggle price-active class to the focused input
        ["f-entry", "f-stop", "f-target"].forEach(function (fid) {
          var fi = pq("#" + fid);
          if (fi) fi.classList.remove("price-active");
        });
        input.classList.add("price-active");
      });
      input.addEventListener("input", function () {
        refreshLine(id);
        refreshRR();
      });
    });

    // Symbol nav: navigate on change
    var nav = pq("#paper-symbol-nav");
    if (nav) {
      nav.addEventListener("change", function (ev) {
        window.location = "/raiox/paper?symbol=" + encodeURIComponent(ev.target.value);
      });
    }

    // TF buttons: switch active class + reload
    document.querySelectorAll(".paper-tfs button").forEach(function (b) {
      b.addEventListener("click", function (ev) {
        ev.preventDefault();
        document.querySelectorAll(".paper-tfs button").forEach(function (x) {
          x.classList.remove("active");
        });
        b.classList.add("active");
        PP.tf = b.dataset.tf || PP.tf;
        loadCandles();
      });
    });

    // Initialise R:R and lines for any pre-filled values (e.g. form re-render on error)
    ["f-entry", "f-stop", "f-target"].forEach(function (id) {
      refreshLine(id);
    });
    refreshRR();
  }

  // ── Void countdown ─────────────────────────────────────────

  function initVoidCountdown() {
    document.querySelectorAll(".paper-trade-row[data-created]").forEach(function (row) {
      var btn = row.querySelector('form[action$="/anular"] button');
      if (!btn) return;
      var created = Number(row.dataset.created);

      function tick() {
        var left = 600 - (Math.floor(Date.now() / 1000) - created);
        if (left <= 0) {
          var form = btn.closest("form");
          if (form) form.remove();
          return;
        }
        btn.textContent = "anular (" + Math.ceil(left / 60) + " min)";
        setTimeout(tick, 15000);
      }

      tick();
    });
  }

  // ── Boot ───────────────────────────────────────────────────

  // Guard: only run if page elements exist (script loaded on paper page only)
  if (!chartEl()) return;

  // Fix 5: guard against missing chart lib so initForm/initVoidCountdown still run
  if (typeof LightweightCharts !== "undefined") {
    initChart();
    loadCandles();
  }
  initForm();
  initVoidCountdown();

})();
