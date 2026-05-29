import asyncio
import aiohttp
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import config_manager
import qd_client
import analyzer as ana
import claude_client
import notifier
import dashboard
import stats

ET = ZoneInfo("America/New_York")
PRE_MARKET   = time(9, 25)   # Opening message 5 min before open
MARKET_OPEN  = time(9, 30)
MARKET_CLOSE = time(16, 0)

SCHEDULE_MINUTES = list(range(0, 60, 10))  # [0, 10, 20, 30, 40, 50]

_last_post_time: datetime = None
_last_analysis: dict = {}
_opening_sent = False
_closing_sent = False
_pre_market_sent = False


def _now_et() -> datetime:
    return datetime.now(ET)


def _is_weekday() -> bool:
    return _now_et().weekday() < 5


def _is_pre_market() -> bool:
    now = _now_et()
    return _is_weekday() and PRE_MARKET <= now.time() < MARKET_OPEN


def _is_market_open() -> bool:
    now = _now_et()
    return _is_weekday() and MARKET_OPEN <= now.time() < MARKET_CLOSE


def _is_closing_time() -> bool:
    now = _now_et()
    return _is_weekday() and MARKET_CLOSE <= now.time() < time(16, 5)


def _is_scheduled_slot() -> bool:
    """Returns True if current minute matches a 30-min schedule slot."""
    now = _now_et()
    return now.minute in SCHEDULE_MINUTES and now.second < 60


def _next_slot_time() -> str:
    now = _now_et()
    current_minutes = now.hour * 60 + now.minute
    # Find next slot strictly after now
    for m in SCHEDULE_MINUTES:
        slot_minutes = now.hour * 60 + m
        if slot_minutes > current_minutes:
            return now.replace(minute=m, second=0, microsecond=0).strftime("%I:%M %p")
    # Next hour first slot
    next_hour = (now + timedelta(hours=1)).replace(minute=SCHEDULE_MINUTES[0], second=0, microsecond=0)
    return next_hour.strftime("%I:%M %p")


async def _post_reading(ticker: str, analysis: dict, config: dict, tipo: str) -> None:
    global _last_post_time

    next_time = _next_slot_time()
    message = await claude_client.generate_reading(
        analysis=analysis,
        anthropic_api_key=config["anthropic_api_key"],
        next_time=next_time,
        tipo=tipo,
    )

    if message:
        ok = await notifier.send_webhook(config["discord"]["webhook_alumnos"], message)
        if ok:
            _last_post_time = datetime.now(ET)
            stats.record_lectura(ticker, analysis.get("price", 0), tipo, message)
            stats.set_active_levels(ticker, analysis.get("supports", []), analysis.get("resistances", []))
            dashboard.add_log(f"[{tipo.upper()}] {ticker} ${analysis.get('price', 0):.0f} → Discord ✅")
    else:
        dashboard.add_log(f"[ERROR] No se pudo generar lectura para {ticker}")


async def run_ticker(ticker: str, config: dict, session: aiohttp.ClientSession, tipo: str) -> None:
    global _last_analysis

    market_data = await qd_client.fetch_market_data(session, ticker, config["qd_api_key"])
    if not market_data.get("price"):
        print(f"[Monitor] Sin precio para {ticker}")
        return

    print(f"[Monitor] {ticker} ${market_data['price']:.2f}")
    analysis = ana.analyze(market_data)
    if not analysis:
        return

    # Immediate alert on significant change (between scheduled posts)
    prev = _last_analysis.get(ticker)
    if tipo == "lectura" and ana.detect_significant_change(prev, analysis):
        print(f"[Monitor] Cambio significativo en {ticker} — alerta inmediata")
        await _post_reading(ticker, analysis, config, "lectura")
    elif tipo in ("apertura", "cierre"):
        await _post_reading(ticker, analysis, config, tipo)
    else:
        await _post_reading(ticker, analysis, config, "lectura")

    _last_analysis[ticker] = analysis


async def manual_trigger(tipo: str = "lectura") -> None:
    """Called from dashboard to send an immediate reading."""
    config = config_manager.load()
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for ticker in config.get("tickers", ["SPY"]):
            await run_ticker(ticker, config, session, tipo)


async def monitor_loop() -> None:
    global _opening_sent, _closing_sent, _pre_market_sent, _last_post_time

    import os
    port = int(os.environ.get("PORT", 8080))
    await dashboard.start_dashboard(port)
    dashboard.set_trigger_callback(manual_trigger)
    dashboard.add_log("QD Bot iniciado")
    print("[Monitor] Iniciando loop QD Bot...")

    last_slot_checked = None

    while True:
        try:
            config = config_manager.load()
            now = _now_et()
            pre_market = _is_pre_market()
            market_open = _is_market_open()
            closing = _is_closing_time()

            status = 'PRE' if pre_market else 'ABIERTO' if market_open else 'CIERRE' if closing else 'CERRADO'
            print(f"[Monitor] {now.strftime('%H:%M:%S ET')} | {status}")

            timeout = aiohttp.ClientTimeout(total=20)
            tickers = config.get("tickers", ["SPY"])

            # 9:25 AM ET — Mensaje de apertura (5 min antes)
            if pre_market and not _pre_market_sent:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    for ticker in tickers:
                        await run_ticker(ticker, config, session, "apertura")
                _pre_market_sent = True
                _opening_sent = False
                _closing_sent = False

            # 9:30 AM ET — Primera lectura del día
            elif market_open and not _opening_sent:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    for ticker in tickers:
                        await run_ticker(ticker, config, session, "lectura")
                _opening_sent = True
                last_slot_checked = now.replace(second=0, microsecond=0)

            # 4:00 PM ET — Mensaje de cierre
            elif closing and _opening_sent and not _closing_sent:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    for ticker in tickers:
                        await run_ticker(ticker, config, session, "cierre")
                _closing_sent = True

            # 9:30–4:00 — Lecturas cada 10 min + alertas por cambio
            elif market_open and _opening_sent:
                current_slot = now.replace(second=0, microsecond=0)

                if _is_scheduled_slot() and current_slot != last_slot_checked:
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        for ticker in tickers:
                            await run_ticker(ticker, config, session, "lectura")
                            await asyncio.sleep(1)
                    last_slot_checked = current_slot
                else:
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        for ticker in tickers:
                            market_data = await qd_client.fetch_market_data(
                                session, ticker, config["qd_api_key"]
                            )
                            if market_data.get("price"):
                                analysis = ana.analyze(market_data)
                                prev = _last_analysis.get(ticker)
                                # Track level outcomes
                                if prev and market_data.get("price"):
                                    price = market_data["price"]
                                    for s in prev.get("supports", []):
                                        if s["dex_signal"] in ("preferido", "solido", "cuidado"):
                                            held = price >= s["strike"]
                                            stats.record_level_outcome(s["strike"], held, ticker)
                                if ana.detect_significant_change(prev, analysis):
                                    await _post_reading(ticker, analysis, config, "lectura")
                                _last_analysis[ticker] = analysis

            # Reset flags al final del día
            if not pre_market and not market_open and not closing:
                _pre_market_sent = False
                _opening_sent = False

        except Exception as e:
            print(f"[Monitor] Error: {e}")

        await asyncio.sleep(60)
