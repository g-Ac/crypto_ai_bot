# Pip-Boy Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Pip-Boy (Fallout) themed dashboard with 5 tabs, real-time log streaming, and ASCII charts for the crypto_ai_bot.

**Architecture:** Flask + HTMX + SSE. Server renders Jinja2 partials, HTMX polls and swaps them into the page. One SSE stream for real-time logs. Zero JS frameworks, zero chart libraries.

**Tech Stack:** Flask (existing), Jinja2, HTMX 2.x (CDN), CSS custom design system, Python ASCII chart generator

**Spec:** `docs/superpowers/specs/2026-04-15-pipboy-dashboard-design.md`

---

## File Structure

### New Files

```
static/css/pipboy.css                     — Design system Pip-Boy completo
static/js/pipboy.js                       — Format helpers, keyboard shortcuts, log terminal
ascii_charts.py                           — Gerador de graficos ASCII (equity curve, daily P&L)
tests/test_ascii_charts.py                — Testes TDD para ascii_charts
tests/test_sse_pipboy.py                  — Testes para SSE + rotas Pip-Boy
templates/pipboy/
  base.html                               — Skeleton: header, tabs, ticker, CRT overlays
  status.html                             — Tab STATUS
  trades.html                             — Tab TRADES
  analysis.html                           — Tab ANALYSIS
  logs.html                               — Tab LOGS
  system.html                             — Tab SYSTEM
  partials/
    kpi_cards.html                        — 4 KPI cards
    positions.html                        — Tabela de posicoes abertas
    status_bar.html                       — Barra de status (rodape)
    equity_chart.html                     — ASCII equity curve
    trade_log.html                        — Tabela de trades paginada
    daily_pnl.html                        — Barras ASCII de P&L diario
    funnel.html                           — Decision funnel
    gauges.html                           — Win rate gauges SVG
    scorer.html                           — Setup scorer ranking
    error_summary.html                    — Resumo de erros 24h
    health_meters.html                    — Meters CPU/RAM/Disk/Temp
    processes.html                        — Tabela de processos
    ticker.html                           — Ticker tape (precos, uptime)
```

### Modified Files

```
dashboard_server.py                       — +1 SSE endpoint, +13 partial routes, +6 page routes
```

---

## Data Flow

```
Browser                          Server (Flask)
  |                                |
  |-- GET /pip/status ----------->| render_template("pipboy/status.html")
  |<-- full page with HTMX ------| (includes hx-get for partials)
  |                                |
  |-- GET /pip/partial/kpis ----->| _build_status() → render partial
  |<-- HTML fragment -------------| (HTMX swaps into target div)
  |   (repeats every 15s)         |
  |                                |
  |-- EventSource /stream/logs -->| generator yields log lines
  |<-- SSE event: log line -------| (JS appends DOM element)
  |   (real-time)                  |
```

---

### Task 1: CSS Design System

**Files:**
- Create: `static/css/pipboy.css`

- [ ] **Step 1: Create pipboy.css**

```css
/* pipboy.css — Pip-Boy Design System for crypto_ai_bot */

/* ── Variables ── */
:root {
  --pip-green:        #00ff41;
  --pip-green-bright: #00ff41;
  --pip-green-mid:    #00ff4188;
  --pip-green-dim:    #00ff4155;
  --pip-green-faint:  #00ff4133;
  --pip-green-ghost:  #00ff4111;
  --pip-red:          #ff4141;
  --pip-red-dim:      #ff414188;
  --pip-bg:           #0a0a0a;
  --pip-bg-card:      #0a0a0a;
  --pip-bg-hover:     #00ff4108;
  --pip-font:         'Courier New', 'Lucida Console', monospace;
}

/* ── Reset & Base ── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

.pip-body {
  background: var(--pip-bg);
  color: var(--pip-green);
  font-family: var(--pip-font);
  font-size: 12px;
  line-height: 1.5;
  min-height: 100vh;
  position: relative;
}

/* ── CRT Effects ── */
.crt-overlay {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: repeating-linear-gradient(
    0deg, transparent, transparent 2px,
    rgba(0,255,65,0.03) 2px, rgba(0,255,65,0.03) 4px
  );
  pointer-events: none; z-index: 9998;
}

.crt-vignette {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: radial-gradient(ellipse at center, transparent 60%, rgba(0,0,0,0.5) 100%);
  pointer-events: none; z-index: 9997;
}

/* ── Glow ── */
.glow { text-shadow: 0 0 8px rgba(0,255,65,0.4); }
.glow-strong { text-shadow: 0 0 12px rgba(0,255,65,0.6), 0 0 4px rgba(0,255,65,0.3); }

/* ── Header ── */
.pip-header {
  position: sticky; top: 0; z-index: 100;
  background: var(--pip-bg);
  border-bottom: 1px solid var(--pip-green-faint);
  padding: 8px 16px;
}

.pip-header-top {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 4px;
}

.pip-branding {
  display: flex; align-items: center; gap: 8px;
}

.pip-title {
  font-size: 14px; font-weight: bold; letter-spacing: 2px;
  text-transform: uppercase;
}

.pip-status-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--pip-green);
  box-shadow: 0 0 8px var(--pip-green);
  animation: pulse-dot 2s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* ── Tabs ── */
.pip-tabs { display: flex; gap: 4px; }

.pip-tab {
  color: var(--pip-green-dim);
  text-decoration: none;
  padding: 4px 12px;
  font-size: 11px;
  letter-spacing: 1px;
  text-transform: uppercase;
  border: 1px solid transparent;
  transition: all 0.15s;
}

.pip-tab:hover {
  color: var(--pip-green);
  background: var(--pip-bg-hover);
  border-color: var(--pip-green-faint);
}

.pip-tab.active {
  color: var(--pip-green-bright);
  border-color: var(--pip-green-faint);
  background: var(--pip-green-ghost);
}

/* ── Divider ── */
.pip-divider {
  height: 2px; margin: 4px 0;
  background: linear-gradient(90deg, var(--pip-green-faint), var(--pip-green-dim), var(--pip-green-faint));
}

/* ── Ticker ── */
.pip-ticker {
  font-size: 10px; color: var(--pip-green-dim);
  letter-spacing: 1px; padding: 4px 0;
  display: flex; gap: 16px; flex-wrap: wrap;
}

.pip-ticker .up { color: var(--pip-green); }
.pip-ticker .down { color: var(--pip-red); }

/* ── Content ── */
.pip-content { padding: 16px; max-width: 1200px; margin: 0 auto; }

/* ── Cards ── */
.pip-card {
  border: 1px solid var(--pip-green-faint);
  padding: 12px;
  margin-bottom: 12px;
  position: relative;
}

.pip-card-title {
  color: var(--pip-green-mid);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 2px;
  margin-bottom: 8px;
}

/* ── KPI ── */
.pip-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.pip-kpi { padding: 12px; border: 1px solid var(--pip-green-faint); }
.pip-kpi-label { color: var(--pip-green-mid); font-size: 9px; text-transform: uppercase; letter-spacing: 1px; }
.pip-kpi-value { font-size: 22px; font-weight: bold; font-variant-numeric: tabular-nums; margin: 4px 0; }
.pip-kpi-sub { font-size: 10px; color: var(--pip-green-dim); }

/* ── Table ── */
.pip-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.pip-table th {
  color: var(--pip-green-mid); font-size: 9px; text-transform: uppercase;
  letter-spacing: 1px; text-align: left; padding: 6px 8px;
  border-bottom: 1px solid var(--pip-green-faint);
}
.pip-table td { padding: 6px 8px; border-bottom: 1px solid var(--pip-green-ghost); }
.pip-table tr:hover { background: var(--pip-bg-hover); }

/* ── Badge ── */
.pip-badge {
  display: inline-block; padding: 1px 6px;
  font-size: 9px; letter-spacing: 1px; text-transform: uppercase;
  border: 1px solid currentColor;
}
.pip-badge.long { color: var(--pip-green); }
.pip-badge.short { color: var(--pip-red); }
.pip-badge.on { color: var(--pip-green); }
.pip-badge.off { color: var(--pip-green-dim); }

/* ── Progress Bar ── */
.pip-bar {
  height: 10px; background: var(--pip-green-ghost);
  position: relative; overflow: hidden;
}
.pip-bar-fill {
  height: 100%; background: var(--pip-green-dim);
  transition: width 0.3s;
}

/* ── Meter (segmented) ── */
.pip-meter {
  display: flex; gap: 2px; height: 14px;
}
.pip-meter-seg {
  flex: 1; background: var(--pip-green-ghost);
}
.pip-meter-seg.filled { background: var(--pip-green-dim); }
.pip-meter-seg.filled.warn { background: #ffaa00; }
.pip-meter-seg.filled.crit { background: var(--pip-red); }

/* ── ASCII Chart ── */
.pip-ascii-chart {
  font-size: 11px; line-height: 1.3;
  white-space: pre; overflow-x: auto;
  color: var(--pip-green);
  padding: 8px; border: 1px solid var(--pip-green-faint);
}

/* ── Terminal (Logs) ── */
.pip-terminal {
  background: #050505;
  border: 1px solid var(--pip-green-faint);
  padding: 8px;
  height: 60vh;
  overflow-y: auto;
  font-size: 11px;
  line-height: 1.4;
}
.pip-terminal .log-line { white-space: pre-wrap; word-break: break-all; }

/* ── Cursor ── */
.pip-cursor {
  display: inline-block; width: 8px; height: 14px;
  background: var(--pip-green);
  animation: blink-cursor 1s step-end infinite;
}
@keyframes blink-cursor { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

/* ── Status Bar ── */
.pip-status-bar {
  font-size: 10px; color: var(--pip-green-dim);
  border-top: 1px solid var(--pip-green-faint);
  padding: 8px 0; margin-top: 16px;
}
.pip-status-bar.alert { color: var(--pip-red); }

/* ── Gauge SVG ── */
.pip-gauge { text-align: center; }
.pip-gauge svg { width: 80px; height: 80px; }
.pip-gauge-label { font-size: 9px; color: var(--pip-green-mid); text-transform: uppercase; margin-top: 4px; }
.pip-gauge-value { font-size: 14px; font-weight: bold; }
.pip-gauge-sub { font-size: 10px; color: var(--pip-green-dim); }

/* ── Filter Bar ── */
.pip-filters {
  display: flex; gap: 4px; margin-bottom: 12px; flex-wrap: wrap;
}
.pip-filter-btn {
  background: none; border: 1px solid var(--pip-green-faint);
  color: var(--pip-green-dim); padding: 3px 10px;
  font-family: var(--pip-font); font-size: 10px;
  cursor: pointer; text-transform: uppercase; letter-spacing: 1px;
}
.pip-filter-btn:hover { color: var(--pip-green); border-color: var(--pip-green-dim); }
.pip-filter-btn.active {
  color: var(--pip-green-bright); border-color: var(--pip-green-dim);
  background: var(--pip-green-ghost);
}

/* ── Grid Layouts ── */
.pip-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.pip-grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.pip-grid-3x3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }

/* ── Sparkline (mini bar chart) ── */
.pip-sparkline { display: flex; align-items: flex-end; gap: 1px; height: 20px; }
.pip-sparkline-bar { width: 4px; background: var(--pip-green-dim); min-height: 1px; }

/* ── Pagination ── */
.pip-pagination { display: flex; gap: 4px; margin-top: 8px; justify-content: center; }
.pip-pagination a {
  color: var(--pip-green-dim); text-decoration: none;
  padding: 2px 8px; border: 1px solid var(--pip-green-faint);
  font-size: 10px;
}
.pip-pagination a.active { color: var(--pip-green); border-color: var(--pip-green-dim); }

/* ── Positive/Negative Colors ── */
.pnl-pos { color: var(--pip-green); }
.pnl-neg { color: var(--pip-red); }

/* ── Responsive ── */
@media (max-width: 768px) {
  .pip-kpi-grid { grid-template-columns: repeat(2, 1fr); }
  .pip-grid-2, .pip-grid-3 { grid-template-columns: 1fr; }
  .pip-grid-3x3 { grid-template-columns: repeat(2, 1fr); }
  .pip-tabs { gap: 2px; }
  .pip-tab { padding: 4px 6px; font-size: 10px; }
  .pip-ticker { font-size: 9px; gap: 8px; }
  .pip-kpi-value { font-size: 18px; }
  .pip-terminal { height: 40vh; }
}

@media (max-width: 480px) {
  .pip-header { padding: 6px 8px; }
  .pip-content { padding: 8px; }
  .pip-kpi-grid { grid-template-columns: 1fr 1fr; gap: 8px; }
  .pip-tab { padding: 3px 5px; font-size: 9px; letter-spacing: 0; }
}
```

- [ ] **Step 2: Commit**

```bash
git add static/css/pipboy.css
git commit -m "feat(dashboard): add Pip-Boy CSS design system"
```

---

### Task 2: ASCII Chart Generator (TDD)

**Files:**
- Create: `tests/test_ascii_charts.py`
- Create: `ascii_charts.py`

- [ ] **Step 1: Write failing tests**

```python
"""Tests for ascii_charts module."""
import pytest
from ascii_charts import render_equity_curve, render_daily_pnl


class TestRenderEquityCurve:
    def test_empty_data_returns_no_data_message(self):
        result = render_equity_curve([])
        assert "NO DATA" in result

    def test_single_point(self):
        data = [{"day": "2025-01-01", "pnl": 100.0}]
        result = render_equity_curve(data, width=20)
        assert "100" in result

    def test_multiple_points_has_axes(self):
        data = [
            {"day": "2025-01-01", "pnl": 0},
            {"day": "2025-01-02", "pnl": 50},
            {"day": "2025-01-03", "pnl": 100},
            {"day": "2025-01-04", "pnl": 75},
        ]
        result = render_equity_curve(data, width=30)
        lines = result.strip().split("\n")
        assert len(lines) >= 3  # at least y-axis labels + data rows
        assert any("|" in line for line in lines)  # y-axis present

    def test_negative_values(self):
        data = [
            {"day": "2025-01-01", "pnl": -50},
            {"day": "2025-01-02", "pnl": -100},
            {"day": "2025-01-03", "pnl": -25},
        ]
        result = render_equity_curve(data, width=30)
        assert "-" in result  # negative values shown

    def test_width_respected(self):
        data = [{"day": f"2025-01-{i:02d}", "pnl": i * 10} for i in range(1, 15)]
        result = render_equity_curve(data, width=40)
        lines = result.strip().split("\n")
        for line in lines:
            assert len(line) <= 55  # width + y-label margin


class TestRenderDailyPnl:
    def test_empty_data(self):
        result = render_daily_pnl([])
        assert "NO DATA" in result

    def test_positive_bars(self):
        data = [
            {"day": "2025-01-01", "pnl": 50},
            {"day": "2025-01-02", "pnl": 100},
        ]
        result = render_daily_pnl(data, width=20)
        assert "\u2588" in result  # block character present

    def test_mixed_positive_negative(self):
        data = [
            {"day": "2025-01-01", "pnl": 50},
            {"day": "2025-01-02", "pnl": -30},
            {"day": "2025-01-03", "pnl": 80},
        ]
        result = render_daily_pnl(data, width=20)
        lines = result.strip().split("\n")
        assert len(lines) >= 2

    def test_summary_line(self):
        data = [
            {"day": "2025-01-01", "pnl": 50},
            {"day": "2025-01-02", "pnl": -30},
        ]
        result = render_daily_pnl(data, width=20)
        assert "AVG" in result.upper() or "W" in result.upper()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/crypto_ai_bot && source .venv/bin/activate && python -m pytest tests/test_ascii_charts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ascii_charts'`

- [ ] **Step 3: Implement ascii_charts.py**

```python
"""ASCII chart generator for Pip-Boy dashboard.

Generates text-based equity curves and daily P&L bar charts
rendered as <pre> blocks in Jinja2 templates.
"""


def render_equity_curve(data: list[dict], width: int = 50) -> str:
    """Render an ASCII equity curve from cumulative P&L data.

    Args:
        data: List of {"day": "YYYY-MM-DD", "pnl": float}
        width: Chart width in columns (data points sampled to fit)

    Returns:
        Multi-line ASCII string ready for <pre> display.
    """
    if not data:
        return "  [ NO DATA ]"

    # Sample data to fit width
    if len(data) > width:
        step = len(data) / width
        sampled = [data[int(i * step)] for i in range(width)]
    else:
        sampled = data

    values = [d["pnl"] for d in sampled]
    vmin = min(values)
    vmax = max(values)

    # Avoid division by zero if all values equal
    if vmax == vmin:
        vmax = vmin + 1

    height = 8
    y_label_width = 8

    lines = []

    # Y-axis labels and chart rows
    for row in range(height, -1, -1):
        y_val = vmin + (vmax - vmin) * row / height
        label = f"{y_val:>+7.0f}" if abs(y_val) >= 1 else f"{y_val:>+7.1f}"
        label = label[:y_label_width].rjust(y_label_width)

        chars = []
        for val in values:
            normalized = (val - vmin) / (vmax - vmin) * height
            if abs(normalized - row) < 0.5:
                chars.append("\u2022")  # bullet ●
            elif normalized > row:
                chars.append("\u2502")  # vertical │
            else:
                chars.append(" ")
        lines.append(f"{label}|{''.join(chars)}")

    # X-axis
    x_axis = " " * y_label_width + "+" + "\u2500" * len(values)
    lines.append(x_axis)

    # X labels (first and last date)
    if sampled:
        first = sampled[0]["day"][-5:]  # MM-DD
        last = sampled[-1]["day"][-5:]
        padding = len(values) - len(first) - len(last)
        if padding > 0:
            x_labels = " " * (y_label_width + 1) + first + " " * padding + last
        else:
            x_labels = " " * (y_label_width + 1) + first
        lines.append(x_labels)

    return "\n".join(lines)


def render_daily_pnl(data: list[dict], width: int = 50) -> str:
    """Render ASCII bar chart of daily P&L.

    Args:
        data: List of {"day": "YYYY-MM-DD", "pnl": float}
        width: Max number of days to show

    Returns:
        Multi-line ASCII string with vertical bars per day.
    """
    if not data:
        return "  [ NO DATA ]"

    recent = data[-width:] if len(data) > width else data
    values = [d["pnl"] for d in recent]

    abs_max = max(abs(v) for v in values) if values else 1
    if abs_max == 0:
        abs_max = 1

    bar_height = 6
    lines = []

    # Positive bars (top half)
    for row in range(bar_height, 0, -1):
        threshold = abs_max * row / bar_height
        chars = []
        for v in values:
            if v > 0 and v >= threshold:
                chars.append("\u2588")  # full block
            else:
                chars.append(" ")
        label = f"{threshold:>+7.0f}" if row == bar_height else " " * 7
        lines.append(f"{label} {''.join(chars)}")

    # Zero line
    lines.append(f"{'0':>7} {''.join(['\u2500' for _ in values])}")

    # Negative bars (bottom half)
    for row in range(1, bar_height + 1):
        threshold = -abs_max * row / bar_height
        chars = []
        for v in values:
            if v < 0 and v <= threshold:
                chars.append("\u2588")
            else:
                chars.append(" ")
        label = f"{threshold:>+7.0f}" if row == bar_height else " " * 7
        lines.append(f"{label} {''.join(chars)}")

    # Summary line
    wins = sum(1 for v in values if v > 0)
    losses = sum(1 for v in values if v < 0)
    avg = sum(values) / len(values) if values else 0
    lines.append(f"  AVG: ${avg:+.0f} | {wins}W {losses}L | DAYS: {len(values)}")

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/crypto_ai_bot && python -m pytest tests/test_ascii_charts.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add ascii_charts.py tests/test_ascii_charts.py
git commit -m "feat: add ASCII chart generator with TDD tests"
```

---

### Task 3: Base Template + Navigation

**Files:**
- Create: `templates/pipboy/base.html`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p templates/pipboy/partials
```

- [ ] **Step 2: Create base.html**

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GABRIEL'S TERMINAL</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='css/pipboy.css') }}">
  <script src="https://unpkg.com/htmx.org@2.0.4"></script>
</head>
<body class="pip-body">
  <!-- CRT Effects -->
  <div class="crt-overlay"></div>
  <div class="crt-vignette"></div>

  <!-- Header -->
  <header class="pip-header">
    <div class="pip-header-top">
      <div class="pip-branding">
        <span class="pip-status-dot"></span>
        <span class="pip-title glow">GABRIEL'S TERMINAL</span>
      </div>
      <nav class="pip-tabs">
        <a href="/pip/status" class="pip-tab {% if active_tab == 'status' %}active{% endif %}">STATUS</a>
        <a href="/pip/trades" class="pip-tab {% if active_tab == 'trades' %}active{% endif %}">TRADES</a>
        <a href="/pip/analysis" class="pip-tab {% if active_tab == 'analysis' %}active{% endif %}">ANALYSIS</a>
        <a href="/pip/logs" class="pip-tab {% if active_tab == 'logs' %}active{% endif %}">LOGS</a>
        <a href="/pip/system" class="pip-tab {% if active_tab == 'system' %}active{% endif %}">SYSTEM</a>
      </nav>
    </div>
    <div class="pip-divider"></div>
    <div class="pip-ticker"
         hx-get="/pip/partial/ticker"
         hx-trigger="load, every 30s">
      > CONNECTING...
    </div>
  </header>

  <!-- Content -->
  <main class="pip-content">
    {% block content %}{% endblock %}
  </main>

  <script src="{{ url_for('static', filename='js/pipboy.js') }}"></script>
  {% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 3: Commit**

```bash
git add templates/pipboy/base.html
git commit -m "feat(dashboard): add Pip-Boy base template with header and navigation"
```

---

### Task 4: JavaScript Helpers

**Files:**
- Create: `static/js/pipboy.js`

- [ ] **Step 1: Create pipboy.js**

```javascript
/* pipboy.js — Helpers for Pip-Boy Dashboard */

/* ── Format Helpers ── */
function fmtUsd(v) {
  if (v == null) return '$0.00';
  var n = parseFloat(v);
  var sign = n >= 0 ? '+' : '';
  return sign + '$' + Math.abs(n).toLocaleString('en-US', {
    minimumFractionDigits: 2, maximumFractionDigits: 2
  });
}

function fmtPct(v) {
  if (v == null) return '0.00%';
  var n = parseFloat(v);
  var sign = n >= 0 ? '+' : '';
  return sign + n.toFixed(2) + '%';
}

function fmtTemp(c) {
  return c != null ? parseFloat(c).toFixed(1) + '\u00b0C' : '--';
}

function fmtUptime(seconds) {
  if (!seconds) return '--';
  var d = Math.floor(seconds / 86400);
  var h = Math.floor((seconds % 86400) / 3600);
  var m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return d + 'd ' + h + 'h';
  if (h > 0) return h + 'h ' + m + 'm';
  return m + 'm';
}

/* ── Keyboard Shortcuts ── */
document.addEventListener('keydown', function(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  var tabs = {'1':'status','2':'trades','3':'analysis','4':'logs','5':'system'};
  if (tabs[e.key]) {
    window.location.href = '/pip/' + tabs[e.key];
  }
});

/* ── SSE Log Terminal ── */
var LOG_MAX_LINES = 500;
var LOG_COLORS = {
  'ERR':     'var(--pip-red)',
  'ERROR':   'var(--pip-red)',
  'WARN':    'var(--pip-green-bright)',
  'WARNING': 'var(--pip-green-bright)',
  'INFO':    'var(--pip-green-mid)',
  'DEBUG':   'var(--pip-green-dim)',
  'PUMP':    'var(--pip-green-bright)'
};

function detectLogLevel(line) {
  var upper = line.toUpperCase();
  if (upper.indexOf('ERROR') !== -1 || upper.indexOf(' ERR ') !== -1) return 'ERR';
  if (upper.indexOf('WARNING') !== -1 || upper.indexOf(' WARN ') !== -1) return 'WARN';
  if (upper.indexOf('PUMP') !== -1) return 'PUMP';
  if (upper.indexOf('DEBUG') !== -1) return 'DEBUG';
  return 'INFO';
}

function initLogTerminal(containerId, sseUrl) {
  var container = document.getElementById(containerId);
  if (!container) return null;

  var paused = false;
  var es = new EventSource(sseUrl);

  es.addEventListener('log', function(evt) {
    if (paused) return;

    var line = evt.data;
    var level = detectLogLevel(line);
    var color = LOG_COLORS[level] || 'var(--pip-green-mid)';

    var div = document.createElement('div');
    div.className = 'log-line';
    div.style.color = color;
    div.textContent = line;
    container.appendChild(div);

    /* Buffer limit — remove oldest lines */
    while (container.childElementCount > LOG_MAX_LINES) {
      container.removeChild(container.firstChild);
    }

    /* Auto-scroll to bottom */
    container.scrollTop = container.scrollHeight;
  });

  es.onerror = function() {
    var div = document.createElement('div');
    div.className = 'log-line';
    div.style.color = 'var(--pip-red-dim)';
    div.textContent = '> CONNECTION LOST \u2014 RECONNECTING...';
    container.appendChild(div);
  };

  return {
    pause:  function() { paused = true; },
    resume: function() { paused = false; },
    toggle: function() { paused = !paused; return paused; },
    close:  function() { es.close(); }
  };
}
```

- [ ] **Step 2: Commit**

```bash
git add static/js/pipboy.js
git commit -m "feat(dashboard): add Pip-Boy JS helpers and SSE log terminal"
```

---

### Task 5: SSE Endpoint + Pip-Boy Routes

**Files:**
- Modify: `dashboard_server.py`
- Create: `tests/test_sse_pipboy.py`

- [ ] **Step 1: Write failing tests**

```python
"""Tests for Pip-Boy routes and SSE endpoint."""
import pytest
import json
from unittest.mock import patch, MagicMock


@pytest.fixture
def client():
    """Flask test client for dashboard."""
    import dashboard_server
    dashboard_server.app.config["TESTING"] = True
    with dashboard_server.app.test_client() as c:
        yield c


class TestPipBoyPages:
    def test_pip_status_page(self, client):
        resp = client.get("/pip/status")
        assert resp.status_code == 200
        assert b"GABRIEL" in resp.data

    def test_pip_trades_page(self, client):
        resp = client.get("/pip/trades")
        assert resp.status_code == 200

    def test_pip_analysis_page(self, client):
        resp = client.get("/pip/analysis")
        assert resp.status_code == 200

    def test_pip_logs_page(self, client):
        resp = client.get("/pip/logs")
        assert resp.status_code == 200

    def test_pip_system_page(self, client):
        resp = client.get("/pip/system")
        assert resp.status_code == 200

    def test_pip_root_redirects_to_status(self, client):
        resp = client.get("/pip/")
        assert resp.status_code in (200, 302)


class TestPipBoyPartials:
    def test_partial_ticker(self, client):
        resp = client.get("/pip/partial/ticker")
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/html")

    def test_partial_kpis(self, client):
        resp = client.get("/pip/partial/kpis")
        assert resp.status_code == 200

    def test_partial_positions(self, client):
        resp = client.get("/pip/partial/positions")
        assert resp.status_code == 200


class TestSSELogs:
    def test_stream_logs_returns_event_stream(self, client):
        resp = client.get("/stream/logs?source=main&lines=5")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/crypto_ai_bot && python -m pytest tests/test_sse_pipboy.py -v`
Expected: FAIL — routes not yet defined

- [ ] **Step 3: Add SSE log stream endpoint to dashboard_server.py**

Add after the existing `/api/logs` route (around line 1760):

```python
# ── PIP-BOY SSE ──────────────────────────────────────────────────────────────

@app.route("/stream/logs")
def stream_logs():
    """SSE: real-time log stream. Each line sent as 'log' event."""
    source = request.args.get("source", "main")
    ALLOWED = {"main", "scalping", "pump", "supervisor", "dashboard"}
    if source not in ALLOWED:
        source = "main"

    log_path = _resolve_log_path(source)

    def generate():
        try:
            with open(log_path, "r", errors="replace") as f:
                # Seek to end
                f.seek(0, 2)
                while True:
                    line = f.readline()
                    if line:
                        clean = line.rstrip()
                        if clean:
                            yield f"event: log\ndata: {clean}\n\n"
                    else:
                        time.sleep(0.5)
        except FileNotFoundError:
            yield f"event: log\ndata: > LOG FILE NOT FOUND: {source}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _resolve_log_path(source: str) -> str:
    """Resolve log source name to file path."""
    log_map = {
        "main": "main_bot.log",
        "scalping": "main_bot.log",
        "pump": "pump_scanner.log",
        "supervisor": "supervisor.log",
        "dashboard": "dashboard.log",
    }
    filename = log_map.get(source, "main_bot.log")
    return os.path.join(str(LOG_DIR), filename)
```

- [ ] **Step 4: Add Pip-Boy page routes**

Add after the SSE endpoint:

```python
# ── PIP-BOY PAGES ────────────────────────────────────────────────────────────

@app.route("/pip/")
@app.route("/pip/status")
def pip_status():
    return render_template("pipboy/status.html", active_tab="status")


@app.route("/pip/trades")
def pip_trades():
    return render_template("pipboy/trades.html", active_tab="trades")


@app.route("/pip/analysis")
def pip_analysis():
    return render_template("pipboy/analysis.html", active_tab="analysis")


@app.route("/pip/logs")
def pip_logs():
    return render_template("pipboy/logs.html", active_tab="logs")


@app.route("/pip/system")
def pip_system():
    return render_template("pipboy/system.html", active_tab="system")
```

- [ ] **Step 5: Add partial routes**

Add after the page routes:

```python
# ── PIP-BOY PARTIALS ─────────────────────────────────────────────────────────

@app.route("/pip/partial/ticker")
def pip_partial_ticker():
    status = _build_status(include_logs=False, include_trades=False)
    return render_template("pipboy/partials/ticker.html", s=status)


@app.route("/pip/partial/kpis")
def pip_partial_kpis():
    status = _build_status(include_logs=False, include_trades=False)
    return render_template("pipboy/partials/kpi_cards.html", s=status)


@app.route("/pip/partial/positions")
def pip_partial_positions():
    status = _build_status(include_logs=False, include_trades=False)
    return render_template("pipboy/partials/positions.html",
                           positions=status["positions"])


@app.route("/pip/partial/status_bar")
def pip_partial_status_bar():
    status = _build_status(include_logs=False, include_trades=False)
    return render_template("pipboy/partials/status_bar.html", s=status)


@app.route("/pip/partial/equity")
def pip_partial_equity():
    from ascii_charts import render_equity_curve
    system = request.args.get("system", "total")
    days = _safe_int(request.args.get("days", "30"), 30)
    status = _build_status(include_logs=False, include_trades=False)
    chart_data = status["chart"].get(system, status["chart"].get("total", []))
    if days and chart_data:
        chart_data = chart_data[-days:]
    ascii_chart = render_equity_curve(chart_data, width=min(50, len(chart_data) or 1))
    return render_template("pipboy/partials/equity_chart.html",
                           chart=ascii_chart, system=system, days=days)


@app.route("/pip/partial/trades")
def pip_partial_trades():
    system = request.args.get("system", "scalping")
    days = _safe_int(request.args.get("days", "7"), 7)
    page = _safe_int(request.args.get("page", "1"), 1)
    per_page = 15

    if system == "scalping":
        from database import get_scalping_trades
        all_trades = get_scalping_trades(days=days, limit=500)
    else:
        table_map = {"paper": "paper_trades", "agent": "agent_trades", "pump": "pump_trades"}
        table = table_map.get(system, "pump_trades")
        all_trades = get_trades_range(table, days=days)

    total = len(all_trades)
    start = (page - 1) * per_page
    trades = all_trades[start:start + per_page]
    total_pages = (total + per_page - 1) // per_page

    return render_template("pipboy/partials/trade_log.html",
                           trades=trades, system=system, days=days,
                           page=page, total_pages=total_pages)


@app.route("/pip/partial/daily_pnl")
def pip_partial_daily_pnl():
    from ascii_charts import render_daily_pnl
    days = _safe_int(request.args.get("days", "14"), 14)
    status = _build_status(include_logs=False, include_trades=False)
    # Build daily P&L from chart data
    total_chart = status["chart"].get("total", [])
    daily = []
    for i, point in enumerate(total_chart):
        prev_pnl = total_chart[i - 1]["pnl"] if i > 0 else 0
        daily.append({"day": point["day"], "pnl": point["pnl"] - prev_pnl})
    daily = daily[-days:]
    ascii_chart = render_daily_pnl(daily, width=days)
    return render_template("pipboy/partials/daily_pnl.html",
                           chart=ascii_chart, days=days)


@app.route("/pip/partial/funnel")
def pip_partial_funnel():
    hours = _safe_int(request.args.get("hours", "24"), 24)
    days = max(1, hours // 24) if hours >= 24 else 1
    funnel = get_scalping_funnel_stats(days=days)
    return render_template("pipboy/partials/funnel.html",
                           funnel=funnel, hours=hours)


@app.route("/pip/partial/gauges")
def pip_partial_gauges():
    from database import get_scalping_trades
    trades = get_scalping_trades(days=30, limit=500)

    # Aggregate by regime
    by_regime = {}
    for t in trades:
        regime = t.get("market_regime", "UNKNOWN") or "UNKNOWN"
        if regime not in by_regime:
            by_regime[regime] = {"wins": 0, "losses": 0, "total": 0, "pnl": 0.0}
        by_regime[regime]["total"] += 1
        pnl = float(t.get("pnl_pct", 0) or 0)
        by_regime[regime]["pnl"] += pnl
        if pnl > 0:
            by_regime[regime]["wins"] += 1
        else:
            by_regime[regime]["losses"] += 1

    # Aggregate by session
    by_session = {}
    for t in trades:
        session = t.get("session_bucket", "unknown") or "unknown"
        if session not in by_session:
            by_session[session] = {"wins": 0, "losses": 0, "total": 0, "pnl": 0.0}
        by_session[session]["total"] += 1
        pnl = float(t.get("pnl_pct", 0) or 0)
        by_session[session]["pnl"] += pnl
        if pnl > 0:
            by_session[session]["wins"] += 1
        else:
            by_session[session]["losses"] += 1

    return render_template("pipboy/partials/gauges.html",
                           by_regime=by_regime, by_session=by_session)


@app.route("/pip/partial/scorer")
def pip_partial_scorer():
    days = _safe_int(request.args.get("days", "30"), 30)
    payload = _build_scalping_scorer_payload(days=str(days), limit="5000")
    return render_template("pipboy/partials/scorer.html", scorer=payload)


@app.route("/pip/partial/errors")
def pip_partial_errors():
    logs = _get_recent_logs(source="main", lines=200)
    errors = [l for l in logs if "ERROR" in l.upper() or "ERR" in l.upper()]
    warnings = [l for l in logs if "WARNING" in l.upper() or "WARN" in l.upper()]
    return render_template("pipboy/partials/error_summary.html",
                           errors=errors[-20:], warnings=warnings[-20:],
                           error_count=len(errors), warning_count=len(warnings))


@app.route("/pip/partial/health")
def pip_partial_health():
    health = _get_system_health()
    return render_template("pipboy/partials/health_meters.html", health=health)


@app.route("/pip/partial/processes")
def pip_partial_processes():
    resp = api_processes()
    data = resp.get_json()
    return render_template("pipboy/partials/processes.html",
                           processes=data.get("processes", []))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd ~/crypto_ai_bot && python -m pytest tests/test_sse_pipboy.py -v`
Expected: All tests PASS (some may need template stubs first — if so, create minimal stubs)

- [ ] **Step 7: Commit**

```bash
git add dashboard_server.py tests/test_sse_pipboy.py
git commit -m "feat(dashboard): add Pip-Boy routes, partials, and SSE log stream"
```

---

### Task 6: Tab STATUS — Template + Partials

**Files:**
- Create: `templates/pipboy/status.html`
- Create: `templates/pipboy/partials/kpi_cards.html`
- Create: `templates/pipboy/partials/positions.html`
- Create: `templates/pipboy/partials/status_bar.html`
- Create: `templates/pipboy/partials/ticker.html`

- [ ] **Step 1: Create ticker.html partial**

```html
{# pipboy/partials/ticker.html — Ticker tape updated via HTMX #}
{% set prices = s.get("summary", {}) %}
{% set health = s.get("health", {}) %}
{% set bot = s.get("bot_status", {}) %}
<span>BTC {{ "${:,.0f}".format(prices.get("btc_price", 0)) if prices.get("btc_price") else "---" }}</span>
<span>ETH {{ "${:,.0f}".format(prices.get("eth_price", 0)) if prices.get("eth_price") else "---" }}</span>
<span>UPTIME {{ bot.get("uptime_str", "--") }}</span>
<span>CYCLE {{ bot.get("last_cycle_ago", "--") }}</span>
<span>TEMP {{ health.get("temperature", "--") }}</span>
<span>RAM {{ health.get("ram_pct", "--") }}%</span>
<span>{{ s.get("instance", {}).get("label", "BASELINE") }} v1.0</span>
```

- [ ] **Step 2: Create kpi_cards.html partial**

```html
{# pipboy/partials/kpi_cards.html — 4 KPI cards, HTMX polled #}
{% set sm = s.get("summary", {}) %}
{% set met = s.get("metrics", {}) %}

<div class="pip-kpi">
  <div class="pip-kpi-label">PORTFOLIO</div>
  <div class="pip-kpi-value glow">${{ "{:,.2f}".format(sm.get("portfolio_value", 0)) }}</div>
  <div class="pip-kpi-sub">{{ "%+.2f"|format(sm.get("portfolio_ret", 0)) }}% ALL TIME</div>
</div>

<div class="pip-kpi">
  <div class="pip-kpi-label">TODAY P&L</div>
  <div class="pip-kpi-value {% if sm.get('today_pnl_usd', 0) >= 0 %}pnl-pos{% else %}pnl-neg{% endif %}">
    ${{ "{:+,.2f}".format(sm.get("today_pnl_usd", 0)) }}
  </div>
  <div class="pip-kpi-sub">WEEK: ${{ "{:+,.2f}".format(sm.get("week_pnl_usd", 0)) }}</div>
</div>

<div class="pip-kpi">
  <div class="pip-kpi-label">WIN RATE</div>
  <div class="pip-kpi-value">{{ "%.1f"|format(met.get("win_rate", 0)) }}%</div>
  <div class="pip-kpi-sub">PF: {{ "%.2f"|format(met.get("profit_factor", 0)) }}</div>
</div>

<div class="pip-kpi">
  <div class="pip-kpi-label">TRADES</div>
  <div class="pip-kpi-value">{{ met.get("total_trades", 0) }}</div>
  <div class="pip-kpi-sub">DD: {{ "%.1f"|format(met.get("max_drawdown_pct", 0)) }}%</div>
</div>
```

- [ ] **Step 3: Create positions.html partial**

```html
{# pipboy/partials/positions.html — Open positions table #}
{% if positions %}
<table class="pip-table">
  <thead>
    <tr>
      <th>SYMBOL</th>
      <th>DIR</th>
      <th>PNL %</th>
      <th>ENTRY</th>
      <th>SL</th>
      <th>SYSTEM</th>
    </tr>
  </thead>
  <tbody>
    {% for p in positions %}
    <tr>
      <td>{{ p.get("symbol", "--") }}</td>
      <td>
        <span class="pip-badge {{ 'long' if p.get('direction', '').upper() == 'LONG' else 'short' }}">
          {{ p.get("direction", "--") }}
        </span>
      </td>
      <td class="{{ 'pnl-pos' if (p.get('pnl_pct', 0)|float) >= 0 else 'pnl-neg' }}">
        {{ "%+.2f"|format(p.get("pnl_pct", 0)|float) }}%
      </td>
      <td>{{ "{:,.2f}".format(p.get("entry_price", 0)|float) }}</td>
      <td>{{ "{:,.2f}".format(p.get("stop_loss", 0)|float) }}</td>
      <td>{{ p.get("system", "--") }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% else %}
<div style="color:var(--pip-green-dim);font-size:11px;padding:12px;">
  > NO OPEN POSITIONS
</div>
{% endif %}
```

- [ ] **Step 4: Create status_bar.html partial**

```html
{# pipboy/partials/status_bar.html — Bottom status bar #}
{% set bot = s.get("bot_status", {}) %}
{% set paused = s.get("paused", false) %}
{% set alerts = s.get("summary", {}).get("curve_drawdown", 0) %}
{% if paused %}
<div class="pip-status-bar alert">> BOT PAUSED &mdash; TRADING SUSPENDED</div>
{% elif alerts > 100 %}
<div class="pip-status-bar alert">> WARNING: DRAWDOWN ${{ "{:,.0f}".format(alerts) }}</div>
{% else %}
<div class="pip-status-bar">> SYSTEM NOMINAL &mdash; {{ bot.get("status", "UNKNOWN") }} &mdash; LAST CYCLE {{ bot.get("last_cycle_ago", "--") }}</div>
{% endif %}
```

- [ ] **Step 5: Create status.html tab page**

```html
{% extends "pipboy/base.html" %}

{% block content %}
<!-- KPIs — polled every 15s -->
<div class="pip-kpi-grid"
     hx-get="/pip/partial/kpis"
     hx-trigger="load, every 15s">
  <div class="pip-kpi"><div class="pip-kpi-label">LOADING...</div></div>
</div>

<!-- Positions — polled every 15s -->
<div class="pip-card">
  <div class="pip-card-title">OPEN POSITIONS</div>
  <div hx-get="/pip/partial/positions"
       hx-trigger="load, every 15s">
    > LOADING...
  </div>
</div>

<!-- Mini Equity Curve — polled every 5 min -->
<div class="pip-card">
  <div class="pip-card-title">EQUITY 30D</div>
  <div hx-get="/pip/partial/equity?days=30&system=total"
       hx-trigger="load, every 300s">
    > LOADING...
  </div>
</div>

<!-- Status Bar — polled every 15s -->
<div hx-get="/pip/partial/status_bar"
     hx-trigger="load, every 15s">
  <div class="pip-status-bar">> CONNECTING...</div>
</div>
{% endblock %}
```

- [ ] **Step 6: Commit**

```bash
git add templates/pipboy/status.html templates/pipboy/partials/kpi_cards.html templates/pipboy/partials/positions.html templates/pipboy/partials/status_bar.html templates/pipboy/partials/ticker.html
git commit -m "feat(dashboard): add Pip-Boy STATUS tab with KPIs, positions, and status bar"
```

---

### Task 7: Tab TRADES — Template + Partials

**Files:**
- Create: `templates/pipboy/trades.html`
- Create: `templates/pipboy/partials/equity_chart.html`
- Create: `templates/pipboy/partials/trade_log.html`
- Create: `templates/pipboy/partials/daily_pnl.html`

- [ ] **Step 1: Create equity_chart.html partial**

```html
{# pipboy/partials/equity_chart.html — ASCII equity curve #}
<div class="pip-filters">
  <button class="pip-filter-btn {{ 'active' if system == 'total' }}"
          hx-get="/pip/partial/equity?system=total&days={{ days }}"
          hx-target="#equity-container">ALL</button>
  <button class="pip-filter-btn {{ 'active' if system == 'pump' }}"
          hx-get="/pip/partial/equity?system=pump&days={{ days }}"
          hx-target="#equity-container">PUMP</button>
  <button class="pip-filter-btn {{ 'active' if system == 'scalping' }}"
          hx-get="/pip/partial/equity?system=scalping&days={{ days }}"
          hx-target="#equity-container">SCALP</button>
  <span style="margin-left:auto;"></span>
  <button class="pip-filter-btn {{ 'active' if days == 7 }}"
          hx-get="/pip/partial/equity?system={{ system }}&days=7"
          hx-target="#equity-container">7D</button>
  <button class="pip-filter-btn {{ 'active' if days == 30 }}"
          hx-get="/pip/partial/equity?system={{ system }}&days=30"
          hx-target="#equity-container">30D</button>
  <button class="pip-filter-btn {{ 'active' if days == 0 }}"
          hx-get="/pip/partial/equity?system={{ system }}&days=0"
          hx-target="#equity-container">ALL</button>
</div>
<pre class="pip-ascii-chart">{{ chart }}</pre>
```

- [ ] **Step 2: Create trade_log.html partial**

```html
{# pipboy/partials/trade_log.html — Paginated trade table #}
{% if trades %}
<table class="pip-table">
  <thead>
    <tr>
      <th>#</th>
      <th>SYMBOL</th>
      <th>DIR</th>
      <th>PNL %</th>
      <th>EXIT</th>
      <th>DURATION</th>
    </tr>
  </thead>
  <tbody>
    {% for t in trades %}
    <tr>
      <td>{{ t.get("id", "--") }}</td>
      <td>{{ t.get("symbol", "--") }}</td>
      <td>
        <span class="pip-badge {{ 'long' if t.get('direction','').upper() == 'LONG' else 'short' }}">
          {{ t.get("direction", "--")|upper }}
        </span>
      </td>
      <td class="{{ 'pnl-pos' if (t.get('pnl_pct', 0)|float) >= 0 else 'pnl-neg' }}">
        {{ "%+.2f"|format(t.get("pnl_pct", 0)|float) }}%
      </td>
      <td>{{ t.get("exit_reason", "--") }}</td>
      <td>{{ t.get("duration_min", "--") }}m</td>
    </tr>
    {% endfor %}
  </tbody>
</table>

<!-- Pagination -->
{% if total_pages > 1 %}
<div class="pip-pagination">
  {% for p in range(1, total_pages + 1) %}
  <a href="#" class="{{ 'active' if p == page }}"
     hx-get="/pip/partial/trades?system={{ system }}&days={{ days }}&page={{ p }}"
     hx-target="#trades-container">{{ p }}</a>
  {% endfor %}
</div>
{% endif %}

{% else %}
<div style="color:var(--pip-green-dim);padding:12px;">> NO TRADES IN PERIOD</div>
{% endif %}
```

- [ ] **Step 3: Create daily_pnl.html partial**

```html
{# pipboy/partials/daily_pnl.html — ASCII daily P&L bars #}
<pre class="pip-ascii-chart">{{ chart }}</pre>
```

- [ ] **Step 4: Create trades.html tab page**

```html
{% extends "pipboy/base.html" %}

{% block content %}
<!-- Performance Overview -->
<div class="pip-card">
  <div class="pip-card-title">PERFORMANCE OVERVIEW</div>
  <div class="pip-kpi-grid" style="grid-template-columns:repeat(3,1fr);"
       hx-get="/pip/partial/kpis"
       hx-trigger="load">
    > LOADING...
  </div>
</div>

<!-- Equity Curve -->
<div class="pip-card">
  <div class="pip-card-title">EQUITY CURVE</div>
  <div id="equity-container"
       hx-get="/pip/partial/equity?system=total&days=30"
       hx-trigger="load">
    > LOADING...
  </div>
</div>

<!-- Trade Log -->
<div class="pip-card">
  <div class="pip-card-title">TRADE LOG</div>
  <div class="pip-filters">
    <button class="pip-filter-btn active"
            hx-get="/pip/partial/trades?system=scalping&days=7"
            hx-target="#trades-container">SCALP</button>
    <button class="pip-filter-btn"
            hx-get="/pip/partial/trades?system=pump&days=7"
            hx-target="#trades-container">PUMP</button>
    <span style="margin-left:auto;"></span>
    <button class="pip-filter-btn active"
            hx-get="/pip/partial/trades?system=scalping&days=7"
            hx-target="#trades-container">7D</button>
    <button class="pip-filter-btn"
            hx-get="/pip/partial/trades?system=scalping&days=30"
            hx-target="#trades-container">30D</button>
  </div>
  <div id="trades-container"
       hx-get="/pip/partial/trades?system=scalping&days=7"
       hx-trigger="load">
    > LOADING...
  </div>
</div>

<!-- Daily P&L -->
<div class="pip-card">
  <div class="pip-card-title">DAILY P&L</div>
  <div hx-get="/pip/partial/daily_pnl?days=14"
       hx-trigger="load">
    > LOADING...
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Commit**

```bash
git add templates/pipboy/trades.html templates/pipboy/partials/equity_chart.html templates/pipboy/partials/trade_log.html templates/pipboy/partials/daily_pnl.html
git commit -m "feat(dashboard): add Pip-Boy TRADES tab with equity curve, trade log, and daily P&L"
```

---

### Task 8: Tab ANALYSIS — Template + Partials

**Files:**
- Create: `templates/pipboy/analysis.html`
- Create: `templates/pipboy/partials/funnel.html`
- Create: `templates/pipboy/partials/gauges.html`
- Create: `templates/pipboy/partials/scorer.html`

- [ ] **Step 1: Create funnel.html partial**

```html
{# pipboy/partials/funnel.html — Decision funnel with progress bars #}
{% set total = funnel.get("total_decisions", 0) %}
{% set stages = [
  ("TOTAL SIGNALS", total),
  ("CONFLUENCE", funnel.get("passed_confluence", 0)),
  ("RISK CHECK", funnel.get("passed_risk", 0)),
  ("COOLDOWN", funnel.get("passed_cooldown", 0)),
  ("EXECUTED", funnel.get("executed", 0)),
] %}

{% for label, count in stages %}
{% set pct = (count / total * 100) if total > 0 else 0 %}
<div style="margin-bottom:8px;">
  <div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:2px;">
    <span style="color:var(--pip-green-mid);">{{ label }}</span>
    <span>{{ count }} ({{ "%.0f"|format(pct) }}%)</span>
  </div>
  <div class="pip-bar">
    <div class="pip-bar-fill" style="width:{{ pct }}%;"></div>
  </div>
</div>
{% endfor %}

{% if funnel.get("top_blockers") %}
<div style="font-size:10px;color:var(--pip-green-dim);margin-top:8px;">
  TOP BLOCK:
  {% for blocker, count in funnel.get("top_blockers", {}).items()[:3] %}
  {{ blocker }} {{ count }}{{ " | " if not loop.last }}
  {% endfor %}
</div>
{% endif %}
```

- [ ] **Step 2: Create gauges.html partial**

```html
{# pipboy/partials/gauges.html — SVG win rate gauges by regime and session #}
{% macro gauge(label, wins, losses, total, pnl) %}
{% set wr = (wins / total * 100) if total > 0 else 0 %}
{% set dash = wr * 2.51 %}
<div class="pip-gauge">
  <svg viewBox="0 0 100 100">
    <circle cx="50" cy="50" r="40" fill="none"
            stroke="var(--pip-green-ghost)" stroke-width="6"/>
    <circle cx="50" cy="50" r="40" fill="none"
            stroke="var(--pip-green-dim)" stroke-width="6"
            stroke-dasharray="{{ dash }} 251.2"
            stroke-linecap="butt"
            transform="rotate(-90 50 50)"/>
    <text x="50" y="48" text-anchor="middle"
          fill="var(--pip-green)" font-size="16" font-family="monospace"
          font-weight="bold">{{ "%.0f"|format(wr) }}%</text>
    <text x="50" y="62" text-anchor="middle"
          fill="var(--pip-green-dim)" font-size="9" font-family="monospace">{{ total }}T</text>
  </svg>
  <div class="pip-gauge-label">{{ label }}</div>
  <div class="pip-gauge-sub">{{ wins }}W {{ losses }}L</div>
</div>
{% endmacro %}

<div style="margin-bottom:16px;">
  <div class="pip-card-title">BY REGIME</div>
  <div class="pip-grid-3" style="margin-top:8px;">
    {% for regime, data in by_regime.items() %}
    {{ gauge(regime, data.wins, data.losses, data.total, data.pnl) }}
    {% endfor %}
  </div>
</div>

<div>
  <div class="pip-card-title">BY SESSION</div>
  <div class="pip-grid-3" style="margin-top:8px;">
    {% for session, data in by_session.items() %}
    {{ gauge(session|upper, data.wins, data.losses, data.total, data.pnl) }}
    {% endfor %}
  </div>
</div>
```

- [ ] **Step 3: Create scorer.html partial**

```html
{# pipboy/partials/scorer.html — Setup scorer ranking table #}
{% set families = scorer.get("families", []) %}
{% if families %}
<table class="pip-table">
  <thead>
    <tr>
      <th>#</th>
      <th>SETUP</th>
      <th>TRADES</th>
      <th>WIN RATE</th>
      <th>EDGE</th>
    </tr>
  </thead>
  <tbody>
    {% for f in families[:15] %}
    <tr>
      <td>{{ loop.index }}</td>
      <td>{{ f.get("family", "--") }}</td>
      <td>{{ f.get("total_trades", 0) }}</td>
      <td>{{ "%.0f"|format(f.get("win_rate", 0)) }}%</td>
      <td>
        {% set score = f.get("edge_score", 0) %}
        {% if score >= 3 %}<span class="glow">&starf;&starf;&starf;</span>
        {% elif score >= 2 %}&starf;&starf;&star;
        {% elif score >= 1 %}&starf;&star;&star;
        {% else %}&star;&star;&star;
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% else %}
<div style="color:var(--pip-green-dim);padding:12px;">> NO SCORER DATA</div>
{% endif %}
```

- [ ] **Step 4: Create analysis.html tab page**

```html
{% extends "pipboy/base.html" %}

{% block content %}
<!-- Decision Funnel -->
<div class="pip-card">
  <div class="pip-card-title">DECISION FUNNEL</div>
  <div class="pip-filters">
    <button class="pip-filter-btn active"
            hx-get="/pip/partial/funnel?hours=24"
            hx-target="#funnel-container">24H</button>
    <button class="pip-filter-btn"
            hx-get="/pip/partial/funnel?hours=168"
            hx-target="#funnel-container">7D</button>
    <button class="pip-filter-btn"
            hx-get="/pip/partial/funnel?hours=720"
            hx-target="#funnel-container">30D</button>
  </div>
  <div id="funnel-container"
       hx-get="/pip/partial/funnel?hours=24"
       hx-trigger="load">
    > LOADING...
  </div>
</div>

<!-- Win Rate Gauges -->
<div class="pip-card">
  <div class="pip-card-title">WIN RATE BREAKDOWN</div>
  <div hx-get="/pip/partial/gauges"
       hx-trigger="load">
    > LOADING...
  </div>
</div>

<!-- Setup Scorer -->
<div class="pip-card">
  <div class="pip-card-title">SETUP SCORER</div>
  <div hx-get="/pip/partial/scorer?days=30"
       hx-trigger="load">
    > LOADING...
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Commit**

```bash
git add templates/pipboy/analysis.html templates/pipboy/partials/funnel.html templates/pipboy/partials/gauges.html templates/pipboy/partials/scorer.html
git commit -m "feat(dashboard): add Pip-Boy ANALYSIS tab with funnel, gauges, and scorer"
```

---

### Task 9: Tab LOGS — SSE Terminal

**Files:**
- Create: `templates/pipboy/logs.html`

- [ ] **Step 1: Create logs.html**

```html
{% extends "pipboy/base.html" %}

{% block content %}
<!-- Controls -->
<div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap;">
  <!-- Source tabs -->
  <div class="pip-filters" style="margin-bottom:0;">
    <button class="pip-filter-btn active" id="src-main"
            onclick="switchLogSource('main', this)">MAIN</button>
    <button class="pip-filter-btn" id="src-pump"
            onclick="switchLogSource('pump', this)">PUMP</button>
    <button class="pip-filter-btn" id="src-supervisor"
            onclick="switchLogSource('supervisor', this)">SUPER</button>
  </div>

  <span style="margin-left:auto;"></span>

  <!-- Pause button -->
  <button class="pip-filter-btn" id="pause-btn"
          onclick="togglePause()">PAUSE</button>
</div>

<!-- Terminal -->
<div class="pip-terminal" id="log-terminal">
  <div class="log-line" style="color:var(--pip-green-dim);">> CONNECTING TO LOG STREAM...</div>
</div>
<div style="margin-top:4px;">
  <span class="pip-cursor"></span>
</div>

<!-- Error Summary -->
<div class="pip-card" style="margin-top:16px;">
  <div class="pip-card-title">ERROR SUMMARY (24H)</div>
  <div hx-get="/pip/partial/errors"
       hx-trigger="load, every 60s">
    > LOADING...
  </div>
</div>
{% endblock %}

{% block scripts %}
<script>
var logTerminal = null;

function startLogStream(source) {
  if (logTerminal) logTerminal.close();
  var container = document.getElementById('log-terminal');
  /* Clear existing content using DOM methods */
  while (container.firstChild) {
    container.removeChild(container.firstChild);
  }
  logTerminal = initLogTerminal('log-terminal', '/stream/logs?source=' + source);
}

function switchLogSource(source, btn) {
  /* Update active button */
  var buttons = document.querySelectorAll('.pip-filters .pip-filter-btn');
  buttons.forEach(function(b) { b.classList.remove('active'); });
  btn.classList.add('active');
  startLogStream(source);
}

function togglePause() {
  if (!logTerminal) return;
  var paused = logTerminal.toggle();
  var btn = document.getElementById('pause-btn');
  btn.textContent = paused ? 'RESUME' : 'PAUSE';
  btn.classList.toggle('active', paused);
}

/* Start default stream */
startLogStream('main');
</script>
{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
git add templates/pipboy/logs.html
git commit -m "feat(dashboard): add Pip-Boy LOGS tab with SSE real-time terminal"
```

---

### Task 10: Tab SYSTEM — Template + Partials

**Files:**
- Create: `templates/pipboy/system.html`
- Create: `templates/pipboy/partials/health_meters.html`
- Create: `templates/pipboy/partials/processes.html`
- Create: `templates/pipboy/partials/error_summary.html`

- [ ] **Step 1: Create health_meters.html partial**

```html
{# pipboy/partials/health_meters.html — Segmented health meters #}
{% macro meter(label, value, max_val, warn_at, crit_at) %}
{% set pct = (value / max_val * 100) if max_val > 0 else 0 %}
{% set segments = 20 %}
{% set filled = (pct / 100 * segments)|int %}
<div style="margin-bottom:10px;">
  <div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:3px;">
    <span style="color:var(--pip-green-mid);">{{ label }}</span>
    <span>{{ "%.1f"|format(value) }}{% if label == "TEMP" %}&deg;C{% elif label == "DISK" %} GB{% else %}%{% endif %}</span>
  </div>
  <div class="pip-meter">
    {% for i in range(segments) %}
    <div class="pip-meter-seg {{ 'filled' if i < filled }}
      {{ 'crit' if i < filled and pct >= crit_at else ('warn' if i < filled and pct >= warn_at else '') }}">
    </div>
    {% endfor %}
  </div>
</div>
{% endmacro %}

{{ meter("CPU", health.get("cpu_pct", 0)|float, 100, 70, 90) }}
{{ meter("RAM", health.get("ram_pct", 0)|float, 100, 70, 85) }}
{{ meter("DISK", health.get("disk_pct", 0)|float, 100, 80, 95) }}
{{ meter("TEMP", health.get("temperature", 0)|float|default(0), 85, 65, 75) }}
```

- [ ] **Step 2: Create processes.html partial**

```html
{# pipboy/partials/processes.html — Running processes table #}
{% if processes %}
<table class="pip-table">
  <thead>
    <tr>
      <th>PROCESS</th>
      <th>PID</th>
      <th>RAM (MB)</th>
      <th>STATUS</th>
      <th>UPTIME</th>
    </tr>
  </thead>
  <tbody>
    {% for p in processes %}
    <tr>
      <td>{{ p.get("name", "--") }}</td>
      <td>{{ p.get("pid", "--") }}</td>
      <td>{{ "%.1f"|format(p.get("ram_mb", 0)) }}</td>
      <td>
        <span class="pip-badge {{ 'on' if p.get('status') == 'running' else 'off' }}">
          {{ p.get("status", "--")|upper }}
        </span>
      </td>
      <td>{{ p.get("uptime_s", 0) // 3600 }}h {{ (p.get("uptime_s", 0) % 3600) // 60 }}m</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% else %}
<div style="color:var(--pip-green-dim);padding:12px;">> NO PROCESS DATA</div>
{% endif %}
```

- [ ] **Step 3: Create error_summary.html partial**

```html
{# pipboy/partials/error_summary.html — Error/warning summary 24h #}
<div class="pip-grid-2" style="margin-bottom:12px;">
  <div>
    <span style="color:var(--pip-red);font-size:18px;font-weight:bold;">{{ error_count }}</span>
    <span style="color:var(--pip-green-mid);font-size:10px;"> ERRORS</span>
  </div>
  <div>
    <span style="color:var(--pip-green-bright);font-size:18px;font-weight:bold;">{{ warning_count }}</span>
    <span style="color:var(--pip-green-mid);font-size:10px;"> WARNINGS</span>
  </div>
</div>

{% if errors %}
<div style="font-size:10px;color:var(--pip-green-mid);margin-bottom:4px;">RECENT ERRORS:</div>
{% for line in errors[-5:] %}
<div style="font-size:10px;color:var(--pip-red-dim);white-space:pre-wrap;word-break:break-all;margin-bottom:2px;">{{ line }}</div>
{% endfor %}
{% endif %}
```

- [ ] **Step 4: Create system.html tab page**

```html
{% extends "pipboy/base.html" %}

{% block content %}
<!-- Pi Health Meters -->
<div class="pip-card">
  <div class="pip-card-title">PI HEALTH</div>
  <div hx-get="/pip/partial/health"
       hx-trigger="load, every 15s">
    > LOADING...
  </div>
</div>

<!-- Processes -->
<div class="pip-card">
  <div class="pip-card-title">PROCESSES</div>
  <div hx-get="/pip/partial/processes"
       hx-trigger="load, every 30s">
    > LOADING...
  </div>
</div>

<!-- Controls -->
<div class="pip-card">
  <div class="pip-card-title">CONTROLS</div>
  <div style="display:flex;gap:12px;padding:8px 0;">
    <form method="POST" action="/pause" style="margin:0;">
      <button type="submit" class="pip-filter-btn"
              onclick="return confirm('CONFIRM PAUSE?')">PAUSE BOT</button>
    </form>
    <form method="POST" action="/resume" style="margin:0;">
      <button type="submit" class="pip-filter-btn"
              onclick="return confirm('CONFIRM RESUME?')">RESUME BOT</button>
    </form>
  </div>
</div>

<!-- Error Summary -->
<div class="pip-card">
  <div class="pip-card-title">ERROR SUMMARY (24H)</div>
  <div hx-get="/pip/partial/errors"
       hx-trigger="load, every 60s">
    > LOADING...
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Commit**

```bash
git add templates/pipboy/system.html templates/pipboy/partials/health_meters.html templates/pipboy/partials/processes.html templates/pipboy/partials/error_summary.html
git commit -m "feat(dashboard): add Pip-Boy SYSTEM tab with health meters, processes, and controls"
```

---

### Task 11: Route Migration + Final Wiring

**Files:**
- Modify: `dashboard_server.py`

- [ ] **Step 1: Update index route to redirect to Pip-Boy**

In `dashboard_server.py`, change the `index()` route (around line 1483):

```python
@app.route("/")
def index():
    """Redirect to Pip-Boy dashboard."""
    return redirect("/pip/status")
```

- [ ] **Step 2: Move old dashboard to /legacy/dashboard**

Add route for old dashboard access:

```python
@app.route("/legacy/dashboard")
def legacy_dashboard():
    """Old V2 dashboard — preserved for reference."""
    return render_template("dashboard.html", active_page="dashboard")
```

- [ ] **Step 3: Run full test suite**

Run: `cd ~/crypto_ai_bot && python -m pytest tests/ --tb=short -q`
Expected: All tests pass (including existing tests + new Pip-Boy tests)

- [ ] **Step 4: Commit**

```bash
git add dashboard_server.py
git commit -m "feat(dashboard): wire Pip-Boy as default dashboard, move old to /legacy"
```

---

### Task 12: End-to-End Verification

- [ ] **Step 1: Restart the service**

```bash
sudo systemctl restart cryptobot
```

- [ ] **Step 2: Verify all Pip-Boy pages load**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/pip/status
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/pip/trades
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/pip/analysis
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/pip/logs
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/pip/system
```

Expected: All return `200`

- [ ] **Step 3: Verify partials return HTML**

```bash
curl -s http://localhost:5000/pip/partial/ticker | head -3
curl -s http://localhost:5000/pip/partial/kpis | head -3
curl -s http://localhost:5000/pip/partial/positions | head -3
```

Expected: HTML fragments (not error pages)

- [ ] **Step 4: Verify SSE stream connects**

```bash
curl -s -N http://localhost:5000/stream/logs?source=main | head -5
```

Expected: Lines starting with `event: log` and `data: `

- [ ] **Step 5: Verify legacy dashboard still accessible**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/legacy
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/api/status
```

Expected: Both return `200`

- [ ] **Step 6: Open in browser and verify visual**

Open `http://<pi-ip>:5000/pip/status` in browser via Tailscale. Check:
- CRT scanlines and vignette visible
- Green phosphor color scheme applied
- KPIs loading and updating
- Tabs navigate correctly
- Ticker tape updating
- Keyboard shortcuts (1-5) work

- [ ] **Step 7: Final commit (if any fixes needed)**

```bash
git add -u
git commit -m "fix(dashboard): final Pip-Boy adjustments from E2E verification"
```
