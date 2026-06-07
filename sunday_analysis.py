import aiohttp
import asyncio
import json
from datetime import date, datetime, timedelta

BASE_URL = "https://api.quantdata.us"


# ─────────────────────────────────────────────
# FECHA
# ─────────────────────────────────────────────

def last_trading_day() -> str:
    today = date.today()
    wd = today.weekday()
    if wd == 5:
        return (today - timedelta(days=1)).isoformat()
    elif wd == 6:
        return (today - timedelta(days=2)).isoformat()
    return today.isoformat()


# ─────────────────────────────────────────────
# FETCHERS
# ─────────────────────────────────────────────

async def _post(session, path, body, api_key, timeout=20):
    url = f"{BASE_URL}/{path}"
    try:
        async with session.post(
            url, json=body,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as resp:
            if resp.status != 200:
                return {}
            return await resp.json()
    except Exception:
        return {}


async def _fetch_exposure(session, ticker, api_key, session_date, greek):
    data = await _post(session, "v1/options/tool/exposure-by-strike", {
        "sessionDate": session_date,
        "filter": {"ticker": ticker, "expirationDate": session_date},
        "greekMode": greek,
        "representationMode": "PER_ONE_PERCENT_MOVE",
    }, api_key)
    return data.get("data", {}).get(ticker, {}).get("exposureMap", {}).get(session_date, {})


async def _fetch_drift(session, ticker, api_key, session_date):
    return await _post(session, "v1/options/tool/net-drift", {
        "sessionDate": session_date,
        "filter": {"ticker": ticker},
    }, api_key)


async def _fetch_net_flow(session, ticker, api_key, session_date, data_mode):
    data = await _post(session, "v1/options/tool/net-flow", {
        "sessionDate": session_date,
        "filter": {"ticker": ticker},
        "dataMode": data_mode,
    }, api_key)
    return data.get("data", {})


async def _fetch_iv_rank(session, ticker, api_key, session_date, maturity=30, look_back=252):
    data = await _post(session, "v1/options/tool/iv-rank", {
        "sessionDate": session_date,
        "filter": {"ticker": ticker},
        "lookBackPeriod": look_back,
        "maturity": maturity,
    }, api_key)
    day_map = data.get("data", {})
    if not day_map:
        return {}
    last_key = sorted(day_map.keys())[-1]
    return day_map[last_key].get("contractTypeToIVData", {})


async def _fetch_dark_pool(session, ticker, api_key, session_date):
    end = date.fromisoformat(session_date)
    start = (end - timedelta(days=7)).isoformat()
    return await _post(session, "v1/equities/tool/dark-pool-levels", {
        "sessionDateRange": {"startDate": start, "endDate": session_date},
        "filter": {"ticker": ticker},
    }, api_key)


async def _fetch_contract_stats(session, ticker, api_key, session_date):
    data = await _post(session, "v1/options/tool/contract-statistics", {
        "sessionDate": session_date,
        "filter": {"ticker": ticker},
    }, api_key)
    return data.get("data", {})


async def _fetch_oi_over_time(session, ticker, api_key, session_date):
    data = await _post(session, "v1/options/tool/open-interest-over-time", {
        "sessionDate": session_date,
        "filter": {"ticker": ticker},
    }, api_key)
    return data.get("data", {})


async def _fetch_order_flow(session, ticker, api_key, session_date):
    """Fetches top blocks/sweeps of the day with day statistics."""
    data = await _post(session, "v1/options/tool/order-flow/consolidated", {
        "sessionDate": session_date,
        "filter": {"ticker": ticker},
        "includeStatistics": True,
        "size": 50,
        "sort": {"field": "premium", "direction": "DESCENDING"},
    }, api_key)
    return data


async def _fetch_vix_price(session, api_key, session_date):
    """VIX price from net-flow VIX ticker."""
    flow = await _fetch_net_flow(session, "VIX", api_key, session_date, "NET_PREMIUM")
    if not flow:
        return None
    last_ts = sorted(flow.keys())[-1]
    return flow[last_ts].get("stockPrice")


async def _fetch_vvix_proxy(session, api_key, session_date):
    """VVIX proxy = IV of VIX options via iv-rank."""
    return await _fetch_iv_rank(session, "VIX", api_key, session_date, maturity=30, look_back=252)


# ─────────────────────────────────────────────
# PROCESADORES
# ─────────────────────────────────────────────

def _price_from_drift(drift_data: dict):
    buckets = drift_data.get("data", {}) if isinstance(drift_data, dict) else {}
    if not buckets:
        return None
    last_key = sorted(buckets.keys())[-1]
    return buckets[last_key].get("stockPrice")


def _summarize_levels(exposure_map: dict) -> list:
    levels = []
    for strike_str, data in exposure_map.items():
        try:
            strike = float(strike_str)
            call = float(data.get("callExposure", 0))
            put = float(data.get("putExposure", 0))
            net = call + put
            levels.append({"strike": strike, "call": call, "put": put, "net": net})
        except (ValueError, TypeError):
            continue
    return sorted(levels, key=lambda x: x["strike"])


def _calc_net_gex(gex_levels: list) -> float:
    return sum(lv["net"] for lv in gex_levels)


def _calc_flip_level(gex_levels: list):
    if not gex_levels:
        return None
    sorted_levels = sorted(gex_levels, key=lambda x: x["strike"])
    cumulative = 0.0
    prev_strike = None
    for lv in sorted_levels:
        prev = cumulative
        cumulative += lv["net"]
        if prev_strike is not None and prev != 0 and prev * cumulative < 0:
            return lv["strike"]
        prev_strike = lv["strike"]
    return None


def _process_dark_pool(dp_data: dict, current_price=None, top_n=10) -> list:
    raw = dp_data.get("data", {})
    if not raw:
        return []
    buckets = {}
    for price_str, info in raw.items():
        try:
            price = float(price_str)
            bucket = round(round(price / 0.5) * 0.5, 2)
            if bucket not in buckets:
                buckets[bucket] = {"notional": 0, "size": 0, "trades": 0}
            buckets[bucket]["notional"] += info.get("notionalValue", 0)
            buckets[bucket]["size"] += info.get("size", 0)
            buckets[bucket]["trades"] += info.get("tradeCount", 0)
        except (ValueError, TypeError):
            continue
    sorted_levels = sorted(buckets.items(), key=lambda x: x[1]["notional"], reverse=True)[:top_n]
    result = []
    for price, info in sorted_levels:
        role = "soporte" if (current_price and price < current_price) else \
               "resistencia" if (current_price and price > current_price) else "neutro"
        result.append({
            "price": price,
            "notional_M": round(info["notional"] / 1e6, 1),
            "shares": info["size"],
            "trades": info["trades"],
            "role": role,
        })
    return sorted(result, key=lambda x: x["price"], reverse=True)


def _process_oi(oi_data: dict) -> dict:
    if not oi_data:
        return {}
    last_5 = sorted(oi_data.keys())[-5:]
    result = {}
    for d in last_5:
        calls = oi_data[d].get("callOpenInterest", 0)
        puts = oi_data[d].get("putOpenInterest", 0)
        pcr = round(puts / calls, 2) if calls > 0 else 0
        result[d] = {"calls": calls, "puts": puts, "put_call_ratio": pcr}
    return result


def _process_order_flow(flow_data: dict) -> dict:
    if not flow_data:
        return {}

    stats = flow_data.get("statistics", {})
    trades = flow_data.get("data", [])

    # Resumir estadisticas por tipo de trade side
    call_above_ask = stats.get("CALL", {}).get("ABOVE_ASK", {})
    put_above_ask = stats.get("PUT", {}).get("ABOVE_ASK", {})
    call_below_bid = stats.get("CALL", {}).get("BELOW_BID", {})
    put_below_bid = stats.get("PUT", {}).get("BELOW_BID", {})

    # Top trades por tipo
    sweeps = [t for t in trades if t.get("tradeConsolidationType") == "SWEEP"]
    blocks = [t for t in trades if t.get("tradeConsolidationType") == "BLOCK"]
    unusual = [t for t in trades if t.get("isUnusual")]

    def summarize_trades(trade_list, n=5):
        return [
            {
                "type": t.get("tradeConsolidationType"),
                "contract": t.get("contractType"),
                "strike": t.get("strikePrice"),
                "exp": t.get("expirationDate"),
                "premium_K": round(t.get("premium", 0) / 1000, 0),
                "size": t.get("size"),
                "side": t.get("tradeSideCode"),
                "unusual": t.get("isUnusual", False),
                "golden": t.get("isGoldenSweep", False),
            }
            for t in trade_list[:n]
        ]

    return {
        "aggressive_call_buys": {
            "trades": call_above_ask.get("tradeCount", 0),
            "premium_M": round(call_above_ask.get("premium", 0) / 1e6, 1),
        },
        "aggressive_put_buys": {
            "trades": put_above_ask.get("tradeCount", 0),
            "premium_M": round(put_above_ask.get("premium", 0) / 1e6, 1),
        },
        "call_selling": {
            "trades": call_below_bid.get("tradeCount", 0),
            "premium_M": round(call_below_bid.get("premium", 0) / 1e6, 1),
        },
        "put_selling": {
            "trades": put_below_bid.get("tradeCount", 0),
            "premium_M": round(put_below_bid.get("premium", 0) / 1e6, 1),
        },
        "top_sweeps": summarize_trades(sweeps),
        "top_blocks": summarize_trades(blocks),
        "unusual_trades": summarize_trades(unusual),
    }


def _process_iv_rank(iv_data: dict) -> dict:
    if not iv_data:
        return {}
    result = {}
    for contract_type, vals in iv_data.items():
        last_iv = vals.get("lastIv", 0)
        max_iv = vals.get("windowMaxIv", 0)
        min_iv = vals.get("windowMinIv", 0)
        iv_range = max_iv - min_iv
        iv_rank = ((last_iv - min_iv) / iv_range * 100) if iv_range > 0 else 0
        result[contract_type] = {
            "lastIv": round(last_iv, 2),
            "maxIv": round(max_iv, 2),
            "minIv": round(min_iv, 2),
            "ivRank": round(iv_rank, 1),
        }
    return result


# ─────────────────────────────────────────────
# RECOLECCION PRINCIPAL
# ─────────────────────────────────────────────

async def collect_sunday_data(qd_api_key: str) -> dict:
    session_date = last_trading_day()

    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(
            # DEX / GEX
            _fetch_exposure(session, "SPY", qd_api_key, session_date, "DELTA"),
            _fetch_exposure(session, "SPY", qd_api_key, session_date, "GAMMA"),
            _fetch_drift(session, "SPY", qd_api_key, session_date),
            _fetch_exposure(session, "SPX", qd_api_key, session_date, "DELTA"),
            _fetch_exposure(session, "SPX", qd_api_key, session_date, "GAMMA"),
            _fetch_drift(session, "SPX", qd_api_key, session_date),
            # Flujo
            _fetch_net_flow(session, "SPY", qd_api_key, session_date, "NET_PREMIUM"),
            _fetch_net_flow(session, "SPY", qd_api_key, session_date, "NET_VOLUME"),
            # IV
            _fetch_iv_rank(session, "SPY", qd_api_key, session_date),
            # VIX / VVIX
            _fetch_vix_price(session, qd_api_key, session_date),
            _fetch_vvix_proxy(session, qd_api_key, session_date),
            # Dark pool
            _fetch_dark_pool(session, "SPY", qd_api_key, session_date),
            # OI
            _fetch_oi_over_time(session, "SPY", qd_api_key, session_date),
            # Contract stats
            _fetch_contract_stats(session, "SPY", qd_api_key, session_date),
            # Order flow (SWEEP/BLOCK)
            _fetch_order_flow(session, "SPY", qd_api_key, session_date),
            return_exceptions=True,
        )

    def safe(r):
        return r if not isinstance(r, Exception) else {}

    (spy_dex_raw, spy_gex_raw, spy_drift,
     spx_dex_raw, spx_gex_raw, spx_drift,
     flow_premium_raw, flow_volume_raw,
     iv_rank_raw,
     vix_price, vvix_raw,
     dark_pool_raw,
     oi_raw,
     contract_stats_raw,
     order_flow_raw) = [safe(r) if not isinstance(r, (float, type(None))) else r for r in results]

    spy_price = _price_from_drift(spy_drift)

    # Flujo premium totales
    def sum_flow(flow_data):
        total_call, total_put = 0, 0
        for bar in flow_data.values() if isinstance(flow_data, dict) else []:
            total_call += bar.get("callSum", 0)
            total_put += bar.get("putSum", 0)
        total = total_call + total_put
        call_pct = total_call / total * 100 if total > 0 else 0
        put_pct = total_put / total * 100 if total > 0 else 0
        bias = "CALLS dominan" if call_pct >= 55 else "PUTS dominan" if put_pct >= 55 else "NEUTRO"
        return {"total_call": total_call, "total_put": total_put,
                "call_pct": round(call_pct, 1), "put_pct": round(put_pct, 1), "bias": bias}

    return {
        "session_date": session_date,
        "SPY": {
            "price": spy_price,
            "dex": _summarize_levels(spy_dex_raw),
            "gex": _summarize_levels(spy_gex_raw),
        },
        "SPX": {
            "price": _price_from_drift(spx_drift),
            "dex": _summarize_levels(spx_dex_raw),
            "gex": _summarize_levels(spx_gex_raw),
        },
        "flow_premium": sum_flow(flow_premium_raw),
        "flow_volume": sum_flow(flow_volume_raw),
        "iv_rank": _process_iv_rank(iv_rank_raw),
        "vix": vix_price,
        "vvix": _process_iv_rank(vvix_raw),
        "dark_pool": _process_dark_pool(dark_pool_raw, current_price=spy_price),
        "oi": _process_oi(oi_raw),
        "contract_stats": contract_stats_raw,
        "order_flow": _process_order_flow(order_flow_raw),
    }


# ─────────────────────────────────────────────
# CONSTRUCCION DEL PROMPT (prompt de la esposa)
# ─────────────────────────────────────────────

def _build_datos(data: dict) -> dict:
    spy = data.get("SPY", {})
    spx = data.get("SPX", {})
    iv = data.get("iv_rank", {})
    vvix = data.get("vvix", {})
    flow_p = data.get("flow_premium", {})
    flow_v = data.get("flow_volume", {})
    dp = data.get("dark_pool", [])
    oi = data.get("oi", {})
    cs = data.get("contract_stats", {})
    of = data.get("order_flow", {})

    spx_gex = spx.get("gex", [])
    spy_gex = spy.get("gex", [])
    net_gex = _calc_net_gex(spx_gex) if spx_gex else _calc_net_gex(spy_gex)
    flip_level = _calc_flip_level(spx_gex) if spx_gex else _calc_flip_level(spy_gex)

    primary_ticker = "SPX" if spx.get("dex") else "SPY"
    primary = spx if spx.get("dex") else spy

    def iv_dict(iv_data):
        if not iv_data:
            return "dato no disponible en QuantData esta semana"
        return {k: {"iv_actual_pct": v["lastIv"], "iv_rank_0_100": v["ivRank"],
                    "rango_min": v["minIv"], "rango_max": v["maxIv"]}
                for k, v in iv_data.items()}

    def flow_dict(f):
        if not f:
            return "dato no disponible en QuantData esta semana"
        return {"total_calls": f["total_call"], "total_puts": f["total_put"],
                "call_pct": f["call_pct"], "put_pct": f["put_pct"], "sesgo": f["bias"]}

    # PCR de OI
    oi_latest = {}
    if oi:
        last_date = sorted(oi.keys())[-1]
        oi_latest = oi[last_date]

    return {
        primary_ticker: {
            "price": primary.get("price"),
            "net_gex": round(net_gex, 2) if net_gex else None,
            "flip_level": flip_level,
            "gex": [{"strike": lv["strike"], "net_gex": round(lv["net"], 2),
                     "call_gex": round(lv["call"], 2), "put_gex": round(lv["put"], 2)}
                    for lv in sorted(primary.get("gex", []), key=lambda x: x["strike"], reverse=True)],
            "dex": [{"strike": lv["strike"], "net_dex": round(lv["net"], 2),
                     "call_dex": round(lv["call"], 2), "put_dex": round(lv["put"], 2)}
                    for lv in sorted(primary.get("dex", []), key=lambda x: x["strike"], reverse=True)],
            "darkpool": dp if dp else "dato no disponible en QuantData esta semana",
            "oi_latest": oi_latest if oi_latest else "dato no disponible en QuantData esta semana",
            "oi_trend_5d": oi if oi else "dato no disponible en QuantData esta semana",
            "maxpain": "dato no disponible en QuantData esta semana",
        },
        "SPY_flujo": {
            "price": spy.get("price"),
            "contract_stats_dia": {
                "calls": {"premium_$": cs.get("CALL", {}).get("premium"),
                          "volume_contratos": cs.get("CALL", {}).get("volume"),
                          "trade_count": cs.get("CALL", {}).get("tradeCount")},
                "puts": {"premium_$": cs.get("PUT", {}).get("premium"),
                         "volume_contratos": cs.get("PUT", {}).get("volume"),
                         "trade_count": cs.get("PUT", {}).get("tradeCount")},
            } if cs else "dato no disponible en QuantData esta semana",
            "flow_premium_usd": flow_dict(flow_p),
            "flow_volume_contratos": flow_dict(flow_v),
            "iv_rank_30d": iv_dict(iv),
            "order_flow_institucional": of if of else "dato no disponible en QuantData esta semana",
        },
        "VIX": data.get("vix") if data.get("vix") else "dato no disponible en QuantData esta semana",
        "VVIX_proxy": iv_dict(vvix) if vvix else "dato no disponible en QuantData esta semana",
        "session_date": data["session_date"],
    }


def _build_prompt(data: dict) -> str:
    fecha = datetime.now().strftime("%d de %B de %Y")
    datos = _build_datos(data)
    primary_ticker = "SPX" if data.get("SPX", {}).get("dex") else "SPY"
    datos_json = json.dumps(datos, indent=2, ensure_ascii=False)

    return (
        f"Eres un analista institucional experto en opciones SPX y estructura\n"
        f"de mercado. Hoy es domingo {fecha}.\n"
        f"\n"
        f"Tu unica fuente de datos es la API de QuantData. No uses conocimiento\n"
        f"general ni suposiciones. Si un dato no esta en los datos recibidos,\n"
        f'di explicitamente: "dato no disponible en QuantData esta semana."\n'
        f"\n"
        f"{'='*39}\n"
        f"DATOS RECIBIDOS DE QUANTDATA API:\n"
        f"{datos_json}\n"
        f"{'='*39}\n"
        f"\n"
        f"LOGICA DE ANALISIS — aplica en este orden exacto:\n"
        f"\n"
        f"PASO 1 — IDENTIFICAR EL REGIMEN GEX\n"
        f"Lee el campo gex de {primary_ticker}.\n"
        f"Si net_gex > 0 → regimen POSITIVO\n"
        f"  Los dealers absorben volatilidad. El mercado tiende a\n"
        f"  quedarse dentro de un rango. Favorece vender premium.\n"
        f"Si net_gex < 0 → regimen NEGATIVO\n"
        f"  Los dealers amplifican movimientos. El mercado puede\n"
        f"  moverse bruscamente en cualquier direccion. Reducir size.\n"
        f"Identifica el flip_level (precio donde GEX cambia de signo).\n"
        f"Compara el precio actual vs el flip_level:\n"
        f"  precio > flip → regimen positivo confirmado\n"
        f"  precio < flip → regimen negativo activo\n"
        f"Lee el dex (delta exposure):\n"
        f"  DEX negativo → dealers compran cuando sube, venden cuando baja\n"
        f"  DEX positivo → dealers venden cuando sube, compran cuando baja\n"
        f"\n"
        f"PASO 2 — MAPEAR NIVELES DE DINERO REAL\n"
        f"Usa darkpool y oi_latest de {primary_ticker}:\n"
        f"  - Dark pool: zonas de mayor notional = soporte/resistencia institucional\n"
        f"  - OI: put_call_ratio > 1.5 = sesgo bajista institucional\n"
        f"  - OI trend 5 dias: si puts crecen = acumulacion de cobertura\n"
        f"  - 2+ strikes DEX consecutivos >2.5B → zona magnetica\n"
        f"  - Put Wall: strike con mayor dex put negativo\n"
        f"  - Call Wall: strike con mayor dex call positivo\n"
        f"  - Max pain estimado: zona de mayor concentracion de exposicion neta\n"
        f"\n"
        f"PASO 3 — LEER EL REGIMEN DE VOLATILIDAD\n"
        f"Lee VIX (precio) y VVIX_proxy (IV de opciones de VIX):\n"
        f"  VIX < 15   → calma extrema, premium vendible con tamano normal\n"
        f"  VIX 15-20  → calma normal, condiciones estandar\n"
        f"  VIX 20-25  → estres moderado, reducir tamano\n"
        f"  VIX > 25   → estres sistemico, solo estructuras defensivas\n"
        f"  VVIX > 100 → VIX mismo es inestable, multiplicar precaucion\n"
        f"Usa iv_rank_30d de SPY_flujo para complementar:\n"
        f"  IV Rank 0-25 = premium barato | 50-75 = buen momento para vender | 75-100 = caro pero riesgoso\n"
        f"Infiere term structure desde GEX:\n"
        f"  GEX positivo alto → IV comprimida, contango | GEX negativo → IV elevada, posible backwardation\n"
        f"\n"
        f"---\n"
        f"\n"
        f"FORMATO DE SALIDA — genera estas secciones con emojis:\n"
        f"Al final de CADA seccion agrega exactamente:\n"
        f"'💡 En resumen: [conclusion simple de 1-2 oraciones]'\n"
        f"\n"
        f"📍 REGIMEN DE MERCADO — GEX neto total (+$XB), flip level exacto en $, DEX sesgo\n"
        f"🏦 NIVELES CLAVE — dark pool con $ notional, OI put/call ratio, Put Wall, Call Wall, max pain estimado, delta notional\n"
        f"🌡 VOLATILIDAD — VIX precio, VVIX proxy, IV Rank, term structure, si el premium esta caro o barato\n"
        f"🔀 FLUJO INSTITUCIONAL — contract stats (calls vs puts en $ y contratos), top SWEEPS y BLOCKS del dia con tipo/strike/premium/direccion, sesgo hedge vs direccional\n"
        f"🎯 SESGO DE LA SEMANA — ALCISTA/BAJISTA/NEUTRAL + rango de precio en $ + strikes ideales para Iron Condor o vertical spread\n"
        f"⚠️ ALERTAS — 4-5 alertas con accion concreta: 'Si {primary_ticker} rompe $X → hacer Y'\n"
        f"\n"
        f"Luego el bloque final:\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\U0001f9e0 ANALISIS FINAL CONDENSADO\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"5 oraciones que respondan:\n"
        f"1. Tipo de semana (tranquila/volatil/direccional)\n"
        f"2. Que hacen los institucionales con su dinero\n"
        f"3. Que estrategia tiene sentido y en que strikes\n"
        f"4. Mayor riesgo a vigilar\n"
        f"5. Veredicto final en una linea sin ambiguedades\n"
        f"\n"
        f"Max 4500 caracteres. Claro, directo, en espanol. Sin jerga innecesaria."
    )


# ─────────────────────────────────────────────
# PIPELINE PRINCIPAL
# ─────────────────────────────────────────────

async def generate_domingo_report(qd_api_key: str, anthropic_api_key: str) -> tuple:
    data = await collect_sunday_data(qd_api_key)
    prompt = _build_prompt(data)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 3000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Anthropic API error {resp.status}: {text[:200]}")
            result = await resp.json()
            report_text = result.get("content", [{}])[0].get("text", "")

    return report_text, data


async def send_domingo_to_discord(report_text: str, webhook_url: str, session_date: str) -> bool:
    header = (
        f"**INFORME DOMINICAL SPX/SPY**\n"
        f"Domingo | Datos del cierre del {session_date}\n"
        f"{'='*36}\n\n"
    )
    full_text = header + report_text
    chunks = []
    current = ""
    for line in full_text.split("\n"):
        candidate = current + line + "\n"
        if len(candidate) > 1900:
            if current:
                chunks.append(current.rstrip())
            current = line + "\n"
        else:
            current = candidate
    if current.strip():
        chunks.append(current.rstrip())

    async with aiohttp.ClientSession() as session:
        for i, chunk in enumerate(chunks):
            if i > 0:
                await asyncio.sleep(1.5)  # evitar rate limit de Discord
            async with session.post(webhook_url, json={"content": chunk},
                                    timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 429:
                    # Rate limited — esperar y reintentar una vez
                    await asyncio.sleep(5)
                    async with session.post(webhook_url, json={"content": chunk},
                                            timeout=aiohttp.ClientTimeout(total=15)) as retry:
                        if retry.status not in (200, 204):
                            return False
                elif resp.status not in (200, 204):
                    return False
    return True


async def run_domingo_analysis(qd_api_key: str, anthropic_api_key: str, webhook_url: str) -> str:
    try:
        report, data = await generate_domingo_report(qd_api_key, anthropic_api_key)
        session_date = data.get("session_date", "N/A")
        ok = await send_domingo_to_discord(report, webhook_url, session_date)
        if ok:
            return f"Informe dominical enviado ({session_date})"
        return "Informe generado pero error al enviar a Discord"
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Error en analisis dominical: {e}"
