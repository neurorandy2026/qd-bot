import aiohttp
from datetime import date
from typing import Optional


BASE_URL = "https://api.quantdata.us"


async def fetch_price(session: aiohttp.ClientSession, ticker: str, api_key: str, session_date: str) -> Optional[float]:
    url = f"{BASE_URL}/v1/options/tool/net-drift"
    body = {"sessionDate": session_date, "filter": {"ticker": ticker}}
    async with session.post(url, json=body, headers={"Authorization": f"Bearer {api_key}"}) as resp:
        if resp.status != 200:
            print(f"[QD] Error precio {ticker}: {resp.status}")
            return None
        data = await resp.json()
        buckets = data.get("data", {})
        if not buckets:
            return None
        last_key = sorted(buckets.keys())[-1]
        return buckets[last_key].get("stockPrice")


async def fetch_exposure_0dte(
    session: aiohttp.ClientSession,
    ticker: str,
    api_key: str,
    session_date: str,
    greek: str,  # "DELTA" or "GAMMA"
) -> dict:
    """Returns dict of {strike_str: {callExposure, putExposure}} for 0DTE only."""
    url = f"{BASE_URL}/v1/options/tool/exposure-by-strike"
    body = {
        "sessionDate": session_date,
        "filter": {"ticker": ticker, "expirationDate": session_date},
        "greekMode": greek,
        "representationMode": "PER_ONE_PERCENT_MOVE",
    }
    async with session.post(url, json=body, headers={"Authorization": f"Bearer {api_key}"}) as resp:
        if resp.status != 200:
            text = await resp.text()
            print(f"[QD] Error {greek} {ticker}: {resp.status} — {text[:150]}")
            return {}
        data = await resp.json()
        return data.get("data", {}).get(ticker, {}).get("exposureMap", {}).get(session_date, {})


async def fetch_market_data(
    session: aiohttp.ClientSession,
    ticker: str,
    api_key: str,
) -> dict:
    """Fetches price + DEX + GEX for a ticker. Returns combined dict."""
    today = date.today().isoformat()

    price = await fetch_price(session, ticker, api_key, today)
    dex_map = await fetch_exposure_0dte(session, ticker, api_key, today, "DELTA")
    gex_map = await fetch_exposure_0dte(session, ticker, api_key, today, "GAMMA")

    return {
        "ticker": ticker,
        "date": today,
        "price": price,
        "dex": dex_map,
        "gex": gex_map,
    }
