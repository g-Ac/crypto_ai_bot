"""
Modulo centralizado de coleta de dados de microestrutura de mercado.

Coleta funding rate, long/short ratio, liquidacoes (proxy), open interest,
basis spread e sessao de mercado via Binance Futures API.
Cache em memoria com TTL de 30s. Retry com backoff exponencial.

Limitacoes conhecidas:
- get_liquidations() usa proxy via aggTrades (volume extremo ≈ liquidacao).
  O endpoint real /fapi/v1/forceOrders requer autenticacao USER_DATA.
  Precisao estimada: ~70%. Para dados exatos, usar WebSocket
  stream forceOrder@{symbol} (nao implementado ainda).
- Funding rate historico vem de /fapi/v1/fundingRate (3 ultimos periodos).
"""
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger("market_data")

# ── Base URLs ────────────────────────────────────────────────────────────────
FAPI_BASE = "https://fapi.binance.com"
SPOT_BASE = "https://api.binance.com"

# ── Cache ────────────────────────────────────────────────────────────────────
_cache: Dict[str, Tuple[float, dict]] = {}
_CACHE_TTL = 30  # seconds


def clear_cache() -> None:
    """Limpa todo o cache. Chamar no inicio de cada ciclo se necessario."""
    _cache.clear()


def _get_cached(key: str) -> Optional[dict]:
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return data
    return None


def _set_cache(key: str, data: dict) -> None:
    _cache[key] = (time.time(), data)


# ── Retry / Backoff ──────────────────────────────────────────────────────────
_MAX_RETRIES = 3


def _backoff_delay(attempt: int, response: Optional[requests.Response] = None) -> float:
    if response is not None and response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(int(retry_after), 60)
            except ValueError:
                pass
        return min(2 ** (attempt + 1), 30)
    return min(2 ** attempt, 10)


def _api_get(url: str, params: Optional[dict] = None, timeout: int = 10) -> Optional:
    """GET request with retry and backoff. Returns parsed JSON or None."""
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
            logger.warning("API %s retornou %d (attempt %d)", url, resp.status_code, attempt + 1)
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_backoff_delay(attempt, resp))
        except requests.RequestException as e:
            logger.warning("API %s erro: %s (attempt %d)", url, e, attempt + 1)
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_backoff_delay(attempt))
    return None


# ── Data Collection Functions ────────────────────────────────────────────────

def get_funding_rate(symbol: str) -> Dict:
    """Retorna funding rate atual e 2 periodos anteriores.

    Usa GET /fapi/v1/fundingRate?symbol={symbol}&limit=3 para historico real.

    Returns:
        {
            "funding_rate": float,       # taxa do periodo mais recente
            "funding_rate_prev1": float,  # taxa 1 periodo atras (~8h)
            "funding_rate_prev2": float,  # taxa 2 periodos atras (~16h)
            "next_funding_time": str,     # ISO timestamp do proximo pagamento
        }
    """
    cache_key = f"funding:{symbol}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    default = {
        "funding_rate": 0.0, "funding_rate_prev1": 0.0,
        "funding_rate_prev2": 0.0, "next_funding_time": "",
    }

    # Historico de funding (3 ultimos periodos, endpoint publico)
    hist = _api_get(
        f"{FAPI_BASE}/fapi/v1/fundingRate",
        {"symbol": symbol, "limit": 3},
    )
    if hist and isinstance(hist, list) and len(hist) > 0:
        # API retorna mais antigo primeiro, mais recente por ultimo
        rates = [float(r.get("fundingRate", 0)) for r in hist]
        default["funding_rate"] = rates[-1]
        if len(rates) >= 2:
            default["funding_rate_prev1"] = rates[-2]
        if len(rates) >= 3:
            default["funding_rate_prev2"] = rates[-3]

    # next_funding_time vem do premiumIndex (endpoint separado)
    premium = _api_get(f"{FAPI_BASE}/fapi/v1/premiumIndex", {"symbol": symbol})
    if premium and premium.get("nextFundingTime"):
        default["next_funding_time"] = datetime.fromtimestamp(
            int(premium["nextFundingTime"]) / 1000, tz=timezone.utc
        ).isoformat()

    _set_cache(cache_key, default)
    return default


def get_long_short_ratio(symbol: str, period: str = "5m") -> Dict:
    """Retorna long/short ratio de top traders e global.

    Args:
        symbol: Par de trading (ex: BTCUSDT)
        period: Periodo (5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d)

    Returns:
        {
            "ls_ratio_top": float,     # L/S ratio top traders (>1 = mais longs)
            "ls_ratio_global": float,  # L/S ratio global
        }
    """
    cache_key = f"lsratio:{symbol}:{period}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    result = {"ls_ratio_top": 1.0, "ls_ratio_global": 1.0}

    # Top traders L/S ratio
    top_data = _api_get(
        f"{FAPI_BASE}/futures/data/topLongShortAccountRatio",
        {"symbol": symbol, "period": period, "limit": 1},
    )
    if top_data and isinstance(top_data, list) and len(top_data) > 0:
        result["ls_ratio_top"] = float(top_data[0].get("longShortRatio", 1.0))

    # Global L/S ratio
    global_data = _api_get(
        f"{FAPI_BASE}/futures/data/globalLongShortAccountRatio",
        {"symbol": symbol, "period": period, "limit": 1},
    )
    if global_data and isinstance(global_data, list) and len(global_data) > 0:
        result["ls_ratio_global"] = float(global_data[0].get("longShortRatio", 1.0))

    _set_cache(cache_key, result)
    return result


def get_liquidations(symbol: str, limit: int = 100) -> Dict:
    """Estima volume de liquidacoes via proxy de aggTrades com volume extremo.

    NOTA: O endpoint real /fapi/v1/forceOrders requer autenticacao USER_DATA
    (API key + signature) e retorna 401 sem ela. Este metodo usa uma
    heuristica: trades recentes com qty > 10x a media sao classificados
    como provaveis liquidacoes (~70% de precisao estimada).

    Para dados exatos de liquidacao, implementar WebSocket stream
    forceOrder@{symbol} em versao futura.

    Returns:
        {
            "liquidation_vol_long": float,   # volume USD estimado (liq de longs = seller)
            "liquidation_vol_short": float,  # volume USD estimado (liq de shorts = buyer)
            "count": int,                    # qtd de trades extremos detectados
            "is_proxy": True,                # SEMPRE True neste metodo
        }
    """
    cache_key = f"liquidations:{symbol}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    default = {
        "liquidation_vol_long": 0.0, "liquidation_vol_short": 0.0,
        "count": 0, "is_proxy": True,
    }

    data = _api_get(
        f"{FAPI_BASE}/fapi/v1/aggTrades",
        {"symbol": symbol, "limit": limit},
    )
    if data is None or not isinstance(data, list) or len(data) < 20:
        logger.warning("Falha ao obter aggTrades para proxy de liquidacoes: %s", symbol)
        return default

    # Calcular media de qty para baseline
    quantities = [float(t.get("q", 0)) for t in data]
    avg_qty = sum(quantities) / len(quantities) if quantities else 0.0
    if avg_qty <= 0:
        return default

    threshold = avg_qty * 10  # trades > 10x a media = provaveis liquidacoes

    vol_long = 0.0   # liquidacao de long = isMakerBuy=false (seller aggressor, taker vende)
    vol_short = 0.0  # liquidacao de short = isMakerBuy=true (buyer aggressor, taker compra)
    count = 0

    for trade in data:
        qty = float(trade.get("q", 0))
        if qty < threshold:
            continue

        price = float(trade.get("p", 0))
        notional = qty * price
        count += 1

        # isMakerBuy (campo "m"): true = buyer is maker, seller is taker (sell aggressor)
        # Liquidacao de LONG = venda forcada = seller e taker (m=true)
        # Liquidacao de SHORT = compra forcada = buyer e taker (m=false)
        is_maker_buyer = trade.get("m", False)
        if is_maker_buyer:
            vol_long += notional
        else:
            vol_short += notional

    result = {
        "liquidation_vol_long": round(vol_long, 2),
        "liquidation_vol_short": round(vol_short, 2),
        "count": count,
        "is_proxy": True,
    }

    if count > 0:
        logger.info(
            "LIQ PROXY %s: %d trades extremos (>%.1fx media), "
            "vol_long=$%.0f vol_short=$%.0f",
            symbol, count, 10.0, vol_long, vol_short,
        )

    _set_cache(cache_key, result)
    return result


def get_open_interest(symbol: str) -> Dict:
    """Retorna open interest atual e variacao percentual recente.

    Returns:
        {
            "open_interest": float,       # OI em contratos
            "oi_change_1h_pct": float,    # variacao % 1h (requer historico)
            "oi_change_4h_pct": float,    # variacao % 4h (requer historico)
        }
    """
    cache_key = f"oi:{symbol}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    result = {"open_interest": 0.0, "oi_change_1h_pct": 0.0, "oi_change_4h_pct": 0.0}

    # OI atual
    oi_data = _api_get(f"{FAPI_BASE}/fapi/v1/openInterest", {"symbol": symbol})
    if oi_data:
        result["open_interest"] = float(oi_data.get("openInterest", 0))

    # OI historico para calcular variacao
    hist_data = _api_get(
        f"{FAPI_BASE}/futures/data/openInterestHist",
        {"symbol": symbol, "period": "1h", "limit": 5},
    )
    if hist_data and isinstance(hist_data, list) and len(hist_data) >= 2:
        current_oi = float(hist_data[-1].get("sumOpenInterest", 0))

        # Variacao 1h (penultimo vs ultimo)
        prev_1h = float(hist_data[-2].get("sumOpenInterest", 0))
        if prev_1h > 0:
            result["oi_change_1h_pct"] = round((current_oi - prev_1h) / prev_1h * 100, 2)

        # Variacao 4h (4 periodos atras vs ultimo, se disponivel)
        if len(hist_data) >= 5:
            prev_4h = float(hist_data[0].get("sumOpenInterest", 0))
            if prev_4h > 0:
                result["oi_change_4h_pct"] = round((current_oi - prev_4h) / prev_4h * 100, 2)

    _set_cache(cache_key, result)
    return result


def get_basis_spread(symbol: str) -> Dict:
    """Calcula basis spread (futures premium vs spot) em percentual.

    Returns:
        {
            "basis_spread_pct": float,  # (futures - spot) / spot * 100
            "futures_price": float,
            "spot_price": float,
        }
    """
    cache_key = f"basis:{symbol}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    result = {"basis_spread_pct": 0.0, "futures_price": 0.0, "spot_price": 0.0}

    # Preco futures
    fut_data = _api_get(f"{FAPI_BASE}/fapi/v1/ticker/price", {"symbol": symbol})
    if fut_data:
        result["futures_price"] = float(fut_data.get("price", 0))

    # Preco spot
    spot_data = _api_get(f"{SPOT_BASE}/api/v3/ticker/price", {"symbol": symbol})
    if spot_data:
        result["spot_price"] = float(spot_data.get("price", 0))

    # Basis spread
    if result["spot_price"] > 0 and result["futures_price"] > 0:
        result["basis_spread_pct"] = round(
            (result["futures_price"] - result["spot_price"]) / result["spot_price"] * 100,
            4,
        )

    _set_cache(cache_key, result)
    return result


def get_market_session() -> str:
    """Classifica a sessao de mercado atual baseado no horario UTC.

    Returns:
        "asia"    (00:00 - 08:00 UTC)
        "europe"  (08:00 - 14:00 UTC)
        "us"      (14:00 - 21:00 UTC)
        "dead"    (21:00 - 00:00 UTC)
    """
    hour = datetime.now(timezone.utc).hour
    if 0 <= hour < 8:
        return "asia"
    elif 8 <= hour < 14:
        return "europe"
    elif 14 <= hour < 21:
        return "us"
    else:
        return "dead"


# ── Aggregate Collector ──────────────────────────────────────────────────────

def collect_microstructure(symbol: str) -> Dict:
    """Coleta todos os dados de microestrutura para um symbol.

    Agrega funding, L/S ratio, liquidacoes (proxy), OI, basis e sessao
    em um unico dict pronto para insert no banco.

    Returns:
        Dict com todas as colunas da tabela market_microstructure
        + campos extras (futures_price, spot_price, is_proxy) usados pelos motores.
    """
    funding = get_funding_rate(symbol)
    ls_ratio = get_long_short_ratio(symbol)
    liquidations = get_liquidations(symbol)
    oi = get_open_interest(symbol)
    basis = get_basis_spread(symbol)
    session = get_market_session()

    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "funding_rate": funding["funding_rate"],
        "funding_rate_prev1": funding["funding_rate_prev1"],
        "funding_rate_prev2": funding["funding_rate_prev2"],
        "next_funding_time": funding["next_funding_time"],
        "ls_ratio_top": ls_ratio["ls_ratio_top"],
        "ls_ratio_global": ls_ratio["ls_ratio_global"],
        "liquidation_vol_long": liquidations["liquidation_vol_long"],
        "liquidation_vol_short": liquidations["liquidation_vol_short"],
        "liquidation_count": liquidations["count"],
        "liquidation_is_proxy": liquidations["is_proxy"],
        "open_interest": oi["open_interest"],
        "oi_change_1h_pct": oi["oi_change_1h_pct"],
        "oi_change_4h_pct": oi["oi_change_4h_pct"],
        "basis_spread_pct": basis["basis_spread_pct"],
        "futures_price": basis["futures_price"],
        "spot_price": basis["spot_price"],
        "session": session,
    }
