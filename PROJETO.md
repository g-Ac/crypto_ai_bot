# Crypto AI Bot — Documentação do Projeto

## Ideia Principal

Bot de análise e simulação de trades em criptomoedas que roda de forma autônoma,
combinando análise técnica clássica com IA (Claude) para validar sinais e gerar
interpretações em português. Opera em modo paper (sem dinheiro real), registra
tudo em CSV/JSON e envia alertas pelo Telegram.

---

## Ativos Monitorados

| Ativo     | Stop Loss configurado |
|-----------|-----------------------|
| BTCUSDT   | 3.0%                  |
| ETHUSDT   | 3.0%                  |
| SOLUSDT   | 1.0%                  |
| BNBUSDT   | 2.5%                  |
| XRPUSDT   | 2.5%                  |
| DOGEUSDT  | 1.0%                  |

Timeframe principal: **5 minutos** | Timeframe de confirmação: **1 hora**

---

## Funcionalidades Atuais

### 1. Análise Técnica (`indicators.py` + `strategy.py`)
Calcula 7 critérios a cada ciclo (5 min) por ativo:

| Critério              | Detalhe                                      |
|-----------------------|----------------------------------------------|
| Tendência SMA         | SMA9 vs SMA21                                |
| Posição do preço      | Acima/abaixo das duas médias                 |
| Direção das SMAs      | Ambas subindo ou ambas caindo                |
| Zona do RSI (14)      | Buy zone: 30-45 / Sell zone: 55-70           |
| Breakout              | Rompeu máxima ou mínima das últimas 10 velas |
| Volume + Breakout     | Confirmação de volume acima da média (20)    |
| Body ratio do candle  | Força do candle na direção do sinal          |

Score mínimo para sinal: **4/7**. Resultado: `BUY`, `SELL` ou `HOLD`.

### 2. Filtro de Tendência HTF (`htf.py`)
Consulta o gráfico de 1h antes de confirmar o sinal.
Sinais contra a tendência do 1h são bloqueados (viram `HOLD`).

### 3. Score de Confiança e Prioridade (`strategy.py`)
- `confidence_score` (0–100): mede o alinhamento dos indicadores
- `priority_score` (0–100): determina se o alerta vai para o Telegram
- Threshold de alerta: priority ≥ 85 ou tipo `sinal`

### 4. Interpretação por IA (`context_agent.py`)
Usa **Claude Haiku** para gerar um comentário de 4 linhas em português
explicando por que o sinal faz (ou não faz) sentido antes de enviar o alerta.

### 5. Alertas via Telegram (`telegram_notifier.py` + `alert_control.py`)
- Envia o sinal mais relevante do ciclo
- Controle de deduplicação: só reenvia se o símbolo, tipo ou prioridade mudar
- Formato: símbolo + decisão + confiança + interpretação da IA

### 6. Paper Trading (`paper_trader.py`)
Simulação de trades com capital virtual de **$10.000**:
- Abre LONG/SHORT ao receber sinal BUY/SELL
- Fecha por sinal contrário ou stop loss por ativo
- Registra cada trade em `paper_trades.csv`
- Exibe win rate, P&L e posições abertas a cada ciclo

### 7. Multi-Agent Trading (`trade_agents.py`)
Pipeline de 3 agentes com capital virtual separado de **$10.000**:

```
Sinal BUY/SELL
     │
     ▼
[Agente 1 - Analista] → Claude Haiku valida o sinal
     │ aprovado?
     ▼
[Agente 2 - Risco]    → Calcula position size (ATR-based), SL e TP (RR 2:1)
     │ aprovado?
     ▼
[Agente 3 - Executor] → Registra a posição e loga o trade
```

- Máximo de 3 posições simultâneas
- Position sizing: risco de 2% do capital por trade
- SL baseado em ATR (ou configuração por ativo, o maior)
- Ajuste de tamanho pela confiança do analista (<70% → 50% do size)

### 8. Pump Scanner (`pump_scanner.py` + `pump_trader.py`)
Processo independente que roda a cada **60 segundos**:
- Monitora as **top 50 moedas** por volume na Binance
- Detecta: volume ≥ 5x a média E variação ≥ 2% (1 candle) ou ≥ 4% (3 candles)
- Abre LONG em pump, SHORT em dump
- Trailing stop de 3% a partir do pico
- Timeout de 30 minutos por posição
- Cooldown de 30 minutos por ativo após alerta

### 9. Circuit Breaker (`daily_report.py`)
Para operações automaticamente se, no dia:
- Perda acumulada ≥ 5% — ou —
- Número de trades ≥ 20

Funciona nos 3 sistemas independentemente (paper, agent, pump).

### 10. Relatório Diário (`daily_report.py`)
Envia automaticamente via Telegram após meia-noite:
- P&L do dia por sistema (paper / multi-agent / pump)
- Win rate, número de trades, wins e losses
- Capital atual de cada sistema
- Posições abertas no momento

### 11. Backtest (`backtest.py`)
Executa a estratégia sobre dados históricos (30 dias por padrão):
- Busca dados da Binance via API (sem limite de velas)
- Usa SL por candle extremo (mais realista)
- Métricas: win rate, retorno total, max drawdown, profit factor
- Separação HTF-alinhado vs contra-HTF
- Exporta resultados para `backtest_{SIMBOLO}.csv`

### 12. Supervisor (`supervisor.py`)
Gerencia `main.py` e `pump_scanner.py` como processos separados:
- Reinicia automaticamente em caso de crash
- Limite de 50 restarts por bot
- Log por arquivo diário em `logs/`

---

## Fluxo de Execução (ciclo de 5 min)

```
Para cada ativo (BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, DOGEUSDT):
  1. Busca 100 velas de 5m na Binance
  2. Calcula indicadores (SMA, RSI, breakout, volume, body ratio)
  3. Busca tendência do 1h
  4. Gera sinal + scores

Pós-análise:
  5. Exporta JSON de análise e oportunidades
  6. Seleciona o TOP 1 do ciclo
  7. Se priority ≥ 85 ou tipo=sinal → Claude interpreta → envia Telegram
  8. Circuit breaker? → Paper Trading
  9. Circuit breaker? → Multi-Agent Trading
  10. Verifica horário → Relatório diário
```

---

## Stack Técnica

| Componente      | Tecnologia                            |
|-----------------|---------------------------------------|
| Linguagem       | Python 3.11                           |
| Dados de mercado| Binance REST API (público, sem chave) |
| Indicadores     | `ta` (Technical Analysis Library)    |
| Processamento   | `pandas`, `numpy`                     |
| IA              | Anthropic Claude Haiku (claude-haiku-4-5-20251001) |
| Notificações    | Telegram Bot API                      |
| Persistência    | JSON (estado) + CSV (histórico)       |
| Dashboard       | React + Vite + TypeScript (em desenvolvimento) |

---

## Arquivos de Estado

| Arquivo                  | Conteúdo                              |
|--------------------------|---------------------------------------|
| `paper_state.json`       | Capital e posições do paper trader    |
| `agent_state.json`       | Capital e posições do multi-agent     |
| `pump_positions.json`    | Posições abertas do pump trader       |
| `last_alert.json`        | Último alerta enviado (deduplicação)  |
| `pump_cooldown.json`     | Cooldown por ativo no pump scanner    |
| `technical_analysis.json`| Última análise completa de todos os ativos |
| `relevant_opportunities.json` | Oportunidades filtradas do ciclo |
| `log.csv`                | Histórico de todas as análises        |
| `alerts.csv`             | Histórico de alertas gerados          |
| `paper_trades.csv`       | Histórico de trades do paper trader   |
| `agent_trades.csv`       | Histórico de trades do multi-agent    |
| `pump_trades.csv`        | Histórico de trades do pump scanner   |

---

## Próximas Atualizações

### Prioridade Alta — Correções de Bugs

- [ ] **Cálculo de alocação no paper_trader**
  Guardar o valor alocado na abertura da posição (como o multi-agent já faz),
  em vez de recalcular no fechamento com base no capital atual.

- [ ] **Circuit breaker com % real de capital**
  Substituir a soma de percentuais por um cálculo baseado no capital inicial
  do dia para medir a perda diária com precisão.

- [ ] **Tratamento de erro por símbolo no main loop**
  Envolver cada símbolo em `try/except` individual para que uma falha de API
  em um ativo não cancele a análise dos outros.

- [ ] **Delay em retries de erro HTTP no `market.py`**
  Adicionar `time.sleep(2)` também nos erros HTTP (não só em exceções),
  especialmente para o erro 429 de rate limit.

### Prioridade Média — Melhorias de Estratégia

- [ ] **Take Profit no paper_trader**
  Definir um alvo de saída (ex: 2x o SL) para que posições vencedoras
  não revertam para loss antes do sinal contrário chegar.

- [ ] **HTF com análise mais rica**
  Complementar a tendência do 1h com price action (preço acima/abaixo de SMA longa,
  inclinação da SMA200) para um filtro HTF mais robusto.

- [ ] **Eliminar duplicação strategy.py / backtest.py**
  Fazer o backtest importar e chamar `generate_signal` diretamente
  em vez de manter uma cópia manual da lógica.

- [ ] **Cooldown por tempo no `alert_control.py`**
  Adicionar janela mínima de X minutos entre alertas do mesmo ativo,
  independentemente de mudança de prioridade.

### Prioridade Média — Novas Funcionalidades

- [ ] **Dashboard web funcional**
  Conectar o React (`dashboard/`) à análise em tempo real via
  WebSocket ou polling do `technical_analysis.json`.
  Exibir: sinais ao vivo, posições abertas, equity curve, histórico.

- [ ] **Relatório semanal/mensal**
  Expandir o `daily_report.py` para enviar resumos semanais e mensais
  com métricas acumuladas de todos os sistemas.

- [ ] **Notificação de circuit breaker ativo**
  Enviar alerta no Telegram quando o circuit breaker for ativado,
  informando qual sistema parou e o motivo (perda ou limite de trades).

- [ ] **Backtest automático periódico**
  Rodar o backtest semanalmente e logar se o desempenho piorou,
  servindo como aviso de degradação da estratégia.

### Prioridade Baixa — Qualidade de Código

- [ ] **Reduzir verbosidade do Telegram notifier**
  Remover os prints de status code e corpo da resposta do Telegram,
  ou movê-los para nível DEBUG.

- [ ] **Race condition no relatório diário**
  Usar um arquivo de lock ou verificação atômica para garantir que
  `main.py` e `pump_scanner.py` não enviem o relatório em duplicata.

- [ ] **Corrigir labels do prompt no `context_agent.py`**
  Trocar `SMA X / SMA Y` por `SMA9: X / SMA21: Y` para que
  o Claude saiba qual é qual.

- [ ] **Cleanup de código morto no `pump_trader.py`**
  Remover condições ternárias redundantes que sempre resultam
  no mesmo valor (`price if X else price`).

---

## Como Rodar

```bash
# Instalar dependências
pip install -r requirements.txt

# Configurar variáveis de ambiente no .env
ANTHROPIC_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Rodar via supervisor (recomendado — reinicia automaticamente)
python supervisor.py

# Rodar apenas o bot principal
python main.py

# Rodar apenas o pump scanner
python pump_scanner.py

# Rodar backtest
python backtest.py

# Gerar relatório diário manualmente
python daily_report.py
```
