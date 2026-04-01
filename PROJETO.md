# Crypto AI Bot — Documentacao do Projeto

## Ideia Principal

Bot de analise e simulacao de trades em criptomoedas que roda de forma autonoma 24/7
em Raspberry Pi 4. Combina analise tecnica classica, scalping multi-motor com confluencia,
e IA (Claude Haiku) para validar sinais e gerar interpretacoes. Opera em modo paper
(sem dinheiro real), registra tudo em SQLite e notifica em tempo real pelo Telegram
com mensagens HTML formatadas.

---

## Ativos Monitorados

| Ativo    | Stop Loss configurado |
|----------|-----------------------|
| BTCUSDT  | 3.0%                  |
| ETHUSDT  | 3.0%                  |
| SOLUSDT  | 1.0%                  |
| BNBUSDT  | 2.5%                  |
| XRPUSDT  | 2.5%                  |
| DOGEUSDT | 1.0%                  |

Timeframe principal: **5 minutos** | Timeframe de confirmacao: **1 hora**

---

## Funcionalidades

### 1. Analise Tecnica (`indicators.py` + `strategy.py`)
Calcula 7 criterios a cada ciclo (5 min) por ativo:

| Criterio              | Detalhe                                      |
|-----------------------|----------------------------------------------|
| Tendencia SMA         | SMA9 vs SMA21                                |
| Posicao do preco      | Acima/abaixo das duas medias                 |
| Direcao das SMAs      | Ambas subindo ou ambas caindo                |
| Zona do RSI (14)      | Buy zone: 30-45 / Sell zone: 55-70           |
| Breakout              | Rompeu maxima ou minima das ultimas 10 velas |
| Volume + Breakout     | Confirmacao de volume acima da media (20)    |
| Body ratio do candle  | Forca do candle na direcao do sinal          |

Score minimo para sinal: **4/7**. Resultado: `BUY`, `SELL` ou `HOLD`.

### 2. Filtro de Tendencia HTF (`htf.py`)
Consulta o grafico de 1h antes de confirmar o sinal.
Sinais contra a tendencia do 1h sao bloqueados (viram `HOLD`).

### 3. Score de Confianca e Prioridade (`strategy.py`)
- `confidence_score` (0-100): mede o alinhamento dos indicadores
- `priority_score` (0-100): determina se o alerta vai para o Telegram
- Threshold de alerta: priority >= 85 ou tipo `sinal`

### 4. Interpretacao por IA (`context_agent.py`)
Usa **Claude Haiku** para gerar um comentario em portugues explicando
por que o sinal faz (ou nao faz) sentido antes de enviar o alerta.

### 5. Alertas via Telegram (`telegram_notifier.py` + `alert_control.py`)
Sistema completo de notificacoes com:
- **Formatacao HTML** com emojis por tipo de alerta
- **Retry automatico** com backoff (3 tentativas, fallback sem formatacao)
- **Rate limiting** (max 25 msg/s)
- **Funcoes especializadas:** `send_trade_alert()`, `send_trade_close()`,
  `send_opportunity_alert()`, `send_pump_alert()`, `send_system_alert()`,
  `send_circuit_breaker_alert()`, `send_daily_report_formatted()`
- **Deduplicacao**: so reenvia se simbolo, tipo ou prioridade mudar
- **Prefixos visuais por sistema**: PAPER, AGENT, SCALPING, PUMP

### 6. Comandos Telegram (`telegram_commands.py`)
9 comandos bidirecionais com respostas formatadas em HTML:

| Comando | Acao |
|---|---|
| `/status` | Capital e trades dos 4 sistemas |
| `/posicoes` | Posicoes abertas de todos os sistemas |
| `/capital` | Capital detalhado por sistema com % desde inicio |
| `/performance` | Win rate, P&L e trades do dia |
| `/saude` | CPU, RAM, disco, temperatura do Pi, uptime |
| `/pausar` | Para abertura de novos trades |
| `/retomar` | Retoma operacao normal |
| `/relatorio` | Relatorio diario completo |
| `/ajuda` | Lista todos os comandos |

### 7. Paper Trading (`paper_trader.py`)
Simulacao de trades com capital virtual de **$10.000**:
- Abre LONG/SHORT ao receber sinal BUY/SELL
- Fecha por sinal contrario ou stop loss por ativo
- Stop loss dinamico baseado em ATR
- Maximo de 3 posicoes simultaneas
- Registra cada trade no banco SQLite

### 8. Multi-Agent Trading (`trade_agents.py`)
Pipeline de 3 agentes com capital virtual separado de **$10.000**:

```
Sinal BUY/SELL
     |
     v
[Agente 1 - Analista] -> Claude Haiku valida o sinal
     | aprovado?
     v
[Agente 2 - Risco]    -> Calcula position size (ATR-based), SL e TP (RR 2:1)
     | aprovado?
     v
[Agente 3 - Executor] -> Registra a posicao e loga o trade
```

- Maximo de 3 posicoes simultaneas
- Position sizing: risco de 2% do capital por trade
- SL baseado em ATR (ou configuracao por ativo, o maior)
- Ajuste de tamanho pela confianca do analista (<70% -> 50% do size)

### 9. Scalping Strategy (4o sistema)
Sistema de scalping com 3 motores independentes e confluencia:

```
Candles multi-timeframe (1m, 3m, 5m, 15m)
     |
     v
[Motor 1] Volume Breakout (volume_breakout.py)
[Motor 2] RSI/BB Reversal (rsi_bb_reversal.py)
[Motor 3] EMA Crossover   (ema_crossover.py)
     |
     v
[Confluencia] (confluence.py) -> Score 0-3
     | score >= 2?
     v
[Risk Manager] (risk_manager.py) -> Position size, SL, TP, alavancagem
     |
     v
[Scalping Trader] (scalping_trader.py) -> Executa e gerencia posicao
```

**Componentes:**
| Modulo | Funcao |
|---|---|
| `volume_breakout.py` | Detecta candles com volume >= 2.5x a media, breakout confirmado |
| `rsi_bb_reversal.py` | RSI extremo + toque Bollinger Band + pullback confirmado |
| `ema_crossover.py` | Cruzamento EMA9/EMA21 + retest na zona + alinhamento 15m |
| `confluence.py` | Soma sinais: 1/3 = invalido, 2/3 = medio (50% size, 3x), 3/3 = alto (100%, 5x) |
| `risk_manager.py` | Position sizing baseado em ATR, SL/TP com RR minimo, parciais em TP1 |
| `signal_types.py` | Tipos padronizados de sinal entre os motores |
| `scalping_data.py` | Coleta dados multi-timeframe (1m, 3m, 5m, 15m) |
| `news_filter.py` | Filtra periodos de noticias macro (FOMC, CPI, etc.) |

### 10. Pump Scanner (`pump_scanner.py` + `pump_trader.py`)
Processo independente que roda a cada **60 segundos**:
- Monitora as **top 50 moedas** por volume na Binance
- Detecta: volume >= 5x a media E variacao >= 2% (1 candle) ou >= 4% (3 candles)
- Abre LONG em pump, SHORT em dump
- Trailing stop de 3% a partir do pico
- Timeout de 30 minutos por posicao
- Cooldown de 30 minutos por ativo apos alerta
- Alertas formatados com `send_pump_alert()`

### 11. Circuit Breaker (`daily_report.py`)
Para operacoes automaticamente se, no dia:
- Perda acumulada >= 5% — ou —
- Numero de trades >= 20

Funciona nos 3 sistemas independentemente (paper, agent, pump).
**Envia alerta no Telegram** quando ativado (com dedup de 1 hora por sistema).

### 12. Relatorio Diario (`daily_report.py`)
Envia automaticamente via Telegram apos meia-noite:
- P&L do dia por sistema (paper / multi-agent / pump)
- Win rate, numero de trades, wins e losses
- Capital atual de cada sistema
- Posicoes abertas no momento

### 13. Supervisor (`supervisor.py`)
Gerencia `main.py`, `pump_scanner.py` e `dashboard_server.py`:
- Reinicia automaticamente em caso de crash
- Limite de 50 restarts por bot
- Log por arquivo diario em `logs/`
- **Notifica via Telegram**: inicio, crash/restart, limite atingido, encerramento

### 14. Dashboard Web (`dashboard_server.py`)
Painel responsivo Flask na porta 5000:
- Status em tempo real dos 4 sistemas
- Cards de capital com retorno %
- Posicoes abertas e historico de trades
- Grafico P&L acumulado (Chart.js)
- Saude do sistema (CPU, RAM, disco, temperatura)
- Botoes de pausar/retomar
- API JSON em `/api/status`

### 15. Backtest (`backtest.py`)
Executa a estrategia sobre dados historicos (30 dias por padrao):
- Busca dados da Binance via API
- Metricas: win rate, retorno total, max drawdown, profit factor
- Separacao HTF-alinhado vs contra-HTF

---

## Fluxo de Execucao

### Ciclo principal (main.py — a cada 5 min)
```
Para cada ativo (BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, DOGEUSDT):
  1. Busca 100 velas de 5m na Binance
  2. Calcula indicadores (SMA, RSI, breakout, volume, body ratio)
  3. Busca tendencia do 1h
  4. Gera sinal + scores

Pos-analise:
  5. Exporta JSON de analise e oportunidades
  6. Seleciona o TOP 1 do ciclo
  7. Se priority >= 85 ou tipo=sinal -> Claude interpreta -> send_opportunity_alert()
  8. Circuit breaker? -> Paper Trading
  9. Circuit breaker? -> Multi-Agent Trading
  10. Circuit breaker? -> Scalping Strategy
  11. Verifica horario -> Relatorio diario
```

### Pump Scanner (pump_scanner.py — a cada 60s)
```
  1. Busca top 50 pares USDT por volume
  2. Analisa volume e preco de cada ativo
  3. Detecta pump/dump -> send_pump_alert()
  4. Gerencia posicoes abertas (trailing stop, timeout)
```

### Supervisor (supervisor.py — processo pai)
```
supervisor.py
├── main.py          <- analise + paper + agent + scalping
├── pump_scanner.py  <- scan de volume a cada 60s
└── dashboard_server.py <- painel web Flask
```

Notifica via Telegram: inicio, crash, restart, limite de restarts, encerramento.

---

## Stack Tecnica

| Componente       | Tecnologia                                        |
|------------------|---------------------------------------------------|
| Linguagem        | Python 3.13                                       |
| Hardware         | Raspberry Pi 4 Model B (4 GB RAM) + SSD externo   |
| Dados de mercado | Binance REST API (publico, sem chave)              |
| Indicadores      | `ta` (Technical Analysis Library)                  |
| Processamento    | `pandas`, `numpy`                                  |
| IA               | Anthropic Claude Haiku (claude-haiku-4-5-20251001) |
| Notificacoes     | Telegram Bot API (HTML, retry, rate limiting)      |
| Persistencia     | SQLite WAL mode (`bot.db`)                         |
| Dashboard        | Flask + Chart.js (porta 5000)                      |

---

## Arquivos de Estado

| Arquivo                       | Conteudo                              |
|-------------------------------|---------------------------------------|
| `paper_state.json`            | Capital e posicoes do paper trader    |
| `agent_state.json`            | Capital e posicoes do multi-agent     |
| `pump_positions.json`         | Posicoes abertas do pump trader       |
| `last_alert.json`             | Ultimo alerta enviado (deduplicacao)  |
| `pump_cooldown.json`          | Cooldown por ativo no pump scanner    |
| `bot_control.json`            | Estado de pausa (via /pausar)         |
| `last_report_date.txt`        | Data do ultimo relatorio enviado      |
| `technical_analysis.json`     | Ultima analise completa               |
| `relevant_opportunities.json` | Oportunidades filtradas do ciclo      |

---

## Banco de Dados (`bot.db`)

SQLite com WAL mode — permite escrita simultanea segura de multiplos processos.

| Tabela | Conteudo |
|---|---|
| `analysis_log` | Analise tecnica de cada ciclo: preco, SMA, RSI, score, decisao |
| `alerts` | Alertas enviados ao Telegram |
| `paper_trades` | Historico do paper trader com P&L |
| `agent_trades` | Historico do agent trader com SL, TP, confianca do Claude |
| `pump_trades` | Historico do pump trader com duracao e peak price |
| `scalping_trades` | Historico do scalping com motor, confluencia, parciais |

---

## Configuracao (config.py)

| Variavel | Valor | Descricao |
|---|---|---|
| `SYMBOLS` | 6 ativos | Pares monitorados |
| `INTERVAL` | `5m` | Timeframe principal |
| `LIMIT` | 100 | Velas por analise |
| `SMA_SHORT` / `SMA_LONG` | 9 / 21 | Periodos das medias moveis |
| `RSI_WINDOW` | 14 | Periodo do RSI |
| `SIGNAL_SCORE_MIN` | 4 | Score minimo para sinal |
| `ALERT_PRIORITY_MIN` | 85 | Priority score para alerta Telegram |
| `PAPER_INITIAL_CAPITAL` | $10.000 | Capital inicial paper trader |
| `AGENT_INITIAL_CAPITAL` | $10.000 | Capital inicial agent trader |
| `PUMP_INITIAL_CAPITAL` | $5.000 | Capital inicial pump trader |
| `ATR_SL_MULTIPLIER` | 1.5 | Multiplicador do ATR para stop loss dinamico |
| `ATR_SL_FLOOR_PCT` | 2.0% | Stop loss minimo universal (fallback quando ATR indisponivel) |
| `DAILY_LOSS_LIMIT_PCT` | 5% | Circuit breaker: limite de perda diaria |
| `DAILY_MAX_TRADES` | 20 | Circuit breaker: maximo de trades/dia |
| `PUMP_VOLUME_MULTIPLIER` | 5x | Multiplo de volume para detectar pump |
| `PUMP_PRICE_CHANGE_MIN` | 2% | Variacao minima de preco para alerta |
| `PUMP_TRAILING_STOP` | 3% | Trailing stop das posicoes de pump |
| `PUMP_MAX_POSITION_TIME` | 30 min | Tempo maximo em posicao de pump |
| `PUMP_RSI_EXHAUSTION` | 80 | RSI acima disso = pump exaurindo |
| `BODY_RATIO_MIN` | 0.6 | Forca minima do candle para pontuar |

---

## Referencia dos Modulos

| Modulo | Funcoes principais |
|---|---|
| `main.py` | `run_bot()` — loop principal com analise, trading e alertas |
| `supervisor.py` | Gerencia processos, reinicia crashes, notifica Telegram |
| `database.py` | `init_db()`, `insert_*()`, `get_trades_today()`, `get_recent_trades()`, `get_cumulative_pnl()` |
| `market.py` | `get_candles(symbol, interval, limit)` |
| `indicators.py` | `add_indicators(df)` |
| `strategy.py` | `generate_signal(df, htf_trend)` |
| `htf.py` | `get_htf_trend(symbol)` |
| `context_agent.py` | `interpret_signal(result)` — interpretacao via Claude Haiku |
| `paper_trader.py` | `process_signals(results)`, `get_status()` |
| `trade_agents.py` | `orchestrate(results)`, `get_agent_status()` |
| `scalping_trader.py` | `process_scalping(symbols)`, `get_scalping_status()` |
| `volume_breakout.py` | Motor de breakout de volume (2.5x media, confirmacao direcional) |
| `rsi_bb_reversal.py` | Motor de reversao RSI + Bollinger Bands |
| `ema_crossover.py` | Motor de cruzamento EMA9/EMA21 com retest |
| `confluence.py` | Score de confluencia entre os 3 motores |
| `risk_manager.py` | Position sizing ATR-based, SL/TP, alavancagem |
| `signal_types.py` | Tipos padronizados de sinal |
| `scalping_data.py` | Coleta multi-timeframe (1m, 3m, 5m, 15m) |
| `news_filter.py` | Filtro de noticias macro |
| `pump_scanner.py` | `scan()` — detecta volume anormal a cada 60s |
| `pump_trader.py` | `open_position()`, `check_positions()`, `get_status()` |
| `telegram_notifier.py` | `send_telegram_message()`, `send_trade_alert()`, `send_pump_alert()`, `send_system_alert()`, `send_circuit_breaker_alert()`, etc. |
| `telegram_commands.py` | `is_paused()`, `start_command_listener()` — 9 comandos |
| `daily_report.py` | `is_circuit_broken()`, `generate_report()`, `calc_daily_stats()` |
| `alert_control.py` | `should_send_alert(data)` — deduplicacao |
| `dashboard_server.py` | Flask app — `/`, `/api/status`, `/pause`, `/resume` |
| `backtest.py` | Backtesting historico com dados da Binance |
