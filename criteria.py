"""
Stores Randy's evolving criteria notes.
These get injected into Claude's prompt dynamically.
"""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
CRITERIA_PATH = os.path.join(os.path.dirname(__file__), "criteria.json")


def _load() -> dict:
    if os.path.exists(CRITERIA_PATH):
        with open(CRITERIA_PATH) as f:
            return json.load(f)
    return {"notes": [], "active_text": ""}


def get_active_text() -> str:
    return _load().get("active_text", "")


def get_all() -> dict:
    return _load()


def save_note(text: str) -> None:
    data = _load()
    data["active_text"] = text.strip()
    data["notes"].insert(0, {
        "text": text.strip(),
        "saved_at": datetime.now(ET).strftime("%Y-%m-%d %I:%M %p ET"),
    })
    data["notes"] = data["notes"][:20]
    with open(CRITERIA_PATH, "w") as f:
        json.dump(data, f, indent=2)
