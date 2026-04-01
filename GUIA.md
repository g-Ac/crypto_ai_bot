# Crypto AI Bot — Guia Completo

## Visao Geral

O Crypto AI Bot e um sistema automatizado de analise e simulacao de trading de criptomoedas.
Roda 24/7 em um Raspberry Pi 4, monitora 6 ativos na Binance a cada 5 minutos, detecta
oportunidades usando indicadores tecnicos e inteligencia artificial (Claude Haiku), executa
scalping com 3 motores independentes, simula trades com capital virtual e notifica em tempo
real pelo Telegram com mensagens HTML formatadas.

**Nao realiza trades reais** — todo o capital e virtual (paper trading).

### Ativos monitorados
`BTCUSDT` `ETHUSDT` `SOLUSDT` `BNBUSDT` `XRPUSDT` `DOGEUSDT`

### Hardware
- **Raspberry Pi 4 Model B Rev 1.5** — 4 GB RAM
- **SSD externo** — 110 GB
- **Python 3.13** | **Hostname:** `cryptobot.local`
- **IP local:** `192.168.0.24`

---

## Acesso ao Bot

### Dashboard Web
Abra no navegador (celular ou computador na mesma rede Wi-Fi):
```
http://192.168.0.24:5000
```
ou
```
http://cryptobot.local:5000
```

### SSH (terminal remoto)
```bash
ssh pi@cryptobot.local
# ou
ssh pi@192.168.0.24
```

---

## Arquitetura — processos e arquivos

O bot roda como **4 processos simultaneos** gerenciados pelo `supervisor.py`:

```
supervisor.py  <- processo pai (PID principal do servico)
├── main.py          <- analise de mercado a cada 5 minutos
├── pump_scanner.py  <- scan de volume anormal a cada 60 segundos
└── dashboard_server.py <- painel web Flask na porta 5000
```

O supervisor notifica via Telegram quando:
- Todos os bots iniciam com sucesso
- Um bot crashou e esta sendo reiniciado
- Um bot atingiu o limite maximo de restarts
- O supervisor e encerrado

### Mapa de arquivos
```
crypto_ai_bot/
│
├── main.py               # Loop principal: analisa mercado + 3 sistemas de trading
├── pump_scanner.py        # Detecta pumps no top 50 moedas por volume
├── supervisor.py          # Inicia/reinicia bots + alertas Telegram de sistema
├── dashboard_server.py    # Painel web (Flask) na porta 5000
│
├── config.py              # Todas as constantes configuraveis
├── database.py            # Banco SQLite: init, inserts, queries (WAL mode)
│
├── market.py              # Busca candles da API Binance
├── indicators.py          # SMA9, SMA21, RSI14, volume, body ratio
├── strategy.py            # Gera sinais BUY/SELL/HOLD (score 0-7)
├── htf.py                 # Tendencia de 1h para filtrar sinais
├── context_agent.py       # Envia sinal ao Claude Haiku para interpretacao
│
├── paper_trader.py        # Paper trading: $10.000 virtual, stop loss ATR
├── trade_agents.py        # Multi-agente: analista (Claude) + risco + executor
├── pump_trader.py         # Pump/dump: LONG no pump, SHORT no dump exausto
│
├── scalping_trader.py     # Orquestrador: 3 motores + confluencia + execucao
├── volume_breakout.py     # Motor 1: breakout de volume anormal (2.5x media)
├── rsi_bb_reversal.py     # Motor 2: reversao RSI extremo + Bollinger Bands
├── ema_crossover.py       # Motor 3: cruzamento EMA9/EMA21 + retest
├── confluence.py          # Score de confluencia (1/3=nao, 2/3=medio, 3/3=alto)
├── risk_manager.py        # Position sizing ATR, SL/TP, alavancagem
├── signal_types.py        # Tipos padronizados de sinal entre motores
├── scalping_data.py       # Coleta dados multi-timeframe (1m, 3m, 5m, 15m)
├── scalping_logger.py     # Logging dedicado do scalping
├── news_filter.py         # Filtro de noticias macro (FOMC, CPI, etc.)
│
├── daily_report.py        # Relatorio diario + circuit breaker + notificacao
├── alert_control.py       # Deduplicacao de alertas (evita spam)
├── telegram_notifier.py   # Envio Telegram: HTML, retry, rate limiting, formatado
├── telegram_commands.py   # 9 comandos bidirecionais com respostas HTML
│
├── logger.py              # Salva analise no banco (analysis_log)
├── alert_logger.py        # Salva alertas no banco (alerts)
├── exporter.py            # Exporta analise para JSON
├── opportunity_exporter.py # Exporta oportunidades relevantes para JSON
│
├── backtest.py            # Backtesting historico nos 6 ativos
├── migrate_csv_to_db.py   # Script de migracao: CSVs antigos -> bot.db
│
├── .env                   # Chaves de API (Telegram, Anthropic)
├── bot.db                 # Banco de dados SQLite (criado automaticamente)
├── bot_control.json       # Estado de pausa (criado pelo /pausar)
├── paper_state.json       # Estado e capital do paper trader
├── agent_state.json       # Estado e capital do agent trader
├── pump_positions.json    # Posicoes abertas do pump trader
├── pump_cooldown.json     # Cooldown de alertas do pump scanner
│
├── logs/                  # Logs diarios de cada processo
│   ├── supervisor.log
│   ├── main_bot_YYYY-MM-DD.log
│   ├── pump_scanner_YYYY-MM-DD.log
│   └── dashboard_YYYY-MM-DD.log
│
├── templates/
│   └── index.html         # Template HTML do dashboard
│
├── estrategia.md          # Documentacao detalhada da estrategia de scalping
├── PROJETO.md             # Documentacao tecnica de todos os modulos
└── GUIA.md                # Este arquivo
```

---

## Como o Bot Funciona

### Ciclo principal (main.py — a cada 5 minutos)
1. Busca 100 velas de 5m para cada ativo na Binance
2. Calcula indicadores: SMA9, SMA21, RSI14, volume, body ratio
3. Verifica tendencia de 1h (HTF) para filtrar sinais falsos
4. Gera score BUY e SELL (0-7) com 7 criterios
5. Se score >= 4: envia alerta ao Telegram com analise do Claude Haiku
6. Paper trader: simula abertura/fechamento de posicoes
7. Multi-agent trader: Claude Haiku analisa, calcula risco, executa trade
8. Scalping: executa os 3 motores, verifica confluencia, opera se score >= 2

### Pump Scanner (pump_scanner.py — a cada 60 segundos)
1. Busca os top 50 pares USDT por volume na Binance
2. Para cada ativo, compara volume atual com media de 20 velas
3. Se volume > 5x a media E variacao de preco > 2%: alerta de PUMP
4. Abre LONG automaticamente no pump detectado
5. Se pump exauriu (RSI > 80 + retrace): abre SHORT
6. Gerencia posicoes com trailing stop de 3% e timeout de 30 minutos

### Scalping Strategy (3 motores + confluencia)
1. Coleta dados multi-timeframe (1m, 3m, 5m, 15m) via `scalping_data.py`
2. Verifica filtro de noticias (news_filter.py) — nao opera perto de FOMC/CPI
3. Executa os 3 motores em paralelo:
   - **Volume Breakout**: volume >= 2.5x media + breakout direcional + corpo forte
   - **RSI/BB Reversal**: RSI extremo + toque Bollinger + pullback confirmado
   - **EMA Crossover**: cruzamento EMA9/21 + retest na zona + alinhamento 15m
4. Calcula confluencia: quantos motores apontam na mesma direcao
   - 1/3 = invalido (nao opera)
   - 2/3 = medio (50% do size, alavancagem 3x)
   - 3/3 = alto (100% do size, alavancagem 5x)
5. Risk manager calcula: position size, SL (ATR-based), TP1 e TP2
6. Executa trade e gerencia parciais (50% no TP1, SL para breakeven, 50% no TP2)

### Sistema de Sinais — 7 criterios (score 0-7)

| Criterio | BUY | SELL |
|---|---|---|
| Tendencia SMA | preco > SMA9 > SMA21 | preco < SMA9 < SMA21 |
| RSI zona | 30-45 (entrada) | 55-70 (saida) |
| RSI extremo | < 30 (sobrevendido) | > 70 (sobrecomprado) |
| Posicao do preco | acima das medias | abaixo das medias |
| Alinhamento HTF 1h | tendencia 1h = alta | tendencia 1h = baixa |
| Breakout | rompimento de alta | rompimento de baixa |
| Volume + candle forte | volume > media + body > 60% | idem |

**Resultado:**
- Score >= 4: sinal forte -> abre trade
- Score = 3 + diferenca >= 2: pre-sinal -> alerta no Telegram
- Score = 2: observacao
- Abaixo ou empatado: HOLD

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
| `ATR_SL_FLOOR_PCT` | 2.0% | Stop loss minimo universal (fallback) |
| `DAILY_LOSS_LIMIT_PCT` | 5% | Circuit breaker: limite de perda diaria |
| `DAILY_MAX_TRADES` | 20 | Circuit breaker: maximo de trades/dia |
| `PUMP_VOLUME_MULTIPLIER` | 5x | Multiplo de volume para detectar pump |
| `PUMP_PRICE_CHANGE_MIN` | 2% | Variacao minima para alerta |
| `PUMP_TRAILING_STOP` | 3% | Trailing stop do pump |
| `PUMP_MAX_POSITION_TIME` | 30 min | Tempo max em posicao pump |

### Stop Loss dinamico (ATR-based)
O SL e calculado dinamicamente para cada trade usando ATR do timeframe 1h:
- `SL% = max(ATR_1h * ATR_SL_MULTIPLIER / preco_entrada * 100, ATR_SL_FLOOR_PCT)`
- Se ATR nao estiver disponivel, usa `ATR_SL_FLOOR_PCT` como fallback universal
- Nao ha mais SL fixo por ativo (STOP_LOSS_MAP foi removido para evitar overfitting)

---

## Comandos do Telegram

O listener de comandos inicia automaticamente com o bot e responde em tempo real
com formatacao HTML e emojis. Funciona enquanto o processo `main.py` estiver rodando.

| Comando | O que faz |
|---|---|
| `/status` | Capital e trades dos 4 sistemas (paper, agent, scalping, pump) |
| `/posicoes` | Lista todas as posicoes abertas de todos os sistemas |
| `/capital` | Capital detalhado por sistema com % de variacao desde inicio |
| `/performance` | Win rate, P&L e numero de trades do dia por sistema |
| `/saude` | CPU, RAM, disco, temperatura do Pi, uptime do sistema e do bot, tamanho do DB |
| `/pausar` | Para abertura de novos trades (posicoes abertas continuam gerenciadas) |
| `/retomar` | Retoma operacao normal apos uma pausa |
| `/relatorio` | Envia o relatorio diario completo agora (nao espera meia-noite) |
| `/ajuda` | Lista todos os comandos disponiveis |

### Tipos de notificacao

| Tipo | Prefixo | Quando |
|---|---|---|
| Oportunidade | 📊 | Sinal com priority >= 85 detectado |
| Paper trade | 📄 [PAPER] | Abertura/fechamento de trade paper |
| Agent trade | 🤖 [AGENT] | Abertura/fechamento de trade agent |
| Scalping | ⚡ [SCALPING] | Abertura/fechamento de trade scalping |
| Pump/Dump | 🚀 | Pump ou dump detectado |
| Pump trade | 🚀 [PUMP] | Abertura/fechamento de posicao pump |
| Circuit breaker | 🛑 | Sistema atingiu limite diario |
| Sistema | ⚠️ / 🚨 | Crash, restart, supervisor inicio/fim |
| Relatorio | 📈 | Relatorio diario (meia-noite) |

### Configurar .env
```
TELEGRAM_BOT_TOKEN=seu_token_aqui
TELEGRAM_CHAT_ID=seu_chat_id_aqui
ANTHROPIC_API_KEY=sua_chave_aqui
```

Para descobrir o `TELEGRAM_CHAT_ID`: envie uma mensagem ao seu bot e acesse
`https://api.telegram.org/bot<SEU_TOKEN>/getUpdates` — o chat id aparece no campo `"id"`.

---

## Dashboard Web

Painel responsivo acessivel pelo navegador. Dark mode. Atualiza automaticamente a cada 30 segundos.

**Acesso:** `http://192.168.0.24:5000` ou `http://cryptobot.local:5000`

### Secoes do painel

| Secao | Descricao |
|---|---|
| **Barra de status** | RODANDO / PAUSADO + botoes Pausar/Retomar + horario |
| **Cards de capital** | Capital, retorno %, trades hoje e P&L — Paper, Agent, Pump |
| **Circuit Breaker** | Badge aparece no card quando limite diario e atingido |
| **Posicoes abertas** | Todas as posicoes dos sistemas com preco de entrada |
| **Trades de hoje** | Abas separadas com historico do dia |
| **Grafico P&L** | Linha acumulada dos ultimos 30 dias (Chart.js) |
| **Saude do sistema** | CPU, RAM, disco, temperatura, uptime |

### API JSON
```
GET http://192.168.0.24:5000/api/status    # Status completo
GET http://192.168.0.24:5000/api/trades    # Historico de trades
GET http://192.168.0.24:5000/api/logs      # Logs recentes
POST http://192.168.0.24:5000/pause        # Pausar bot
POST http://192.168.0.24:5000/resume       # Retomar bot
```

---

## Circuit Breaker

Protege o capital parando operacoes automaticamente quando os limites diarios sao atingidos.

**Gatilhos (qualquer um):**
- Perda acumulada no dia >= **5%** do capital inicial
- Numero de trades no dia >= **20**

**Comportamento:**
- Posicoes ja abertas continuam sendo gerenciadas (stop loss ativo)
- Nenhuma nova posicao e aberta
- Reset automatico a meia-noite
- Aparece no dashboard com badge "Circuit Breaker"
- **Envia alerta no Telegram** quando ativado (com dedup de 1 hora por sistema)
- Afeta cada sistema independentemente (paper, agent, pump)

---

## Relatorio Diario

Enviado automaticamente pelo Telegram todo dia apos meia-noite (entre 00:00 e 00:10).

Conteudo:
- Trades e P&L do dia para cada sistema
- Capital atual de cada sistema
- Posicoes abertas no momento
- Total consolidado

Pode ser solicitado a qualquer hora com `/relatorio`.

---

## Banco de Dados (bot.db)

SQLite com WAL mode — permite escrita simultanea segura de multiplos processos.

### Tabelas

| Tabela | Conteudo |
|---|---|
| `analysis_log` | Analise tecnica de cada ciclo: preco, SMA, RSI, score, decisao |
| `alerts` | Alertas enviados ao Telegram |
| `paper_trades` | Historico do paper trader com P&L |
| `agent_trades` | Historico do agent trader com SL, TP, confianca do Claude |
| `pump_trades` | Historico do pump trader com duracao e peak price |
| `scalping_trades` | Historico do scalping com motor, confluencia, parciais |

### Consultas uteis no Pi
```bash
cd ~/crypto_ai_bot

# Total de registros por tabela
sqlite3 bot.db "SELECT 'analysis_log', COUNT(*) FROM analysis_log
                UNION SELECT 'paper_trades', COUNT(*) FROM paper_trades
                UNION SELECT 'agent_trades', COUNT(*) FROM agent_trades
                UNION SELECT 'pump_trades', COUNT(*) FROM pump_trades
                UNION SELECT 'scalping_trades', COUNT(*) FROM scalping_trades;"

# Ultimos 10 trades do paper trader
sqlite3 bot.db "SELECT timestamp, symbol, type, pnl_pct, pnl_usd, exit_reason
                FROM paper_trades ORDER BY id DESC LIMIT 10;"

# P&L total acumulado
sqlite3 bot.db "SELECT 'paper', ROUND(SUM(pnl_usd),2) FROM paper_trades
                UNION SELECT 'agent', ROUND(SUM(pnl_usd),2) FROM agent_trades
                UNION SELECT 'pump',  ROUND(SUM(pnl_usd),2) FROM pump_trades;"

# Win rate geral
sqlite3 bot.db "SELECT COUNT(*) as total,
                SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins
                FROM paper_trades;"
```

---

## Gerenciamento do Bot no Pi

### Comandos systemd
```bash
sudo systemctl status cryptobot    # Ver status (PIDs dos 4 processos)
sudo systemctl start cryptobot     # Iniciar
sudo systemctl stop cryptobot      # Parar tudo
sudo systemctl restart cryptobot   # Reiniciar (apos atualizar codigo)
sudo systemctl is-enabled cryptobot # Verificar boot automatico
```

### Ver logs em tempo real
```bash
# Log principal (analise de mercado + paper + agent + scalping)
tail -f ~/crypto_ai_bot/logs/main_bot_$(date +%Y-%m-%d).log

# Log do pump scanner
tail -f ~/crypto_ai_bot/logs/pump_scanner_$(date +%Y-%m-%d).log

# Log do dashboard
tail -f ~/crypto_ai_bot/logs/dashboard_$(date +%Y-%m-%d).log

# Log do supervisor (restarts, crashes)
tail -f ~/crypto_ai_bot/logs/supervisor.log

# Logs do systemd (ultimas 50 linhas)
sudo journalctl -u cryptobot -n 50 --no-pager
```

### Verificar consumo de recursos
```bash
ps aux | grep python        # CPU e RAM dos processos
htop                        # Uso geral do sistema
df -h /                     # Espaco em disco
du -sh ~/crypto_ai_bot/bot.db  # Tamanho do banco
```

Ou use o comando `/saude` no Telegram para ver CPU, RAM, disco, temperatura e uptime.

### Pausa de emergencia (sem Telegram)
```bash
# Parar imediatamente
sudo systemctl stop cryptobot

# Ou pausar via arquivo (sem parar o processo)
echo '{"paused": true}' > ~/crypto_ai_bot/bot_control.json
```

---

## Servico systemd

O bot inicia automaticamente quando o Pi liga (apos conexao com a rede).

**Arquivo:** `/etc/systemd/system/cryptobot.service`

```ini
[Unit]
Description=Crypto AI Bot Supervisor
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/crypto_ai_bot
ExecStart=/home/pi/crypto_ai_bot/.venv/bin/python supervisor.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

---

## Deploy

### Via script automatico (recomendado)
```bash
# No Windows: commita, push, pull no Pi, reinicia servico
bash deploy.sh
```

### Manual via SCP
```bash
# Copiar arquivo especifico
scp arquivo.py pi@cryptobot.local:~/crypto_ai_bot/

# Reiniciar no Pi
ssh pi@cryptobot.local "sudo systemctl restart cryptobot"
```

---

## Deploy do Zero (em um Pi novo)

### Requisitos
- Raspberry Pi 4 com Raspberry Pi OS Lite 64-bit
- SSD ou cartao SD (SSD recomendado)
- Conexao com internet

### Passo a passo

**1. Preparar o sistema**
```bash
sudo apt update && sudo apt install -y python3-venv sqlite3
```

**2. Copiar o projeto para o Pi**
```bash
# No Windows (PowerShell ou Git Bash):
scp cryptobot.tar.gz pi@<IP>:~/
ssh pi@<IP> "mkdir -p ~/crypto_ai_bot && tar xzf ~/cryptobot.tar.gz -C ~/crypto_ai_bot && rm ~/cryptobot.tar.gz"
```

**3. Criar ambiente virtual e instalar pacotes**
```bash
cd ~/crypto_ai_bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**4. Configurar o .env**
```bash
nano ~/crypto_ai_bot/.env
```
```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
ANTHROPIC_API_KEY=...
```

**5. Inicializar o banco de dados**
```bash
cd ~/crypto_ai_bot
.venv/bin/python database.py
```

**6. Testar manualmente**
```bash
.venv/bin/python main.py
# Aguardar 1 ciclo e verificar saida
# CTRL+C para parar
```

**7. Instalar servico systemd**
```bash
sudo nano /etc/systemd/system/cryptobot.service
# (colar conteudo da secao acima)
sudo systemctl daemon-reload
sudo systemctl enable cryptobot
sudo systemctl start cryptobot
sudo systemctl status cryptobot
```

---

## Como Rodar (sem Pi)

```bash
# Instalar dependencias
pip install -r requirements.txt

# Configurar .env
# ANTHROPIC_API_KEY=...
# TELEGRAM_BOT_TOKEN=...
# TELEGRAM_CHAT_ID=...

# Rodar via supervisor (recomendado)
python supervisor.py

# Rodar apenas o bot principal
python main.py

# Rodar apenas o pump scanner
python pump_scanner.py

# Rodar backtest
python backtest.py

# Gerar relatorio diario manualmente
python daily_report.py
```
