# SPEC: Multi-Engine 1-Minute Trading System

## Revisao Tecnica — Fixes Aplicados

1. **Nome do config:** `config_1m.py` (Python nao aceita modulo comecando com numero)
2. **Loop separado:** O sistema 1-min precisa de seu proprio processo no supervisor (3o processo: main_5m + dashboard + loop_1m), com ciclo de ~10 segundos
3. **VWAP 24/7:** Usar rolling VWAP (nao daily reset) — cripto nao tem daily open. Rolling de 200 candles (~3.3h)
4. **Memoria no Pi (3.7GB RAM):** Live: manter so ultimas 200 candles por simbolo. Backtest: processar em chunks de 1 dia (1440 candles)
5. **Faseamento:** Opcao A — Fundacao + APENAS Momentum Burst primeiro. Validar base antes de plugar mais engines.

---

## Visao Geral

Sistema modular de trading para timeframe de 1 minuto em cripto (Binance Futures).
Usa micro-posicoes com alavancagem alta e risco controlado por trade.

**Filosofia:** Escanear como maquina, executar como sniper.
O sistema avalia TODAS as candles, mas so executa quando ha confluencia real.

**Principio de posicao:** Nao existe valor fixo de posicao ($4, $10, etc).
O tamanho e calculado dinamicamente pelo Risk Calculator baseado na distancia do stop e no risco maximo por trade definido pelo operador.

---

## Arquitetura

```
                    +------------------------------------------+
                    |            RISK CALCULATOR               |
                    |  (Motor 0 -- construir PRIMEIRO)         |
                    |  Calcula: tamanho, alavancagem, fees,    |
                    |  viabilidade. Decide SE vale entrar.     |
                    +------------------+-----------------------+
                                       |
                              +--------+--------+
                              |  SIGNAL ROUTER   |
                              |  Recebe sinais    |
                              |  de N engines,    |
                              |  valida via Risk  |
                              |  Calculator,      |
                              |  executa.         |
                              +--+---+---+---+---+
                                 |   |   |   |
                           +-----+   |   |   +------+
                           v         v   v          v
                        Engine1    E2   E3      Engine N
                        Moment.  Break Support  (futuras)
                        Burst    out   Bounce
```

Cada engine e:
- Independente (roda sozinho)
- Backtestavel isoladamente
- Plugavel no Signal Router
- Segue a interface `Signal` existente em `signal_types.py`

---

## Motor 0: Risk Calculator

### Objetivo
Antes de qualquer trade, responder: **"Este trade e viavel? Se sim, com qual tamanho e alavancagem?"**

### Localizacao
`risk_calculator_1m.py` (novo arquivo)

### Interface

```python
@dataclass
class TradeViability:
    viable: bool                  # Trade vale a pena?
    reason: str                   # Por que sim/nao
    position_size_usd: float      # Capital a usar (margem)
    leverage: int                 # Alavancagem calculada
    notional_usd: float           # Exposicao real (size x leverage)
    fee_cost_usd: float           # Custo de fees round-trip
    fee_impact_pct: float         # Fees como % do lucro esperado
    min_profit_to_breakeven: float # Movimento minimo pra empatar
    expected_profit_usd: float    # Lucro esperado se bater TP
    expected_loss_usd: float      # Perda esperada se bater SL
    risk_reward_net: float        # R:R liquido (ja descontando fees)

def calculate_viability(
    symbol: str,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    max_risk_per_trade_usd: float,  # Definido pelo operador (ex: $2)
    preferred_leverage: int = None,  # Se None, calcula o otimo
    maker_fee_pct: float = 0.02,    # 0.02% maker
    taker_fee_pct: float = 0.04,    # 0.04% taker
    use_maker: bool = False,        # Limit order vs market order
) -> TradeViability:
```

### Logica de Calculo

```
1. sl_distance_pct = abs(entry - sl) / entry x 100
2. tp_distance_pct = abs(tp - entry) / entry x 100
3. fee_per_side = taker_fee_pct (ou maker_fee_pct se use_maker)
4. fee_roundtrip_pct = fee_per_side x 2

5. notional = max_risk_per_trade_usd / (sl_distance_pct / 100)
   -- Exposicao necessaria para que a perda no SL = max_risk

6. Se notional < BINANCE_MIN_NOTIONAL[symbol]: viable = False
   -- Nao atinge minimo da Binance

7. Se preferred_leverage e None:
   -- Usar alavancagem maxima para minimizar margem necessaria
   leverage = max alavancagem valida da Binance onde notional/leverage >= margem minima
   Alavancagens validas: 1, 2, 3, 5, 10, 20, 25, 50, 75, 100, 125
   -- Na pratica: usar a maior possivel (ex: 125x para BTC) pois o risco
   -- ja e controlado pelo max_risk_per_trade_usd, nao pela alavancagem
   Senao: leverage = preferred_leverage

8. position_size_usd = notional / leverage  (margem)
9. fee_cost_usd = notional x fee_roundtrip_pct / 100

10. expected_profit_usd = (tp_distance_pct - fee_roundtrip_pct) / 100 x notional
11. expected_loss_usd = (sl_distance_pct + fee_roundtrip_pct) / 100 x notional
    -- No loss, fees somam a perda. No win, fees subtraem do ganho.

12. risk_reward_net = expected_profit_usd / expected_loss_usd

13. fee_impact_pct = fee_cost_usd / expected_profit_usd x 100

14. min_profit_to_breakeven = fee_roundtrip_pct
    -- Preco precisa se mover pelo menos fee_roundtrip_pct% pra empatar

15. viable = True SE:
    - risk_reward_net >= 1.5 (minimo R:R liquido)
    - fee_impact_pct < 30% (fees nao comem demais do lucro)
    - notional >= BINANCE_MIN_NOTIONAL[symbol]
    - sl_distance_pct >= 0.05% (evitar stops impossiveis por spread)
    - sl_distance_pct <= 1.0% (evitar overexposure em stops largos)
```

### Validacoes de Minimo da Binance

```python
# Minimos variam por par -- buscar via API ou hardcode os principais
BINANCE_MIN_NOTIONAL = {
    "BTCUSDT": 100,    # $100 minimo nocional
    "ETHUSDT": 20,
    "SOLUSDT": 5,
    "BNBUSDT": 20,
    "XRPUSDT": 5,
    "DOGEUSDT": 5,
    "DEFAULT": 5,
}

# Se notional calculado < minimo: viable = False
# Reason: "Nocional {notional:.2f} abaixo do minimo {min} para {symbol}"
```

### Config

```python
# config_1m.py
RISK_1M_MAX_RISK_PER_TRADE_USD = 2.0    # Maximo a perder por trade
RISK_1M_MIN_RR_NET = 1.5                # R:R minimo liquido
RISK_1M_MAX_FEE_IMPACT_PCT = 30.0       # Fees max como % do lucro
RISK_1M_MIN_SL_DISTANCE_PCT = 0.05      # Stop minimo (evita spread)
RISK_1M_MAX_SL_DISTANCE_PCT = 1.0       # Stop maximo (evita overexposure)
RISK_1M_PREFERRED_LEVERAGE = None        # None = calcula otimo
RISK_1M_USE_MAKER_ORDERS = False         # True = limit orders
```

### Backtesting do Risk Calculator

Criar `backtest_risk_calculator.py`:
- Input: dados historicos de 1-min de N dias
- Para cada candle, simular entries com stops variados (0.05% a 1.0%)
- Medir: distribuicao de fee impact, viabilidade por faixa de stop
- Output: tabela mostrando "pra stops de X%, com Y leverage, fee come Z% do lucro"
- Objetivo: encontrar empiricamente as faixas otimas de operacao

---

## Motor 1: Momentum Burst Engine

### Objetivo
Detectar explosoes de momentum no 1-min e surfar o movimento.

### Localizacao
`engines_1m/momentum_burst.py` (novo diretorio `engines_1m/`)

### Deteccao

```
Condicoes (TODAS devem ser verdadeiras):
1. Candle atual: range > 2.0 x ATR(14) no 1-min
2. Volume: > 2.5x media das ultimas 20 candles
3. Body ratio: >= 65% (candle forte, nao doji)
4. Direcao: alinhada com EMA8 > EMA21 no 1-min (LONG se above, SHORT se below)
5. RSI(14): entre 30 e 70 (nao exaurido)
```

### Entry/Exit

```
LONG:
  entry: open da proxima candle (sem look-ahead no backtest)
  sl: low da candle de sinal - 0.3 x ATR(14)
  tp: dinamico -- trailing stop baseado em ATR
    tp_initial = entry + 1.5 x ATR(14)
    trailing: a cada nova candle que fecha acima do entry, move SL pra:
      max(sl_atual, close - 1.0 x ATR(14))
    tp_max = entry + 3.0 x ATR(14) (take profit forcado)

SHORT: espelha LONG invertendo direcao.
```

### Filtros Opcionais (testar no backtest)
- HTF alignment: tendencia do 5-min na mesma direcao (EMA8 vs EMA21 no 5-min)
- Volume profile: candle dentro de zona de alto volume historico
- Spread check: se bid-ask spread > 0.03%, nao entrar (slippage alto)

### Metadata no Signal

```python
metadata = {
    "engine": "momentum_burst_1m",
    "atr_multiple": candle_range / atr14,
    "volume_multiple": volume / avg_volume,
    "body_ratio": body / range,
    "ema_alignment": "ALIGNED" | "COUNTER",
    "rsi": rsi_value,
    "trailing_active": bool,
}
```

---

## Motor 2: Breakout Engine (Fase 3)

### Objetivo
Detectar rompimentos de consolidacao/range no 1-min.

### Localizacao
`engines_1m/breakout.py`

### Deteccao

```
Fase 1 -- Identificar consolidacao:
  - Ultimas N candles (N = 10-20, parametrizavel)
  - Range do periodo: (max_high - min_low) / min_low x 100
  - Consolidacao confirmada se range < THRESHOLD_PCT (ex: 0.3%)
  - Bollinger Bandwidth < 1.5% (BB squeeze)

Fase 2 -- Detectar rompimento:
  - Candle atual: close > max_high dos ultimos N candles (LONG)
  - Ou: close < min_low dos ultimos N candles (SHORT)
  - Volume: > 2.0x media (confirmacao)
  - Body ratio: >= 55%

Condicoes (TODAS):
1. Consolidacao confirmada (Fase 1)
2. Rompimento confirmado (Fase 2)
3. Volume acima do threshold
4. Body ratio minimo
```

### Entry/Exit

```
LONG breakout:
  entry: open da proxima candle
  sl: meio do range de consolidacao
     sl = (max_high + min_low) / 2
  tp: projecao do range
     tp = entry + (max_high - min_low)           # Projecao 1:1
     tp_extended = entry + 1.5 x (max_high - min_low)  # Projecao 1.5:1

SHORT: espelha invertendo.
```

### Filtros
- Falso rompimento: se a candle de rompimento fecha de volta dentro do range, cancelar
- Re-teste: opcionalmente esperar re-teste do nivel rompido antes de entrar
- Horario: evitar dead zones (21:00-00:00 UTC) -- rompimentos falsos mais comuns

---

## Motor 3: Support/Resistance Bounce Engine (Fase 4)

### Objetivo
Entrar em bounces confirmados de zonas de suporte/resistencia.

### Localizacao
`engines_1m/sr_bounce.py`

### Deteccao de Zonas S/R

```
Metodo 1 -- Swing Points:
  - Swing low: candle com low menor que as 3 anteriores E posteriores
  - Swing high: candle com high maior que as 3 anteriores E posteriores
  - Zona: agrupa swing points dentro de 0.1% de distancia
  - Forca: numero de toques na zona (minimo 2)

Metodo 2 -- Volume Profile (simplificado):
  - Dividir range das ultimas 100 candles em 50 bins
  - POC (Point of Control): bin com mais volume
  - VAH/VAL: limites de 70% do volume

Metodo 3 -- Numeros redondos:
  - BTC: multiplos de $500 e $1000
  - ETH: multiplos de $50 e $100
  - SOL: multiplos de $5 e $10
```

### Entry

```
Condicoes para BOUNCE LONG em suporte:
1. Preco toca zona de suporte (low da candle dentro da zona)
2. Candle de rejeicao: shadow inferior > 2x body (pavio de rejeicao)
3. Volume: spike (> 1.5x media) na candle de rejeicao
4. Close acima da zona de suporte (nao perdeu o nivel)

entry: open da proxima candle
sl: abaixo da zona de suporte - 0.2 x ATR(14)
tp: proxima zona de resistencia (dinamico)
tp_alt: se nao ha resistencia clara, usar 2x distancia do SL

SHORT em resistencia: espelha invertendo.
```

---

## Motor 4: Mean Reversion Engine (Fase 4)

### Objetivo
Capturar correcoes quando o preco se afasta demais da media.

### Localizacao
`engines_1m/mean_reversion.py`

### Deteccao

```
Condicoes para LONG (reversion de queda):
1. Preco: abaixo de BB lower band (20, 2.0) no 1-min
2. RSI(14): < 25 (sobrevendido extremo)
3. Distancia do rolling VWAP: > 0.3% abaixo
4. Exaustao: volume diminuindo nas ultimas 3 candles (selling exhaustion)
5. Candle de reversao: close > open (candle verde) apos sequencia de vermelhas

Condicoes para SHORT (reversion de alta):
  Espelha invertendo (RSI > 75, acima BB upper, etc.)
```

### Entry/Exit

```
LONG reversion:
  entry: open da proxima candle
  sl: low da candle mais baixa da sequencia - 0.1 x ATR(14)
  tp: rolling VWAP (target natural de mean reversion)
  tp_extended: BB middle band (SMA20)

Filtro obrigatorio: NAO usar se EMA8 e EMA21 estao separando
(tendencia acelerando -- mean reversion contra tendencia forte e perigoso).
```

---

## Motor 5: Liquidity Sweep Engine (Fase 4)

### Objetivo
Detectar varreduras de liquidez (fake breakouts) e entrar na reversao.

### Localizacao
`engines_1m/liquidity_sweep.py`

### Deteccao

```
Fase 1 -- Identificar pools de liquidez:
  - Equal highs: 2+ candles com highs dentro de 0.05% de distancia
  - Equal lows: 2+ candles com lows dentro de 0.05%
  - Esses sao pontos onde stops estao acumulados

Fase 2 -- Detectar sweep:
  - Candle fura o nivel (new high acima de equal highs)
  - MAS fecha de volta abaixo/acima do nivel (rejeicao)
  - Volume alto no sweep (> 2x media) -- liquidacoes acontecendo
  - Shadow longa na direcao do sweep (> 2x body)

Condicoes (TODAS):
1. Pool de liquidez identificado
2. Sweep confirmado (fura e volta)
3. Volume alto
4. Candle de rejeicao
```

### Entry/Exit

```
LONG (sweep de lows):
  entry: open da proxima candle
  sl: low do sweep - 0.1 x ATR(14)
  tp: equal highs opostos (proximo pool de liquidez acima)
  tp_alt: 2x distancia do SL se nao ha target claro

SHORT (sweep de highs): espelha.

Nota: RR geralmente e excelente (3:1+) porque o SL e muito curto
(logo abaixo do sweep) e o TP e o outro lado do range.
```

---

## Signal Router

### Objetivo
Receber sinais de TODOS os engines, validar via Risk Calculator, e decidir execucao.

### Localizacao
`signal_router_1m.py` (novo arquivo)

### Logica

```python
class SignalRouter1m:
    def __init__(self, engines: List[Engine1m], risk_calculator: RiskCalculator1m):
        self.engines = engines
        self.risk = risk_calculator

    def process_candle(self, symbol: str, df_1m: pd.DataFrame,
                       df_5m: pd.DataFrame = None) -> Optional[Signal]:
        """
        1. Roda TODOS os engines
        2. Coleta sinais gerados
        3. Se multiplos engines concordam -> confluencia (boost confidence)
        4. Para cada sinal, passa pelo Risk Calculator
        5. Se viavel, retorna o melhor sinal
        6. Se nao viavel, retorna None (nao opera)
        """
        signals = []
        for engine in self.engines:
            signal = engine.analyze(symbol, df_1m, df_5m)
            if signal and signal.valid:
                signals.append(signal)

        if not signals:
            return None

        # Confluencia: multiplos engines na mesma direcao
        # boost de confianca mas NAO e requisito
        # Um unico engine com setup forte basta
        best = self._select_best(signals)

        viability = self.risk.calculate_viability(
            symbol=symbol,
            entry_price=best.entry_price,
            sl_price=best.sl_price,
            tp_price=best.tp1_price,
            max_risk_per_trade_usd=config.RISK_1M_MAX_RISK_PER_TRADE_USD,
        )

        if not viability.viable:
            # Loga rejeicao no SQLite com metadata completa
            return None

        best.metadata["viability"] = asdict(viability)
        return best

    def _select_best(self, signals: List[Signal]) -> Signal:
        """
        Criterios de selecao:
        1. Se ha confluencia (2+ engines mesma direcao): prioridade
        2. Se nao, seleciona por maior R:R estimado
        3. Desempate: maior strength do signal
        """
        ...
```

### Regras do Router

```
- Maximo 1 posicao aberta por par no sistema 1-min
- Maximo 3 posicoes simultaneas total (configuravel)
- Cooldown de 5 candles (5 min) apos fechar posicao no mesmo par
- Se ja ha posicao aberta por outro sistema (momentum/scalping), NAO abrir no 1-min
- Kill switch: se perda diaria > 5% do capital alocado, para tudo
```

---

## Engine Interface (contrato)

Todos os engines devem seguir esta interface para serem plugaveis:

```python
from signal_types import Signal, Direction
from typing import Optional, List
import pandas as pd

class Engine1m:
    """Interface base para engines de 1 minuto."""

    name: str       # Ex: "momentum_burst_1m"
    version: str    # Ex: "1.0.0"

    def analyze(
        self,
        symbol: str,
        df_1m: pd.DataFrame,        # Candles de 1-min com indicadores
        df_5m: pd.DataFrame = None,  # Opcional: contexto de 5-min
        market_data: dict = None,    # Opcional: funding, OI, etc
    ) -> Optional[Signal]:
        """
        Retorna Signal se houver setup valido, None caso contrario.

        O Signal DEVE conter:
        - direction: Direction.LONG ou Direction.SHORT
        - entry_price, sl_price, tp1_price
        - sl_distance_pct
        - strength: 0.0-1.0
        - source: self.name
        - metadata: dict com detalhes do setup
        - valid: True
        """
        raise NotImplementedError

    def required_indicators(self) -> List[str]:
        """Lista indicadores que precisam estar no DataFrame."""
        raise NotImplementedError
```

---

## Indicadores Necessarios

Calculados 1 vez por ciclo, reutilizados por todos engines.

### Localizacao
`indicators_1m.py` (novo)

```python
def add_indicators_1m(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona todos indicadores necessarios pro timeframe de 1-min."""

    # Medias moveis
    df["ema8"] = ta.trend.ema_indicator(df["close"], window=8)
    df["ema21"] = ta.trend.ema_indicator(df["close"], window=21)
    df["sma20"] = ta.trend.sma_indicator(df["close"], window=20)

    # Volatilidade
    df["atr14"] = ta.volatility.average_true_range(
        df["high"], df["low"], df["close"], window=14)
    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_bandwidth"] = bb.bollinger_wband()

    # Momentum
    df["rsi14"] = ta.momentum.rsi(df["close"], window=14)

    # Volume
    df["vol_avg20"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_avg20"]

    # Rolling VWAP (cripto 24/7 -- sem daily open)
    typical = (df["high"] + df["low"] + df["close"]) / 3
    df["vwap"] = (
        (typical * df["volume"]).rolling(200).sum()
        / df["volume"].rolling(200).sum()
    )

    # Propriedades da candle
    df["body"] = abs(df["close"] - df["open"])
    df["range"] = df["high"] - df["low"]
    df["body_ratio"] = df["body"] / df["range"].replace(0, float("nan"))
    df["upper_shadow"] = df["high"] - df[["close", "open"]].max(axis=1)
    df["lower_shadow"] = df[["close", "open"]].min(axis=1) - df["low"]
    df["is_green"] = df["close"] > df["open"]

    return df
```

---

## Dados Necessarios da Binance

### Localizacao
`market_1m.py` (novo) ou extensao de `market.py`

```python
def fetch_1m_candles(symbol: str, limit: int = 200) -> pd.DataFrame:
    """
    Busca candles de 1-min da Binance Futures.
    200 candles = ~3.3 horas de dados.
    """
    url = BINANCE_FUTURES_KLINES_URL  # de config.py
    params = {"symbol": symbol, "interval": "1m", "limit": limit}
    # Mesmo padrao de market.py com retry

def fetch_5m_candles(symbol: str, limit: int = 100) -> pd.DataFrame:
    """Contexto de 5-min para filtros HTF dos engines."""
    # Mesmo padrao, interval=5m
```

### Rate Limits
- 3 symbols x 2 intervals x a cada 10s = ~36 req/min
- Binance permite 1200 req/min -- bem dentro do limite

---

## Backtest Framework

### Localizacao
`backtest_1m.py` (novo)

### Estrutura

```python
class Backtest1m:
    """
    Backtest para engines de 1 minuto.

    Pode rodar:
    - Engine individual (ex: so Momentum Burst)
    - Multiplos engines via Signal Router
    - Com ou sem Risk Calculator
    """

    def __init__(
        self,
        engines: List[Engine1m],
        risk_calculator: RiskCalculator1m,
        symbols: List[str],
        days: int = 30,
        max_risk_per_trade: float = 2.0,
    ):
        pass

    def run(self) -> BacktestResult:
        """
        Loop candle-by-candle:
        1. Para cada candle i:
           a. Calcula indicadores com dados ate candle i (sem look-ahead!)
           b. Roda engines -> sinais
           c. Risk Calculator valida
           d. Simula entrada no open da candle i+1
           e. Gerencia posicoes abertas (check SL/TP/trailing via high/low)
        2. Processa em chunks de 1 dia (1440 candles) para economizar memoria
        3. Ao final: calcula metricas
        """
        pass

    def report(self) -> dict:
        """
        Metricas:
        - Total trades, win rate, profit factor
        - P&L bruto e liquido (COM FEES)
        - Max drawdown
        - Sharpe ratio
        - Media de trades por dia
        - Fee total pago
        - P&L por engine (qual engine contribui mais)
        - Distribuicao de R:R realizado
        - Tempo medio em posicao (candles)
        """
        pass
```

### Dados para Backtest

```
30 dias x 1440 candles/dia = 43.200 candles por simbolo.
Para 3 simbolos = ~130k candles.

Opcao 1: API (simples, ~3 min por simbolo)
  - Lotes de 1500 candles (maximo por request)
  - 43200 / 1500 = 29 requests por simbolo

Opcao 2: Binance Data Vision (rapido)
  - https://data.binance.vision/ tem CSVs de klines
  - Download direto, parse com pandas
```

---

## Loop Principal do Sistema 1-min

### Localizacao
`main_1m.py` (novo arquivo -- processo separado)

### Integracao com Supervisor

```python
# supervisor.py -- adicionar 3o processo:
BOTS = [
    {"name": "main_bot",    "script": "main.py"},
    {"name": "dashboard",   "script": "dashboard_server.py"},
    {"name": "loop_1m",     "script": "main_1m.py"},     # NOVO
]
```

### Estrutura do Loop

```python
LOOP_INTERVAL_SECONDS = 10  # Checa a cada 10 segundos
# Candle de 1-min muda a cada 60s. 10s da margem pra pegar fechamento.

def main_loop():
    router = SignalRouter1m(
        engines=[MomentumBurst1m()],
        risk_calculator=RiskCalculator1m()
    )

    while True:
        try:
            for symbol in config.SYSTEM_1M_SYMBOLS:
                df_1m = fetch_1m_candles(symbol, limit=200)
                df_1m = add_indicators_1m(df_1m)

                signal = router.process_candle(symbol, df_1m)

                if signal:
                    execute_1m(signal)

                manage_open_positions_1m()

            time.sleep(LOOP_INTERVAL_SECONDS)
        except Exception as e:
            log_error(e)
            time.sleep(30)
```

### Cache de Dados
- Cache de candles por (symbol, interval): TTL = 10 segundos
- 3 symbols x 1 request a cada 10s = 18 req/min (bem abaixo do limite)

---

## Plano de Construcao (motor por motor)

### Fase 1: Fundacao
```
1. config_1m.py          -- Configuracao do sistema
2. risk_calculator_1m.py -- Motor 0
3. indicators_1m.py      -- Indicadores compartilhados
4. market_1m.py          -- Fetch de dados 1-min
5. backtest_1m.py        -- Framework de backtest
6. engines_1m/__init__.py -- Estrutura do diretorio
7. Testes unitarios de cada modulo

Validacao: backtest_risk_calculator.py
  -> Confirmar que rejeita trades inviaveis
  -> Encontrar faixas otimas de stop x leverage x fees
```

### Fase 2: Primeiro Engine
```
8. engines_1m/momentum_burst.py -- Motor 1
9. Testes unitarios do engine
10. Backtest isolado: 30 dias BTCUSDT + ETHUSDT
    -> Medir: win rate, P&L liquido, drawdown
    -> Ajustar parametros se necessario

Meta: engine lucrativo isoladamente, ja descontando fees.
Se nao for lucrativo, ajustar parametros ou pivotar antes de continuar.
```

### Fase 3: Segundo Engine
```
11. engines_1m/breakout.py -- Motor 2
12. Backtest isolado
13. signal_router_1m.py com 2 engines
14. Backtest combinado -> medir se a combinacao melhora ou piora
```

### Fase 4: Engines Restantes (um por vez)
```
15-17. sr_bounce.py, mean_reversion.py, liquidity_sweep.py
18. Backtest de cada um isolado
19. Backtest do sistema completo (todos engines via Router)
```

### Fase 5: Integracao Live
```
20. main_1m.py + integracao supervisor
21. Paper executor para 1-min (DB: system_1m_trades, system_1m_decisions)
22. Dashboard: aba de 1-min
23. Telegram: alertas de sinais 1-min
```

### Fase 6: Paper Trading
```
24. Rodar em paper com capital virtual
25. Monitorar por no minimo 1 semana
26. Comparar resultados paper vs backtest
27. Ajustar se necessario
```

### Fase 7: Live (futuro)
```
28. Capital real, comecando com risco minimo ($1 por trade)
29. Aumentar gradualmente se resultados positivos
```

---

## Config Geral

```python
# config_1m.py

# === Risk Calculator ===
RISK_1M_MAX_RISK_PER_TRADE_USD = 2.0
RISK_1M_MIN_RR_NET = 1.5
RISK_1M_MAX_FEE_IMPACT_PCT = 30.0
RISK_1M_MIN_SL_DISTANCE_PCT = 0.05
RISK_1M_MAX_SL_DISTANCE_PCT = 1.0
RISK_1M_PREFERRED_LEVERAGE = None  # Auto-calc
RISK_1M_USE_MAKER_ORDERS = False

# === Position Management ===
SYSTEM_1M_MAX_POSITIONS = 3
SYSTEM_1M_COOLDOWN_CANDLES = 5  # 5 min
SYSTEM_1M_DAILY_LOSS_LIMIT_PCT = 5.0  # % do capital alocado

# === Capital ===
SYSTEM_1M_CAPITAL_USD = 100  # Capital alocado pro sistema 1-min
# (separado dos outros sistemas)

# === Symbols ===
SYSTEM_1M_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

# === Engines Ativos (feature flags) ===
ENGINE_1M_MOMENTUM_BURST = True
ENGINE_1M_BREAKOUT = False        # Ativar na Fase 3
ENGINE_1M_SR_BOUNCE = False       # Ativar na Fase 4
ENGINE_1M_MEAN_REVERSION = False  # Ativar na Fase 4
ENGINE_1M_LIQUIDITY_SWEEP = False # Ativar na Fase 4

# === Backtest ===
BACKTEST_1M_DAYS = 30
BACKTEST_1M_FEE_PCT = 0.08  # Round-trip taker
```

---

## Notas para Implementacao

1. **Sem look-ahead no backtest:** Signal em candle i usa dados ate candle i. Entry no open da candle i+1. SEMPRE.
2. **Fees sao obrigatorias:** Todo calculo de P&L DEVE incluir fees. O Risk Calculator e o guardiao disso.
3. **Cada engine e independente:** Deve funcionar sozinho. Confluencia e bonus, nao requisito.
4. **Alvos dinamicos:** Cada engine define seus proprios TP/SL baseado no contexto do setup.
5. **Trailing stop:** Implementar como opcao em todos engines. Especialmente util no Momentum Burst.
6. **Logging:** Todo signal gerado (aceito ou rejeitado) deve ser logado no SQLite com metadata completa.
7. **Compatibilidade:** Usar a dataclass `Signal` de `signal_types.py`. Novos campos vao no `metadata` dict.
8. **Separacao de capital:** O sistema 1-min tem seu proprio capital isolado.
9. **Memoria no Pi:** Live: ultimas 200 candles por simbolo (~300KB total). Backtest: chunks de 1 dia.
10. **Paper primeiro, SEMPRE:** Nenhum trade real ate paper trading validar por no minimo 1 semana.
11. **Processo separado:** main_1m.py roda como 3o processo no supervisor, ciclo de ~10s.
