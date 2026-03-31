"""
Filtro de noticias e eventos economicos para o sistema de scalping.

Bloqueia operacoes proximas a eventos macroeconomicos programados
(FOMC, CPI, PPI, NFP, etc.) que causam volatilidade extrema e
invalidam sinais tecnicos.

Regra da estrategia: "Volume spike ocorreu dentro de 3 candles
de uma noticia programada — nao operar."

Dependencias: apenas stdlib + requests (opcional, para Binance announcements).
"""
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("scalping.news_filter")

# Timeout curto para nao travar o loop no Pi
_REQUEST_TIMEOUT = 5


# ============================================================
#  DATACLASS DE EVENTO
# ============================================================

@dataclass(frozen=True)
class EconomicEvent:
    """Evento economico programado."""
    name: str
    # dia_do_mes: None = todo mes, int = dia especifico
    # weekday: None = qualquer, 0=seg..6=dom
    # Para eventos tipo "primeira sexta do mes" usamos week_of_month + weekday
    hour: int           # hora UTC
    minute: int         # minuto UTC
    # Recorrencia mensal
    day: Optional[int] = None          # dia fixo do mes (ex: CPI sempre ~13)
    weekday: Optional[int] = None      # 0=seg, 4=sex
    week_of_month: Optional[int] = None  # 1=primeira semana, etc.
    # Meses em que ocorre (None = todos)
    months: Optional[tuple] = None
    # Intervalo em semanas para FOMC (a cada ~6 semanas, usamos datas fixas)
    fixed_dates: Optional[tuple] = None  # tuplas (mes, dia) para o ano corrente


# ============================================================
#  CALENDARIO DE EVENTOS RECORRENTES (2026)
# ============================================================

# FOMC: 8 reunioes/ano em datas fixas. Decisao as 18:00 UTC (2pm ET).
# Atualizamos as datas todo inicio de ano — sao publicadas com antecedencia.
FOMC_2026_DATES = (
    (1, 28), (1, 29),    # Jan 28-29
    (3, 17), (3, 18),    # Mar 17-18
    (5, 5), (5, 6),      # May 5-6
    (6, 16), (6, 17),    # Jun 16-17
    (7, 28), (7, 29),    # Jul 28-29
    (9, 15), (9, 16),    # Sep 15-16
    (10, 27), (10, 28),  # Oct 27-28
    (12, 15), (12, 16),  # Dec 15-16
)

# Eventos recorrentes com horario tipico UTC
RECURRING_EVENTS: list[EconomicEvent] = [
    # --- CPI (Consumer Price Index) ---
    # Geralmente segunda ou terceira semana do mes, 12:30 UTC (8:30 ET)
    # Cobrimos dia 10-15 de cada mes como janela tipica
    EconomicEvent(
        name="CPI (Consumer Price Index)",
        hour=12, minute=30,
        week_of_month=2, weekday=1,  # ~segunda terca do mes
    ),

    # --- PPI (Producer Price Index) ---
    # Geralmente 1-2 dias apos CPI, 12:30 UTC
    EconomicEvent(
        name="PPI (Producer Price Index)",
        hour=12, minute=30,
        week_of_month=2, weekday=3,  # ~segunda quinta do mes
    ),

    # --- NFP (Non-Farm Payrolls) ---
    # Primeira sexta-feira do mes, 12:30 UTC
    EconomicEvent(
        name="NFP (Non-Farm Payrolls)",
        hour=12, minute=30,
        week_of_month=1, weekday=4,  # primeira sexta
    ),

    # --- Unemployment Claims (semanal) ---
    # Toda quinta-feira, 12:30 UTC — impacto menor, janela curta
    EconomicEvent(
        name="Weekly Jobless Claims",
        hour=12, minute=30,
        weekday=3,  # toda quinta
    ),

    # --- PCE (Personal Consumption Expenditures) ---
    # Ultima sexta do mes, 12:30 UTC — metrica favorita do Fed
    EconomicEvent(
        name="PCE Price Index",
        hour=12, minute=30,
        week_of_month=4, weekday=4,  # ~quarta sexta do mes
    ),

    # --- FOMC Minutes ---
    # ~3 semanas apos cada reuniao, 18:00 UTC
    # Dificil prever exato, marcamos terceira quarta do mes de ata
    EconomicEvent(
        name="FOMC Minutes",
        hour=18, minute=0,
        week_of_month=3, weekday=2,  # ~terceira quarta
        months=(2, 4, 6, 7, 9, 11),  # meses apos reunioes
    ),

    # --- ISM Manufacturing PMI ---
    # Primeiro dia util do mes, 14:00 UTC
    EconomicEvent(
        name="ISM Manufacturing PMI",
        hour=14, minute=0,
        day=1,
    ),

    # --- Retail Sales ---
    # ~15 do mes, 12:30 UTC
    EconomicEvent(
        name="Retail Sales",
        hour=12, minute=30,
        week_of_month=3, weekday=1,  # ~terceira terca
    ),
]


# ============================================================
#  LOGICA DE MATCHING
# ============================================================

def _get_week_of_month(dt: datetime) -> int:
    """Retorna a semana do mes (1-5) para uma data."""
    return (dt.day - 1) // 7 + 1


def _is_fomc_day(now: datetime) -> Optional[str]:
    """Verifica se hoje e dia de decisao FOMC (segundo dia da reuniao)."""
    month, day = now.month, now.day
    for m, d in FOMC_2026_DATES:
        if month == m and day == d:
            return "FOMC Decision Day"
    return None


def _match_recurring_event(now: datetime, event: EconomicEvent) -> bool:
    """Verifica se um evento recorrente cai no dia atual."""
    # Filtro de meses
    if event.months and now.month not in event.months:
        return False

    # Dia fixo do mes
    if event.day is not None:
        # Permite +/- 1 dia porque dia 1 pode cair em fds
        return abs(now.day - event.day) <= 1

    # weekday + week_of_month
    if event.weekday is not None and now.weekday() != event.weekday:
        return False

    if event.week_of_month is not None:
        if _get_week_of_month(now) != event.week_of_month:
            return False

    # Se weekday definido sem week_of_month = evento semanal
    if event.weekday is not None and event.week_of_month is None:
        return True

    # Se week_of_month definido e weekday bateu
    if event.week_of_month is not None:
        return True

    return False


def _get_event_time(now: datetime, event: EconomicEvent) -> datetime:
    """Retorna o datetime do evento para o dia atual."""
    return now.replace(hour=event.hour, minute=event.minute, second=0, microsecond=0)


# ============================================================
#  CACHE DO BINANCE ANNOUNCEMENTS (OPCIONAL)
# ============================================================

_binance_cache: dict = {
    "last_fetch": None,
    "events": [],
}

# Intervalo minimo entre fetches (evitar rate limit)
_BINANCE_CACHE_TTL = timedelta(hours=1)


def _fetch_binance_announcements() -> list[dict]:
    """
    Busca anuncios recentes da Binance (manutencoes, listings, etc.).

    Retorna lista de dicts com 'title' e 'releaseDate'.
    Falha silenciosamente se a API nao responder.
    """
    now = datetime.now(timezone.utc)

    # Usar cache se ainda valido
    if (_binance_cache["last_fetch"] is not None
            and now - _binance_cache["last_fetch"] < _BINANCE_CACHE_TTL):
        return _binance_cache["events"]

    try:
        import requests
        # Endpoint publico de anuncios da Binance
        url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
        params = {
            "type": 1,          # anuncios gerais
            "catalogId": 48,    # system maintenance / announcements
            "pageNo": 1,
            "pageSize": 5,
        }
        resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)

        if resp.status_code == 200:
            data = resp.json()
            articles = data.get("data", {}).get("catalogs", [{}])
            events = []
            for catalog in articles:
                for article in catalog.get("articles", []):
                    events.append({
                        "title": article.get("title", ""),
                        "releaseDate": article.get("releaseDate", 0),
                    })
            _binance_cache["events"] = events
            _binance_cache["last_fetch"] = now
            logger.debug("Binance announcements atualizados: %d items", len(events))
            return events

    except Exception as e:
        logger.debug("Binance announcements indisponiveis: %s", e)

    return _binance_cache["events"]  # retorna cache antigo se falhar


def _check_binance_maintenance() -> Optional[str]:
    """
    Verifica se ha anuncio de manutencao recente da Binance.

    Retorna titulo do anuncio se encontrar manutencao nas ultimas 24h, None caso contrario.
    """
    events = _fetch_binance_announcements()
    if not events:
        return None

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    one_day_ms = 24 * 60 * 60 * 1000

    keywords = ("maintenance", "manutenção", "upgrade", "system", "suspend", "wallet")

    for event in events:
        title = event.get("title", "").lower()
        release_ms = event.get("releaseDate", 0)

        # Anuncio recente (24h) com keyword de manutencao
        if (now_ms - release_ms < one_day_ms
                and any(kw in title for kw in keywords)):
            return event.get("title", "Binance maintenance")

    return None


# ============================================================
#  API PUBLICA
# ============================================================

def is_near_news_event(
    minutes_before: int = 15,
    minutes_after: int = 10,
) -> tuple[bool, str]:
    """
    Verifica se o momento atual esta proximo de um evento economico programado.

    Parametros:
        minutes_before: minutos antes do evento para comecar a bloquear
        minutes_after: minutos apos o evento para continuar bloqueando

    Retorna:
        (is_blocked, reason) — True + descricao se estamos na zona de bloqueio
    """
    now = datetime.now(timezone.utc)

    # 1. Verificar FOMC (datas fixas, 18:00 UTC)
    fomc = _is_fomc_day(now)
    if fomc:
        fomc_time = now.replace(hour=18, minute=0, second=0, microsecond=0)
        delta = (now - fomc_time).total_seconds() / 60

        if -minutes_before <= delta <= minutes_after:
            reason = f"FOMC Decision: {minutes_before}min antes ate {minutes_after}min depois (delta: {delta:+.0f}min)"
            logger.warning("NEWS FILTER BLOQUEIO: %s", reason)
            return True, reason

        # FOMC dia inteiro e arriscado — bloquear janela mais ampla (2h antes)
        if -120 <= delta <= minutes_after:
            reason = f"FOMC Decision Day: janela ampliada 2h antes (delta: {delta:+.0f}min)"
            logger.warning("NEWS FILTER BLOQUEIO: %s", reason)
            return True, reason

    # 2. Verificar eventos recorrentes
    for event in RECURRING_EVENTS:
        if not _match_recurring_event(now, event):
            continue

        event_time = _get_event_time(now, event)
        delta = (now - event_time).total_seconds() / 60

        if -minutes_before <= delta <= minutes_after:
            reason = (
                f"{event.name}: {minutes_before}min antes ate "
                f"{minutes_after}min depois (delta: {delta:+.0f}min)"
            )
            logger.warning("NEWS FILTER BLOQUEIO: %s", reason)
            return True, reason

    # 3. Verificar manutencao Binance (opcional, falha silenciosa)
    maintenance = _check_binance_maintenance()
    if maintenance:
        reason = f"Binance Announcement: {maintenance}"
        logger.warning("NEWS FILTER ALERTA: %s", reason)
        return True, reason

    logger.debug("NEWS FILTER: nenhum evento proximo")
    return False, ""


def get_upcoming_events(hours_ahead: int = 24) -> list[dict]:
    """
    Lista eventos economicos previstos nas proximas N horas.

    Util para logging e alertas do Telegram.

    Retorna lista de dicts com 'name', 'time_utc', 'minutes_until'.
    """
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=hours_ahead)
    upcoming = []

    # FOMC
    for m, d in FOMC_2026_DATES:
        try:
            event_dt = now.replace(month=m, day=d, hour=18, minute=0, second=0, microsecond=0)
        except ValueError:
            continue
        if now <= event_dt <= cutoff:
            minutes_until = (event_dt - now).total_seconds() / 60
            upcoming.append({
                "name": "FOMC Decision",
                "time_utc": event_dt.isoformat(),
                "minutes_until": round(minutes_until),
            })

    # Eventos recorrentes — verificar hoje e amanha
    for day_offset in range(2):
        check_day = now + timedelta(days=day_offset)
        for event in RECURRING_EVENTS:
            if not _match_recurring_event(check_day, event):
                continue
            event_dt = _get_event_time(check_day, event)
            if now <= event_dt <= cutoff:
                minutes_until = (event_dt - now).total_seconds() / 60
                upcoming.append({
                    "name": event.name,
                    "time_utc": event_dt.isoformat(),
                    "minutes_until": round(minutes_until),
                })

    upcoming.sort(key=lambda x: x["minutes_until"])
    return upcoming


# ============================================================
#  TESTE RAPIDO
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    blocked, reason = is_near_news_event()
    print(f"Bloqueado: {blocked}")
    if reason:
        print(f"Motivo: {reason}")

    print("\nProximos eventos (24h):")
    for ev in get_upcoming_events(24):
        print(f"  {ev['name']} — {ev['time_utc']} ({ev['minutes_until']}min)")
