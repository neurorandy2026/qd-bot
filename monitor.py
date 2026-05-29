import asyncio
import aiohttp
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import config_manager
import qd_client
import analyzer as ana
import claude_client
import notifier

ET = ZoneInfo("America/New_York")
MARKET_OPEN  = time(9, 30)
MARKET_CLOSE = time(16, 0)

# Fixed 30-min schedule: 9:30, 10:00, 10:30 ... 15:30, 16:00
SCHEDULE_MINUTES = list(range(0, 60, 10))  # [0, 10, 20, 30, 40, 50]

_last_post_time: datetime = None
_last_analysis: dict = {}
_opening_sent = False
_closing_sent = False


def _now_et() -> datetime:
    return datetime.now(ET)


def _is_market_open() -> bool:
    now = _now_et()
    if now.weekday() >= 5:
        return False
    return MARKET_OPEN <= now.time() < MARKET_CLOSE


def _is_closing_time() -> bool:
    now = _now_et()
    if now.weekday() >= 5:
        return False
    return now.time() >= MARKET_CLOSE and now.time() < time(16, 5)


def _is_scheduled_slot() -> bool:
    """Returns True if current minute matches a 30-min schedule slot."""
    now = _now_et()
    return now.minute in SCHEDULE_MINUTES and now.second < 60


def _next_slot_time() -> str:
    now = _now_et()
    # Find next scheduled minute
    for m in SCHEDULE_MINUTES:
        if m > now.minute:
            next_dt = now.replace(minute=m, second=0)
            return next_dt.strftime("%I:%M %p")
    # Next hour
    next_dt = (now + timedelta(hours=1)).replace(minute=SCHEDULE_MINUTES[0], second=0)
    return next_dt.strftime("%I:%M %p")


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
            print(f"[Monitor] [{tipo.upper()}] Mensaje enviado para {ticker}")
    else:
        print(f"[Monitor] Error generando mensaje para {ticker}")


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


async def monitor_loop() -> None:
    global _opening_sent, _closing_sent, _last_post_time

    print("[Monitor] Iniciando loop QD Bot...")

    last_slot_checked = None

    while True:
        try:
            config = config_manager.load()
            now = _now_et()
            market_open = _is_market_open()
            closing = _is_closing_time()

            print(f"[Monitor] {now.strftime('%H:%M:%S ET')} | {'ABIERTO' if market_open else 'CERRADO'}")

            timeout = aiohttp.ClientTimeout(total=20)

            # Opening message — first slot 9:30
            if market_open and not _opening_sent:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    for ticker in config.get("tickers", ["SPY"]):
                        await run_ticker(ticker, config, session, "apertura")
                _opening_sent = True
                _closing_sent = False
                last_slot_checked = now.replace(second=0, microsecond=0)

            # Closing message — at 4:00 PM
            elif closing and _opening_sent and not _closing_sent:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    for ticker in config.get("tickers", ["SPY"]):
                        await run_ticker(ticker, config, session, "cierre")
                _closing_sent = True

            # Scheduled 30-min readings during market hours
            elif market_open and _opening_sent:
                current_slot = now.replace(second=0, microsecond=0)

                # Check if we're in a new 30-min slot
                if _is_scheduled_slot() and current_slot != last_slot_checked:
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        for ticker in config.get("tickers", ["SPY"]):
                            await run_ticker(ticker, config, session, "lectura")
                            await asyncio.sleep(1)
                    last_slot_checked = current_slot

                # Between slots: check for significant changes only
                else:
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        for ticker in config.get("tickers", ["SPY"]):
                            market_data = await qd_client.fetch_market_data(
                                session, ticker, config["qd_api_key"]
                            )
                            if market_data.get("price"):
                                analysis = ana.analyze(market_data)
                                prev = _last_analysis.get(ticker)
                                if ana.detect_significant_change(prev, analysis):
                                    await _post_reading(ticker, analysis, config, "lectura")
                                _last_analysis[ticker] = analysis

            # Reset opening flag after close
            if not market_open and not closing:
                _opening_sent = False

        except Exception as e:
            print(f"[Monitor] Error: {e}")

        await asyncio.sleep(60)
