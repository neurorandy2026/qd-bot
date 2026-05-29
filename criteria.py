"""
Persistent criteria store for Randy's evolving trading rules.
Stored in /data/criteria.json (Railway Volume) or local fallback.
"""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Use Railway Volume if available, otherwise local
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(__file__))
CRITERIA_PATH = os.path.join(DATA_DIR, "criteria.json")

CATEGORIES = ["DEX", "GEX", "Mensajes", "Alertas", "General"]


def _load() -> dict:
    if os.path.exists(CRITERIA_PATH):
        try:
            with open(CRITERIA_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "rules": [],         # list of rule objects
        "active_prompt": "", # compiled prompt text sent to Claude
        "version": 1,
    }


def _save(data: dict):
    os.makedirs(os.path.dirname(CRITERIA_PATH), exist_ok=True)
    with open(CRITERIA_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _rebuild_prompt(rules: list) -> str:
    """Compile active rules into a single prompt string for Claude."""
    active = [r for r in rules if r.get("active", True)]
    if not active:
        return ""
    lines = []
    for r in active:
        cat = r.get("category", "General")
        text = r.get("text", "").strip()
        if text:
            lines.append(f"[{cat}] {text}")
    return "\n".join(lines)


def get_active_prompt() -> str:
    return _load().get("active_prompt", "")


def get_all() -> dict:
    return _load()


def add_rule(text: str, category: str = "General") -> dict:
    """Add a new rule. Returns the new rule."""
    data = _load()
    rule = {
        "id": len(data["rules"]) + 1,
        "text": text.strip(),
        "category": category,
        "active": True,
        "created_at": datetime.now(ET).strftime("%Y-%m-%d %I:%M %p ET"),
        "notes": "",
    }
    data["rules"].insert(0, rule)
    data["active_prompt"] = _rebuild_prompt(data["rules"])
    _save(data)
    return rule


def toggle_rule(rule_id: int, active: bool):
    data = _load()
    for r in data["rules"]:
        if r["id"] == rule_id:
            r["active"] = active
            break
    data["active_prompt"] = _rebuild_prompt(data["rules"])
    _save(data)


def delete_rule(rule_id: int):
    data = _load()
    data["rules"] = [r for r in data["rules"] if r["id"] != rule_id]
    data["active_prompt"] = _rebuild_prompt(data["rules"])
    _save(data)


def update_rule_note(rule_id: int, note: str):
    data = _load()
    for r in data["rules"]:
        if r["id"] == rule_id:
            r["notes"] = note
            break
    _save(data)
