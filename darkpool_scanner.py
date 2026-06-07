"""
Dark Pool Scanner — detecta entradas institucionales de alta probabilidad.

Filtros de calidad aplicados:
  1. Clustering: acumula prints por ticker en ventana de 10 min.
     Solo alerta cuando el total supera CLUSTER_THRESHOLD.
  2. Solo ABOVE_ASK (compra agresiva) o BELOW_BID (venta agresiva).
  3. Mínimo de shares por print para evitar acciones de precio alto con poco volumen.
  4. Horario: solo entre 10:00 AM y 3:30 PM ET (ignora ruido de apertura/cierre).
  5. Deduplicación: no repite alerta del mismo ticker en menos de 30 min.
"""

import aiohttp
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from collections import defaultdict

BASE_URL = "https://api.quantdata.us"
ET = ZoneInfo("America/New_York")

# ── Umbrales ──────────────────────────────────────────
MIN_NOTIONAL_PER_PRINT = 5_000_000    # $5M por print individual
MIN_SHARES_PER_PRINT   = 25_000       # mínimo de acciones por print
CLUSTER_THRESHOLD      = 20_000_000   # $20M acumulados en 10 min → alerta
CLUSTER_WINDOW_MIN     = 10           # ventana de clustering en minutos
ALERT_COOLDOWN_MIN     = 30           # no repetir alerta del mismo ticker antes de 30 min

# Horario válido (ET)
VALID_START = time(9, 30)
VALID_END   = time(15, 55)

# ── Estado de sesión ───────────────────────────────────
_seen_ids: set = set()
_clusters: dict = defaultdict(list)           # ticker → [{"notional", "side", "time"}]
_last_alert_time: dict = {}                   # ticker → datetime de última alerta


def reset_session():
    """Llamar al inicio de cada sesión (9:25 AM ET)."""
    global _seen_ids, _clusters, _last_alert_time
    _seen_ids = set()
    _clusters = defaultdict(list)
    _last_alert_time = {}


def _now_et() -> datetime:
    return datetime.now(ET)


def _in_valid_hours() -> bool:
    t = _now_et().time()
    return VALID_START <= t <= VALID_END


def _trade_side_label(side: str) -> str:
    return {
        "ABOVE_ASK": "compra agresiva ↑",
        "BELOW_BID":  "venta agresiva ↓",
    }.get(side, side)


def _interpretation(side: str, ticker: str, total_m: float) -> str:
    if side == "ABOVE_ASK":
        return (f"📊 Institucional acumulando **{ticker}** — "
                f"${total_m}M en dark pool · posible movimiento alcista")
    return (f"📊 Institucional distribuyendo **{ticker}** — "
            f"${total_m}M en dark pool · posible presión bajista")


def _format_alert(ticker: str, side: str, cluster: list) -> str:
    total_notional = sum(p["notional"] for p in cluster)
    total_shares   = sum(p["shares"] for p in cluster)
    avg_price      = sum(p["price"] * p["notional"] for p in cluster) / total_notional
    n_prints       = len(cluster)
    total_m        = round(total_notional / 1_000_000, 1)
    shares_k       = f"{round(total_shares / 1000, 1)}K"
    side_label     = _trade_side_label(side)
    interp         = _interpretation(side, ticker, total_m)

    prints_tag = f" · {n_prints} prints" if n_prints > 1 else ""

    return (
        f"🏦 **DARK POOL INSTITUCIONAL** | **{ticker}**{prints_tag}\n"
        f"💰 **${total_m}M** · {shares_k} acciones a ~${avg_price:.2f}\n"
        f"⚡ {side_label}\n"
        f"{interp}"
    )


async def fetch_large_prints(session: aiohttp.ClientSession, api_key: str) -> list:
    """Trae todos los prints dark pool direccionales grandes del mercado completo."""
    today = date.today().isoformat()
    url   = f"{BASE_URL}/v1/equities/tool/equity-prints"
    body  = {
        "sessionDate": today,
        "filter": {
            "equityPrintTypes":  ["DARK_POOL"],
            "tradeSideCodes":    ["ABOVE_ASK", "BELOW_BID"],
            "notionalValueRange": {"min": MIN_NOTIONAL_PER_PRINT},
            "sizeRange":          {"min": MIN_SHARES_PER_PRINT},
        },
        "sort":     {"field": "tradeTime", "direction": "DESCENDING"},
        "size":     100,
        "includes": ["ID", "TICKER", "PRICE", "SIZE", "NOTIONAL_VALUE",
                     "PRINT_TYPE", "TRADE_SIDE", "TRADE_TIME"],
    }
    try:
        async with session.post(
            url, json=body,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data.get("data", [])
    except Exception as e:
        print(f"[DarkPool] Error fetch: {e}")
        return []


async def scan_and_alert(api_key: str, webhook_url: str,
                          session: aiohttp.ClientSession) -> int:
    """
    Acumula prints nuevos en clusters por ticker.
    Alerta cuando el cluster supera CLUSTER_THRESHOLD en la ventana de tiempo.
    """
    global _seen_ids, _clusters, _last_alert_time

    if not _in_valid_hours():
        return 0

    prints = await fetch_large_prints(session, api_key)
    now    = _now_et()
    alerts_sent = 0

    # Agregar prints nuevos al cluster de su ticker
    for p in prints:
        pid = p.get("id")
        if not pid or pid in _seen_ids:
            continue
        _seen_ids.add(pid)

        ticker = p.get("ticker", "")
        side   = p.get("tradeSide", "")
        if not ticker or side not in ("ABOVE_ASK", "BELOW_BID"):
            continue

        _clusters[ticker].append({
            "notional": p.get("notionalValue", 0),
            "shares":   p.get("size", 0),
            "price":    p.get("price", 0),
            "side":     side,
            "time":     now,
        })

    # Revisar clusters: alertar si supera el umbral y no está en cooldown
    tickers_to_alert = []
    for ticker, cluster in list(_clusters.items()):
        # Limpiar prints fuera de la ventana de tiempo
        cutoff = now.replace(tzinfo=ET) if now.tzinfo else now
        active = [p for p in cluster
                  if (now - p["time"]).total_seconds() <= CLUSTER_WINDOW_MIN * 60]
        _clusters[ticker] = active

        if not active:
            continue

        # Verificar que todos los prints activos sean del mismo lado (ABOVE o BELOW)
        sides = {p["side"] for p in active}
        if len(sides) != 1:
            continue  # señales mixtas = no es direccional

        total_notional = sum(p["notional"] for p in active)
        if total_notional < CLUSTER_THRESHOLD:
            continue

        # Cooldown: no repetir alerta del mismo ticker antes de ALERT_COOLDOWN_MIN
        last = _last_alert_time.get(ticker)
        if last and (now - last).total_seconds() < ALERT_COOLDOWN_MIN * 60:
            continue

        tickers_to_alert.append((ticker, list(sides)[0], active))
        _last_alert_time[ticker] = now
        _clusters[ticker] = []  # resetear cluster tras alertar

    # Enviar alertas
    for ticker, side, cluster in tickers_to_alert:
        msg = _format_alert(ticker, side, cluster)
        try:
            async with session.post(
                webhook_url,
                json={"content": msg},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status in (200, 204):
                    total_m = round(sum(p["notional"] for p in cluster) / 1_000_000, 1)
                    print(f"[DarkPool] ALERTA {ticker} ${total_m}M {side} "
                          f"({len(cluster)} prints)")
                    alerts_sent += 1
        except Exception as e:
            print(f"[DarkPool] Error webhook {ticker}: {e}")

    return alerts_sent
