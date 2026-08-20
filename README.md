# crypto_ai_bot

Bot em Python que analisa o mercado de criptomoedas, aplica regras de risco e simula operações — com alertas automáticos no Telegram. Rodou continuamente em um Raspberry Pi 4 de março a agosto de 2026.

> ⚠️ **Projeto encerrado em 12/08/2026.** Operou sempre em modo de simulação (paper trading), sem dinheiro real. Não é recomendação de investimento.
>
> O relatório final está em **[docs/POST_MORTEM.md](docs/POST_MORTEM.md)** — é o documento mais útil deste repositório.

## A pergunta e a resposta

O projeto tinha um objetivo declarado: **dá para construir uma fonte de renda automática operando cripto?**

Depois de 4,5 meses, 16 experimentos formais, 849+ hipóteses testadas e 7 julgamentos forward pré-registrados, a resposta foi **não** — e o número que resume melhor que qualquer outro:

| Estratégia | Retorno (16/04 → 02/08) | Max drawdown |
|---|---|---|
| Momentum Pullback v1.1 (o bot) | **−20,40%** | — |
| BTC buy-and-hold | −14,96% | — |
| ETH buy-and-hold | −19,77% | — |
| **50% BTC / 50% caixa** | **~−7,5%** | **~−15%** |

Uma carteira que qualquer pessoa monta em cinco minutos venceu quatro meses e meio de engenharia **nas duas dimensões** — mais retorno e menos drawdown. O bot ainda ficou 74,5% do tempo fora do mercado: assumiu o risco de estar errado sem capturar o prêmio de estar exposto.

Custou 4,5 meses e zero dinheiro real. A alternativa usual é descobrir a mesma coisa em três anos, com a conta no vermelho.

## Como funciona

O fluxo é dividido em etapas independentes:

1. **Análise** — lê os dados de mercado (candles da Binance, funding, open interest, liquidações, basis) e avalia as condições
2. **Risco** — aplica as regras definidas para decidir se a operação é aceitável (position sizing, stop loss, take profit)
3. **Execução** — registra a operação simulada e dispara o alerta no Telegram

Dois processos rodam em paralelo sob um supervisor: o loop principal (ciclo de 5 min) e um dashboard web. O scanner de pump/dump rodava como terceiro processo até ser aposentado.

## Sistemas de trading

Todos desligados. Nenhuma estratégia opera.

| Sistema | Trades | Status final |
|---|---|---|
| Momentum Pullback v1.1 | 299 | Desligado 12/08 — **última estratégia ativa** |
| Pump Scanner | 205 | Aposentado — resultado era cauda, não edge |
| Agent Trader | 40 | Desativado — perdeu 21% |
| Scalping | 14 | Aposentado — os 3 motores nunca convergiram |
| Paper Trader | 4 | Desativado |

**Sobre os números que você não vai encontrar aqui:** versões anteriores deste README exibiam "+40,71%" para o pump scanner. Esse tipo de número é a soma dos percentuais de cada trade, calculada **sem descontar taxa** — e superestima o retorno real. Foi só o momentum que ganhou instrumentação para medir o líquido, e o resultado explica o projeto inteiro:

| Momentum Pullback v1.1 | |
|---|---|
| Soma dos percentuais, bruto | **+3,48%** |
| Soma dos percentuais, líquido de taxa | **−26,42%** |
| Taxa acumulada | US$ 302,84 |
| Win rate líquido | 50,2% |

Taxa de 10 bps por round-trip contra um edge bruto de ~5 bps por trade: a corretora ganhava o dobro do que a estratégia gerava. E um win rate de 50,2% em 299 trades é o que se espera de uma moeda.

## O que eu aprendi

Comecei achando que o projeto era sobre estratégia. Não era.

**Desligar custa mais que construir.** Todos os sistemas que escrevi acabaram desativados — o Agent Trader perdeu 21% em 40 trades, apesar de parecer sólido no papel. Escrever a estratégia levava dias; admitir que ela não funcionava levava semanas.

**Para desligar, primeiro é preciso medir sem se enganar.** E medir foi a parte mais difícil. Backtest engana com facilidade — mostra o que você quer ver. O que não engana é histórico persistido: cada decisão gravada em banco (21.774 delas, com 32 campos de auditoria cada), um funil que mostra onde os sinais morrem antes de virar trade, um registro de experimentos e um dashboard construído só para eu conseguir olhar os números de frente.

**Manter de pé é o trabalho de verdade.** A parte que mais consumiu tempo não aparece em nenhum gráfico: supervisor gerenciando processos com backoff exponencial, systemd para sobreviver a reboot, testes rodando por hook antes de cada push, health check que aborta o deploy se um import quebrar, circuit breaker para o dia ruim não virar semana ruim. Um bot que roda 24/7 e precisa de babá não roda 24/7.

**A restrição de hardware melhorou as decisões.** Um Raspberry Pi 4 com menos de 4 GB não deixa margem para desperdício. Tentei trocar a chamada de API por um modelo local: compilei llama.cpp no Pi e comparei Qwen2.5-0.5B, TinyLlama e Phi-2 medindo latência, RAM e qualidade de saída, com fallback para a API se o modelo local falhasse. Sem espaço sobrando, cada escolha de arquitetura precisou ser justificada.

**A régua precisa ser fixada antes — e não pode ser mexida depois.** Essa é a lição que eu não esperava, e é a mais valiosa. Construí uma máquina de pré-registro: hipóteses congeladas com critério de aprovação definido *antes* de ver o resultado, julgadas automaticamente por cron na data marcada. Em 01/08, sete hipóteses foram julgadas e deram sete NO-GO. **Nenhuma foi relitigada.** O aparato funcionou contra quem o construiu — que é exatamente para isso que ele existe.

**E o desconforto final: a régua era cega.** Uma auditoria de poder estatístico feita depois descobriu que aqueles sete NO-GO não provaram ausência de efeito — provaram falta de resolução. As 28 criptos do painel são correlacionadas (ρ≈0,50) e estavam sendo contadas como independentes. Sob efeito verdadeiro zero, aquela régua produzia entre 6,5% e 27% de falso GO. O instrumento estava quebrado nas duas direções. Descobrir isso é a lição metodológica mais cara do projeto — e a razão de o post-mortem dizer que, se alguém voltar, deve consertar a régua antes de escrever qualquer linha de estratégia.

## O que sobrou de valor

O bot não sobreviveu. Duas outras coisas sim.

**Um dataset de microestrutura de cripto** (216 MB, ainda crescendo — a coleta continua ligada, custo operacional zero): liquidações tick-level, cadeia de opções histórica, funding, open interest, basis e long/short ratio, em 28 símbolos. Liquidação tick-level e cadeia de opções são caras de comprar.

**Um framework genérico de pré-registro e julgamento forward** — gerador de hipóteses, juiz versionado, livro-razão. Não tem nada de trading dentro dele: serve para qualquer contexto em que se queira testar uma hipótese sem se enganar.

## Stack

- Python 3.13
- Raspberry Pi 4 (execução contínua via systemd)
- SQLite (modo WAL) para persistência
- Flask (dashboard web)
- Binance Futures API (fonte dos dados de mercado)
- API do Telegram (alertas e comandos)
- Anthropic API / Claude Haiku (gate de decisão por IA)
- pytest — 1.445 testes em 99 arquivos, rodados por hook de pre-push

## Como rodar

O código está congelado, mas funciona. Com o trading desligado, sobe o dashboard e os coletores de dados.

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

Para rodar um processo isolado durante o desenvolvimento: `python main.py` ou `python dashboard_server.py`.

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

Trading permanece desligado por `MOMENTUM_TRADER_ENABLED=false`.

## Dashboard e comandos

O dashboard sobe em `http://<ip-do-pi>:5000` com páginas de trades, curva de equity e funil de decisão.

Pelo Telegram: `/status`, `/posicoes`, `/capital`, `/performance`, `/saude`, `/pausar`, `/retomar`, `/relatorio`, `/ajuda`.

## Testes

```bash
python -m pytest tests/ --tb=short -q   # suíte completa
bash ci.sh                              # pytest + py_compile
```

---

Feito por [Gabriel Caetano](https://www.linkedin.com/in/gabriel-caetano-040034305/)
