Estratégia de Scalping Combinada — Binance Futuros USDT-M

1. Visão Geral
A estratégia combina três "motores" de sinal independentes que, isolados, têm taxa de erro alta em scalping — mas quando alinhados, criam uma janela de entrada de alta probabilidade. O Breakout de Volume atua como gatilho de atenção (algo está acontecendo), a Reversão RSI/BB define o timing preciso de entrada (o movimento está exausto ou prestes a virar), e o EMA Crossover fornece o contexto direcional (qual lado da fita operar). O robô só executa quando pelo menos 2 dos 3 motores confirmam a mesma direção, e a posição só é aberta se o RR calculado em tempo real atinge o mínimo exigido.

2. As Três Abordagens

🔴 ABORDAGEM 1 — Breakout de Volume
Lógica: Detectar candles com volume anormalmente alto em relação à média recente. Volume acima da média indica participação institucional ou liquidação em massa — ambos criam movimento direcional forte que pode ser capturado nos primeiros candles após o spike.

a. Condições de Entrada (LONG)
#RegraValor Exato1Volume do candle atual ≥ X × média dos últimos N candlesX = 2.5×, N = 20 candles2O candle de breakout fecha acima do high dos últimos 5 candlesverificável via OHLCV3O corpo do candle ≥ 60% do range total (high - low)evita candles indecisivos4Preço está acima da EMA20 no timeframe de entradacontexto de alta5Entrada no candle seguinte ao breakout, no opennão perseguir o candle spike
Para SHORT: espelhar todas as condições (fecha abaixo do low dos últimos 5, abaixo da EMA20).

b. Filtros — Quando NÃO Operar

Volume spike ocorreu dentro de 3 candles de uma notícia programada (FOMC, CPI, etc.)
O spike é o terceiro consecutivo na mesma direção — movimento provavelmente exausto
Spread bid/ask > 0.05% no momento da entrada
ATR(14) do timeframe de 5m está abaixo de 0.15% do preço — mercado sem volatilidade, breakout falso provável
O candle de breakout tem wick superior > 40% do range (rejeição imediata = armadilha)


c. Stop Loss
SL = Low do candle de breakout − (0.5 × ATR14 do timeframe de entrada)

Para SHORT: High do candle de breakout + (0.5 × ATR14)
Nunca ultrapassar 0.8% de distância do preço de entrada (se ATR implicar SL mais largo, não operar)


d. Take Profit

TP1 (parcial — 50% da posição): entrada + 1.0 × ATR14
TP2 (alvo final — 50% restante): entrada + 2.2 × ATR14
Após TP1 atingido: mover SL para breakeven (entrada exata)


e. RR Mínimo

Calculado contra TP2: RR ≥ 1.8
Se distância até TP2 ÷ distância até SL < 1.8 → não abrir a operação


f. Timeframes
FunçãoTimeframeDetecção do spike (entrada)3mContexto de tendência15mGestão e saída1m


🔵 ABORDAGEM 2 — Reversão por RSI + Bollinger Bands
Lógica: Quando o preço toca ou perfura a banda externa de Bollinger enquanto o RSI está em zona extrema, há alta probabilidade de reversão para a média. Em Futuros, esse retorno à média acontece com frequência e velocidade — ideal para scalping curto contra o excesso.

a. Condições de Entrada (LONG — reversão de sobrevenda)
#RegraValor Exato1RSI(14) ≤ 32 no fechamento do candlesobrevenda confirmada2Candle fecha abaixo da Banda Inferior de Bollinger (20, 2.0)toque ou perfuração3Candle seguinte abre acima da Banda Inferior (pullback confirmado)evita faca caindo4RSI no candle de entrada está subindo em relação ao candle anteriordivergência mínima de momentum5Volume do candle de reversão ≥ 1.5× média dos últimos 20confirmação de absorção
Para SHORT (sobrecompra): RSI(14) ≥ 68, fecha acima da Banda Superior, candle seguinte abre abaixo da banda.

b. Filtros — Quando NÃO Operar

Tendência forte no 15m: se EMA9 > EMA21 (alta forte) e o sinal é SHORT — não operar contra tendência maior
RSI está em sobrevenda há mais de 6 candles consecutivos — indica tendência, não excesso
Bollinger Bandwidth (largura das bandas) < 0.8% do preço médio — bandas comprimidas = sinal não confiável
O toque na banda é o terceiro toque consecutivo sem bounce — "surfando a banda", tendência prevalece
ATR14 no 5m < 0.10% — mercado plano demais, reversão não tem espaço para se desenvolver


c. Stop Loss
SL = Mínimo (ou Máximo para SHORT) dos últimos 3 candles − 0.3 × ATR14

Distância máxima tolerada: 0.6% do preço de entrada
Se o SL calculado resultar em distância > 0.6%, não operar


d. Take Profit

TP1 (50%): Média móvel central do Bollinger (SMA20) — retorno à média
TP2 (50% restante): Banda oposta de Bollinger (entrada em sobrevenda → TP2 na banda superior)
Após TP1: SL movido para entrada


e. RR Mínimo

RR ≥ 1.5 calculado contra TP1
Essa abordagem tem alvos menores (retorno à média), por isso o RR mínimo é mais agressivo mas o alvo é mais próximo e mais confiável


f. Timeframes
FunçãoTimeframeSinal de entrada (RSI + BB)5mContexto macro15mAcompanhamento e saída1m


🟢 ABORDAGEM 3 — Tendência por EMA Crossover
Lógica: Cruzamentos de EMAs curtas em timeframes baixos capturam a transição de micro-estrutura de mercado — quando a EMA rápida cruza a lenta, o momentum mudou de direção recente. Em scalping, a janela útil é curta, então a entrada deve ser feita no retest pós-cruzamento, não no cruzamento em si (que frequentemente faz whipsaw).

a. Condições de Entrada (LONG)
#RegraValor Exato1EMA9 cruza acima da EMA21 no fechamento do candlecruzamento confirmado no fechamento2Após o cruzamento, preço recua até a zona entre EMA9 e EMA21 (retest)entrada no pullback, não no cruzamento3No retest, o candle fecha acima da EMA9defesa da média rápida4EMA21 está inclinando para cima (EMA21[0] > EMA21[3])tendência genuína, não lateral5No timeframe de 15m, EMA50 está abaixo do preçoalinhamento macro mínimo
Para SHORT: EMA9 cruza abaixo da EMA21, retest pela parte de cima, EMA50 no 15m acima do preço.

b. Filtros — Quando NÃO Operar

Cruzamento ocorreu com gap grande: distância entre EMA9 e EMA21 no cruzamento > 0.3% do preço — indica exaustão, não momentum
Sem retest após 5 candles: se o preço não retorna para a zona EMA9–EMA21 em até 5 candles, o movimento já está longe demais — não perseguir
Mercado em range no 15m: EMA9 e EMA21 no 15m estão entrelaçadas (distância < 0.1%) — cruzamentos no 3m serão ruído
Mais de 3 cruzamentos de EMA9/EMA21 nos últimos 15 candles — choppy, sem direção


c. Stop Loss
SL = abaixo da EMA21 no momento da entrada − 0.2 × ATR14

A EMA21 funciona como suporte dinâmico; o SL fica levemente abaixo dela
Distância máxima: 0.7% do preço


d. Take Profit

TP1 (50%): 1.5 × ATR14 a partir da entrada
TP2 (50% restante): próxima resistência relevante (high dos últimos 20 candles no timeframe de entrada) ou 2.5 × ATR14, o que vier primeiro
Após TP1: SL movido para entrada


e. RR Mínimo

RR ≥ 2.0 — essa abordagem tem mais falsos cruzamentos, então exige compensação maior


f. Timeframes
FunçãoTimeframeCruzamento e entrada3mFiltro de tendência15mRetest e execução fina1m


3. Tabela de Confluência
A confluência define o tamanho da posição e se o sinal é operável. Cada abordagem que confirma a mesma direção no momento da análise adiciona 1 ponto.
ConfluênciaClassificaçãoTamanho da PosiçãoAlavancagem Sugerida1 de 3❌ InválidoNão operar—2 de 3🟡 Médio50% do tamanho máximo calculado3x3 de 3🟢 Alto100% do tamanho máximo calculado5x
Como verificar confluência em tempo real
Para cada novo candle fechado no timeframe de entrada, o robô deve calcular:
Sinal_Volume:    volume_spike AND direcao_breakout == direcao_alvo → +1
Sinal_Reversão:  RSI_extremo AND BB_toque AND pullback_confirmado AND direcao == direcao_alvo → +1
Sinal_EMA:       cruzamento_confirmado AND retest_valido AND alinhamento_15m → +1

Score = Sinal_Volume + Sinal_Reversão + Sinal_EMA
Regra de desempate: se dois sinais estão ativos mas apontam para direções opostas entre si → não operar (mercado indeciso).
Exemplo de cenário 3 de 3 (LONG em BTC/USDT):

Volume spike de 3.1× a média nos últimos 3 candles de 3m ✅
RSI em 29, fechou abaixo da BB inferior, próximo candle abrindo acima ✅
EMA9 cruzou EMA21 há 2 candles, retest na zona EMA acontecendo agora ✅
→ Sinal alto. Posição 100%. Alavancagem 5x.


4. Alertas e Armadilhas Comuns
☠️ 1. Whipsaw em mercado lateral
O problema: Em ranging market, EMA crossovers geram 4–6 sinais falsos por hora. Volume spikes em lateralização são armadilhas de market maker.
Como evitar: Checar Bollinger Bandwidth no 15m antes de qualquer entrada. Se bandwidth < 1.2%, nenhuma das três abordagens deve ser ativada — o mercado não tem condições de scalping direcional.

☠️ 2. Entrar no spike, não no retest
O problema: O candle de volume spike parece irresistível. Entrar nele coloca você no pior preço do movimento.
Como evitar: Regra rígida de esperar o candle seguinte ao gatilho em todas as três abordagens. Codificar isso como verificação de candle_index > spike_index.

☠️ 3. Funding rate adverso (específico de Futuros)
O problema: Funding rate de 0.1%+ a cada 8h representa custo real em posições mantidas perto das janelas de pagamento (00:00, 08:00, 16:00 UTC).
Como evitar: Verificar funding rate atual via API antes de abrir posição. Se |funding_rate| > 0.05% e você está operando contra a direção do funding (ex: LONG com funding positivo alto), reduzir tamanho em 50% ou pular.

☠️ 4. Liquidez falsa no book
O problema: Em BTC e ETH, grandes ordens no book desaparecem quando o preço se aproxima — spoofing. O robô pode interpretar suporte/resistência que não existe.
Como evitar: Não usar dados do order book como condição de entrada. Usar apenas OHLCV + indicadores calculados. O book pode ser monitorado para alertas, nunca para gatilhos.

☠️ 5. Overtrading por sinais de baixa qualidade
O problema: Em 1m/3m, sinais aparecem dezenas de vezes por dia. Sem filtro de frequência, o robô abre posições demais e a taxa de fee destrói o lucro (Binance Futures: 0.02% maker / 0.05% taker por lado = 0.1% round trip).
Como evitar: Implementar cooldown obrigatório por par: após fechar uma posição (lucro ou prejuízo), aguardar mínimo de 3 candles no timeframe de entrada antes de permitir novo sinal no mesmo par.

☠️ 6. Stop loss muito justo em alta volatilidade
O problema: ATR sobe durante eventos de mercado. Um SL calibrado para ATR normal é stopado instantaneamente por noise.
Como evitar: Recalcular ATR a cada candle fechado. Se ATR subiu > 50% em relação à média de 20 períodos, aumentar SL em 0.3% ou simplesmente não operar até ATR estabilizar.

☠️ 7. Alavancagem emocional após sequência de ganhos
O problema: Após 4–5 trades lucrativos, há tentação (mesmo em robô mal configurado) de aumentar tamanho. Uma sequência de ganhos não valida a estratégia.
Como evitar: Fixar o cálculo de tamanho de posição como função exclusiva do capital atual + % de risco (2%), sem memória de trades anteriores. Nenhum multiplicador dinâmico até ter 200+ trades de dados para análise estatística.