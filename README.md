# Crypto AI Bot

Bot de trading automatico de criptomoedas rodando 24/7 em Raspberry Pi 4.
Combina analise tecnica classica, scalping de alta frequencia e IA (Claude Haiku)
para detectar oportunidades, simular trades e notificar em tempo real pelo Telegram.

**Todo o capital e virtual** — nenhum trade real e executado.

## Sistemas de Trading

| Sistema | Descricao | Capital |
|---|---|---|
| **Paper Trader** | Algoritmico puro — testa a estrategia tecnica sem IA | $10.000 |
| **Agent Trader** | Claude Haiku valida cada sinal antes de executar (3 agentes) | $10.000 |
| **Scalping** | 3 motores (Volume Breakout + RSI/BB Reversal + EMA Crossover) com confluencia | Integrado |
| **Pump Scanner** | Detecta anomalias de volume/preco em 50 moedas a cada 60s | $5.000 |

## Acesso

| Recurso | Endereco |
|---|---|
| Dashboard Web | `http://192.168.0.24:5000` ou `http://cryptobot.local:5000` |
| SSH | `ssh pi@192.168.0.24` |

## Comandos Telegram

| Comando | Acao |
|---|---|
| `/status` | Resumo geral dos 4 sistemas com formatacao rica |
| `/posicoes` | Posicoes abertas no momento |
| `/capital` | Capital detalhado por sistema com % desde inicio |
| `/performance` | Win rate, P&L e trades do dia |
| `/saude` | CPU, RAM, disco, temperatura do Pi, uptime |
| `/pausar` | Para de abrir novas posicoes |
| `/retomar` | Volta a operar normalmente |
| `/relatorio` | Relatorio completo do dia |
| `/ajuda` | Lista todos os comandos |

Mensagens com formatacao HTML, emojis por tipo de alerta, retry automatico e rate limiting.

## Deploy

```bash
# Subir mudancas para o Pi
bash deploy.sh
```

O script commita, faz push para o GitHub, puxa no Pi e reinicia o servico automaticamente.

## Estrutura dos Arquivos

```
crypto_ai_bot/
├── main.py               # Loop principal (5 min): analise + paper + agent + scalping
├── supervisor.py          # Gerencia os 3 processos + alertas Telegram de crash/restart
├── config.py              # Todos os parametros configuraveis
│
├── strategy.py            # Logica de sinais tecnicos (7 criterios, score 0-7)
├── indicators.py          # SMA9, SMA21, RSI14, volume, body ratio
├── htf.py                 # Tendencia de 1h para filtrar sinais
├── market.py              # Busca candles da API Binance
├── context_agent.py       # Interpretacao de sinais via Claude Haiku
│
├── paper_trader.py        # Executor paper (algoritmico puro)
├── trade_agents.py        # Executor agent (pipeline Claude: analista + risco + executor)
├── pump_scanner.py        # Scanner de pumps (processo independente)
├── pump_trader.py         # Executor pump (trailing stop + timeout)
│
├── scalping_trader.py     # Orquestrador do scalping (3 motores + confluencia)
├── volume_breakout.py     # Motor 1: breakout de volume anormal
├── rsi_bb_reversal.py     # Motor 2: reversao RSI + Bollinger Bands
├── ema_crossover.py       # Motor 3: cruzamento EMA com retest
├── confluence.py          # Score de confluencia (2/3 = medio, 3/3 = alto)
├── risk_manager.py        # Position sizing, SL/TP, alavancagem
├── signal_types.py        # Tipos de sinal padronizados
├── scalping_data.py       # Coleta de dados multi-timeframe
├── scalping_logger.py     # Logging do scalping
├── news_filter.py         # Filtro de noticias macro (FOMC, CPI, etc.)
│
├── telegram_notifier.py   # Envio HTML, retry, rate limiting, funcoes formatadas
├── telegram_commands.py   # 9 comandos bidirecionais
├── alert_control.py       # Deduplicacao de alertas
├── daily_report.py        # Relatorio diario + circuit breaker com notificacao
│
├── dashboard_server.py    # Dashboard Flask (porta 5000)
├── database.py            # SQLite WAL mode (bot.db)
├── backtest.py            # Backtesting historico
├── deploy.sh              # Script de deploy automatico
├── templates/index.html   # Interface do dashboard
├── estrategia.md          # Documentacao da estrategia de scalping
├── PROJETO.md             # Documentacao tecnica do projeto
└── GUIA.md                # Guia completo de uso e operacao
```

## Gerenciamento no Pi

```bash
sudo systemctl status cryptobot    # Ver status
sudo systemctl restart cryptobot   # Reiniciar
sudo systemctl stop cryptobot      # Parar
journalctl -u cryptobot -f         # Ver logs em tempo real
```

## Documentacao

| Arquivo | Conteudo |
|---|---|
| [GUIA.md](GUIA.md) | Guia completo: como funciona, config, deploy, comandos |
| [PROJETO.md](PROJETO.md) | Documentacao tecnica de todos os modulos e sistemas |
| [estrategia.md](estrategia.md) | Estrategia de scalping detalhada (3 motores) |
