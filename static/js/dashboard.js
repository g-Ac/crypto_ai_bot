/* ============================================================
   Dashboard V2 — Bloomberg density, live feel
   ============================================================ */

let _equityChart = null;
let _pollTimer = null;
let _tradesLoaded = false;

document.addEventListener('DOMContentLoaded', async () => {
  const d = await fetchStatus();
  if (d) renderAll(d);
  loadTrades();
  _pollTimer = setInterval(poll, 15000);  // 15s — Pi-friendly
});

async function poll() {
  const d = await fetchStatus();
  if (d) renderAll(d);
}

function renderAll(d) {
  renderKPIs(d);
  renderPositions(d.positions || []);
  renderSystemCards(d);
  renderMiniEquity(d.chart || {});
  updateFreshnessChips(d);
  // Trades loaded separately, not on every poll
}

function updateFreshnessChips(d) {
  // Positions + KPIs: freshness = last_update from backend
  setFreshness('fc-positions', d.last_update ? parseBackendTs(d.last_update) : null);

  // Equity: freshness = last data point day. If today, show as fresh; otherwise show age of last day
  const total = d.chart?.total || [];
  if (total.length) {
    const lastDay = total[total.length - 1].day;
    const today = new Date().toISOString().slice(0, 10);
    const equityTs = lastDay === today ? new Date().toISOString() : lastDay + 'T23:59:59';
    setFreshness('fc-equity', equityTs);
  }
}

/* ── KPIs (8-metric strip) ──────────────────────────────── */
function renderKPIs(d) {
  const s = d.summary || {};
  const m = d.metrics || {};
  const h = d.health || {};

  _kpi('kpi-portfolio', fmtUsd(s.portfolio_value));
  _kpiColor('kpi-portfolio', s.portfolio_ret);
  _kpiDelta('kpi-portfolio-delta', s.portfolio_ret, '%');

  _kpi('kpi-today', fmtPnl(s.today_pnl_usd, '$'));
  _kpiColor('kpi-today', s.today_pnl_usd);

  // Week PnL from backend (computed over last 7 days)
  _kpi('kpi-week', s.week_pnl_usd != null ? fmtPnl(s.week_pnl_usd, '$') : '---');
  _kpiColor('kpi-week', s.week_pnl_usd);

  _kpi('kpi-winrate', m.win_rate != null ? m.win_rate.toFixed(1) + '%' : '---');

  // Profit Factor (direct from backend)
  _kpi('kpi-sharpe', m.profit_factor != null ? m.profit_factor.toFixed(2) : '---');

  _kpi('kpi-maxdd', m.max_drawdown_pct ? '-' + m.max_drawdown_pct.toFixed(2) + '%' : '---');
  if (m.max_drawdown_pct > 0) _kpiColor('kpi-maxdd', -1);

  _kpi('kpi-openpos', s.open_positions != null ? s.open_positions : '0');

  // Exposure from backend (includes all position types)
  _kpi('kpi-exposure', (s.exposure_pct != null ? s.exposure_pct.toFixed(0) : '0') + '%');

  // Sparklines
  const chart = d.chart?.total || [];
  _drawKpiSpark('spark-portfolio', chart.map(p => p.pnl), s.portfolio_ret >= 0 ? '#00D395' : '#FF3B6B');
  _drawKpiSpark('spark-today', _todaySpark(d), s.today_pnl_usd >= 0 ? '#00D395' : '#FF3B6B');
}

function _kpi(id, text) { const el = document.getElementById(id); if (el) el.textContent = text; }
function _kpiColor(id, val) { const el = document.getElementById(id); if (el) el.className = el.className.replace(/positive|negative|neutral/g, '') + ' ' + pnlClass(val); }
function _kpiDelta(id, val, suffix) {
  const el = document.getElementById(id);
  if (!el) return;
  if (val == null) { el.textContent = '---'; return; }
  el.textContent = fmtPnl(val) + (suffix || '');
  el.className = 'kpi-delta mono ' + pnlClass(val);
}

function _drawKpiSpark(id, data, color) {
  const c = document.getElementById(id);
  if (c) drawSparkline(c, data, color);
}

function _todaySpark(d) {
  // Build intra-day spark from trades
  const trades = d.trades?.scalping || [];
  const pumpT = d.trades?.pump || [];
  const all = [...trades, ...pumpT].sort((a, b) => (a.timestamp || '').localeCompare(b.timestamp || ''));
  let acc = 0;
  return all.map(t => { acc += +(t.pnl_usd || 0); return acc; });
}

/* ── Positions ──────────────────────────────────────────── */
function renderPositions(positions) {
  const container = document.getElementById('positions-list');
  if (!container) return;

  const badge = document.getElementById('positions-count');
  if (badge) badge.textContent = positions.length;

  if (!positions.length) {
    container.innerHTML = '<div class="text-3 text-xs" style="padding:var(--sp-3)">No open positions</div>';
    return;
  }

  container.innerHTML = positions.map(p => {
    const dir = (p.type || '').toUpperCase();
    const isLong = dir === 'LONG' || dir === 'BUY';
    const pnlCls = pnlClass(p.pnl_pct);
    const system = (p.system || '').toLowerCase();

    // SL/TP progress
    const entry = p.entry_price || 0;
    const current = p.current_price || entry;
    const sl = p.sl_price || entry;
    const tp = p.tp_price || p.tp1_price || entry;
    const range = Math.abs(tp - sl) || 1;
    const progress = Math.min(100, Math.max(0, Math.abs(current - sl) / range * 100));

    return `<div class="pos-row">
      <div class="pos-left">
        <span class="badge ${isLong ? 'long' : 'short'}">${esc(dir)}</span>
        <span class="pos-symbol">${esc(p.symbol?.replace('USDT',''))}</span>
        <span class="badge">${esc(system)}</span>
      </div>
      <div class="pos-prices mono text-xs">
        <span class="text-3">E:${entry.toFixed(1)}</span>
        <span class="text-2">C:${current.toFixed(1)}</span>
      </div>
      <div class="pos-pnl mono ${pnlCls}">${p.pnl_pct != null ? fmtPct(p.pnl_pct) : '---'}</div>
      <div class="pos-bar">
        <div class="progress-bar" style="width:80px">
          <div class="progress-fill ${isLong ? 'progress-tp' : 'progress-sl'}" style="width:${progress}%"></div>
        </div>
        <span class="text-xxs text-3">SL ${sl.toFixed(0)} / TP ${tp.toFixed(0)}</span>
      </div>
    </div>`;
  }).join('');
}

/* ── System Cards ──────────────────────────────────────── */
function renderSystemCards(d) {
  const container = document.getElementById('system-cards');
  if (!container) return;

  const systems = [
    { key: 'pump', label: 'Pump', color: '#06b6d4' },
    { key: 'scalping', label: 'Scalping', color: '#8b5cf6' },
  ];

  container.innerHTML = systems.map(sys => {
    const cap = d.capital?.[sys.key] || {};
    const stats = d.stats_today?.[sys.key] || {};
    const met = d.metrics?.per_system?.[sys.key] || {};
    const retCls = pnlClass(cap.ret);
    const glowCls = cap.cb ? 'glow-danger' : (cap.ret > 0 ? 'glow-success' : '');

    return `<div class="sys-card ${glowCls}">
      <div class="flex items-center justify-between mb-2">
        <span class="label">${sys.label}</span>
        ${cap.cb ? '<span class="badge red">CB</span>' : ''}
      </div>
      <div class="mono ${retCls}" style="font-size:1.1rem;font-weight:300">${fmtUsd(cap.value)}</div>
      <div class="mono ${retCls} text-sm">${fmtPct(cap.ret)}</div>
      <div class="text-3 text-xxs mt-3">${met.total_trades||0} trades &middot; WR ${met.win_rate!=null?met.win_rate.toFixed(1):'0'}% &middot; Today: ${stats.count||0}</div>
    </div>`;
  }).join('');
}

/* ── Mini Equity (Lightweight Charts) ──────────────────── */
function renderMiniEquity(charts) {
  const container = document.getElementById('equity-mini');
  if (!container || typeof LightweightCharts === 'undefined') return;

  const total = charts.total || [];
  const pump = charts.pump || [];
  const scalping = charts.scalping || [];

  if (!_equityChart) {
    _equityChart = {};
    _equityChart.chart = LightweightCharts.createChart(container, {
      layout: { background: { type: 'solid', color: 'transparent' }, textColor: 'rgba(240,244,255,.3)', fontFamily: "'Inter', sans-serif", fontSize: 10 },
      grid: { vertLines: { color: 'rgba(255,255,255,.02)' }, horzLines: { color: 'rgba(255,255,255,.02)' } },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: { borderColor: 'rgba(255,255,255,.04)', autoScale: true, scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { borderColor: 'rgba(255,255,255,.04)', timeVisible: false },
      handleScroll: false,
      handleScale: false,
    });

    // Total area
    _equityChart.totalSeries = _equityChart.chart.addAreaSeries({
      lineColor: '#5EC8FF',
      topColor: 'rgba(94, 200, 255, .1)',
      bottomColor: 'rgba(94, 200, 255, .01)',
      lineWidth: 2,
    });

    // Pump
    _equityChart.pumpSeries = _equityChart.chart.addLineSeries({
      color: '#06b6d4', lineWidth: 1,
    });

    // Scalping
    _equityChart.scalpSeries = _equityChart.chart.addLineSeries({
      color: '#8b5cf6', lineWidth: 1,
    });

    // Drawdown underlay marker area
    // (We'll overlay via CSS if needed — LW charts doesn't have native underlay)

    const ro = new ResizeObserver(() => {
      _equityChart.chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
    });
    ro.observe(container);
  }

  const toData = arr => (arr || []).map(p => ({ time: p.day, value: p.pnl }));
  _equityChart.totalSeries.setData(toData(total));
  _equityChart.pumpSeries.setData(toData(pump));
  _equityChart.scalpSeries.setData(toData(scalping));

  // Add trade markers on total series
  const marks = [];
  // Would need trade timestamps from separate endpoint — skip for now to keep it fast

  _equityChart.chart.timeScale().fitContent();
}

/* ── Recent Trades ─────────────────────────────────────── */
async function loadTrades() {
  try {
    const r = await fetch('/api/trades?days=7&system=scalping');
    const trades = await r.json();
    const list = Array.isArray(trades) ? trades : (trades.trades || []);
    renderTrades(list);
    // Freshness chip for trades: timestamp of most recent trade
    if (list.length) {
      const sorted = [...list].sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''));
      setFreshness('fc-trades', parseBackendTs(sorted[0]?.timestamp));
    }
    _tradesLoaded = true;
  } catch {}
}

function renderTrades(allTrades) {
  const tbody = document.getElementById('trades-tbody');
  if (!tbody) return;

  // Sort desc
  allTrades.sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''));
  const recent = allTrades.slice(0, 25);

  if (!recent.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="text-3 text-xs">No trades</td></tr>';
    return;
  }

  tbody.innerHTML = recent.map(t => {
    const time = (t.timestamp || '').slice(5, 16) || '---';
    const sym = (t.symbol || '---').replace('USDT', '');
    const side = (t.type || t.direction || '---').toUpperCase();
    const pnl = t.pnl_pct;
    const pCls = pnlClass(pnl);
    const system = t.system || t._system || '---';
    const reason = t.exit_reason || t.close_reason || '---';
    const pnlUsd = t.pnl_usd;

    return `<tr>
      <td class="text-3 mono text-xxs">${esc(time)}</td>
      <td>${esc(sym)}</td>
      <td><span class="badge ${side==='LONG'||side==='BUY'?'long':'short'}">${esc(side)}</span></td>
      <td class="num pnl ${pCls}">${pnl != null ? fmtPct(pnl) : '---'}</td>
      <td class="num ${pCls}">${pnlUsd != null ? fmtPnl(pnlUsd, '$') : ''}</td>
      <td class="text-3 text-xxs">${esc(system)}</td>
      <td class="text-3 text-xxs">${esc(reason)}</td>
    </tr>`;
  }).join('');
}
