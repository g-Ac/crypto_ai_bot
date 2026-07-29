# crypto_ai_bot

Bot em Python que analisa o mercado de criptomoedas, aplica regras de risco e simula operações — com alertas automáticos no Telegram. Roda continuamente em um Raspberry Pi 4.

> ⚠️ **Projeto de estudo.** Opera em modo de simulação (paper trading), sem dinheiro real. Não é recomendação de investimento.

## Como funciona

O fluxo é dividido em etapas independentes:

1. **Análise** — lê os dados de mercado (candles da Binance, funding, open interest, liquidações, basis) e avalia as condições
2. **Risco** — aplica as regras definidas para decidir se a operação é aceitável (position sizing, stop loss, take profit)
3. **Execução** — registra a operação simulada e dispara o alerta no Telegram

Três processos rodam em paralelo sob um supervisor: o loop principal (ciclo de 5 min), o scanner de pump/dump (ciclo de 60s sobre 50 moedas) e um dashboard web.

## Sistemas de trading

| Sistema | Status | Resultado acumulado |
|---|---|---|
| Pump Scanner | Ativo | +40,71% (133 trades) |
| Scalping | Ativo, em validação | +0,43% (14 trades) |
| Agent Trader | Desativado | −21,07% (40 trades) |
| Paper Trader | Desativado | −4,74% (4 trades) |

O scalping combina três motores de microestrutura — funding rate, cascata de liquidação + open interest, e basis spread — e só entra quando pelo menos 2 dos 3 concordam.

## O que eu aprendi

A parte mais útil do projeto não foi escrever estratégia, foi **desligar estratégia**. Dois dos quatro sistemas que construí deram resultado negativo em operação real simulada e foram desativados — o Agent Trader perdeu 21% em 40 trades, apesar de parecer sólido no papel.

Isso me obrigou a levar a sério a parte chata: registrar cada decisão em banco, montar funil de decisão para ver onde os sinais morriam, e construir um dashboard só para conseguir olhar os números sem me enganar. Backtest engana com facilidade; o que não engana é histórico persistido de trade a trade.

## Stack

- Python 3.13
- Raspberry Pi 4 (execução contínua via systemd)
- SQLite (modo WAL) para persistência
- Flask (dashboard web)
- Binance Futures API (fonte dos dados de mercado)
- API do Telegram (alertas e comandos)
- Anthropic API / Claude Haiku (gate de decisão por IA)
- pytest (~200 testes, rodados por hook de pre-push)

## Como rodar

```bash
# 1. Clone e crie o ambiente
git clone https://github.com/g-Ac/crypto_ai_bot.git ~/crypto_ai_bot
cd ~/crypto_ai_bot
python3 -m venv .venv
source .venv/bin/activate

# 2. Instale as dependências
pip install -r requirements.txt

# 3. Configure as variáveis de ambiente
cp .env.example .env
# edite o .env com suas credenciais

# 4. Execute
python supervisor.py
```

Para rodar um processo isolado durante o desenvolvimento: `python main.py`, `python pump_scanner.py` ou `python dashboard_server.py`.

## Configuração

Copie `.env.example` para `.env` e preencha:

```
BINANCE_API_KEY=          # apenas leitura — só dados de mercado
BINANCE_SECRET_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ANTHROPIC_API_KEY=
```

> 🔒 Nunca faça commit do arquivo `.env` — ele está no `.gitignore`.

## Dashboard e comandos

O dashboard sobe em `http://<ip-do-pi>:5000` com páginas de trades, curva de equity e funil de decisão do scalping.

Pelo Telegram: `/status`, `/posicoes`, `/capital`, `/performance`, `/saude`, `/pausar`, `/retomar`, `/relatorio`, `/ajuda`.

O bot também envia alertas proativos: drawdown ≥ 3% no dia, zero trades em 24h e erros repetidos na última hora.

## Testes

```bash
python -m pytest tests/ --tb=short -q   # suíte completa
bash ci.sh                              # pytest + py_compile
```

---

Feito por [Gabriel Caetano](https://www.linkedin.com/in/gabriel-caetano-040034305/)
