# Crypto AI Bot — Guia Completo

## Visao Geral

O Crypto AI Bot e um sistema automatizado de analise e simulacao de trading de criptomoedas.
Roda 24/7 em um Raspberry Pi 4, monitora 6 ativos na Binance a cada 5 minutos, detecta
oportunidades usando indicadores tecnicos e inteligencia artificial (Claude Haiku), simula
trades com capital virtual e notifica em tempo real pelo Telegram.

**Nao realiza trades reais** — todo o capital e virtual (paper trading).

### Ativos monitorados
`BTCUSDT` `ETHUSDT` `SOLUSDT` `BNBUSDT` `XRPUSDT` `DOGEUSDT`

### Hardware atual
- **Raspberry Pi 4 Model B Rev 1.5** — 4 GB RAM
- **SSD externo** — 110 GB (4.4 GB usados)
- **Python 3.13.5** | **Hostname:** `cryptobot.local`
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
supervisor.py  ← processo pai (PID principal do servico)
├── main.py          ← analise de mercado a cada 5 minutos
├── pump_scanner.py  ← scan de volume anormal a cada 60 segundos
└── dashboard_server.py ← painel web Flask na porta 5000
```

### Mapa de arquivos
```
crypto_ai_bot/
│
├── main.py              # Loop principal: analisa mercado, paper e agent trading
├── pump_scanner.py      # Detecta pumps no top 50 moedas por volume
├── supervisor.py        # Inicia e reinicia os 3 bots automaticamente
├── dashboard_server.py  # Painel web (Flask) na porta 5000
│
├── config.py            # Todas as constantes configuráveis
├── database.py          # Banco SQLite: init, inserts, queries
│
├── market.py            # Busca candles da API Binance
├── indicators.py        # SMA9, SMA21, RSI14, volume, body ratio
├── strategy.py          # Gera sinais BUY/SELL/HOLD (score 0-7)
├── htf.py               # Tendencia de 1h para filtrar sinais
├── context_agent.py     # Envia sinal ao Claude Haiku para interpretacao
│
├── paper_trader.py      # Paper trading: $10.000 virtual, gerencia stop loss
├── trade_agents.py      # Multi-agente: analista (Claude) + risco + executor
├── pump_trader.py       # Pump/dump: LONG no pump, SHORT no dump exausto
│
├── daily_report.py      # Relatorio diario Telegram + circuit breaker
├── alert_control.py     # Cooldown de alertas (evita spam)
├── telegram_notifier.py # Envia mensagens ao Telegram
├── telegram_commands.py # Recebe comandos do Telegram e responde
│
├── logger.py            # Salva analise no banco (analysis_log)
├── alert_logger.py      # Salva alertas no banco (alerts)
├── exporter.py          # Exporta analise para JSON
├── opportunity_exporter.py # Exporta oportunidades relevantes para JSON
│
├── backtest.py          # Backtesting historico nos 6 ativos
├── migrate_csv_to_db.py # Script de migracao: CSVs antigos -> bot.db
│
├── .env                 # Chaves de API (Telegram, Anthropic)
├── bot.db               # Banco de dados SQLite (criado automaticamente)
├── bot_control.json     # Estado de pausa (criado pelo /pausar)
├── paper_state.json     # Estado e capital do paper trader
├── agent_state.json     # Estado e capital do agent trader
├── pump_positions.json  # Posicoes abertas do pump trader
├── pump_cooldown.json   # Cooldown de alertas do pump scanner
│
├── logs/                # Logs diarios de cada processo
│   ├── supervisor.log
│   ├── main_bot_YYYY-MM-DD.log
│   ├── pump_scanner_YYYY-MM-DD.log
│   └── dashboard_YYYY-MM-DD.log
│
└── templates/
    └── index.html       # Template HTML do dashboard
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

### Pump Scanner (pump_scanner.py — a cada 60 segundos)
1. Busca os top 50 pares USDT por volume na Binance
2. Para cada ativo, compara volume atual com media de 20 velas
3. Se volume > 5x a media E variacao de preco > 2%: alerta de PUMP
4. Abre LONG automaticamente no pump detectado
5. Se pump exauriu (RSI > 80 + retrace): abre SHORT
6. Gerencia posicoes com trailing stop de 3% e timeout de 30 minutos

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
- Score >= 4: sinal forte → abre trade
- Score = 3 + diferenca >= 2: pre-sinal → alerta no Telegram
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
| `STOP_LOSS_PCT` | 1.5% | Stop loss padrao |
| `STOP_LOSS_MAP` | por ativo | Stop loss otimizado por backtesting |
| `DAILY_LOSS_LIMIT_PCT` | 5% | Circuit breaker: limite de perda diaria |
| `DAILY_MAX_TRADES` | 20 | Circuit breaker: maximo de trades/dia |
| `PUMP_VOLUME_MULTIPLIER` | 5x | Multiplo de volume para detectar pump |
| `PUMP_PRICE_CHANGE_MIN` | 2% | Variacao minima de preco para alerta |
| `PUMP_TRAILING_STOP` | 3% | Trailing stop das posicoes de pump |
| `PUMP_MAX_POSITION_TIME` | 30 min | Tempo maximo em posicao de pump |
| `PUMP_RSI_EXHAUSTION` | 80 | RSI acima disso = pump exaurindo |
| `BODY_RATIO_MIN` | 0.6 | Forca minima do candle para pontuar |

### Stop Loss otimizado por ativo (STOP_LOSS_MAP)
| Ativo | Stop Loss |
|---|---|
| BTCUSDT | 3.0% |
| ETHUSDT | 3.0% |
| SOLUSDT | 1.0% |
| BNBUSDT | 2.5% |
| XRPUSDT | 2.5% |
| DOGEUSDT | 1.0% |

---

## Comandos do Telegram

O listener de comandos inicia automaticamente com o bot e responde em tempo real.
Funciona enquanto o processo `main.py` estiver rodando.

| Comando | O que faz |
|---|---|
| `/status` | Mostra capital, trades e P&L dos 3 sistemas (paper, agent, pump) |
| `/posicoes` | Lista todas as posicoes abertas agora com preco de entrada |
| `/pausar` | Para abertura de novos trades (posicoes abertas continuam gerenciadas) |
| `/retomar` | Retoma operacao normal apos uma pausa |
| `/relatorio` | Envia o relatorio diario completo agora (nao espera meia-noite) |
| `/ajuda` | Lista todos os comandos disponiveis |

### Exemplos de resposta

**`/status`**
```
Status do Bot

--- Paper Trading ---
Capital: $9.962,64 (-0.37%)
Trades: 3 | W:1 L:2 | WR: 33.3%
Posicoes abertas: 2
  BTCUSDT: LONG @ 70982.88
  ETHUSDT: LONG @ 2173.13

--- Multi-Agent ---
[AGENTS] Capital: $9988.57 (-0.11%)
...
```

**`/pausar`**
```
Bot PAUSADO.
Posicoes abertas continuam gerenciadas (stop/timeout).
Nenhuma nova posicao sera aberta.
Use /retomar para voltar.
```

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
| **Barra de status** | RODANDO / PAUSADO + botoes Pausar/Retomar + horario da ultima atualizacao |
| **Cards de capital** | Capital atual, retorno total (%), trades hoje e P&L hoje — Paper, Agent e Pump |
| **Circuit Breaker** | Badge laranja aparece no card quando o limite diario e atingido |
| **Posicoes abertas** | Todas as posicoes dos 3 sistemas com preco de entrada |
| **Trades de hoje** | Abas separadas para Paper, Agent e Pump com historico do dia atual |
| **Grafico P&L** | Linha acumulada dos ultimos 30 dias para cada sistema (Chart.js) |

### Botoes de controle
- **Pausar** — equivalente ao `/pausar` do Telegram
- **Retomar** — equivalente ao `/retomar` do Telegram

### API JSON
Para integracoes externas:
```
GET http://192.168.0.24:5000/api/status
```
Retorna JSON com capital, posicoes, trades do dia e dados do grafico.

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
- Aparece no dashboard com badge vermelho "Circuit Breaker"
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

### Consultas uteis no Pi
```bash
cd ~/crypto_ai_bot

# Total de registros por tabela
sqlite3 bot.db "SELECT 'analysis_log', COUNT(*) FROM analysis_log
                UNION SELECT 'paper_trades', COUNT(*) FROM paper_trades
                UNION SELECT 'agent_trades', COUNT(*) FROM agent_trades
                UNION SELECT 'pump_trades', COUNT(*) FROM pump_trades;"

# Ultimos 10 trades do paper trader
sqlite3 bot.db "SELECT timestamp, symbol, type, pnl_pct, pnl_usd, exit_reason
                FROM paper_trades ORDER BY id DESC LIMIT 10;"

# P&L total acumulado
sqlite3 bot.db "SELECT 'paper', ROUND(SUM(pnl_usd),2) FROM paper_trades
                UNION SELECT 'agent', ROUND(SUM(pnl_usd),2) FROM agent_trades
                UNION SELECT 'pump',  ROUND(SUM(pnl_usd),2) FROM pump_trades;"

# Taxa de acerto
sqlite3 bot.db "SELECT COUNT(*) as total,
                SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins
                FROM paper_trades;"
```

---

## Gerenciamento do Bot no Pi

### Comandos systemd
```bash
# Ver status (mostra se esta rodando e os 4 PIDs)
sudo systemctl status cryptobot

# Iniciar
sudo systemctl start cryptobot

# Parar tudo
sudo systemctl stop cryptobot

# Reiniciar (apos atualizar codigo)
sudo systemctl restart cryptobot

# Ver se inicia no boot
sudo systemctl is-enabled cryptobot
```

### Ver logs em tempo real
```bash
# Log principal (analise de mercado)
tail -f ~/crypto_ai_bot/logs/main_bot_$(date +%Y-%m-%d).log

# Log do pump scanner
tail -f ~/crypto_ai_bot/logs/pump_scanner_$(date +%Y-%m-%d).log

# Log do dashboard
tail -f ~/crypto_ai_bot/logs/dashboard_$(date +%Y-%m-%d).log

# Log do supervisor (restarts, erros)
tail -f ~/crypto_ai_bot/logs/supervisor.log

# Logs do systemd (ultimas 50 linhas)
sudo journalctl -u cryptobot -n 50 --no-pager
```

### Atualizar o codigo
```bash
# No Windows: editar os arquivos, depois transferir para o Pi:
scp arquivo.py pi@cryptobot.local:~/crypto_ai_bot/
sudo systemctl restart cryptobot
```

### Verificar consumo de recursos
```bash
# CPU e RAM dos processos
ps aux | grep python

# Uso geral do sistema
htop

# Espaco em disco
df -h /

# Tamanho do banco de dados
du -sh ~/crypto_ai_bot/bot.db
```

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

## Deploy do Zero (em um Pi novo)

### Requisitos
- Raspberry Pi 4 com Raspberry Pi OS Lite 64-bit
- SSD ou cartao SD (SSD recomendado — mais duravel para escrita continua)
- Conexao com internet

### Passo a passo

**1. Preparar o sistema**
```bash
sudo apt update && sudo apt install -y python3-venv
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
.venv/bin/pip install pandas ta anthropic
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
# Se tiver dados antigos em CSV:
.venv/bin/python migrate_csv_to_db.py
```

**6. Testar manualmente**
```bash
.venv/bin/python main.py
# Aguardar 1 ciclo (~2 min) e verificar saida
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

## Referencia dos Modulos

| Modulo | Funcoes principais |
|---|---|
| `database.py` | `init_db()`, `insert_analysis_log()`, `insert_alert()`, `insert_paper_trade()`, `insert_agent_trade()`, `insert_pump_trade()`, `get_trades_today()`, `get_recent_trades()`, `get_cumulative_pnl()` |
| `market.py` | `get_candles(symbol, interval, limit)` |
| `indicators.py` | `add_indicators(df)` |
| `strategy.py` | `generate_signal(df, htf_trend)` |
| `htf.py` | `get_htf_trend(symbol)` |
| `paper_trader.py` | `process_signals(results)`, `get_status()` |
| `trade_agents.py` | `orchestrate(results)`, `get_agent_status()` |
| `pump_trader.py` | `open_position()`, `check_positions()`, `check_dump_entry()`, `get_status()` |
| `telegram_notifier.py` | `send_telegram_message(text)` |
| `telegram_commands.py` | `is_paused()`, `start_command_listener()` |
| `daily_report.py` | `is_circuit_broken(system)`, `generate_report()`, `calc_daily_stats(trades)`, `get_open_positions()`, `get_capital_status()` |
| `dashboard_server.py` | Flask app — rotas `/`, `/api/status`, `/pause`, `/resume` |
| `supervisor.py` | Inicia e monitora main.py, pump_scanner.py, dashboard_server.py |
| `backtest.py` | Backtesting historico com dados da Binance |
| `alert_control.py` | `should_send_alert(data)` — controle de cooldown |
| `context_agent.py` | `interpret_signal(result)` — interpretacao via Claude Haiku |
