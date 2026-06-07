import asyncio
import aiohttp
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import config_manager
import qd_client
import analyzer as ana
import claude_client
import lessons as ls
import notifier
import dashboard
import stats
import sunday_analysis

ET = ZoneInfo("America/New_York")
PRE_MARKET   = time(9, 25)
MARKET_OPEN  = time(9, 30)
MARKET_CLOSE = time(16, 0)

SCHEDULE_MINUTES = list(range(0, 60, 10))  # [0, 10, 20, 30, 40, 50]

# Sweep alert: minimum premium to trigger an immediate alert
SWEEP_ALERT_MIN_PREMIUM = 300_000   # $300K
SWEEP_ALERT_MIN_GOLDEN  = 100_000   # golden sweep always alerts if > $100K

_last_post_time: datetime = None
_last_analysis: dict = {}
_opening_sent   = False
_closing_sent   = False
_pre_market_sent = False
_seen_sweep_keys: set = set()   # fingerprints of already-alerted sweeps


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
    now = _now_et()
    return now.minute in SCHEDULE_MINUTES and now.second < 60


def _next_slot_time() -> str:
    now = _now_et()
    current_minutes = now.hour * 60 + now.minute
    for m in SCHEDULE_MINUTES:
        slot_minutes = now.hour * 60 + m
        if slot_minutes > current_minutes:
            return now.replace(minute=m, second=0, microsecond=0).strftime("%I:%M %p")
    next_hour = (now + timedelta(hours=1)).replace(minute=SCHEDULE_MINUTES[0],
                                                    second=0, microsecond=0)
    return next_hour.strftime("%I:%M %p")


# ─────────────────────────────────────────────
# SWEEP ALERT
# ─────────────────────────────────────────────

def _sweep_key(trade: dict) -> str:
    return f"{trade['type']}_{trade['contract']}_{trade['strike']}_{trade['exp']}_{trade['premium']}"


def _sweep_interpretation(trade: dict, ticker: str) -> str:
    contract = trade.get("contract", "")
    strike   = trade.get("strike")
    side     = trade.get("side", "")
    if not strike:
        return ""
    strike = int(strike)
    if contract == "CALL" and side == "ABOVE_ASK":
        return f"📊 Institucional apuesta al alza — posible movimiento hacia ${strike} o más arriba"
    if contract == "PUT" and side == "ABOVE_ASK":
        return f"📊 Institucional apuesta a la baja — posible movimiento hacia ${strike} o más abajo"
    if contract == "CALL" and side == "BELOW_BID":
        return f"📊 Venta de calls en ${strike} — posible techo o cobertura de posición larga"
    if contract == "PUT" and side == "BELOW_BID":
        return f"📊 Venta de puts en ${strike} — posible piso o acumulación institucional"
    return f"📊 Actividad institucional concentrada en ${strike}"


def _format_sweep_alert(trade: dict, ticker: str) -> str:
    premium_k   = round(trade["premium"] / 1000)
    side_label  = {"ABOVE_ASK": "compra agresiva ↑", "BELOW_BID": "venta agresiva ↓"}.get(
        trade.get("side", ""), trade.get("side", ""))
    golden_tag  = " ⭐ GOLDEN SWEEP" if trade.get("golden") else ""
    unusual_tag = " 🔎 inusual" if trade.get("unusual") else ""
    interp      = _sweep_interpretation(trade, ticker)
    return (
        f"🚨 **SWEEP INSTITUCIONAL{golden_tag}** | {ticker}{unusual_tag}\n"
        f"📍 **{trade['contract']} ${int(trade['strike'])}** | Vence {trade['exp']}\n"
        f"💰 **${premium_k}K premium** · {trade['size']} contratos\n"
        f"⚡ {side_label}\n"
        f"{interp}"
    )


async def _check_sweep_alerts(ticker: str, config: dict,
                               session: aiohttp.ClientSession) -> None:
    global _seen_sweep_keys
    today = __import__("datetime").date.today().isoformat()
    trades = await qd_client.fetch_order_flow_top(session, ticker,
                                                   config["qd_api_key"], today)
    new_alerts = []
    for trade in trades:
        if not trade.get("type") or not trade.get("premium"):
            continue
        key = _sweep_key(trade)
        if key in _seen_sweep_keys:
            continue
        premium = trade["premium"]
        is_golden = trade.get("golden", False)
        is_sweep  = trade.get("type") == "SWEEP"
        if (is_golden and premium >= SWEEP_ALERT_MIN_GOLDEN) or \
           (is_sweep and premium >= SWEEP_ALERT_MIN_PREMIUM):
            new_alerts.append(trade)
            _seen_sweep_keys.add(key)

    for trade in new_alerts:
        msg = _format_sweep_alert(trade, ticker)
        dashboard.add_log(f"[SWEEP] {ticker} ${int(trade['strike'])} "
                          f"${round(trade['premium']/1000)}K{'  GOLDEN' if trade.get('golden') else ''}")
        await notifier.send_webhook(config["discord"]["webhook_alumnos"], msg)


# ─────────────────────────────────────────────
# POST READING
# ─────────────────────────────────────────────

async def _post_reading(ticker: str, analysis: dict, config: dict, tipo: str,
                        enriched: dict = None) -> None:
    global _last_post_time

    next_time = _next_slot_time()
    dashboard.add_log(f"Llamando a Claude ({tipo})...")
    anthropic_key = config.get("anthropic_api_key", "")
    if not anthropic_key:
        dashboard.add_log("[ERROR] ANTHROPIC_API_KEY no configurada en Railway")
        return
    dashboard.add_log(f"API key: ...{anthropic_key[-8:]}")

    active_lessons = ls.get_active_lessons()
    if active_lessons:
        dashboard.add_log(f"Inyectando {len(active_lessons)} leccion(es) en contexto")

    # Merge enriched context into analysis if available
    if enriched:
        analysis = {**analysis, **enriched}

    message = await claude_client.generate_reading(
        analysis=analysis,
        anthropic_api_key=anthropic_key,
        next_time=next_time,
        tipo=tipo,
        lessons=active_lessons if active_lessons else None,
    )

    if message:
        dashboard.add_log(f"Claude OK ({len(message)} chars) — enviando Discord...")
        ok = await notifier.send_webhook(config["discord"]["webhook_alumnos"], message)
        if ok:
            _last_post_time = datetime.now(ET)
            stats.record_lectura(ticker, analysis.get("price", 0), tipo, message)
            stats.set_active_levels(ticker, analysis.get("supports", []),
                                    analysis.get("resistances", []))
            dashboard.add_log(f"[{tipo.upper()}] {ticker} ${analysis.get('price', 0):.0f} → Discord ✅")
        else:
            err = "[ERROR] Discord webhook fallo"
            dashboard.add_log(err)
            await notifier.send_webhook(config["discord"]["webhook_alumnos"],
                                        f"⚠️ **Bot Error:** {err}")
    else:
        err = (f"[ERROR] Claude no genero mensaje — revisa ANTHROPIC_API_KEY en Railway "
               f"(key termina en ...{anthropic_key[-6:]})")
        dashboard.add_log(err)
        await notifier.send_webhook(config["discord"]["webhook_alumnos"],
                                    f"⚠️ **Bot Error:** {err}")


# ─────────────────────────────────────────────
# RUN TICKER (scheduled post)
# ─────────────────────────────────────────────

async def run_ticker(ticker: str, config: dict, session: aiohttp.ClientSession,
                     tipo: str) -> None:
    global _last_analysis

    market_data = await qd_client.fetch_market_data(session, ticker, config["qd_api_key"])
    if not market_data.get("price"):
        print(f"[Monitor] Sin precio para {ticker}")
        return

    print(f"[Monitor] {ticker} ${market_data['price']:.2f}")
    analysis = ana.analyze(market_data)
    if not analysis:
        return

    # Fetch enriched context (VIX, IV rank, flow) for scheduled posts
    enriched = await qd_client.fetch_enriched_context(session, ticker, config["qd_api_key"])
    if enriched.get("vix"):
        dashboard.add_log(f"VIX: {enriched['vix']:.1f} | "
                          f"IV Rank: {_iv_rank_label(enriched.get('iv_rank', {}))} | "
                          f"Flujo: {enriched.get('flow_bias', {}).get('bias', '?')}")

    prev = _last_analysis.get(ticker)
    if tipo == "lectura" and ana.detect_significant_change(prev, analysis):
        print(f"[Monitor] Cambio significativo en {ticker} — alerta inmediata")
        await _post_reading(ticker, analysis, config, "lectura", enriched)
    elif tipo in ("apertura", "cierre"):
        await _post_reading(ticker, analysis, config, tipo, enriched)
    else:
        await _post_reading(ticker, analysis, config, "lectura", enriched)

    _last_analysis[ticker] = analysis


def _iv_rank_label(iv_rank: dict) -> str:
    if not iv_rank:
        return "N/A"
    # Try CALL or ALL or first key
    for key in ("ALL", "CALL", "PUT"):
        if key in iv_rank:
            return f"{iv_rank[key].get('ivRank', 0):.0f}%"
    first = next(iter(iv_rank.values()), {})
    return f"{first.get('ivRank', 0):.0f}%"


# ─────────────────────────────────────────────
# MANUAL / DOMINGO TRIGGERS
# ─────────────────────────────────────────────

async def domingo_trigger() -> None:
    try:
        config = config_manager.load()
        qd_key       = config.get("qd_api_key", "")
        anthropic_key = config.get("anthropic_api_key", "")
        webhook      = config.get("discord", {}).get("webhook_alumnos", "")
        if not qd_key or not anthropic_key or not webhook:
            dashboard.add_log("[ERROR] Faltan credenciales para analisis dominical")
            return
        dashboard.add_log("Recolectando datos SPX/SPY del viernes...")
        status = await sunday_analysis.run_domingo_analysis(qd_key, anthropic_key, webhook)
        dashboard.add_log(f"Domingo: {status}")
    except Exception as e:
        dashboard.add_log(f"[ERROR] Analisis dominical: {e}")


async def manual_trigger(tipo: str = "lectura") -> None:
    try:
        config = config_manager.load()
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for ticker in config.get("tickers", ["SPX"]):
                try:
                    dashboard.add_log(f"Obteniendo datos {ticker}...")
                    market_data = await qd_client.fetch_market_data(
                        session, ticker, config["qd_api_key"])
                    price = market_data.get("price")
                    dex_count = len(market_data.get("dex", {}))
                    gex_count = len(market_data.get("gex", {}))
                    dashboard.add_log(f"{ticker} precio=${price} dex={dex_count} gex={gex_count}")
                    if not price:
                        dashboard.add_log("[ERROR] Sin precio — posible mercado cerrado")
                        continue
                    analysis = ana.analyze(market_data)
                    s = len(analysis.get("supports", []))
                    r = len(analysis.get("resistances", []))
                    dashboard.add_log(f"Analisis OK: {s} soportes {r} resistencias")
                    enriched = await qd_client.fetch_enriched_context(
                        session, ticker, config["qd_api_key"])
                    await _post_reading(ticker, analysis, config, tipo, enriched)
                    _last_analysis[ticker] = analysis
                except Exception as e:
                    dashboard.add_log(f"[ERROR] {ticker}: {str(e)}")
    except Exception as e:
        dashboard.add_log(f"[ERROR FATAL] {str(e)}")


# ─────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────

async def monitor_loop() -> None:
    global _opening_sent, _closing_sent, _pre_market_sent, _last_post_time, _seen_sweep_keys

    import os
    port = int(os.environ.get("PORT", 8080))
    await dashboard.start_dashboard(port)
    dashboard.set_trigger_callback(manual_trigger)
    dashboard.set_domingo_callback(domingo_trigger)
    _cfg = config_manager.load()
    dashboard.set_anthropic_key(_cfg.get("anthropic_api_key", ""))
    dashboard.add_log("QD Bot iniciado — ticker: SPX")
    print("[Monitor] Iniciando loop QD Bot...")

    last_slot_checked = None

    while True:
        try:
            config = config_manager.load()
            now = _now_et()
            pre_market  = _is_pre_market()
            market_open = _is_market_open()
            closing     = _is_closing_time()

            status = ('PRE' if pre_market else 'ABIERTO' if market_open
                      else 'CIERRE' if closing else 'CERRADO')
            print(f"[Monitor] {now.strftime('%H:%M:%S ET')} | {status}")

            timeout = aiohttp.ClientTimeout(total=20)
            tickers = config.get("tickers", ["SPX"])

            # 9:25 AM — apertura
            if pre_market and not _pre_market_sent:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    for ticker in tickers:
                        await run_ticker(ticker, config, session, "apertura")
                _pre_market_sent = True
                _opening_sent    = False
                _closing_sent    = False
                _seen_sweep_keys  = set()

            # 9:30 AM — primera lectura
            elif market_open and not _opening_sent:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    for ticker in tickers:
                        await run_ticker(ticker, config, session, "lectura")
                _opening_sent = True
                last_slot_checked = now.replace(second=0, microsecond=0)

            # 4:00 PM — cierre
            elif closing and _opening_sent and not _closing_sent:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    for ticker in tickers:
                        await run_ticker(ticker, config, session, "cierre")
                _closing_sent = True

            # 9:30–4:00 — lecturas cada 10 min + change detection + sweep alerts
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
                                session, ticker, config["qd_api_key"])
                            if market_data.get("price"):
                                analysis = ana.analyze(market_data)
                                prev = _last_analysis.get(ticker)

                                # Track level outcomes
                                if prev and market_data.get("price"):
                                    price = market_data["price"]
                                    for sup in prev.get("supports", []):
                                        if sup["dex_signal"] in ("preferido", "solido", "cuidado"):
                                            held = price >= sup["strike"]
                                            stats.record_level_outcome(
                                                sup["strike"], held, ticker)

                                # Change detection → immediate post
                                if ana.detect_significant_change(prev, analysis):
                                    enriched = await qd_client.fetch_enriched_context(
                                        session, ticker, config["qd_api_key"])
                                    await _post_reading(ticker, analysis, config,
                                                        "lectura", enriched)

                                _last_analysis[ticker] = analysis

                            # Sweep alert check (every cycle, independent of change detection)
                            await _check_sweep_alerts(ticker, config, session)

            # Reset flags al fin del día
            if not pre_market and not market_open and not closing:
                _pre_market_sent = False
                _opening_sent    = False

        except Exception as e:
            print(f"[Monitor] Error: {e}")

        await asyncio.sleep(60)
