# Melhorias Planejadas — Crypto AI Bot

Auditoria completa realizada em 31/03/2026 por 4 agentes especializados:
Scalping Strategy, Trading Validation, Ops Safety, Backtest Robustness.

---

## OBJETIVO DESTE ARQUIVO

Este documento passa a ser a fonte central para decidir:

1. O que precisa ser corrigido antes de escalar o bot
2. Quais metricas precisam existir antes de mexer pesado em IA
3. Qual e a ordem de construcao para evitar retrabalho

Escopo desta versao:
- integridade de dados
- robustez de estrategia
- observabilidade
- seguranca operacional
- uso de IA no agent trader e no scalping

---

## SNAPSHOT ATUAL — 31/03/2026

Observacoes confirmadas no ambiente atual:

- O dashboard da plaquinha esta saudavel e o bot esta rodando normalmente
- O scalping nao esta pausado nem com circuit breaker visualmente ativo
- Hoje o scalping fez `0` trades
- Os logs do scalping mostram que o sistema esta vivo, mas os filtros estao muito rigidos:
  - volume frequentemente abaixo de `2.5x`
  - RSI frequentemente fora das zonas extremas de reversao
  - EMA frequentemente bloqueada por mercado choppy
  - varios casos de `1/3` de confluencia sem seguir adiante
- O dashboard remoto nao expoe commit, SHA, versao de prompt nem assinatura de build

Leitura pratica:

- O problema de hoje nao parece ser crash
- O problema principal parece ser combinacao de rigidez + pouca observabilidade para entender onde o funil esta matando os trades
- Antes de "aumentar IA", precisamos medir exatamente o funil do scalping

---

## METRICAS OBRIGATORIAS ANTES DA CONSTRUCAO

Estas metricas devem existir no proprio sistema antes de qualquer refatoracao grande de IA.

### Metrica 1. Funil de decisao do scalping
Registrar por ciclo e por simbolo:

- candles buscados com sucesso
- bloqueado por cooldown
- bloqueado por max positions
- score de confluencia 0, 1, 2, 3
- bloqueado por risco
- bloqueado por noticia
- bloqueado por funding
- bloqueado por BB bandwidth
- bloqueado por ATR elevado
- aprovado para abertura

Objetivo: responder com numero, e nao por intuicao, em qual etapa o setup esta morrendo.

### Metrica 2. Qualidade de entrada
Para cada trade aberto:

- motor principal
- score de confluencia
- RR planejado
- sl_distance_pct
- leverage
- position_size_usd
- tempo ate TP1, TP2 ou SL
- MAE e MFE
- PnL final

Objetivo: descobrir se os trades aprovados sao bons de verdade ou apenas raros.

### Metrica 3. Efetividade da IA
Para cada decisao com IA:

- modelo usado
- versao do prompt
- latencia
- custo estimado
- resposta parseada com sucesso ou fallback
- approved / rejected
- confianca retornada
- resultado final do trade aprovado
- resultado contrafactual quando possivel (o que teria acontecido sem IA)

Objetivo: provar se a IA adiciona edge ou apenas custo e atraso.

### Metrica 4. Robustez de estrategia
Obrigatorio acompanhar:

- win rate
- profit factor
- expectancy por trade
- max drawdown
- retorno composto
- sharpe simplificado ou retorno por unidade de drawdown
- amostra total de trades
- resultados por regime de mercado
- resultados in-sample vs out-of-sample

Objetivo: parar de avaliar estrategia so por win rate ou retorno bruto.

### Metrica 5. Saude operacional
Medir continuamente:

- tempo medio do ciclo
- taxa de erro por modulo
- uptime por processo
- numero de retries de API
- falhas de banco
- uso de CPU, RAM e disco
- divergencia entre estado em JSON e banco

Objetivo: separar bug operacional de fraqueza de estrategia.

### Metrica 6. Rastreabilidade de versao
Toda execucao deveria expor:

- git SHA
- data de build/deploy
- versao do prompt do agent trader
- versao do prompt do validador scalping
- modelo atual de cada etapa

Objetivo: nunca mais depender de inferencia visual para saber o que esta rodando na plaquinha.

---

## DIRECAO RECOMENDADA PARA IA

### Recomendacao principal
Nao migrar para um sistema 100% IA agora.

### Motivo
Hoje faltam:

- dataset historico estruturado de decisoes
- baseline confiavel do scalping
- metricas de aprovacao/rejeicao por IA
- infraestrutura para comparar versoes de modelo/prompt

Sem isso, um sistema 100% IA ficaria mais opaco, mais caro e mais dificil de depurar.

### Caminho mais forte
Usar IA como camada de decisao incremental sobre um nucleo sistematico:

- sistema por regras gera features e candidatos
- IA entra como ranker ou validador nos casos borderline
- cada decisao da IA fica logada com contexto e resultado
- depois comparar `algo puro` vs `algo + IA`

### Primeiro experimento de IA que faz sentido
Enviar casos `1/3 forte` e `2/3` para um modelo mais forte via API, com payload estruturado contendo:

- features dos 3 motores
- contexto 15m
- ATR
- funding
- distancia do SL
- RR
- regime recente

Resposta desejada:

- `approved`
- `confidence`
- `size_multiplier`
- `reason`

Isso reduz rigidez sem perder governanca.

---

## CRITICO — Corrigir Imediatamente

Bugs que causam dados errados, metricas contaminadas ou comportamento perigoso.

### C1. Scalping grava trades nas tabelas erradas
**Arquivo:** `scalping_trader.py` linhas 197, 268
**Problema:** Trades de fechamento do scalping vao para `paper_trades` e de abertura para `agent_trades`. Contamina metricas, win rate, P&L e circuit breaker de outros sistemas.
**Correcao:** Criar `insert_scalping_trade()` em `database.py` e usar tabela `scalping_trades` dedicada. Alterar `scalping_trader.py` para chamar a funcao correta.
**Esforco:** Baixo

### C2. Circuit breaker envia alerta Telegram pelo dashboard
**Arquivo:** `daily_report.py` linhas 255-278, `dashboard_server.py` linhas 597-599
**Problema:** `is_circuit_broken()` tem side effect de enviar alerta. Quando o dashboard chama para exibir status, dispara alerta no Telegram a cada refresh (mitigado por dedup de 1h, mas conceptualmente errado).
**Correcao:** Separar em `check_circuit_breaker(system)` (read-only, para dashboard) e `enforce_circuit_breaker(system)` (com alerta, para main loop).
**Esforco:** Baixo

### C3. Scalping sem circuit breaker
**Arquivo:** `daily_report.py` linhas 241-250
**Problema:** `is_circuit_broken("scalping")` cai no `else: return False`. O scalping opera sem limite de perda diaria.
**Correcao:** Adicionar mapeamento `"scalping": "scalping_trades"` no dict de tabelas. Depende de C1 estar resolvido.
**Esforco:** Minimo (2 linhas)

### C4. Posicoes agent/paper abandonadas com circuit breaker ativo
**Arquivo:** `main.py` linhas 152-173
**Problema:** Quando circuit breaker ou pausa esta ativo, `orchestrate()` e `process_signals()` nao sao chamados. Mas sao eles que verificam SL/TP das posicoes abertas. Posicoes ficam sem gerenciamento.
**Correcao:** Separar `check_positions()` do fluxo de abertura. Sempre gerenciar posicoes abertas, mesmo com circuit breaker.
**Esforco:** Medio

### C5. Look-ahead bias no backtest
**Arquivo:** `backtest.py` linha 85
**Problema:** O sinal e gerado com dados do candle corrente (close) e a entrada acontece no mesmo candle. Em producao, o sinal usa o candle fechado e a entrada e no proximo.
**Correcao:** Gerar sinal com candle `i-1`, entrar no `open` do candle `i`.
**Esforco:** Medio

### C6. Backtest sem fees
**Arquivo:** `backtest.py`
**Problema:** Nenhuma taxa de trading aplicada. Binance Spot: 0.1%/lado = 0.2% round trip. Em 100 trades, ~20% de retorno fantasma.
**Correcao:** Subtrair 0.2% do `pnl_pct` de cada trade.
**Esforco:** Minimo (1 linha)

### C7. NameError em rsi_bb_reversal.py
**Arquivo:** `rsi_bb_reversal.py` linha 373
**Problema:** Variavel `bandwidth_pct` referenciada no metadata mas nunca definida se `bb_bandwidth` for NaN. Crash em runtime.
**Correcao:** Inicializar `bandwidth_pct = 0.0` antes do bloco de filtros.
**Esforco:** Minimo (1 linha)

---

## ALTO — Resolver em Breve

Problemas que distorcem metricas ou criam riscos operacionais.

### A1. Scalping usa API Spot em vez de Futures
**Arquivo:** `scalping_data.py` linha 58
**Problema:** Usa `api.binance.com/api/v3/klines` (Spot). A estrategia e para Futuros USDT-M (`fapi.binance.com/fapi/v1/klines`). Precos podem divergir.
**Correcao:** Adicionar parametro configurable para endpoint. Default para Futures.
**Esforco:** Baixo

### A2. Dashboard sem autenticacao
**Arquivo:** `dashboard_server.py` linha 839
**Problema:** Flask roda em `0.0.0.0:5000` sem auth. Qualquer dispositivo na rede (ou Tailscale) pode pausar/retomar o bot via POST.
**Correcao:** Adicionar HTTP Basic Auth com `flask-httpauth`. ~5 linhas.
**Esforco:** Baixo

### A3. deploy.sh com `git add -A` e pull sem verificacao
**Arquivo:** `deploy.sh` linhas 12, 29-33
**Problema:** `git add -A` pode commitar arquivos indesejados. `git pull` pode ter conflito e o restart roda mesmo assim.
**Correcao:** Usar lista explicita de arquivos no add. Usar `git pull --ff-only`. Verificar resultado antes do restart.
**Esforco:** Baixo

### A4. Backtest com logica duplicada do strategy.py
**Arquivo:** `backtest.py` linhas 77-180
**Problema:** Reimplementa toda a logica de `strategy.py` em `signal_for_row()`. Qualquer mudanca futura gera divergencia silenciosa.
**Correcao:** Importar e chamar `generate_signal()` de `strategy.py` diretamente.
**Esforco:** Medio

### A5. Backtest de apenas 30 dias
**Arquivo:** `config.py` linha 33
**Problema:** 30 dias cobre ~1 regime de mercado. Insuficiente para validacao estatistica.
**Correcao:** Aumentar para 180 dias minimo (idealmente 365).
**Esforco:** Minimo (mudar config)

### A6. STOP_LOSS_MAP overfitted in-sample
**Arquivo:** `config.py` linhas 37-44
**Problema:** SL por ativo "otimizado via backtest" em 30 dias = overfitting puro. SOL com 1% e BTC com 3% reflete volatilidade recente, nao futura.
**Correcao:** Usar ATR-based SL para todos os ativos (ja existe `ATR_SL_MULTIPLIER`). Eliminar mapa fixo.
**Esforco:** Medio

### A7. Pump trader sem limite de posicoes simultaneas
**Arquivo:** `pump_trader.py` linha 81
**Problema:** So verifica se ja tem posicao no mesmo simbolo. 10 pumps = 10 posicoes abertas.
**Correcao:** Adicionar `PUMP_MAX_POSITIONS = 5` e verificar antes de abrir.
**Esforco:** Baixo

### A8. Dump detection efetivamente inoperante
**Arquivo:** `pump_trader.py` linhas 197-205
**Problema:** Exige retrace >= 12.5% mas trailing stop e de 3%. O trailing sempre dispara primeiro.
**Correcao:** Reduzir threshold de retrace para `PUMP_TRAILING_STOP * 1.5` ou verificar dump ANTES do trailing stop fechar.
**Esforco:** Medio

### A9. Supervisor com MAX_RESTARTS=50 sem backoff
**Arquivo:** `supervisor.py` linhas 22, 92-101
**Problema:** 50 restarts com delay fixo de 10s = crash loop com spam de alertas Telegram.
**Correcao:** Reduzir para 5-10 restarts com backoff exponencial (10s, 30s, 60s, 120s...).
**Esforco:** Baixo

### A10. Trade agent log sem try/except
**Arquivo:** `trade_agents.py` linhas 428-444
**Problema:** Se `log_trade()` (insert no banco) falhar com excecao, o capital ja foi modificado em memoria mas a posicao nao foi removida. Trade fantasma.
**Correcao:** Envolver `log_trade()` em try/except para nao interromper gerenciamento de posicoes.
**Esforco:** Minimo

### A11. Scalping ausente do /capital e relatorio diario
**Arquivo:** `daily_report.py` linhas 80-96, `telegram_commands.py`
**Problema:** `get_capital_status()` le paper, agent, pump, mas nao le `scalping_state.json`.
**Correcao:** Adicionar leitura do scalping state. Incluir no `/capital` e relatorio.
**Esforco:** Baixo

---

## MEDIO — Planear para Proximas Sprints

### M1. Nao existe backtest para scalping
**Problema:** Os 3 motores (volume breakout, RSI/BB, EMA crossover) + confluencia nao tem nenhum backtest historico. Parametros sao validados "na marcha".
**Correcao:** Criar `backtest_scalping.py` usando dados de 3m/5m/15m. Testar confluencia 2/3 e 3/3 em pelo menos 90 dias.
**Esforco:** Alto

### M2. Nao existe backtest para pump scanner
**Problema:** Nenhum dado historico de deteccao e performance de pumps.
**Correcao:** Criar `backtest_pump.py` com dados de 5m das top 50 moedas.
**Esforco:** Alto

### M3. Criterios 1-3 da strategy.py altamente correlacionados
**Problema:** Tendencia SMA + posicao do preco + direcao das SMAs quase sempre ativam juntos. Score "4/7" na pratica mede 3-4 fatores, nao 7.
**Correcao:** Ponderar criterios correlacionados (ex: dar 1.5 pts ao grupo SMA em vez de 3x1pt). Ou trocar por criterios independentes.
**Esforco:** Medio

### M4. Priority score com double-counting
**Arquivo:** `strategy.py` linha 199
**Problema:** `score_difference * 5` contado no confidence E no priority. Infla prioridades.
**Correcao:** Remover duplicacao. Priority = confidence + bonus por tipo.
**Esforco:** Minimo

### M5. Fallback do analista Claude aprova tudo em caso de erro
**Arquivo:** `trade_agents.py` linhas 187-192
**Problema:** Se a API Anthropic falhar, o fallback aprova automaticamente qualquer sinal.
**Correcao:** Fallback conservador: rejeitar ou aprovar com confidence reduzida (50%).
**Esforco:** Baixo

### M6. Paper trader permite reentrada imediata apos TP
**Arquivo:** `paper_trader.py`
**Problema:** Apos TP hit, a posicao e removida e no mesmo ciclo pode reabrir no mesmo ativo.
**Correcao:** Adicionar cooldown apos TP (similar ao cooldown apos SL).
**Esforco:** Baixo

### M7. Conexoes SQLite sem try/finally
**Arquivo:** `database.py` linhas 133-280
**Problema:** Conexoes podem vazar se excecao ocorrer entre open e close.
**Correcao:** Usar context manager (`with sqlite3.connect(...) as conn`).
**Esforco:** Medio

### M8. get_status() do pump faz chamadas API
**Arquivo:** `pump_trader.py` linhas 262-269
**Problema:** Funcao de leitura (status) chama API Binance para cada posicao. Dashboard com auto-refresh multiplica chamadas.
**Correcao:** Usar preco cacheado ou ultimo preco do candle em vez de request em tempo real.
**Esforco:** Baixo

### M9. State lido 2x do disco por ciclo no scalping
**Arquivo:** `risk_manager.py` linha 373, `scalping_trader.py` linha 311
**Problema:** `load_scalping_state()` chamado no trader e novamente no risk_manager.
**Correcao:** Passar `state` como parametro para `evaluate_risk()`.
**Esforco:** Baixo

### M10. Janela de 10 minutos para relatorio diario
**Arquivo:** `daily_report.py` linhas 209-212
**Problema:** Se o ciclo atrasar, a janela 00:00-00:10 e perdida e o relatorio nao e enviado.
**Correcao:** Remover restricao de horario. Enviar se `should_send_report()` retornar True.
**Esforco:** Minimo

### M11. Verificacao de espaco em disco
**Problema:** Nenhuma verificacao. Se disco encher, crash loop.
**Correcao:** Verificar no inicio de cada ciclo. Alerta se < 500 MB livre.
**Esforco:** Baixo

### M12. Metricas do backtest com soma aritmetica
**Arquivo:** `backtest.py` linhas 302-315
**Problema:** Retorno total, drawdown e profit factor calculados com soma de %, nao retorno composto.
**Correcao:** Aplicar retornos sequencialmente sobre capital simulado.
**Esforco:** Medio

---

## BAIXO — Quando Houver Tempo

### B1. Filtro de spread bid/ask nao implementado no volume_breakout
**Arquivo:** `volume_breakout.py`
**Parametro existe** em `ScalpingConfig` (`vb_spread_max_pct`) mas nunca e usado. Requer dados de `bookTicker`.

### B2. RSI/BB pode gerar sinais atrasados 1 candle
**Arquivo:** `rsi_bb_reversal.py` linhas 122-124
**Signal candle e `iloc[-3]` em vez de `iloc[-2]`**. Atraso de 5 minutos.

### B3. EMA crossover com dead code e variavel fragil
**Arquivo:** `ema_crossover.py` linhas 128, 374
**`return False` unreachable** e `'gap_pct' in dir()` fragil. Inicializar com default.

### B4. total_pnl_usd nunca atualizado no scalping state
**Arquivo:** `scalping_trader.py`
**Campo definido** no state inicial mas permanece 0 para sempre.

### B5. News filter com datas FOMC hardcoded para 2026
**Arquivo:** `news_filter.py`
**Funciona em 2026** mas precisa atualizacao manual anual. PCE pode ser perdido em meses com 5 semanas.

### B6. total_pnl do paper acumula % aritmeticamente
**Arquivo:** `paper_trader.py` linha 198
**Campo no JSON** nao e usado por nada critico, mas valor e enganoso.

### B7. Alert control pode spammar em oscilacao de priority
**Arquivo:** `alert_control.py`
**Se priority oscila** 84->86->84->86, envia alerta a cada subida.

### B8. Dashboard le log inteiro para contar erros
**Arquivo:** `dashboard_server.py` linhas 295-299
**Ler ultimas N linhas** ou cachear contagem por 60s.

### B9. Supervisor restart counter nunca reseta
**Arquivo:** `supervisor.py`
**Se bot crashar 1x/dia** por 50 dias, atinge limite permanente.

### B10. f-string em nome de tabela SQL
**Arquivo:** `database.py` linhas 273-278
**Nao exploravel hoje** (nomes sao constantes internas), mas perigoso se exposto.

### B11. Dashboard sem endpoint de versao
**Arquivo:** `dashboard_server.py`
**Problema:** Nao ha `/api/version` ou bloco equivalente com SHA, data de deploy e versao dos prompts/modelos.
**Correcao:** Expor endpoint e card no dashboard com fingerprint completa da execucao.
**Esforco:** Baixo

### B12. Ausencia de dataset de decisoes do scalping
**Arquivo:** `scalping_trader.py`, `confluence.py`, `risk_manager.py`, `database.py`
**Problema:** O sistema registra trades, mas nao registra todas as decisoes recusadas no funil.
**Correcao:** Criar tabela `scalping_decisions` com 1 linha por simbolo/ciclo e status final do funil.
**Esforco:** Medio

### B13. Ausencia de dataset de IA
**Arquivo:** `trade_agents.py`, `database.py`
**Problema:** Nao ficam persistidos modelo, prompt version, latencia, fallback e parse success das decisoes de IA.
**Correcao:** Criar tabela `ai_decisions` para agent trader e validador do scalping.
**Esforco:** Medio

---

## MELHORIAS ESTRATEGICAS — Longo Prazo

### E1. Walk-forward testing
Otimizar em janela N dias, testar em janela N+1, avancar. Unica forma confiavel de validar parametros.

### E2. Out-of-sample validation
Separar dados em treino (70%) e teste (30%). Nunca otimizar no conjunto de teste.

### E3. Monte Carlo simulation
Randomizar ordem dos trades para estimar distribuicao de drawdowns e intervalo de confianca.

### E4. Tracking performance real vs backtest
Criar relatorio automatico comparando paper trading real com backtest do mesmo periodo.

### E5. Calendario economico via API
Substituir datas hardcoded por API de calendario (ForexFactory, Investing.com) para maior precisao.

### E6. Migrar dados de Spot para Futures
Usar `fapi.binance.com` em vez de `api.binance.com` em todo o projeto, ja que a estrategia e para Futuros.

### E7. Analise de sensibilidade de parametros
Rodar backtest com variacao sistematica de: score_min (3-6), RSI zones, ATR multipliers, SL%. Identificar quais parametros sao frageis.

### E8. Teste A/B de IA
Rodar por periodo controlado:

- lane A: scalping puramente sistematico
- lane B: sistematico + validador IA

Comparar:

- taxa de aprovacao
- win rate
- expectancy
- drawdown
- custo por trade aprovado
- latencia adicional

### E9. Sistema de score probabilistico
Em vez de limiar duro `2/3`, combinar features dos motores em um score continuo de probabilidade de sucesso.
Pode ser logistic regression, gradient boosting ou IA estruturada. So faz sentido apos existir dataset limpo.

---

## CRITERIOS DE ACEITACAO POR FASE

### Fase de dados
- scalping separado em tabela propria
- dashboard, relatorio e circuit breaker lendo a mesma fonte correta
- nenhuma contaminacao entre paper, agent, pump e scalping

### Fase de observabilidade
- funil do scalping visivel por simbolo e por dia
- endpoint de versao disponivel
- decisoes de IA persistidas com contexto

### Fase de estrategia
- backtest sem look-ahead
- fees e slippage aplicados
- minimo de 180 dias de historico
- teste out-of-sample documentado

### Fase de IA
- baseline sem IA medido
- experimento com IA rodado em paralelo
- melhoria comprovada em expectancy ou drawdown-adjusted return
- fallback automatico permissivo removido

---

## PRINCIPIO DE IMPLEMENTACAO

Antes de construir qualquer camada nova de IA, o bot precisa responder 3 perguntas com dados:

1. Onde o scalping esta filtrando demais?
2. Quando a IA aprova, isso melhora o resultado ou piora?
3. Qual versao exata de codigo e prompt gerou cada resultado?

Se essas 3 respostas nao estiverem disponiveis, a construcao com IA deve parar e voltar para instrumentacao.

---

## ORDEM SUGERIDA DE EXECUCAO

### Fase 1 — Bugs criticos (1-2 dias)
1. C1 — Tabela scalping_trades
2. C2 — Separar is_circuit_broken
3. C3 — Mapear scalping no circuit breaker
4. C7 — Fix NameError rsi_bb
5. C4 — Gerenciar posicoes com CB ativo
6. A10 — try/except no log_trade

### Fase 2 — Integridade de dados (1 dia)
7. C5 — Fix look-ahead no backtest
8. C6 — Adicionar fees no backtest
9. A4 — Importar strategy no backtest
10. A11 — Scalping no /capital e relatorio

### Fase 3 — Seguranca ops (1 dia)
11. A2 — Auth no dashboard
12. A3 — Fix deploy.sh
13. A9 — Backoff no supervisor
14. M10 — Ampliar janela relatorio
15. M11 — Check espaco disco

### Fase 4 — Robustez de estrategia (3-5 dias)
16. A1 — API Futures
17. A5 — Backtest 180 dias
18. A6 — ATR-based SL universal
19. A7 — Limite posicoes pump
20. A8 — Fix dump detection
21. M1 — Backtest scalping
22. M2 — Backtest pump

### Fase 5 — Refinamentos (ongoing)
23. M3-M12 — Melhorias medias
24. B1-B13 — Melhorias baixas
25. E1-E9 — Estrategicas
