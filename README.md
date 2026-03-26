# Crypto AI Bot

Bot de trading automatico de criptomoedas rodando em Raspberry Pi 4.

## Sistemas de Trading

| Sistema | Descricao |
|---|---|
| **Paper Trader** | Algoritmico puro, sem IA. Testa a estrategia tecnica. |
| **Agent Trader** | Claude Haiku valida cada sinal antes de executar. |
| **Pump Scanner** | Detecta anomalias de volume e price action em 50 moedas. |

## Acesso

| Recurso | Endereco |
|---|---|
| Dashboard Web | http://192.168.0.24:5000 |
| SSH | `ssh pi@192.168.0.24` |

## Comandos Telegram

| Comando | Acao |
|---|---|
| `/status` | Resumo geral dos 3 sistemas |
| `/posicoes` | Posicoes abertas no momento |
| `/pausar` | Para de abrir novas posicoes |
| `/retomar` | Volta a operar normalmente |
| `/relatorio` | Relatorio do dia |
| `/ajuda` | Lista todos os comandos |

## Deploy

```bash
# Subir mudancas para o Pi
bash deploy.sh
```

O script commita, faz push para o GitHub, puxa no Pi e reinicia o servico automaticamente.

## Estrutura dos Arquivos

```
crypto_ai_bot/
├── main.py               # Loop principal
├── supervisor.py         # Gerencia os 3 processos
├── config.py             # Todos os parametros configuráveis
├── strategy.py           # Logica de sinais tecnicos
├── paper_trader.py       # Executor paper (algoritmico)
├── trade_agents.py       # Executor agent (Claude Haiku)
├── pump_scanner.py       # Scanner de pumps
├── pump_trader.py        # Executor pump
├── dashboard_server.py   # Dashboard Flask
├── telegram_commands.py  # Comandos bidirecionais
├── daily_report.py       # Relatorio diario + circuit breaker
├── database.py           # SQLite (bot.db)
├── templates/index.html  # Interface do dashboard
├── deploy.sh             # Script de deploy
└── GUIA.md               # Documentacao completa
```

## Gerenciamento no Pi

```bash
sudo systemctl status cryptobot    # Ver status
sudo systemctl restart cryptobot   # Reiniciar
sudo systemctl stop cryptobot      # Parar
journalctl -u cryptobot -f         # Ver logs em tempo real
```

## Documentacao Completa

Ver [GUIA.md](GUIA.md) para documentacao detalhada de todos os modulos, indicadores, config e deploy.
