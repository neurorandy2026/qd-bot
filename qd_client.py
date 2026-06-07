import aiohttp
import asyncio
from datetime import date
from typing import Optional


BASE_URL = "https://api.quantdata.us"


async def fetch_price(session: aiohttp.ClientSession, ticker: str, api_key: str,
                      session_date: str) -> Optional[float]:
    url = f"{BASE_URL}/v1/options/tool/net-drift"
    body = {"sessionDate": session_date, "filter": {"ticker": ticker}}
    async with session.post(url, json=body,
                            headers={"Authorization": f"Bearer {api_key}"}) as resp:
        if resp.status != 200:
            print(f"[QD] Error precio {ticker}: {resp.status}")
            return None
        data = await resp.json()
        buckets = data.get("data", {})
        if not buckets:
            return None
        last_key = sorted(buckets.keys())[-1]
        return buckets[last_key].get("stockPrice")


async def fetch_exposure_0dte(session: aiohttp.ClientSession, ticker: str,
                               api_key: str, session_date: str, greek: str) -> dict:
    url = f"{BASE_URL}/v1/options/tool/exposure-by-strike"
    body = {
        "sessionDate": session_date,
        "filter": {"ticker": ticker, "expirationDate": session_date},
        "greekMode": greek,
        "representationMode": "PER_ONE_PERCENT_MOVE",
    }
    async with session.post(url, json=body,
                            headers={"Authorization": f"Bearer {api_key}"}) as resp:
        if resp.status != 200:
            text = await resp.text()
            print(f"[QD] Error {greek} {ticker}: {resp.status} — {text[:150]}")
            return {}
        data = await resp.json()
        return (data.get("data", {})
                    .get(ticker, {})
                    .get("exposureMap", {})
                    .get(session_date, {}))


async def fetch_vix_price(session: aiohttp.ClientSession, api_key: str,
                           session_date: str) -> Optional[float]:
    url = f"{BASE_URL}/v1/options/tool/net-flow"
    body = {"sessionDate": session_date, "filter": {"ticker": "VIX"}, "dataMode": "NET_PREMIUM"}
    try:
        async with session.post(url, json=body,
                                headers={"Authorization": f"Bearer {api_key}"},
                                timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            flow = data.get("data", {})
            if not flow:
                return None
            last_ts = sorted(flow.keys())[-1]
            return flow[last_ts].get("stockPrice")
    except Exception:
        return None


async def fetch_iv_rank(session: aiohttp.ClientSession, ticker: str,
                        api_key: str, session_date: str) -> dict:
    url = f"{BASE_URL}/v1/options/tool/iv-rank"
    body = {
        "sessionDate": session_date,
        "filter": {"ticker": ticker},
        "lookBackPeriod": 252,
        "maturity": 30,
    }
    try:
        async with session.post(url, json=body,
                                headers={"Authorization": f"Bearer {api_key}"},
                                timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return {}
            data = await resp.json()
            day_map = data.get("data", {})
            if not day_map:
                return {}
            last_key = sorted(day_map.keys())[-1]
            iv_data = day_map[last_key].get("contractTypeToIVData", {})
            # Flatten to {contract_type: {lastIv, ivRank}}
            result = {}
            for ct, vals in iv_data.items():
                last_iv = vals.get("lastIv", 0)
                max_iv  = vals.get("windowMaxIv", 0)
                min_iv  = vals.get("windowMinIv", 0)
                iv_range = max_iv - min_iv
                iv_rank = round((last_iv - min_iv) / iv_range * 100, 1) if iv_range > 0 else 0
                result[ct] = {"lastIv": round(last_iv * 100, 1), "ivRank": iv_rank}
            return result
    except Exception:
        return {}


async def fetch_net_flow_bias(session: aiohttp.ClientSession, ticker: str,
                               api_key: str, session_date: str) -> dict:
    url = f"{BASE_URL}/v1/options/tool/net-flow"
    body = {"sessionDate": session_date, "filter": {"ticker": ticker}, "dataMode": "NET_PREMIUM"}
    try:
        async with session.post(url, json=body,
                                headers={"Authorization": f"Bearer {api_key}"},
                                timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return {}
            data = await resp.json()
            flow = data.get("data", {})
            if not flow:
                return {}
            total_call, total_put = 0, 0
            for bar in flow.values():
                total_call += bar.get("callSum", 0)
                total_put  += bar.get("putSum", 0)
            total = total_call + total_put
            if total == 0:
                return {}
            call_pct = round(total_call / total * 100, 1)
            put_pct  = round(total_put  / total * 100, 1)
            bias = "CALLS" if call_pct >= 55 else "PUTS" if put_pct >= 55 else "NEUTRO"
            return {"call_pct": call_pct, "put_pct": put_pct, "bias": bias}
    except Exception:
        return {}


async def fetch_order_flow_top(session: aiohttp.ClientSession, ticker: str,
                                api_key: str, session_date: str) -> list:
    """Returns top institutional trades (sweeps + golden sweeps) for alert detection."""
    url = f"{BASE_URL}/v1/options/tool/order-flow/consolidated"
    body = {
        "sessionDate": session_date,
        "filter": {"ticker": ticker},
        "size": 30,
        "sort": {"field": "premium", "direction": "DESCENDING"},
    }
    try:
        async with session.post(url, json=body,
                                headers={"Authorization": f"Bearer {api_key}"},
                                timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            trades = data.get("data", [])
            result = []
            for t in trades:
                result.append({
                    "type":    t.get("tradeConsolidationType"),
                    "contract": t.get("contractType"),
                    "strike":  t.get("strikePrice"),
                    "exp":     t.get("expirationDate"),
                    "premium": t.get("premium", 0),
                    "size":    t.get("size"),
                    "side":    t.get("tradeSideCode"),
                    "golden":  t.get("isGoldenSweep", False),
                    "unusual": t.get("isUnusual", False),
                })
            return result
    except Exception:
        return []


async def fetch_enriched_context(session: aiohttp.ClientSession, ticker: str,
                                  api_key: str) -> dict:
    """Fetches VIX, IV rank, and flow bias in parallel for enriched daily readings."""
    today = date.today().isoformat()
    vix_task   = asyncio.create_task(fetch_vix_price(session, api_key, today))
    iv_task    = asyncio.create_task(fetch_iv_rank(session, ticker, api_key, today))
    flow_task  = asyncio.create_task(fetch_net_flow_bias(session, ticker, api_key, today))

    vix, iv_rank, flow_bias = await asyncio.gather(vix_task, iv_task, flow_task,
                                                    return_exceptions=True)

    def safe(r, default):
        return r if not isinstance(r, Exception) else default

    return {
        "vix":       safe(vix, None),
        "iv_rank":   safe(iv_rank, {}),
        "flow_bias": safe(flow_bias, {}),
    }


async def fetch_market_data(session: aiohttp.ClientSession, ticker: str,
                             api_key: str) -> dict:
    """Fetches price + DEX + GEX in parallel."""
    today = date.today().isoformat()

    price_task = asyncio.create_task(fetch_price(session, ticker, api_key, today))
    dex_task   = asyncio.create_task(fetch_exposure_0dte(session, ticker, api_key, today, "DELTA"))
    gex_task   = asyncio.create_task(fetch_exposure_0dte(session, ticker, api_key, today, "GAMMA"))

    price, dex_map, gex_map = await asyncio.gather(price_task, dex_task, gex_task)

    return {
        "ticker": ticker,
        "date":   today,
        "price":  price,
        "dex":    dex_map,
        "gex":    gex_map,
    }
