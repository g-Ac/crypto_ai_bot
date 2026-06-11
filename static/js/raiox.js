// Raio-X dos Trades — frontend (vanilla). Le /api/raiox/* e plota com lightweight-charts 4.2.0.
// Estilo Pip-Boy legivel + didatico (veredito, passos, glossario) + simulador what-if sobre candles reais.
const RX = {
  chart: null, candleSeries: null, priceLines: [],
  liveTimer: null, current: null, currentTf: "15m",
  feed: { open: null, closed: [] }, filters: { symbol: "", result: "" },
  selectedId: null, candles: [], noteEstimated: false, noteTf: null,
};
const q = (s) => document.querySelector(s);
const TF = ["15m", "1h", "4h", "1d"];
const TF_SEC = { "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400 };
const TFSEC = TF_SEC;
const FETCH_MARGIN = 150;     // velas buscadas pra cada lado do trade (estrada pra arrastar/zoom)
const VIEW_MARGIN_BARS = 20;  // velas visiveis em volta do trade ao abrir (mesmo foco de antes)
const COL = { g: "#46ff9a", red: "#ff6b6b", tp: "#5fe3c8" };

function fmtTime(s) {
  return new Date(s * 1000).toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}
function resultClass(exitReason) {
  const r = (exitReason || "").toLowerCase();
  if (r.includes("tp")) return "ganho";
  if (r.includes("sl")) return "perda";
  if (r.includes("timeout")) return "timeout";
  return "outro";
}
function durTxt(candles) {
  const m = (candles || 0) * 15;
  return m >= 60 ? `~${(m / 60).toFixed(1)}h (${candles} velas)` : `${m}min (${candles} velas)`;
}
function tfMin() { return TFSEC[RX.currentTf] / 60; }

function initChart() {
  RX.chart = LightweightCharts.createChart(q("#chart"), {
    height: 380,
    layout: { background: { color: "#0a120a" }, textColor: "#8fe6b3" },
    grid: { vertLines: { color: "#13251a" }, horzLines: { color: "#13251a" } },
    timeScale: { timeVisible: true, borderColor: "#1d3a24" },
    rightPriceScale: { borderColor: "#1d3a24" },
  });
  RX.candleSeries = RX.chart.addCandlestickSeries({
    upColor: COL.g, downColor: COL.red, wickUpColor: COL.g, wickDownColor: COL.red, borderVisible: false,
    autoscaleInfoProvider: (orig) => {
      const res = orig();
      if (!res || !res.priceRange) return res;
      const ps = RX.overlayPrices || [];
      if (!ps.length) return res;
      let mn = res.priceRange.minValue, mx = res.priceRange.maxValue;
      ps.forEach(p => { if (p < mn) mn = p; if (p > mx) mx = p; });
      return { priceRange: { minValue: mn, maxValue: mx }, margins: res.margins };
    },
  });
  q("#tf-buttons").innerHTML = TF.map(t => `<button data-tf="${t}"${t === "15m" ? ' class="on"' : ""}>${t}</button>`).join("");
  q("#tf-buttons").querySelectorAll("button").forEach(b =>
    b.onclick = () => {
      if (!RX.current) return;
      q("#tf-buttons").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
      if (RX.current.kind === "market") loadMarketChart(RX.current.t.symbol, b.dataset.tf);
      else loadChart(RX.current, b.dataset.tf);
    });
  q("#rx-filter-symbol").onchange = (e) => { RX.filters.symbol = e.target.value; renderFeed(); };
  q("#rx-filter-result").onchange = (e) => { RX.filters.result = e.target.value; renderFeed(); };
  q("#copy-context-btn").onclick = copyContext;
  initPaper();
}

function clearLines() {
  RX.priceLines.forEach(l => RX.candleSeries.removePriceLine(l));
  RX.priceLines = [];
  RX.overlayPrices = [];
}
function addLine(price, color, title, style) {
  if (price == null) return;
  RX.priceLines.push(RX.candleSeries.createPriceLine({ price, color, lineWidth: 1, lineStyle: style || 0, title }));
  (RX.overlayPrices || (RX.overlayPrices = [])).push(+price);
}
function rescale() {
  try { const s = RX.chart.priceScale("right"); s.applyOptions({ autoScale: false }); s.applyOptions({ autoScale: true }); } catch (e) { /* ignore */ }
}
function setTfButton(tf) {
  q("#tf-buttons").querySelectorAll("button").forEach(x => x.classList.toggle("on", x.dataset.tf === tf));
}
function lightSteps() {
  q("#rx-steps").querySelectorAll(".step").forEach(s => s.classList.add("on"));
}

async function loadFeed() {
  let d;
  try {
    const r = await fetch("/api/raiox/trades");
    d = await r.json();
  } catch (e) {
    q("#open-pos").innerHTML = `<div class="open-empty">feed indisponível: ${e.message}</div>`;
    return;
  }
  if (!d.ok) { q("#open-pos").innerHTML = `<div class="open-empty">feed indisponível</div>`; return; }
  RX.feed = { open: d.open || null, closed: d.closed || [] };
  populateSymbolFilter();
  renderOpen();
  renderFeed();
}
function populateSymbolFilter() {
  const sel = q("#rx-filter-symbol");
  const extra = RX.feed.open ? [RX.feed.open.symbol] : [];
  const syms = [...new Set(RX.feed.closed.map(t => t.symbol).concat(extra))].sort();
  const cur = RX.filters.symbol;
  sel.innerHTML = `<option value="">Todos os símbolos</option>` +
    syms.map(s => `<option value="${s}"${s === cur ? " selected" : ""}>${s}</option>`).join("");
}
function renderOpen() {
  const op = RX.feed.open;
  const el = q("#open-pos");
  if (!op) { el.innerHTML = `<div class="open-empty">nenhuma posição aberta</div>`; return; }
  const active = RX.current && RX.current.kind === "open" ? " active" : "";
  el.innerHTML =
    `<div class="open-card${active}"><span class="live">●</span> <strong>ABERTA</strong> · ${op.symbol} ${op.direction} · entrou ${op.entry_price}
       <button class="toolbtn" id="live-btn" type="button" style="margin-top:6px">ver ao vivo →</button></div>`;
  q("#live-btn").onclick = () => openLive(op);
}
function renderFeed() {
  const { symbol, result } = RX.filters;
  const searchVal = q("#rx-search") ? q("#rx-search").value.trim().toUpperCase() : "";
  const rows = RX.feed.closed.filter(t =>
    (!symbol || t.symbol === symbol) &&
    (!result || resultClass(t.exit_reason) === result) &&
    (!searchVal || t.symbol.toUpperCase().includes(searchVal))
  );
  q("#trade-feed").innerHTML = rows.map(t => {
    const w = t.pnl_pct >= 0;
    return `<li data-id="${t.id}" class="row${String(t.id) === String(RX.selectedId) ? " on" : ""}">
      <span>${t.exit_icon} <span class="sym">${t.symbol}</span> ${t.direction}</span>
      <span class="${w ? "win" : "loss"}">${w ? "+" : ""}${t.pnl_pct.toFixed(2)}% · ${t.exit_reason}</span></li>`;
  }).join("") || `<li class="open-empty">nenhum trade para esse filtro</li>`;
  q("#trade-feed").querySelectorAll("li[data-id]").forEach(li => li.onclick = () => openTrade(li.dataset.id));
  const total = RX.feed.closed.length;
  q("#rx-count").textContent = rows.length === total ? `${total} trades` : `${rows.length} de ${total}`;
}
function markActiveRow() {
  q("#trade-feed").querySelectorAll("li[data-id]").forEach(li =>
    li.classList.toggle("on", li.dataset.id === RX.selectedId));
}

function verdict(t) {
  const r = (t.exit_reason || "").toLowerCase();
  const d = durTxt(t.duration_candles);
  if (r.includes("tp2")) return { cls: "w", html: `✓ Bateu o <strong>TP2</strong> (alvo cheio) — ganho de +${t.pnl_pct.toFixed(2)}% em ${d}.` };
  if (r.includes("tp1") || r.includes("tp")) return { cls: "w", html: `✓ Bateu o <strong>TP1</strong> (primeiro alvo) — ganho de +${t.pnl_pct.toFixed(2)}% em ${d}.` };
  if (r.includes("sl")) return { cls: "l", html: `✗ Bateu o <strong>stop</strong> — perda de ${t.pnl_pct.toFixed(2)}% em ${d}.` };
  if (r.includes("timeout")) return { cls: t.pnl_pct >= 0 ? "w" : "l", html: `⏱️ Saiu por <strong>timeout</strong> — resultado ${t.pnl_pct >= 0 ? "+" : ""}${t.pnl_pct.toFixed(2)}% em ${d}.` };
  return { cls: "", html: `Saiu (${t.exit_reason}) — ${t.pnl_pct >= 0 ? "+" : ""}${t.pnl_pct.toFixed(2)}%.` };
}

async function openTrade(id) {
  stopLive();
  let d;
  try {
    const r = await fetch(`/api/raiox/trade/${id}`);
    d = await r.json();
  } catch (e) { showChartError(`detalhe indisponível: ${e.message}`, false); return; }
  if (!d.ok) { showChartError("trade não encontrado", false); return; }
  RX.current = { kind: "closed", t: d.trade };
  RX.selectedId = String(id);
  markActiveRow(); renderOpen(); lightSteps();
  const v = verdict(d.trade);
  const el = q("#rx-verdict");
  el.className = "verdict " + v.cls; el.style.borderStyle = "solid"; el.innerHTML = v.html;
  q("#trade-summary").style.display = "block";
  q("#trade-summary").textContent = d.trade.summary;
  prefillTicket(d.trade.symbol, d.trade.entry_price);
  showCopyButton(true);
  showEntryNote(d.trade.entry_time_estimated);
  setTfButton("15m");
  await loadChart(RX.current, "15m");
}

function openLive(op) {
  stopLive();
  RX.current = { kind: "open", t: op };
  RX.selectedId = null;
  markActiveRow(); renderOpen(); lightSteps();
  showEntryNote(false);
  showCopyButton(true);
  const el = q("#rx-verdict");
  el.className = "verdict"; el.style.borderStyle = "solid";
  el.innerHTML = `● Posição <strong>ABERTA</strong> · ${op.symbol} ${op.direction} · entrada ${op.entry_price} · acompanhando ao vivo.`;
  q("#trade-summary").style.display = "block";
  q("#trade-summary").textContent = `${op.symbol} ${op.direction} · entrada ${op.entry_price} · ao vivo`;
  prefillTicket(op.symbol, op.entry_price);
  setTfButton("15m");
  loadChart(RX.current, "15m");
  RX.liveTimer = setInterval(() => loadChart(RX.current, RX.currentTf), 30000);
}

function stopLive() {
  if (RX.liveTimer) { clearInterval(RX.liveTimer); RX.liveTimer = null; }
}

function setMarkers(ctx, t) {
  const entryTime = ctx.kind === "closed" ? t.entry_time_s : t.open_time_s;
  const markers = [{
    time: entryTime,
    position: t.direction === "LONG" ? "belowBar" : "aboveBar",
    color: COL.g, shape: t.direction === "LONG" ? "arrowUp" : "arrowDown",
    text: ctx.kind === "closed" ? "entrada estimada" : "entrada",
  }];
  if (ctx.kind === "closed") {
    markers.push({
      time: t.exit_time_s,
      position: t.direction === "LONG" ? "aboveBar" : "belowBar",
      color: COL.red, shape: "circle", text: t.exit_reason,
    });
  }
  RX.candleSeries.setMarkers(markers);
}

async function loadChart(ctx, tf) {
  RX.currentTf = tf; RX.noteTf = null;
  const t = ctx.t;
  const entry = ctx.kind === "closed" ? t.entry_time_s : t.open_time_s;
  const exit = ctx.kind === "closed" ? t.exit_time_s : Math.floor(Date.now() / 1000);
  const url = `/api/raiox/candles?symbol=${t.symbol}&interval=${tf}&start=${entry}&end=${exit}&margin=${FETCH_MARGIN}`;
  let r, d;
  try { r = await fetch(url); d = await r.json(); }
  catch (e) { showChartError(`Não foi possível carregar candles (rede): ${e.message}`, true); return; }
  if (!d.ok) { showCandleError(d, r ? r.status : 0); return; }
  clearChartError();
  RX.candles = d.candles || [];
  RX.candleSeries.setData(RX.candles);
  if (RX.candles.length) {
    const effTfSec = TF_SEC[d.effective_interval] || TF_SEC[tf] || 900;
    RX.chart.timeScale().setVisibleRange({
      from: entry - VIEW_MARGIN_BARS * effTfSec,
      to: exit + VIEW_MARGIN_BARS * effTfSec,
    });
  } else {
    RX.chart.timeScale().fitContent();
  }
  clearLines();
  addLine(t.entry_price, COL.g, "entrada");
  addLine(t.sl_price, COL.red, "stop");
  addLine(t.tp1_price, COL.tp, "TP1");
  addLine(t.tp2_price, COL.tp, "TP2");
  setMarkers(ctx, t);
  if (ctx.kind === "open") {
    const last = RX.candles[RX.candles.length - 1];
    if (last) {
      const pnl = ((last.close - t.entry_price) / t.entry_price * 100) * (t.direction === "LONG" ? 1 : -1);
      q("#trade-summary").textContent =
        `${t.symbol} ${t.direction} · entrada ${t.entry_price} · agora ${last.close} · PnL ${pnl.toFixed(2)}% · ao vivo`;
    }
  }
  if (d.effective_interval !== tf) RX.noteTf = `janela longa: mostrando em ${d.effective_interval}`;
  renderNote();
  rescale();
}

function showEntryNote(estimated) { RX.noteEstimated = !!estimated; renderNote(); }
function renderNote() {
  const parts = [];
  if (RX.noteEstimated) parts.push("⚠ Entrada estimada — reconstruída a partir da duração do trade; pode divergir do candle real.");
  if (RX.noteTf) parts.push("🔎 " + RX.noteTf);
  const el = q("#entry-note");
  if (parts.length) { el.innerHTML = parts.join("<br>"); el.style.display = "block"; }
  else { el.style.display = "none"; el.innerHTML = ""; }
}
function showCandleError(d, status) {
  let msg;
  if (d.error === "binance_unavailable" || status === 502) msg = "⚠ Binance indisponível agora — não foi possível carregar os candles.";
  else if (d.error === "janela_muito_longa") msg = "Janela longa demais, até para velas diárias — sem candles para exibir.";
  else if (d.error === "intervalo_invalido") msg = "Intervalo inválido para esse trade.";
  else msg = `Candles indisponíveis: ${d.message || d.error || "erro desconhecido"}.`;
  const retry = d.error !== "janela_muito_longa" && d.error !== "intervalo_invalido";
  showChartError(msg, retry);
}
function showChartError(msg, retry) {
  const el = q("#chart-error");
  el.innerHTML = msg + (retry ? ` <button id="rx-retry" type="button">tentar de novo</button>` : "");
  el.style.display = "block";
  if (retry) { const b = q("#rx-retry"); if (b) b.onclick = retryChart; }
}
function retryChart() {
  if (!RX.current) return;
  if (RX.current.kind === "market") loadMarketChart(RX.current.t.symbol, RX.currentTf);
  else loadChart(RX.current, RX.currentTf);
}
function clearChartError() { const el = q("#chart-error"); el.style.display = "none"; el.innerHTML = ""; }

function showCopyButton(show) { q("#copy-context-btn").style.display = show ? "inline-block" : "none"; }
function buildContext(ctx) {
  const t = ctx.t;
  const mfe = t.mfe_pct != null ? "+" + t.mfe_pct + "%" : "n/d";
  const mae = t.mae_pct != null ? t.mae_pct + "%" : "n/d";
  if (ctx.kind === "closed") {
    return [
      `Raio-X · Trade #${t.id} · ${t.symbol} ${t.direction} · regime ${t.regime}`,
      `Entrada estimada: ${t.entry_price} (${fmtTime(t.entry_time_s)})`,
      `Saída: ${t.exit_price} (${t.exit_reason}, ${fmtTime(t.exit_time_s)})`,
      `SL ${t.sl_price} · TP1 ${t.tp1_price} · TP2 ${t.tp2_price}`,
      `Duração: ${t.duration_candles} velas`,
      `Resultado: ${t.pnl_pct.toFixed(2)}% (${t.pnl_source === "net_pnl_pct" ? "net" : "bruto"})`,
      `MFE ${mfe} · MAE ${mae}`,
    ].join("\n");
  }
  return [
    `Raio-X · Posição ABERTA · ${t.symbol} ${t.direction} · regime ${t.regime || "n/d"}`,
    `Entrada: ${t.entry_price} (${t.open_time_s ? fmtTime(t.open_time_s) : "n/d"})`,
    `SL ${t.sl_price} · TP1 ${t.tp1_price} · TP2 ${t.tp2_price}`,
    `Velas decorridas: ${t.candles_elapsed != null ? t.candles_elapsed : "n/d"}`,
  ].join("\n");
}
function copyFeedback() {
  const f = q("#copy-feedback"); f.style.display = "inline";
  setTimeout(() => f.style.display = "none", 1500);
}
function fallbackCopy(text) {
  const ta = document.createElement("textarea");
  ta.value = text; document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); copyFeedback(); } catch (e) { /* ignore */ }
  document.body.removeChild(ta);
}
function copyContext() {
  if (!RX.current) return;
  const text = buildContext(RX.current);
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(copyFeedback).catch(() => fallbackCopy(text));
  } else { fallbackCopy(text); }
}

const PAPER = { side: "LONG" };
const ERRMAP = {
  side_invalido: "Escolha Comprar ou Vender.",
  symbol_invalido: "Par não suportado.",
  param_invalido: "Margem/alavancagem inválidas.",
  margin_invalido: "Margem inválida.",
  leverage_invalido: "Alavancagem deve ser entre 1x e 125x.",
  saldo_insuficiente: "Saldo insuficiente para essa margem.",
  sl_invalido: "Stop do lado errado (LONG: abaixo da entrada; SHORT: acima).",
  tp_invalido: "Alvo do lado errado (LONG: acima da entrada; SHORT: abaixo).",
  entry_invalido: "Preço de entrada inválido.",
  preco_indisponivel: "Sem preço de mercado agora — informe o preço manualmente.",
  nao_encontrado: "Posição não encontrada.",
};
function usd(v) { return (v < 0 ? "-" : "") + "$" + Math.abs(v).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function pcls(v) { return v > 0 ? "win" : v < 0 ? "loss" : "dim"; }

function renderOffsetButtons() {
  const priceInput = q("#o-price");
  const price = parseFloat(priceInput.value) || (RX.candles && RX.candles.length ? RX.candles[RX.candles.length - 1].close : null);
  const side = PAPER.side;
  
  const slPresets = side === "LONG" ? [-0.5, -1, -2] : [0.5, 1, 2];
  const tpPresets = side === "LONG" ? [1, 2, 5] : [-1, -2, -5];
  
  const slContainer = q("#sl-presets");
  const tpContainer = q("#tp-presets");
  if (slContainer && tpContainer) {
    slContainer.innerHTML = `<button type="button" data-cancel="1">Off</button>` + slPresets.map(p => `<button type="button" data-offset="${p}">${p > 0 ? "+" : ""}${p}%</button>`).join("");
    tpContainer.innerHTML = `<button type="button" data-cancel="1">Off</button>` + tpPresets.map(p => `<button type="button" data-offset="${p}">${p > 0 ? "+" : ""}${p}%</button>`).join("");
    
    slContainer.querySelectorAll("button").forEach(b => {
      b.onclick = () => {
        if (b.dataset.cancel) {
          q("#o-sl").value = "";
        } else {
          const offset = parseFloat(b.dataset.offset);
          if (price > 0) q("#o-sl").value = (price * (1 + offset / 100)).toFixed(2);
        }
        if (RX.current && RX.current.kind === "market") drawTicketLines();
      };
    });
    tpContainer.querySelectorAll("button").forEach(b => {
      b.onclick = () => {
        if (b.dataset.cancel) {
          q("#o-tp").value = "";
        } else {
          const offset = parseFloat(b.dataset.offset);
          if (price > 0) q("#o-tp").value = (price * (1 + offset / 100)).toFixed(2);
        }
        if (RX.current && RX.current.kind === "market") drawTicketLines();
      };
    });
  }
}

function initPaper() {
  q("#o-side").querySelectorAll("button").forEach(b => b.onclick = () => setSide(b.dataset.side));
  q("#o-lev").oninput = () => { q("#o-lev-out").textContent = q("#o-lev").value + "x"; updateCalc(); };
  ["o-price", "o-margin"].forEach(id => q("#" + id).oninput = () => { updateCalc(); renderOffsetButtons(); });
  q("#o-symbol").onchange = () => loadMarketChart(q("#o-symbol").value, RX.currentTf || "15m");
  ["o-price", "o-sl", "o-tp"].forEach(id => q("#" + id).addEventListener("input", () => {
    if (RX.current && RX.current.kind === "market") drawTicketLines();
  }));
  q("#o-submit").onclick = submitOrder;
  q("#pp-reset").onclick = resetBook;

  // Search input hook
  const searchInput = q("#rx-search");
  if (searchInput) searchInput.oninput = () => { renderFeed(); };

  // Margin quick presets hook
  const marginPresets = q("#margin-presets");
  if (marginPresets) {
    marginPresets.querySelectorAll("button").forEach(b => {
      b.onclick = () => {
        const pct = parseFloat(b.dataset.pct);
        const avail = RX.availableBalance || 10000;
        q("#o-margin").value = Math.floor(avail * (pct / 100));
        updateCalc();
      };
    });
  }

  // Leverage quick presets hook
  const leveragePresets = q("#leverage-presets");
  if (leveragePresets) {
    leveragePresets.querySelectorAll("button").forEach(b => {
      b.onclick = () => {
        const lev = parseInt(b.dataset.lev);
        q("#o-lev").value = lev;
        q("#o-lev-out").textContent = lev + "x";
        updateCalc();
        if (RX.current && RX.current.kind === "market") drawTicketLines();
      };
    });
  }

  setSide("LONG");
  updateCalc();
  loadPaper();
  setInterval(loadPaper, 6000);
  loadMarketChart(q("#o-symbol").value || "ETHUSDT", "15m");
}
function setSide(side) {
  PAPER.side = side;
  q("#o-side").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.side === side));
  const sb = q("#o-submit");
  sb.className = "submit " + (side === "LONG" ? "buy" : "sell");
  sb.textContent = side === "LONG" ? "Comprar / Long" : "Vender / Short";
  const form = q("#ticket-form");
  if (form) {
    form.classList.toggle("long-mode", side === "LONG");
    form.classList.toggle("short-mode", side === "SHORT");
  }
  renderOffsetButtons();
  updateCalc();
}
function prefillTicket(symbol, price) {
  if (symbol) q("#o-symbol").value = symbol;
  if (price != null) q("#o-price").value = price;
  renderOffsetButtons();
  updateCalc();
}
function updateCalc() {
  const price = parseFloat(q("#o-price").value);
  const margin = parseFloat(q("#o-margin").value);
  const lev = parseFloat(q("#o-lev").value);
  const notional = (margin || 0) * (lev || 0);
  let txt = `Tamanho da posição: <strong>${usd(notional || 0)}</strong> (margem ${usd(margin || 0)} × ${lev || 0}x).`;
  if (price > 0 && lev > 0) {
    const liq = PAPER.side === "LONG" ? price * (1 - 1 / lev) : price * (1 + 1 / lev);
    txt += `<br>Liquidação aprox.: <strong>${liq.toFixed(2)}</strong> · cada 1% a favor ≈ <strong>${usd((notional || 0) / 100)}</strong>.`;
  }
  q("#o-calc").innerHTML = txt;
}


async function submitOrder() {
  const msg = q("#o-msg");
  msg.className = "o-msg"; msg.textContent = "enviando...";
  const body = {
    symbol: q("#o-symbol").value,
    side: PAPER.side,
    entry_price: q("#o-price").value || null,
    margin_usd: q("#o-margin").value,
    leverage: q("#o-lev").value,
    sl_price: q("#o-sl").value || null,
    tp_price: q("#o-tp").value || null,
  };
  let d;
  try {
    const r = await fetch("/api/raiox/paper/order", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    d = await r.json();
  } catch (e) { msg.className = "o-msg err"; msg.textContent = "falha de rede: " + e.message; return; }
  if (!d.ok) { msg.className = "o-msg err"; msg.textContent = ERRMAP[d.error] || ("erro: " + d.error); return; }
  const p = d.position;
  msg.className = "o-msg ok";
  msg.textContent = `Ordem aberta: ${p.side} ${p.symbol} · ${usd(p.notional_usd)} @ ${p.entry_price}.`;
  q("#o-sl").value = ""; q("#o-tp").value = "";
  loadPaper();
}

async function loadPaper() {
  let d;
  try { d = await (await fetch("/api/raiox/paper")).json(); }
  catch (e) { return; }
  if (!d.ok) return;
  RX.availableBalance = d.available;
  q("#pp-balance").textContent = usd(d.balance);
  q("#pp-equity").textContent = usd(d.equity);
  q("#pp-available").textContent = usd(d.available);
  const u = q("#pp-unreal"); u.textContent = (d.unrealized_usd >= 0 ? "+" : "") + usd(d.unrealized_usd).replace("$", "$");
  u.className = "v " + pcls(d.unrealized_usd);
  renderPositions(d.positions || []);
  renderClosed(d.closed || []);
  RX.openPositions = d.positions || [];
  RX.closedPositions = d.closed || [];
  if (RX.current && RX.current.kind === "market") drawTicketLines();
}

function renderPositions(rows) {
  const el = q("#pp-positions");
  if (!rows.length) { el.innerHTML = `<div class="open-empty">nenhuma posição paper aberta</div>`; return; }
  el.innerHTML = rows.map(p => {
    const m = p.mark;
    const pnl = m ? `<span class="${pcls(m.pnl_usd)}">${m.pnl_usd >= 0 ? "+" : ""}${usd(m.pnl_usd)} (${m.pnl_pct >= 0 ? "+" : ""}${m.pnl_pct}%)</span>` : `<span class="dim">sem preço</span>`;
    const sideTxt = p.side === "LONG" ? `<span class="win">${p.side}</span>` : `<span class="loss">${p.side}</span>`;
    const liq = m ? ` · liq ${m.liq_price}` : "";
    return `<div class="pos"><div class="top">
        <span>${sideTxt} ${p.symbol} · ${p.leverage}x · ${usd(p.notional_usd)}</span>
        <button class="closebtn" data-id="${p.id}" type="button">fechar</button></div>
      <div class="lvl">entrada ${p.entry_price}${m ? " · agora " + m.price : ""}${liq} · SL ${p.sl_price ?? "—"} · TP ${p.tp_price ?? "—"}</div>
      <div style="margin-top:3px">PnL: ${pnl}</div></div>`;
  }).join("");
  el.querySelectorAll(".closebtn").forEach(b => b.onclick = () => closePos(b.dataset.id));
}

function renderClosed(rows) {
  const el = q("#pp-closed");
  if (!rows.length) { el.innerHTML = `<div class="open-empty">sem fechamentos ainda</div>`; return; }
  el.innerHTML = rows.slice(0, 12).map(p =>
    `<div class="pos"><div class="top">
       <span>${p.side} ${p.symbol} · ${p.exit_reason}</span>
       <span class="${pcls(p.pnl_usd)}">${p.pnl_usd >= 0 ? "+" : ""}${usd(p.pnl_usd)} (${p.pnl_pct >= 0 ? "+" : ""}${p.pnl_pct}%)</span>
     </div><div class="lvl">entrada ${p.entry_price} → saída ${p.exit_price}</div></div>`).join("");
}

async function closePos(id) {
  try {
    const r = await fetch(`/api/raiox/paper/close/${id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    const d = await r.json();
    if (!d.ok) { q("#o-msg").className = "o-msg err"; q("#o-msg").textContent = ERRMAP[d.error] || ("erro: " + d.error); return; }
  } catch (e) { return; }
  loadPaper();
}

async function resetBook() {
  if (!confirm("Resetar o livro de paper manual? Apaga posições e histórico.")) return;
  try { await fetch("/api/raiox/paper/reset", { method: "POST" }); } catch (e) { }
  loadPaper();
}

function drawTicketLines() {
  if (!RX.current || RX.current.kind !== "market") return;
  clearLines();
  const sym = RX.current.t.symbol;
  const LIQ = "#ff9f1c", CUR = "#cfd8d0";
  const markers = [];
  const has = RX.candles.length;
  const first = has ? RX.candles[0].time : 0;
  const last = has ? RX.candles[RX.candles.length - 1].time : 0;
  // Preço atual (ao vivo se houver posição marcada a mercado, senão último candle)
  let cur = has ? RX.candles[RX.candles.length - 1].close : null;
  const mk = (RX.openPositions || []).find(p => p.symbol === sym && p.mark);
  if (mk) cur = mk.mark.price;
  if (cur) addLine(cur, CUR, "preço atual", 2);
  // Ordem sendo montada (preview a partir do ticket)
  const price = parseFloat(q("#o-price").value);
  const sl = parseFloat(q("#o-sl").value);
  const tp = parseFloat(q("#o-tp").value);
  if (price > 0) addLine(price, COL.g, "ordem: entrada");
  if (sl > 0) addLine(sl, COL.red, "ordem: stop");
  if (tp > 0) addLine(tp, COL.tp, "ordem: alvo");
  // Posições paper abertas nesse par: entrada (linha+marker), SL, TP, liquidação
  (RX.openPositions || []).filter(p => p.symbol === sym).forEach(p => {
    const c = p.side === "LONG" ? COL.g : COL.red;
    addLine(p.entry_price, c, `#${p.id} ${p.side} entrada ${p.entry_price}`);
    if (p.sl_price) addLine(p.sl_price, COL.red, `#${p.id} SL`);
    if (p.tp_price) addLine(p.tp_price, COL.tp, `#${p.id} TP`);
    const liq = p.mark ? p.mark.liq_price : (p.side === "LONG" ? p.entry_price * (1 - 1 / p.leverage) : p.entry_price * (1 + 1 / p.leverage));
    addLine(liq, LIQ, `#${p.id} LIQ ${(+liq).toFixed(2)}`, 2);
    if (has) {
      let t = p.open_time_s;
      if (t > last) t = last;
      if (t < first) t = first;
      markers.push({
        time: t, position: p.side === "LONG" ? "belowBar" : "aboveBar",
        color: c, shape: p.side === "LONG" ? "arrowUp" : "arrowDown",
        text: `entrada #${p.id} @ ${p.entry_price}`,
      });
    }
  });
  // Marker de saída para posições fechadas recentemente (dentro da janela)
  (RX.closedPositions || []).filter(p => p.symbol === sym).forEach(p => {
    if (!has) return;
    const t = p.close_time_s;
    if (t < first || t > last) return;
    markers.push({
      time: t, position: p.pnl_usd >= 0 ? "aboveBar" : "belowBar",
      color: p.pnl_usd >= 0 ? COL.g : COL.red, shape: "circle",
      text: `saída #${p.id} ${p.exit_reason}`,
    });
  });
  markers.sort((a, b) => a.time - b.time);
  if (has) RX.candleSeries.setMarkers(markers);
  rescale();
}

async function loadMarketChart(symbol, tf) {
  RX.current = { kind: "market", t: { symbol } };
  RX.currentTf = tf;
  setTfButton(tf);
  RX.selectedId = null;
  markActiveRow();
  showCopyButton(false);
  q("#trade-summary").style.display = "none";
  const now = Math.floor(Date.now() / 1000);
  const start = now - 50 * TFSEC[tf];
  let d;
  try {
    d = await (await fetch(`/api/raiox/candles?symbol=${symbol}&interval=${tf}&start=${start}&end=${now}`)).json();
  } catch (e) { showChartError("Não foi possível carregar o gráfico: " + e.message, true); return; }
  if (!d.ok) { showCandleError(d, 0); return; }
  clearChartError();
  RX.candles = d.candles || [];
  RX.candleSeries.setData(RX.candles);
  RX.chart.timeScale().fitContent();
  RX.candleSeries.setMarkers([]);
  drawTicketLines();
  showEntryNote(false);
  const last = RX.candles[RX.candles.length - 1];
  const el = q("#rx-verdict");
  el.className = "verdict"; el.style.borderStyle = "dashed";
  el.innerHTML = `📈 Mercado <strong>${symbol}</strong> (${tf})` + (last ? ` · último ${last.close}` : "") +
    ` <span class="dim">— clique num trade do feed para analisar o histórico</span>`;
}

initChart();
loadFeed();
// deep-link: /raiox/?trade=<id> abre direto o detalhe (usado pelo mapa)
const deepId = new URLSearchParams(location.search).get("trade");
if (deepId && /^\d+$/.test(deepId)) openTrade(deepId);
