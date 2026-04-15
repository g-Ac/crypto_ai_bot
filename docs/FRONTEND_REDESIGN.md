# Frontend Redesign — Dashboard V2

> Prompt de referencia para redesign completo do dashboard do crypto_ai_bot.
> Usar com Claude Code / Cowork para implementar iterativamente.

---

## Contexto

Bot de trading de criptomoedas rodando 24/7 num Raspberry Pi 4. Backend Flask servindo templates Jinja2. Todo trading e paper (virtual). Dois sistemas ativos: **Pump** (+40.71%, 133 trades) e **Scalping** (+0.43%, 14 trades). Os sistemas Paper e Agent estao desativados.

### Problemas do front atual
- `index.html` e um monolito de 2.787 linhas (CSS+HTML+JS inline)
- 7 templates com 2 design systems diferentes (Inter vs IBM Plex)
- CSS duplicado ~200 linhas copiado 6 vezes
- Chart.js em 2 versoes diferentes (4.4.3 vs 4.4.7)
- Bootstrap carregado em 1 template (peso morto)
- Sistemas mortos (Paper, Agent) ocupam 50% do UI
- 3 APIs sem frontend consumindo

### Constraints tecnicas
- **Raspberry Pi 4** (3.7GB RAM) — tudo deve ser leve
- **Flask + Jinja2** — sem build step, sem React/Vue/Angular
- **HTML/CSS/JS vanilla** — funcionar direto no browser
- **CDN** para libs externas (Chart.js, Lightweight Charts, fontes)
- **Mobile + Desktop** — responsivo, dark mode only

---

## Arquitetura nova

### Ficheiros

```
static/
  css/
    style.css              # Design system unico (~400 linhas)
  js/
    dashboard.js           # Polling, formatacao, utils compartilhados
    charts.js              # Configuracao de charts (LW Charts + Chart.js)
templates/
  base.html                # Layout Jinja2 (topbar, nav sidebar, footer)
  dashboard.html           # Pagina principal: KPIs + equity + positions + trades
  analytics.html           # Funil + outcomes + scorer + microestrutura
  equity.html              # Equity curve hero (Lightweight Charts, fullscreen)
  system.html              # Health do Pi + logs + circuit breakers
```

**4 paginas em vez de 7.** Zero duplicacao de CSS/JS.

### Navegacao

```
[Topbar fixa]
  Logo/Nome | Dashboard | Analytics | Equity | System | [Pause/Resume]

[Sidebar opcional em desktop, hamburger em mobile]
  Filtros contextuais (periodo, simbolo, sistema)
```

---

## Design System

### Paleta de cores

```css
:root {
  /* Backgrounds */
  --bg-primary: #0a0e17;          /* Fundo principal — quase preto azulado */
  --bg-secondary: #111827;        /* Paineis e cards */
  --bg-tertiary: #1a2332;         /* Hover, selected states */
  --bg-glass: rgba(17, 24, 39, 0.8);  /* Glassmorphism panels */

  /* Borders */
  --border: rgba(99, 145, 255, 0.08);
  --border-hover: rgba(99, 145, 255, 0.2);

  /* Texto */
  --text-primary: #f0f4ff;        /* Titulos, numeros importantes */
  --text-secondary: #94a3b8;      /* Labels, descricoes */
  --text-muted: #475569;          /* Timestamps, metadata */

  /* Semanticas */
  --green: #10b981;               /* Lucro, sucesso, long */
  --green-soft: rgba(16, 185, 129, 0.12);
  --red: #ef4444;                 /* Perda, erro, short */
  --red-soft: rgba(239, 68, 68, 0.12);
  --blue: #3b82f6;                /* Accent primario, links */
  --cyan: #06b6d4;                /* Accent secundario, highlights */
  --yellow: #f59e0b;              /* Warnings */
  --purple: #8b5cf6;              /* Neutral/info */

  /* Spacing */
  --gap-xs: 4px;
  --gap-sm: 8px;
  --gap-md: 16px;
  --gap-lg: 24px;
  --gap-xl: 32px;

  /* Radius */
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 16px;

  /* Shadows */
  --shadow-card: 0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2);
  --shadow-elevated: 0 10px 25px rgba(0,0,0,0.4);
}
```

### Tipografia

```css
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  font-size: 14px;
  color: var(--text-primary);
}

/* Numeros, precos, percentuais — SEMPRE monospace */
.mono, .price, .pct, .pnl, td.num {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-variant-numeric: tabular-nums;
}

/* KPI grande */
.kpi-value { font-size: 28px; font-weight: 700; }

/* KPI label */
.kpi-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); }
```

### Fontes (CDN)

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
```

### Componentes visuais

**KPI Card:**
```html
<div class="kpi-card">
  <span class="kpi-label">Portfolio Value</span>
  <span class="kpi-value mono">$35,421.50</span>
  <span class="kpi-delta positive">+2.41%</span>
  <canvas class="sparkline" width="80" height="30"></canvas>  <!-- mini chart 7d -->
</div>
```

**Panel (card generico):**
```html
<div class="panel">
  <div class="panel-header">
    <h3>Open Positions</h3>
    <span class="badge">3</span>
  </div>
  <div class="panel-body">
    <!-- conteudo -->
  </div>
</div>
```

**Badge de PnL (cor automatica):**
```html
<span class="pnl positive">+2.41%</span>   <!-- verde -->
<span class="pnl negative">-1.05%</span>   <!-- vermelho -->
<span class="pnl neutral">0.00%</span>     <!-- cinza -->
```

**Status dot (pulsante):**
```html
<span class="status-dot healthy"></span>    <!-- verde pulsante -->
<span class="status-dot degraded"></span>   <!-- amarelo -->
<span class="status-dot offline"></span>    <!-- vermelho -->
```

---

## Libs externas (CDN)

```html
<!-- Charts: equity curve, candlestick (visual TradingView) -->
<script src="https://unpkg.com/lightweight-charts@4/dist/lightweight-charts.standalone.production.js"></script>

<!-- Charts: barras, donut, radar, distribuicoes -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>

<!-- Chart.js plugin: zoom/pan interativo -->
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2/dist/chartjs-plugin-zoom.min.js"></script>
```

Total JS externo: ~130KB gzipped. Sem framework.

---

## Paginas — Spec detalhada

---

### Pagina 1: Dashboard (`/` → `dashboard.html`)

> A pagina que o usuario ve 90% do tempo. Deve responder a pergunta: "como esta o bot agora?"

**Layout:**
```
┌─────────────────────────────────────────────────────────┐
│ Topbar: Bot Name | Status dot | Uptime | Pause/Resume  │
├──────────┬──────────┬──────────┬────────────────────────┤
│ KPI:     │ KPI:     │ KPI:     │ KPI:                   │
│ Portfolio│ Today PnL│ Win Rate │ Open Positions          │
│ $35,421  │ +$142    │ 66.7%   │ 3                       │
│ [spark]  │ [spark]  │ [spark]  │                         │
├──────────┴──────────┴──────────┴────────────────────────┤
│                                                         │
│  Equity Curve (Lightweight Charts — area, 30d default)  │
│  [7d] [30d] [90d]                                       │
│                                                         │
├─────────────────────────────┬───────────────────────────┤
│ Open Positions              │ System Cards              │
│ ┌─────────────────────────┐ │ ┌───────────────────────┐ │
│ │ BTCUSDT LONG  +1.2%    │ │ │ Pump     +40.71%     │ │
│ │ Entry: $67,200          │ │ │ 133 trades | CB: off │ │
│ │ SL: $66,800 TP: $68,000│ │ ├───────────────────────┤ │
│ └─────────────────────────┘ │ │ Scalping  +0.43%     │ │
│ ┌─────────────────────────┐ │ │ 14 trades | CB: off  │ │
│ │ ETHUSDT SHORT -0.5%    │ │ └───────────────────────┘ │
│ └─────────────────────────┘ │                           │
├─────────────────────────────┴───────────────────────────┤
│ Recent Trades (ultimos 20)                    [Ver all] │
│ ┌──────────┬────────┬──────┬───────┬────────┬─────────┐ │
│ │ Time     │ Symbol │ Side │ PnL%  │ System │ Reason  │ │
│ ├──────────┼────────┼──────┼───────┼────────┼─────────┤ │
│ │ 10:32    │ DOGE   │ LONG │ +2.1% │ pump   │ trail   │ │
│ │ 09:15    │ BTC    │ SHORT│ -0.8% │ scalp  │ sl_hit  │ │
│ └──────────┴────────┴──────┴───────┴────────┴─────────┘ │
└─────────────────────────────────────────────────────────┘
```

**APIs consumidas:**
- `GET /api/status` (polling 30s) → KPIs, positions, chart, capital, bot_status, health
- `GET /api/trades?days=7` → Recent trades

**Interacoes:**
- Click no periodo do equity (7d/30d/90d) recarrega chart
- Click numa position expande detalhes (SL/TP, leverage, confluence score)
- Click num trade abre modal com detalhes completos
- Pause/Resume com confirmacao

---

### Pagina 2: Analytics (`/analytics` → `analytics.html`)

> Pagina de analise profunda. Responde: "por que o bot esta performando assim?"

**Layout:**
```
┌─────────────────────────────────────────────────────────┐
│ Topbar                                                  │
├─────────────────────────┬───────────────────────────────┤
│ Decision Funnel (24h)   │ Score Distribution            │
│                         │                               │
│ 1008 sinais avaliados   │ [histogram Chart.js]          │
│ ████████████████ 100%   │  0: ████████ 62%              │
│ █████████████░░░  96%   │  1: ██████░░ 34%              │
│ █░░░░░░░░░░░░░░░  0.1% │  2: █░░░░░░░  4%              │
│                         │                               │
│ Blocked by:             │                               │
│  confluence: 960        │                               │
│  risk: 35               │                               │
│  error: 13              │                               │
├─────────────────────────┴───────────────────────────────┤
│ Performance by Regime           │ Performance by Session │
│ ┌──────────┬───────┬──────────┐ │ ┌─────────┬──────────┐│
│ │ Regime   │ Trades│ Win Rate │ │ │ Session │ Win Rate ││
│ │ TRENDING │  8    │  62.5%   │ │ │ US      │ 70%      ││
│ │ VOLATILE │  4    │  50.0%   │ │ │ Europe  │ 55%      ││
│ │ RANGING  │  2    │  100%    │ │ │ Asia    │ 40%      ││
│ └──────────┴───────┴──────────┘ │ └─────────┴──────────┘│
├─────────────────────────────────┴───────────────────────┤
│ Microstructure Live (6 symbols)                         │
│ ┌────────┬──────────┬─────────┬────────┬───────────────┐│
│ │ Symbol │ Funding  │ Basis   │ OI Chg │ Liq Vol      ││
│ │ BTC    │ +0.008%  │ +0.05%  │ +1.2%  │ $125K / $80K ││
│ │ ETH    │ +0.003%  │ -0.02%  │ -0.5%  │ $45K / $92K  ││
│ └────────┴──────────┴─────────┴────────┴───────────────┘│
├─────────────────────────────────────────────────────────┤
│ Tabs: [Outcomes] [Scorer] [Audit Trail]                 │
│                                                         │
│ (conteudo da tab selecionada — tabela paginada)         │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**APIs consumidas:**
- `GET /api/funnel?hours=24` → Funil de decisoes
- `GET /api/microstructure/latest` → Dados ao vivo dos 6 symbols
- `GET /api/scalping/outcomes?days=7` → Labels forward
- `GET /api/scalping/scorer?days=30` → Ranking de setups
- `GET /api/scalping/audit?days=1` → Trail de auditoria
- `GET /api/signal-subtypes?days=7` → Distribuicao de signal types

**Interacoes:**
- Tabs para alternar entre Outcomes/Scorer/Audit
- Click num setup do Scorer expande detalhes
- Filtros de periodo (1h/6h/24h/7d)
- Click num symbol da microestrutura abre historico

---

### Pagina 3: Equity (`/equity` → `equity.html`)

> Equity curve fullscreen. Responde: "como esta a tendencia de longo prazo?"

**Layout:**
```
┌─────────────────────────────────────────────────────────┐
│ Topbar                                                  │
├─────────────────────────────────────────────────────────┤
│ Filtros: [7d] [30d] [90d] [All]  Sistema: [All] [Pump] │
│          [Scalping]                                     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│                                                         │
│     Lightweight Charts — Area fill                      │
│     2 series: Pump (cyan) + Scalping (purple)           │
│     Crosshair com tooltip detalhado                     │
│     Zoom/Pan com mouse/touch                            │
│                                                         │
│                                                         │
│                                                         │
├─────────────────────────────────────────────────────────┤
│ Stats resumo:                                           │
│ Total PnL: +$2,140  |  Peak: +$2,500  |  Drawdown: -3% │
│ Best day: +$340 (Apr 8)  |  Worst: -$120 (Apr 3)       │
└─────────────────────────────────────────────────────────┘
```

**APIs consumidas:**
- `GET /api/equity?days=N` → Series temporais pump + scalping

**Interacoes:**
- Seletor de periodo muda range do chart
- Seletor de sistema filtra series
- Zoom/pan nativo do Lightweight Charts
- Hover mostra tooltip com data + PnL exato

---

### Pagina 4: System (`/system` → `system.html`)

> Saude operacional do Pi. Responde: "o bot esta saudavel?"

**Layout:**
```
┌─────────────────────────────────────────────────────────┐
│ Topbar                                                  │
├────────────┬────────────┬────────────┬──────────────────┤
│ CPU        │ RAM        │ Disco      │ Temperatura      │
│ ○ 12%      │ ○ 43%      │ ○ 10%      │ 31.1°C          │
│ (gauge)    │ (gauge)    │ (gauge)    │ (gauge)          │
├────────────┴────────────┴────────────┴──────────────────┤
│ Processos                                               │
│ ┌──────────────────┬────────┬──────┬──────────────────┐ │
│ │ Nome             │ PID    │ RAM  │ Status           │ │
│ │ supervisor.py    │ 95202  │ 33MB │ ● running        │ │
│ │ main.py          │ 95206  │ 119MB│ ● running (140s) │ │
│ │ pump_scanner.py  │ 95207  │ 82MB │ ● running        │ │
│ │ dashboard_server │ 95208  │ 87MB │ ● running        │ │
│ └──────────────────┴────────┴──────┴──────────────────┘ │
├─────────────────────────────────────────────────────────┤
│ Circuit Breakers                                        │
│ Pump: OFF (3/20 trades hoje) | Scalping: OFF (0/20)    │
├─────────────────────────────────────────────────────────┤
│ Logs: [Main] [Pump] [Scalping] [Supervisor]             │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 20:45:32 [MAIN] Ciclo 1423: 6 symbols processados  │ │
│ │ 20:45:28 [MAIN] BTCUSDT: score=3.5, regime=TRENDING│ │
│ │ 20:40:31 [MAIN] Ciclo 1422: 6 symbols processados  │ │
│ │ ...                                                 │ │
│ └─────────────────────────────────────────────────────┘ │
│ [Auto-scroll: ON] [Lines: 100]                          │
└─────────────────────────────────────────────────────────┘
```

**APIs consumidas:**
- `GET /api/status` → health, bot_status, scalping_funnel (circuit breakers)
- `GET /api/logs?source=X&lines=100` → Logs ao vivo

**Interacoes:**
- Gauges animados para CPU/RAM/Disco/Temp
- Tabs para alternar fonte de logs
- Auto-scroll toggle nos logs
- Cores nos logs (verde=info, amarelo=warn, vermelho=erro)

---

## APIs disponiveis (referencia rapida)

### Core (usar no dashboard principal)

| Endpoint | Polling | O que retorna |
|----------|---------|---------------|
| `GET /api/status` | 30s | Tudo: capital, positions, chart, metrics, health, bot_status |
| `GET /api/equity?days=N` | On-demand | PnL cumulativo diario (pump + scalping arrays) |
| `GET /api/trades?system=X&days=N` | On-demand | Historico de trades. Scalping: 51 campos. Pump: 12 campos |
| `GET /api/version` | Boot | Metadata da instancia (git sha, version tag, bot_id) |

### Analytics (usar na pagina de analise)

| Endpoint | Polling | O que retorna |
|----------|---------|---------------|
| `GET /api/funnel?hours=N` | On-demand | Funil: total, passed, by_blocker, by_regime, by_session, by_score |
| `GET /api/scalping/audit?days=N` | 30s | Trail de auditoria: eventos com contexto completo |
| `GET /api/scalping/outcomes?days=N` | On-demand | Labels forward: verdict, winner/loser, horizons 5/15/30/60min |
| `GET /api/scalping/scorer?days=N` | On-demand | Ranking de setups: recommendation, edge_score, win_rate |
| `GET /api/microstructure/latest` | 60s | 6 symbols: funding, basis, OI, liquidations, session |
| `GET /api/microstructure/history?symbol=X&hours=N` | On-demand | Serie temporal de microestrutura |
| `GET /api/signal-subtypes?days=N` | On-demand | Distribuicao: cascade, divergence, continuation |

### System (usar na pagina de sistema)

| Endpoint | Polling | O que retorna |
|----------|---------|---------------|
| `GET /api/logs?source=X&lines=N` | 10s | Linhas de log (main, pump, scalping, supervisor) |
| `POST /pause` | Action | Pausa o bot (requer auth) |
| `POST /resume` | Action | Retoma o bot (requer auth) |

### APIs a NAO usar (mortas ou redundantes)

| Endpoint | Motivo |
|----------|--------|
| `GET /api/ai-brain` | AI gate desativado, dados irrelevantes |
| `GET /api/compare` | Requer 2 runtimes, nunca usado |
| `GET /api/scalping/outcomes/export` | Backend only, nao precisa de UI |

---

## Dados chave do /api/status (shape resumido)

```javascript
// O que consumir do mega-endpoint /api/status:
const data = await fetch('/api/status').then(r => r.json());

// KPIs
data.summary.portfolio_value     // float: valor total do portfolio
data.summary.today_pnl_usd      // float: PnL do dia em USD
data.summary.open_positions      // int: posicoes abertas
data.metrics.win_rate            // float: win rate geral

// Capital por sistema (so mostrar pump + scalping)
data.capital.pump.value          // float
data.capital.pump.ret            // float (retorno %)
data.capital.scalping.value
data.capital.scalping.ret

// Posicoes abertas (com PnL ao vivo)
data.positions[]                 // array de objetos
  .system                        // "scalping" | "pump"
  .symbol                        // "BTCUSDT"
  .type                          // "LONG" | "SHORT"
  .entry_price                   // float
  .current_price                 // float
  .pnl_pct                       // float
  .sl_price, .tp_price           // float
  .leverage                      // int
  .confluence_score              // int

// Equity chart data
data.chart.pump[]                // [{day: "2026-04-10", pnl: 2140.5}, ...]
data.chart.scalping[]
data.chart.total[]

// Health do Pi
data.health.cpu_usage_pct
data.health.ram_usage_pct
data.health.disk_usage_pct
data.health.temperature_c
data.health.uptime               // "5d 3h 50m"

// Bot status
data.bot_status.overall          // "healthy" | "degraded" | "offline"
data.bot_status.last_cycle_ago   // "140s"
data.bot_status.errors_today     // int

// Circuit breakers
data.capital.pump.cb             // bool
data.capital.scalping.cb         // bool

// Stats hoje por sistema
data.stats_today.pump            // {count, wins, losses, pnl_pct, pnl_usd}
data.stats_today.scalping

// Paused
data.paused                      // bool
```

---

## Etapas de implementacao

### Etapa 1: Fundacao (base.html + style.css)

**Objetivo:** Criar o esqueleto compartilhado por todas as paginas.

**Ficheiros a criar:**
- `static/css/style.css` — Design system completo (paleta, tipografia, componentes)
- `templates/base.html` — Layout Jinja2 com topbar, nav, `{% block content %}`, footer

**Criterios de done:**
- Topbar com: nome do bot, status dot (healthy/degraded), uptime, nav links
- Nav com 4 links: Dashboard, Analytics, Equity, System
- Footer com: version tag, git sha, ultimo refresh
- Mobile: hamburger menu, nav collapsa
- Todas as CSS vars definidas
- Testar com `{% block content %}<p>Hello</p>{% endblock %}`

**Validacao:** Abrir no browser, verificar que a topbar e nav funcionam em desktop e mobile.

---

### Etapa 2: Dashboard principal (dashboard.html)

**Objetivo:** Pagina principal que substitui o index.html monolito.

**Ficheiros a criar/editar:**
- `templates/dashboard.html` — extends base.html
- `static/js/dashboard.js` — Polling /api/status a cada 30s, render dos componentes

**Seccoes (top to bottom):**
1. KPI Strip (4 cards): Portfolio Value, Today PnL, Win Rate 30d, Open Positions
2. Equity Curve compacta (Chart.js area, 30d, pump+scalping+total)
3. Open Positions (cards com PnL ao vivo, cor verde/vermelho)
4. System Cards (Pump + Scalping — capital, return, trades hoje, CB status)
5. Recent Trades (tabela com ultimos 20 trades, cor por PnL)

**Criterios de done:**
- Auto-refresh a cada 30s sem piscar (update DOM seletivo)
- Numeros de PnL em verde/vermelho automatico
- Numeros em fonte monospace
- Positions com entry price, current price, SL/TP, PnL%
- Tabela de trades com sorting por data (mais recente primeiro)
- Responsivo: KPIs empilham em mobile, tabela com scroll horizontal

**Validacao:** Dados reais do /api/status renderizados. Nenhum dado de Paper/Agent visivel.

---

### Etapa 3: Equity curve (equity.html)

**Objetivo:** Equity curve hero com visual profissional (estilo TradingView).

**Ficheiros a criar/editar:**
- `templates/equity.html` — extends base.html
- `static/js/charts.js` — Config do Lightweight Charts

**Seccoes:**
1. Filtros: periodo (7d/30d/90d/All) + sistema (All/Pump/Scalping)
2. Chart hero (~70% viewport): Lightweight Charts area series
3. Stats resumo: Total PnL, Peak, Drawdown, Best/Worst day

**Criterios de done:**
- Lightweight Charts renderizando com area fill
- 2 series: Pump (cyan #06b6d4) + Scalping (purple #8b5cf6)
- Crosshair com tooltip mostrando data + PnL exato
- Zoom/pan nativo (mouse wheel + drag)
- Botoes de periodo mudam range e destacam o ativo
- Stats abaixo do chart calculados a partir dos dados
- Responsivo: chart ocupa 100% width

**Validacao:** Chart com dados reais do /api/equity. Zoom funciona. Mobile OK.

---

### Etapa 4: Analytics (analytics.html)

**Objetivo:** Pagina de analise profunda — funil, outcomes, scorer, microestrutura.

**Ficheiros a criar/editar:**
- `templates/analytics.html` — extends base.html

**Seccoes:**
1. Decision Funnel (barras horizontais CSS — total → bloqueados → passaram)
2. Breakdown por regime + por sessao (mini tabelas lado a lado)
3. Microstructure Live (tabela com 6 symbols, funding/basis/OI/liq)
4. Tabs: Outcomes | Scorer | Audit Trail (conteudo alternado via JS)
   - Outcomes: tabela paginada com verdict, direction, symbol, edge_score
   - Scorer: cards por setup family com recommendation badge (promising/watch/avoid)
   - Audit: tabela de eventos recentes com filtro por outcome

**Criterios de done:**
- Funil visual com barras proporcionais e contagens
- Microestrutura com cor por valor (funding alto = vermelho, negativo = verde)
- Tabs funcionam sem reload da pagina
- Tabelas paginadas (20 items por pagina)
- Filtros de periodo funcionam para cada secao

**Validacao:** Dados reais de todas as APIs renderizados. Tabs funcionam. Mobile OK.

---

### Etapa 5: System (system.html)

**Objetivo:** Saude operacional do Pi + logs.

**Ficheiros a criar/editar:**
- `templates/system.html` — extends base.html

**Seccoes:**
1. Health Gauges: CPU, RAM, Disco, Temperatura (circular SVG ou CSS)
2. Process Table: supervisor, main, pump_scanner, dashboard (status, RAM)
3. Circuit Breakers: status por sistema (pump, scalping)
4. Log Viewer: tabs por fonte (Main/Pump/Scalping/Supervisor), auto-scroll

**Criterios de done:**
- Gauges mudam de cor conforme nivel (verde < 60%, amarelo < 85%, vermelho >= 85%)
- Logs com syntax highlight basico (timestamps cinza, [ERRO] vermelho, numeros cyan)
- Auto-scroll toggle
- Polling de logs a cada 10s
- Polling de health a cada 30s (via /api/status)

**Validacao:** Gauges com dados reais. Logs renderizando. Mobile OK.

---

### Etapa 6: Polish e integracao

**Objetivo:** Integrar tudo, remover codigo antigo, polir.

**Tarefas:**
1. Atualizar `dashboard_server.py`:
   - Rota `/` renderiza `dashboard.html` em vez de `index.html`
   - Adicionar rota `/analytics`
   - Adicionar rota `/system`
   - Manter rotas API sem mudanca
   - Remover rota `/comparison` (morta)
2. Remover templates antigos: `index.html`, `comparison.html`
3. Manter templates de detalhe: `scalping_audit.html`, `scalping_outcomes.html`, `scalping_scorer.html` (ou migrar para tabs dentro de analytics.html)
4. Testar em mobile (viewport 375px)
5. Testar em desktop (1920px)
6. Verificar que polling nao sobrecarrega o Pi (max 1 request/10s por pagina)
7. Lighthouse check: performance score > 80

**Criterios de done:**
- 4 paginas funcionais, 0 paginas mortas
- Zero CSS duplicado (tudo em style.css)
- Zero JS inline nos templates (tudo em ficheiros .js)
- Navegacao funciona em todas as paginas
- Nenhuma referencia a Paper Trading ou Agent Trading no UI

---

## Regras para o implementador

1. **Sempre ler o ficheiro antes de modificar** — nao criar componente sem ver o que ja existe
2. **Testar no browser apos cada mudanca** — nao acumular mudancas sem validar
3. **Mobile first** — comecar pelo layout mobile, expandir para desktop
4. **Dados reais** — usar sempre as APIs reais, nunca hardcodar dados fake
5. **Performance** — o Pi tem 3.7GB RAM. Cuidado com polling agressivo e DOM pesado
6. **Sem frameworks** — HTML/CSS/JS vanilla. Jinja2 para templating server-side
7. **Sem build step** — tudo deve funcionar com um refresh no browser
8. **Incremental** — uma etapa de cada vez, testar, validar, avancar

---

## Checklist final

- [ ] `base.html` com topbar + nav + footer
- [ ] `style.css` com design system completo
- [ ] `dashboard.html` com KPIs + equity + positions + trades
- [ ] `equity.html` com Lightweight Charts
- [ ] `analytics.html` com funil + micro + tabs
- [ ] `system.html` com gauges + logs
- [ ] Dashboard server atualizado com novas rotas
- [ ] Templates antigos removidos (index.html, comparison.html)
- [ ] Zero CSS/JS inline
- [ ] Mobile responsivo em todas as paginas
- [ ] Nenhuma referencia a Paper/Agent no UI
- [ ] Polling nao sobrecarrega o Pi
