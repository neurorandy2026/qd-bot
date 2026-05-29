"""
Tracks bot performance: readings sent, level accuracy, alerts.
Persisted in stats.json.
"""
import json
import os
from datetime import datetime, date
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
STATS_PATH = os.path.join(os.path.dirname(__file__), "stats.json")

_defaults = {
    "total_lecturas": 0,
    "total_alertas": 0,
    "levels_held": 0,
    "levels_broken": 0,
    "today": "",
    "today_lecturas": 0,
    "today_alertas": 0,
    "week_lecturas": 0,
    "last_message_time": "",
    "last_price": 0,
    "last_ticker": "",
    "active_levels": {},   # {ticker: [{"strike": x, "type": "support"|"resistance", "ts": ...}]}
    "history": [],         # last 50 outcomes
}


def _load() -> dict:
    if os.path.exists(STATS_PATH):
        with open(STATS_PATH) as f:
            data = json.load(f)
        # merge with defaults for new keys
        for k, v in _defaults.items():
            if k not in data:
                data[k] = v
        return data
    return dict(_defaults)


def _save(data: dict):
    with open(STATS_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _reset_today_if_needed(data: dict):
    today_str = date.today().isoformat()
    if data.get("today") != today_str:
        data["today"] = today_str
        data["today_lecturas"] = 0
        data["today_alertas"] = 0


def record_lectura(ticker: str, price: float, tipo: str):
    data = _load()
    _reset_today_if_needed(data)
    data["total_lecturas"] += 1
    data["today_lecturas"] += 1
    data["week_lecturas"] += 1
    data["last_message_time"] = datetime.now(ET).strftime("%I:%M %p ET")
    data["last_price"] = price
    data["last_ticker"] = ticker
    if tipo == "alerta":
        data["total_alertas"] += 1
        data["today_alertas"] += 1
    _save(data)


def record_level_outcome(strike: float, held: bool, ticker: str):
    data = _load()
    outcome = "✅ Aguantó" if held else "❌ Rompió"
    if held:
        data["levels_held"] += 1
    else:
        data["levels_broken"] += 1
    entry = {
        "time": datetime.now(ET).strftime("%I:%M %p"),
        "ticker": ticker,
        "strike": strike,
        "outcome": outcome,
    }
    data["history"].insert(0, entry)
    data["history"] = data["history"][:50]
    _save(data)


def set_active_levels(ticker: str, supports: list, resistances: list):
    data = _load()
    data["active_levels"][ticker] = {
        "supports": [s["strike"] for s in supports[:3]],
        "resistances": [r["strike"] for r in resistances[:2]],
        "updated": datetime.now(ET).strftime("%I:%M %p ET"),
    }
    _save(data)


def get() -> dict:
    return _load()


def accuracy_pct() -> float:
    data = _load()
    total = data["levels_held"] + data["levels_broken"]
    if total == 0:
        return 0.0
    return round(data["levels_held"] / total * 100, 1)
