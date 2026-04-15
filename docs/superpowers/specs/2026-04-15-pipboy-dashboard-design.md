# Pip-Boy Dashboard — Design Spec

> Redesign completo do dashboard do crypto_ai_bot com estetica Pip-Boy (Fallout).
> Verde fosforescente monocromatico, scanlines CRT, personalizado para Gabriel.
> Aprovado em 2026-04-15.

---

## 1. Visao Geral

### Objetivo

Substituir o dashboard Flask atual (7 templates, 2 design systems, CSS duplicado) por um frontend Pip-Boy unificado com 5 abas, dados em tempo real via SSE, e zero bibliotecas de graficos.

### Requisitos

- **Monitoramento 24/7**: Status ao vivo, posicoes abertas, alertas, saude do Pi
- **Analise**: Funil de decisoes, breakdown por regime/sessao, scorer de setups, microestrutura
- **Vitrine**: Equity curve, metricas de destaque, visual impressionante pra mostrar resultados
- **Real-time**: Logs scrollando, dados atualizando sem reload de pagina
- **Personalizado**: Nome "Gabriel" no sistema, branding proprio
- **Responsivo**: Notebook + celular via Tailscale

### Nao-requisitos

- Nao precisa de acesso publico (Tailscale cuida da rede)
- Nao precisa de autenticacao complexa (HTTP Basic Auth atual suficiente)
- Nao precisa de build step (zero node/npm/bundler)

---

## 2. Stack Tecnica

| Camada | Tecnologia | Justificativa |
|--------|-----------|---------------|
| Backend | Flask (existente) | Ja roda, leve, Pi-friendly |
| Templating | Jinja2 | Server-side rendering, sem build step |
| Frontend reativo | HTMX 2.x (14KB CDN) | Atualizacoes parciais sem JS manual |
| Real-time | SSE (Server-Sent Events) | Unidirecional (Pi→browser), mais leve que WebSocket, sem eventlet/gevent |
| Estilizacao | CSS custom (`pipboy.css`) | Design system Pip-Boy completo |
| Charts | Zero bibliotecas | ASCII art (servidor), SVG inline (gauges), CSS (progress bars) |
| Fonts | Courier New / monospace nativa | Sem CDN de fontes, puro terminal |

### O que muda vs atual

- Templates novos substituem os 7 atuais → 1 base + 5 tabs
- 3 endpoints SSE novos (`/stream/status`, `/stream/logs`, `/stream/ticker`)
- CSS novo completo (`static/css/pipboy.css`)
- JS minimo: HTMX + helpers de formatacao (~100 linhas)
- APIs JSON atuais permanecem intactas (backward compatible)
- Templates antigos preservados em `/legacy` durante transicao

### Endpoints SSE novos

| Endpoint | Frequencia | Dados |
|----------|-----------|-------|
| `GET /stream/status` | 15s | KPIs, posicoes, capital, bot_status, health |
| `GET /stream/logs?source=main&level=info` | Real-time | Linhas de log conforme aparecem |
| `GET /stream/ticker` | 30s | Precos BTC/ETH, uptime, ultimo ciclo, temperatura |

---

## 3. Design System Pip-Boy

### Paleta de cores

```css
/* Cor principal — verde fosforo */
--pip-green:        #00ff41;
--pip-green-bright: #00ff41;        /* texto principal, valores */
--pip-green-mid:    #00ff4188;      /* labels, INFO */
--pip-green-dim:    #00ff4155;      /* timestamps, secundario */
--pip-green-faint:  #00ff4133;      /* bordas, separadores */
--pip-green-ghost:  #00ff4111;      /* backgrounds de barra */

/* Unica excecao ao monocromatico */
--pip-red:          #ff4141;        /* ERR em logs, perdas criticas */
--pip-red-dim:      #ff414188;      /* texto de erro secundario */

/* Backgrounds */
--pip-bg:           #0a0a0a;        /* fundo principal */
--pip-bg-card:      #0a0a0a;        /* cards (mesmo fundo, borda diferencia) */
--pip-bg-hover:     #00ff4108;      /* hover state */
```

### Efeitos CRT

```css
/* Scanlines — overlay em todo container principal */
.crt-overlay {
  background: repeating-linear-gradient(
    0deg, transparent, transparent 2px,
    rgba(0,255,65,0.03) 2px, rgba(0,255,65,0.03) 4px
  );
}

/* Vinheta — escurece bordas como CRT real */
.crt-vignette {
  background: radial-gradient(
    ellipse at center, transparent 60%, rgba(0,0,0,0.5) 100%
  );
}

/* Glow — texto/valores importantes */
.glow { text-shadow: 0 0 8px rgba(0,255,65,0.4); }
```

### Tipografia

- **Toda a UI**: `'Courier New', 'Lucida Console', monospace` — sem fontes externas
- **Numeros/precos**: mesmo font, `font-variant-numeric: tabular-nums`
- **Labels**: uppercase, letter-spacing 1-2px, cor `--pip-green-mid`
- **Tamanhos**: valores grandes 18-22px, corpo 11px, labels 8-9px

### Componentes reutilizaveis

| Componente | Descricao | Uso |
|-----------|-----------|-----|
| `pip-card` | Container com borda `--pip-green-faint`, scanlines, padding | Tudo |
| `pip-kpi` | Label + valor grande + subtexto | STATUS, TRADES |
| `pip-gauge` | Circulo SVG com % preenchido | ANALYSIS (win rates) |
| `pip-bar` | Progress bar horizontal com label | ANALYSIS (funil) |
| `pip-table` | Tabela monospace com hover | TRADES, LOGS, SYSTEM |
| `pip-terminal` | Container de log com auto-scroll | LOGS |
| `pip-meter` | Barra horizontal segmentada (CPU, RAM) | SYSTEM |
| `pip-ascii-chart` | Pre-formatted ASCII art chart | TRADES (equity, P&L) |
| `pip-badge` | Pill pequena (LONG/SHORT, ON/OFF) | Posicoes, sistemas |
| `pip-status-dot` | Dot animado com glow | Header, processos |
| `pip-sparkline` | Mini bar chart inline (8 barras) | Microestrutura |

---

## 4. Navegacao

### Header fixo (todas as telas)

```
┌──────────────────────────────────────────────────────────┐
│ ● GABRIEL'S TERMINAL        [STATUS][TRADES][ANALYSIS][LOGS][SYSTEM] │
│ ▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰ │
│ BTC $67,200 ▲ | ETH $2,500 ▼ | UPTIME 5d 3h | CYCLE 2m | 31°C     │
└──────────────────────────────────────────────────────────┘
```

- **Linha 1**: Branding personalizado ("GABRIEL'S TERMINAL") + tabs. Aba ativa com glow.
- **Linha 2**: Barra decorativa Pip-Boy (separador visual).
- **Linha 3**: Ticker tape via SSE — precos, uptime, ciclo, temp.

### Responsivo (celular)

- Tabs viram icones compactos: `[S][T][A][L][Y]` com tooltip
- Ticker tape: so BTC + ultimo ciclo (esconde resto)
- Cards empilham verticalmente
- Tabelas ganham scroll horizontal

### Atalhos de teclado

| Tecla | Acao |
|-------|------|
| `1-5` | Muda de aba (STATUS=1, TRADES=2, ...) |
| `P` | Pause/Resume bot |
| `K` | Command palette |

---

## 5. Tab STATUS — Monitoramento 24/7

A tela que fica aberta o tempo todo. Atualiza via SSE.

### Layout

```
┌─────────────────────────────────────────────┐
│  [KPI: Portfolio] [KPI: Today] [KPI: WR] [KPI: Trades/d] │
│                                             │
│  [Posicoes Abertas — tabela com SL/TP bar]  │
│                                             │
│  [Systems: Pump + Scalp] [Mini Equity 30d]  │
│                                             │
│  > STATUS BAR: alertas e estado geral       │
└─────────────────────────────────────────────┘
```

### Componentes

| Componente | Dados (API source) | Update |
|-----------|-------------------|--------|
| 4x KPI cards | `/stream/status` → summary.* | SSE 15s |
| Posicoes abertas | `/stream/status` → positions[] | SSE 15s |
| System cards (Pump, Scalp) | `/stream/status` → capital.* | SSE 15s |
| Mini equity ASCII | `/api/equity?days=30` | HTMX 5min |
| Status bar | `/stream/status` → bot_status, alerts | SSE 15s |

### KPI Cards

| Card | Valor | Subtexto |
|------|-------|----------|
| PORTFOLIO | `$35,421` | `+2.41% ALL TIME` |
| TODAY P&L | `+$142` | `3W 2L` |
| WIN RATE | `66.7%` | `PF: 2.15` |
| TRADES/DAY | `5` | mini barra de atividade |

### Posicoes abertas

Tabela com: symbol, direction (badge LONG/SHORT), PnL %, preco entrada, SL, TP, barra visual de progresso (distancia ate SL/TP), sistema de origem.

### Status bar (rodape)

Linha unica: `> SYSTEM NOMINAL — NO ALERTS — NEXT CYCLE 4m`
Muda cor/texto com alertas: drawdown, zero trades 24h, erros repetidos.

---

## 6. Tab TRADES — Vitrine de Resultados

### Layout

```
┌─────────────────────────────────────────────┐
│  [Performance Overview — 9 metricas 3x3]    │
│                                             │
│  [Equity Curve ASCII — filtros sistema/dia] │
│                                             │
│  [Trade Log — tabela filtrada + paginacao]  │
│                                             │
│  [Daily P&L — barras ASCII]                 │
└─────────────────────────────────────────────┘
```

### Componentes

| Componente | Dados (API source) | Update |
|-----------|-------------------|--------|
| Performance Overview | `/api/status` → summary + metrics | HTMX load |
| Equity Curve | `/api/equity?days=30&system=all` | HTMX on filter change |
| Trade Log | `/api/trades?system=pump&days=7` | HTMX on filter change |
| Daily P&L | `/api/equity?days=14` | HTMX load |

### Performance Overview (3x3 grid)

| | Col 1 | Col 2 | Col 3 |
|---|---|---|---|
| Row 1 | TOTAL RETURN | ALL-TIME % | BEST MONTH |
| Row 2 | TOTAL TRADES | WIN RATE | PROFIT FACTOR |
| Row 3 | MAX DRAWDOWN | AVG TRADE | SHARPE (est) |

### Equity Curve

- Grafico ASCII gerado no servidor (Jinja2 template ou helper Python)
- Filtros: `[ALL] [PUMP] [SCALPING]` e `[7D] [30D] [ALL]`
- HTMX: `hx-get="/partial/equity?system=pump&days=30"` retorna bloco HTML parcial

### Trade Log

- Filtros dropdown: sistema, periodo, regime
- Colunas: #id, symbol, direction, PnL %, exit_reason, duracao
- Paginacao: 15 trades por pagina
- Click em trade → expande detalhes (51 campos do audit)

### Daily P&L

- Barras ASCII verticais por dia (verde pra cima, espaco pra baixo)
- Resumo: avg diario, melhor dia, pior dia, contagem W/L

---

## 7. Tab ANALYSIS — Laboratorio

### Layout

```
┌─────────────────────────────────────────────┐
│  [Decision Funnel — progress bars + tree]   │
│                                             │
│  [Win Rate Regime — gauges] [Win Rate Session — gauges] │
│                                             │
│  [Microstructure — 3 readouts ao vivo]      │
│                                             │
│  [Setup Scorer — ranking com estrelas]      │
└─────────────────────────────────────────────┘
```

### Componentes

| Componente | Dados (API source) | Update |
|-----------|-------------------|--------|
| Decision Funnel | `/api/funnel?hours=24` | HTMX on filter change |
| Win Rate by Regime | `/api/trades` agregado | HTMX load |
| Win Rate by Session | `/api/trades` agregado | HTMX load |
| Microstructure | `/stream/status` → micro data | SSE 60s |
| Setup Scorer | `/api/scalping/scorer?days=30` | HTMX load |

### Decision Funnel

- Tree view com progress bars: TOTAL → CONFLUENCE → RISK → COOLDOWN → TRADE
- Cada nivel mostra count + % do total
- Linha final: `TOP BLOCK: confluence 91% | risk 6% | cooldown 2%`
- Filtro periodo: `[24H] [7D] [30D]`

### Win Rate Gauges

- Gauge SVG circular por regime (TRENDING, VOLATILE, RANGING) e por sessao (ASIA, EUR, US)
- Dentro: % win rate. Abaixo: contagem W/L e PnL medio

### Microstructure Readouts

- 3 cards lado a lado: M1 Funding, M2 Open Interest, M3 Basis
- Cada um: valor atual + mini sparkline (8 barras) + label descritivo
- Toggle entre simbolos: `[BTCUSDT] [ETHUSDT]`
- Linha inferior: status de confluencia (`1/3 INSUFICIENTE`)

### Setup Scorer

- Tabela rankeada: posicao, nome do setup, total trades, win rate, edge score (estrelas)
- Estrelas: ★★★ = edge confirmado, ★★☆ = promissor, ★☆☆ = sem edge
- Dados de `/api/scalping/scorer`

---

## 8. Tab LOGS — Terminal Real-Time

### Layout

```
┌─────────────────────────────────────────────┐
│  [Tabs fonte] [Filter severity] [Pause]     │
│  [Live Terminal — SSE stream]               │
│                                             │
│  [Error Summary — 24h]                      │
└─────────────────────────────────────────────┘
```

### Componentes

| Componente | Dados (API source) | Update |
|-----------|-------------------|--------|
| Live Terminal | `/stream/logs?source=main&level=info` | SSE real-time |
| Error Summary | `/api/logs` agregado | HTMX 60s |

### Live Terminal

- SSE stream: cada linha de log e um evento, browser faz append no DOM
- Cores por severidade: INFO=`--pip-green-mid`, WARN=`--pip-green-bright`, ERR=`--pip-red`, PUMP=`--pip-green` com glow
- Auto-scroll: ligado por default, botao pra pausar
- Buffer: maximo 500 linhas no DOM (remove as mais antigas)
- Cursor piscando no final (`█` com animacao CSS)

### Tabs de fonte

Botoes toggle: `[MAIN] [PUMP] [SCALP] [SUPER] [ALL]`
Mudar tab reconecta o SSE com `?source=<novo>`.

### Filter de severidade

Dropdown: `[ALL] [INFO+] [WARN+] [ERR only]`
Muda parametro `&level=` no SSE.

### Error Summary

- Agregado 24h: total errors, total warnings
- Lista: tipo de erro, contagem, ultimo visto
- Barras horizontais proporcionais a contagem

---

## 9. Tab SYSTEM — Controle

### Layout

```
┌─────────────────────────────────────────────┐
│  [Pi Health — meters CPU/RAM/Disk/Temp]     │
│                                             │
│  [Processes — tabela PID/RAM/status]        │
│                                             │
│  [Controls — Pause/Resume + Circuit Breaker]│
│                                             │
│  [Config Ativo — env vars leitura]          │
└─────────────────────────────────────────────┘
```

### Componentes

| Componente | Dados (API source) | Update |
|-----------|-------------------|--------|
| Pi Health | `/stream/status` → health.* | SSE 15s |
| Processes | `/api/processes` | HTMX 30s |
| Controls | POST `/pause`, `/resume` | On click |
| Config Ativo | Leitura de runtime_config | HTMX load |

### Pi Health

4 meters horizontais estilo Pip-Boy: CPU, RAM, Disco, Temperatura.
Cada um com barra segmentada + valor + estado (OK/WARN/CRIT baseado em thresholds).

### Controls

- Botoes PAUSE/RESUME com confirmacao (dialog Pip-Boy: `> CONFIRM PAUSE? [Y/N]`)
- Estado do circuit breaker: daily loss vs limit, trades today vs limit
- Visual: barra de progresso ate o limite

---

## 10. Arquivos e Estrutura

### Novos arquivos

```
static/css/pipboy.css          — design system completo (~500 linhas)
static/js/pipboy.js            — HTMX helpers, SSE setup, formatacao (~150 linhas)
templates/pipboy/
  base.html                    — skeleton (header, tabs, ticker, CRT effects)
  status.html                  — tab STATUS
  trades.html                  — tab TRADES
  analysis.html                — tab ANALYSIS
  logs.html                    — tab LOGS
  system.html                  — tab SYSTEM
  partials/
    kpi_cards.html             — fragmento HTMX: 4 KPIs
    positions.html             — fragmento HTMX: tabela posicoes
    equity_chart.html          — fragmento HTMX: ASCII equity
    trade_log.html             — fragmento HTMX: tabela trades
    funnel.html                — fragmento HTMX: funil
    gauges.html                — fragmento HTMX: gauges regime/sessao
    micro_readouts.html        — fragmento HTMX: microestrutura
    scorer.html                — fragmento HTMX: setup scorer
    error_summary.html         — fragmento HTMX: resumo erros
    health_meters.html         — fragmento HTMX: meters do Pi
    processes.html             — fragmento HTMX: tabela processos
```

### Modificacoes em arquivos existentes

```
dashboard_server.py            — adicionar rotas SSE + rotas /partial/* + servir novos templates
```

### Arquivos preservados (backward compatible)

```
templates/dashboard.html       — antigo, acessivel via /legacy
templates/analytics.html       — antigo
static/css/style.css          — antigo
static/js/dashboard.js        — antigo
```

---

## 11. Geracao de ASCII Charts

Os graficos ASCII sao gerados no servidor (Python) e enviados como HTML `<pre>` blocks.

### Equity Curve

Funcao Python que recebe array de pontos `[{day, pnl}]` e gera:
- Eixo Y: 6 linhas com labels de valor
- Eixo X: timestamps
- Linha: caracteres `╭─╯╰│┤┼├` (box drawing)
- Largura: ajustavel (default 50 colunas)

### P&L Bars

Funcao Python que recebe P&L diario e gera:
- Barras verticais com `█` (positivo pra cima, negativo pra baixo)
- Eixo zero central
- Labels de data no eixo X

### Helper

```python
# ascii_charts.py (novo arquivo)
def render_equity_curve(data: list[dict], width: int = 50) -> str: ...
def render_daily_pnl(data: list[dict], width: int = 50) -> str: ...
```

---

## 12. Responsivo

### Breakpoints

| Largura | Dispositivo | Adaptacao |
|---------|------------|-----------|
| > 1024px | Notebook | Layout completo, 2-3 colunas |
| 768-1024px | Tablet / notebook pequeno | 2 colunas, ticker reduzido |
| < 768px | Celular | 1 coluna, tabs compactas, tabelas scrollam |

### Adaptacoes mobile

- Header: tabs viram `[S][T][A][L][Y]`
- Ticker: so BTC + ciclo
- KPIs: 2x2 grid em vez de 4 em linha
- Gauges: empilham verticalmente
- Tabelas: scroll horizontal
- Logs: font menor, menos colunas
- ASCII charts: largura reduzida (30 colunas)
