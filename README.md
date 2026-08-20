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

Comecei achando que o projeto era sobre estratégia. Não era.

**Desligar custa mais que construir.** Dois dos quatro sistemas que escrevi deram resultado negativo e foram desativados — o Agent Trader perdeu 21% em 40 trades, apesar de parecer sólido no papel. Escrever a estratégia levou dias; admitir que ela não funcionava levou semanas.

**Para desligar, primeiro é preciso medir sem se enganar.** E medir foi a parte mais difícil. Backtest engana com facilidade — mostra o que você quer ver. O que não engana é histórico persistido: cada decisão gravada em banco, um funil que mostra onde os sinais morrem antes de virar trade, um registro de experimentos e um dashboard construído só para eu conseguir olhar os números de frente.

**Manter de pé é o trabalho de verdade.** A parte que mais consumiu tempo não aparece em nenhum gráfico: supervisor gerenciando três processos, systemd para sobreviver a reboot, ~200 testes rodando por hook antes de cada push, health check que aborta o deploy se um import quebrar, circuit breaker para o dia ruim não virar semana ruim. Um bot que roda 24/7 e precisa de babá não roda 24/7.

**A restrição de hardware melhorou as decisões.** Um Raspberry Pi 4 com menos de 4 GB não deixa margem para desperdício. Tentei trocar a chamada de API por um modelo local: compilei llama.cpp no Pi e comparei Qwen2.5-0.5B, TinyLlama e Phi-2 medindo latência, RAM e qualidade de saída, com fallback para a API se o modelo local falhasse. Sem espaço sobrando, cada escolha de arquitetura precisou ser justificada — o que, no fim, deixou o sistema melhor do que se eu tivesse servidor à vontade.

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
