# Segundo Cerebro — Analise Estrategica 07/04/2026

Data: 07 de abril de 2026, 23:35 UTC-3
Instancia: BASELINE | Git 096a745 | Capital total: $1.000 (resetado em 06/04)
Portfolio atual: $799.32 (-20.07%)

---

## 1. ACERTOS — O que esta funcionando

### Infraestrutura e operacao
A plaquinha esta saudavel. CPU 1.5%, RAM 19.9%, disco 7.3%, temperatura 38.5C, uptime estavel. Os 3 processos (main, pump_scanner, dashboard) estao vivos e o supervisor reinicia automaticamente em caso de crash. O deploy via deploy.sh funciona, o systemd gerencia tudo, e os logs rotativos evitam encher o disco. A base esta solida.

### Todos os 6 bugs criticos foram corrigidos
Verificacao no codigo atual confirma:
- C1: Scalping grava na tabela scalping_trades (nao mais em paper/agent)
- C2: Circuit breaker separado em check (read-only) e enforce (com alerta)
- C3: Scalping mapeado no circuit breaker ("scalping" -> "scalping_trades")
- C4: Posicoes gerenciadas mesmo com CB ativo (open_new=False)
- C5: Backtest sem look-ahead (sinal em candle i-1, entrada em candle i)
- C7: bandwidth_pct inicializado antes do uso

Isso e uma conquista grande — a base de codigo esta mais confiavel do que quando o melhorias.md foi escrito.

### Scalping experimental e o unico sistema positivo
2 trades, 2 wins, +0.16%. Amostra minuscula, mas e o unico sistema no verde. O funil mostra 810 ciclos avaliados, 806 bloqueados por confluencia, 2 abertos. O sistema e extremamente seletivo — quando abre, acerta.

### AI Gate do Agent esta filtrando bem
19 decisoes de IA, 6 aprovadas (31.6%). Claude Haiku esta rejeitando sinais com conflito de timeframe, volume fraco, e losing streak. O reasoning e de qualidade: "tendencia 5m alta mas sistema manda SELL — rejeite". Isso e exatamente o comportamento desejado. O problema nao e o filtro — e o que passa pelo filtro nao estar convertendo.

### Dashboard evoluiu muito
AI Brain tab, equity curve por sistema, system leaderboard, funil do scalping, validation audit, trade reviews, pattern memory. A observabilidade melhorou drasticamente desde o inicio do projeto.

### Arquitetura de handoffs bem documentada
17 handoffs com escopo claro, review checklist, regras para Claude Code. Isso manteve o projeto organizado e evitou refatoracoes soltas.

---

## 2. ERROS — O que esta quebrado

### ERRO CRITICO: Paper Trader colapsou (-69%)
Capital: $87.77 de $285.71 inicial. Circuit breaker ativo. Drawdown maximo de 61.48%.

Causa raiz identificada: quando o capital foi resetado manualmente de $10k para $285 no JSON da Pi, as posicoes abertas antigas (4 SHORTs de 25/03 com allocations de ~$2000 cada) provavelmente nao foram fechadas antes do reset. Quando essas posicoes bateram stop loss, a perda em dolares foi calculada sobre a allocation antiga (~$2000), nao sobre o capital novo ($285). Uma unica posicao perdendo 2% sobre $2000 = $40, que representa 14% do capital total de $285.

Licao: nunca editar JSON de estado manualmente. Precisa de um script que fecha posicoes, zera estado, e so entao ajusta capital.

### Agent com 0% win rate recente
3 trades, 3 losses. P&L: -$2.67. Claude Haiku esta aprovando com confidence reduzida (78%) e recomendando scalping rapido, mas os trades aprovados ainda perdem. O Agent esta sendo cauteloso (rejeitou 13 de 19 sinais), mas quando aprova, o mercado esta indo contra.

### Pump com 28.6% win rate
14 trades, 6 wins, 8 losses. P&L: -$0.53. Muitos micro trades em moedas pequenas (RED, TRU, NOM perdendo; ZEC, KITE, FET ganhando centavos). O pump esta gerando atividade mas nao lucro.

### Scalping ultra-seletivo (99.5% bloqueio)
806 de 810 ciclos bloqueados por confluencia. Apenas 2 aberturas. O modo experimental esta com force_entries=true e todos os filtros desligados, mas a confluencia dos 3 motores quase nunca alinha. Isso confirma o que o melhorias.md ja dizia: os filtros sao muito rigidos para as condicoes atuais de mercado.

### Capital muito pequeno para position sizing eficaz
$285 por sistema e insuficiente para absorver a volatilidade normal dos pares monitorados. Stop losses de 2-3% sobre posicoes pequenas geram P&L irrelevante, mas uma sequencia de losses acumula rapido.

---

## 3. DIAGNOSTICO — Onde esta o problema real

O projeto tem 3 camadas de problema, em ordem de importancia:

### Camada 1: Operacional (resolver AGORA)
O reset de capital foi mal executado. Posicoes antigas com sizing de $10k devastaram o Paper. Isso nao e problema de estrategia — e problema de operacao. Antes de avaliar qualquer estrategia, precisa de um estado limpo.

### Camada 2: Amostra insuficiente (aguardar)
Com apenas 23 trades totais (4 paper, 3 agent, 14 pump, 2 scalping), nenhuma conclusao estatistica e possivel. Win rate, profit factor, expectancy — tudo e ruido com essa amostra. O melhorias.md ja pedia "minimo 200 trades para analise". Estamos em 23.

### Camada 3: Calibracao de estrategia (so depois de dados)
Os parametros podem estar errados (confluencia muito rigida, SL muito apertado, etc.), mas so da pra saber com dados. Mudar parametros agora e chutar no escuro.

---

## 4. PLANO DE ACAO — O que fazer e em que ordem

### FASE 0: Parar a sangria (HOJE — 30 minutos)
1. Fechar as 2 posicoes abertas do Agent (ETH LONG -0.43%, DOGE LONG -0.38%) — aceitar a perda pequena antes que piore
2. Verificar se paper_state na Pi tem posicoes orfas — se tiver, fechar e resetar
3. Resetar paper_state para $285.71 com 0 posicoes, 0 trades, 0 wins/losses
4. Verificar pump_positions na Pi — limpar se necessario

### FASE 1: Criar script de reset seguro (ESTA SEMANA — 2 horas)
Criar reset_capital.py que:
- Faz backup do estado atual
- Fecha todas as posicoes abertas (registrando no banco como "manual_close")
- Zera contadores (trades, wins, losses, pnl)
- Define novo capital
- Valida que nao ficou nada orfao
- Nunca mais depender de edicao manual de JSON

### FASE 2: Deixar rodar e coletar dados (PROXIMOS 7-14 DIAS)
O bot precisa operar sem interferencia para gerar amostra.
Metas:
- Scalping: 30+ trades (hoje tem 2)
- Paper: 20+ trades (hoje tem 4)
- Agent: 15+ trades (hoje tem 3)
- Pump: continuar acumulando (ja tem 14)
Se o scalping continuar com 99.5% bloqueio, considerar:
- Reduzir confluencia minima de 2/3 para 1/3 (com size reduzido)
- Ou relaxar thresholds individuais dos motores

### FASE 3: Primeira analise com dados (APOS 50+ TRADES TOTAIS)
So entao avaliar:
- Win rate por sistema e por motor
- Expectancy (avg win * WR - avg loss * LR)
- Onde o funil do scalping bloqueia mais
- Se a IA do Agent adiciona ou subtrai edge
- Comparar paper (sem IA) vs agent (com IA) no mesmo periodo

### FASE 4: Ajustar estrategia com base em dados (APOS ANALISE)
Possibilidades:
- Se scalping e rentavel: concentrar capital nele
- Se IA nao ajuda: simplificar agent para algo puro
- Se pump nao funciona: pausar e redirecionar capital
- Se confluencia e muito rigida: ajustar thresholds gradualmente

---

## 5. DECISAO PENDENTE: O que fazer com o capital

Opcoes a considerar:

### Opcao A: Manter $1.000 dividido em 4 sistemas
Pro: testa todos os sistemas em paralelo
Contra: $285 e pouco para cada, position sizing fragil

### Opcao B: Concentrar em 2 sistemas ($500 cada)
Escolher Scalping + Agent (os mais sofisticados)
Pausar Paper e Pump temporariamente
Pro: mais capital por sistema, sizing melhor
Contra: perde dados dos sistemas pausados

### Opcao C: Aumentar capital total para $5.000
Manter a divisao em 4 mas com mais folga
Pro: sizing mais realista, absorve drawdowns melhor
Contra: mais capital virtual em risco de resultados ruins

Recomendacao: Opcao B. Scalping e o unico positivo e Agent tem a IA que queremos validar. Paper e redundante (Agent sem IA = Paper com IA desligada). Pump e independente e pode rodar com capital minimo.

---

## 6. ITENS DO MELHORIAS.MD — Status atualizado

### CRITICOS (C1-C7): TODOS CORRIGIDOS

### ALTOS — O que ainda falta
- A1: API Spot vs Futures — config.py ja tem USE_FUTURES_API=True, verificar se scalping_data usa
- A2: Dashboard auth — DASHBOARD_USER/PASS no .env (existe no config.py, verificar se esta configurado na Pi)
- A3: deploy.sh com git add -A — ainda pendente
- A4: Backtest com logica duplicada — verificar se backtest.py importa strategy.py
- A5: Backtest 180 dias — config.py ja tem BACKTEST_DAYS=180 (CORRIGIDO)
- A7: Pump max positions — config.py ja tem PUMP_MAX_POSITIONS=5 (CORRIGIDO)
- A8: Dump detection — config.py ja tem PUMP_DUMP_RETRACE_PCT=4.5 (CORRIGIDO)
- A9: Supervisor backoff — verificar supervisor.py
- A10: try/except no log_trade — verificar trade_agents.py
- A11: Scalping no /capital e relatorio — verificar daily_report.py

### MEDIOS — Para proximas sprints
- M1: Backtest scalping — backtest_scalping.py existe no projeto (verificar se funciona)
- M2: Backtest pump — backtest_pump.py existe no projeto (verificar se funciona)
- M5: Fallback do Claude aprova tudo — CRITICO para confianca na IA
- M7: SQLite sem context manager — risco de leak em erros

---

## 7. PERGUNTAS QUE O BOT PRECISA RESPONDER COM DADOS

Antes de qualquer mudanca grande, estas 3 perguntas (do melhorias.md) continuam validas:

1. Onde o scalping esta filtrando demais?
   Status: funil existe, mostra 99.5% bloqueio por confluencia. Falta detalhar QUAL motor falha.

2. Quando a IA aprova, isso melhora o resultado ou piora?
   Status: IA rejeitou 68% dos sinais. Dos 6 aprovados que viraram trade, 0% WR. Amostra muito pequena.

3. Qual versao de codigo e prompt gerou cada resultado?
   Status: ai_decisions registra modelo e prompt_version. Git SHA exposto no dashboard. Bom progresso.

---

## 8. RESUMO EXECUTIVO

O bot esta vivo e saudavel na plaquinha. A infraestrutura e solida. Os bugs criticos foram corrigidos. O problema imediato e operacional (reset de capital mal feito), nao estrategico. O caminho e: limpar o estado, deixar rodar, coletar dados, e so entao decidir. O scalping e o candidato mais promissor. A IA do Agent filtra bem mas os trades aprovados nao convertem — precisa de mais amostra para saber se e azar ou problema real.

Proximo passo concreto: executar a Fase 0 (limpar estado e posicoes orfas na Pi).
