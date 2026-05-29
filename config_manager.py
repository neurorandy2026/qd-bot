import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULTS = {
    "qd_api_key": "",
    "anthropic_api_key": "",
    "tickers": ["SPY"],
    "discord": {
        "webhook_alumnos": ""
    },
    "monitor_interval_seconds": 60,
    "post_interval_minutes": 20,
    "market_hours": {
        "open": "09:30",
        "close": "16:00"
    }
}


def load() -> dict:
    config = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            saved = json.load(f)
        config.update(saved)

    # Railway env vars override config.json
    if os.environ.get("QD_API_KEY"):
        config["qd_api_key"] = os.environ["QD_API_KEY"]
    if os.environ.get("ANTHROPIC_API_KEY"):
        config["anthropic_api_key"] = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("DISCORD_WEBHOOK_ALUMNOS"):
        config["discord"]["webhook_alumnos"] = os.environ["DISCORD_WEBHOOK_ALUMNOS"]

    return config


def save(config: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
