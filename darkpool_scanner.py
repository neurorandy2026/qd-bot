"""
Dark Pool Scanner — detecta entradas institucionales grandes en cualquier empresa.

Llama a equity-prints sin ticker, filtrando solo DARK_POOL > MIN_NOTIONAL.
Una sola llamada cubre todo el mercado. Alerta a Discord cuando aparece
un print nuevo que no se ha notificado en la sesión actual.
"""

import aiohttp
from datetime import date

BASE_URL = "https://api.quantdata.us"

# Umbral mínimo para alertar (en dólares)
MIN_NOTIONAL = 5_000_000   # $5M

# IDs ya notificados en la sesión (se resetea en apertura)
_seen_ids: set = set()


def reset_session():
    """Llamar al inicio de cada sesión (9:25 AM ET)."""
    global _seen_ids
    _seen_ids = set()


def _trade_side_label(side: str) -> str:
    return {
        "ABOVE_ASK": "compra agresiva ↑",
        "BELOW_BID":  "venta agresiva ↓",
        "ASK":        "compra en ask",
        "BID":        "venta en bid",
        "MID_MARKET": "cruce neutral",
    }.get(side, side)


def _interpretation(side: str, ticker: str) -> str:
    if side == "ABOVE_ASK":
        return f"📊 Institucional acumulando {ticker} en silencio — posible movimiento alcista"
    if side == "BELOW_BID":
        return f"📊 Institucional distribuyendo {ticker} — posible presión bajista"
    return f"📊 Actividad institucional en {ticker} fuera de mercado"


def _format_alert(print_data: dict) -> str:
    ticker    = print_data.get("ticker", "???")
    price     = print_data.get("price", 0)
    size      = print_data.get("size", 0)
    notional  = print_data.get("notionalValue", 0)
    side      = print_data.get("tradeSide", "")
    ptype     = print_data.get("printType", "DARK_POOL")

    notional_m = round(notional / 1_000_000, 1)
    size_k     = f"{round(size / 1000, 1)}K" if size >= 1000 else str(size)
    side_label = _trade_side_label(side)
    interp     = _interpretation(side, ticker)
    venue      = "Dark Pool" if ptype == "DARK_POOL" else "Lit Pool"

    return (
        f"🏦 **{venue.upper()} INSTITUCIONAL** | **{ticker}**\n"
        f"💰 **${notional_m}M** · {size_k} acciones a ${price:.2f}\n"
        f"⚡ {side_label}\n"
        f"{interp}"
    )


async def fetch_large_prints(session: aiohttp.ClientSession, api_key: str) -> list:
    """Consulta equity-prints sin ticker — devuelve todos los prints grandes del mercado."""
    today = date.today().isoformat()
    url   = f"{BASE_URL}/v1/equities/tool/equity-prints"
    body  = {
        "sessionDate": today,
        "filter": {
            "equityPrintTypes": ["DARK_POOL"],
            "notionalValueRange": {"min": MIN_NOTIONAL},
            "tradeSideCodes": ["ABOVE_ASK", "BELOW_BID"],  # solo señales direccionales
        },
        "sort":  {"field": "tradeTime", "direction": "DESCENDING"},
        "size":  100,
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
    Detecta prints nuevos y envía alertas a Discord.
    Retorna el número de alertas enviadas.
    """
    global _seen_ids

    prints = await fetch_large_prints(session, api_key)
    alerts_sent = 0

    for p in prints:
        pid = p.get("id")
        if not pid or pid in _seen_ids:
            continue

        _seen_ids.add(pid)
        msg = _format_alert(p)

        try:
            async with session.post(
                webhook_url,
                json={"content": msg},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status in (200, 204):
                    ticker   = p.get("ticker", "?")
                    notional = round(p.get("notionalValue", 0) / 1_000_000, 1)
                    side     = p.get("tradeSide", "")
                    print(f"[DarkPool] {ticker} ${notional}M {side}")
                    alerts_sent += 1
        except Exception as e:
            print(f"[DarkPool] Error webhook: {e}")

    return alerts_sent
