"""
Persistent criteria store using PostgreSQL (Railway) with JSON fallback.
"""
import json
import os
import psycopg2
import psycopg2.extras
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

DATABASE_URL = os.environ.get("DATABASE_URL")
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(__file__) or ".")
CRITERIA_PATH = os.path.join(DATA_DIR, "criteria.json")

CATEGORIES = ["DEX", "GEX", "Mensajes", "Alertas", "General"]


def _get_conn():
    return psycopg2.connect(DATABASE_URL)


def _ensure_table():
    if not DATABASE_URL:
        return
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS criteria_rules (
                        id SERIAL PRIMARY KEY,
                        text TEXT NOT NULL,
                        category VARCHAR(50) DEFAULT 'General',
                        active BOOLEAN DEFAULT TRUE,
                        created_at VARCHAR(50),
                        notes TEXT DEFAULT ''
                    )
                """)
            conn.commit()
    except Exception as e:
        print(f"[Criteria] Error creando tabla: {e}")


def _rebuild_prompt(rules: list) -> str:
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


def _load_from_pg() -> dict:
    try:
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM criteria_rules ORDER BY id DESC")
                rows = cur.fetchall()
                rules = [dict(r) for r in rows]
                return {
                    "rules": rules,
                    "active_prompt": _rebuild_prompt(rules),
                    "version": 1,
                }
    except Exception as e:
        print(f"[Criteria] Error leyendo DB: {e}")
        return {"rules": [], "active_prompt": "", "version": 1}


def _load_from_json() -> dict:
    if os.path.exists(CRITERIA_PATH):
        try:
            with open(CRITERIA_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {"rules": [], "active_prompt": "", "version": 1}


def _save_to_json(data: dict):
    os.makedirs(os.path.dirname(CRITERIA_PATH) or ".", exist_ok=True)
    with open(CRITERIA_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _load() -> dict:
    if DATABASE_URL:
        return _load_from_pg()
    return _load_from_json()


def get_active_prompt() -> str:
    return _load().get("active_prompt", "")


def get_all() -> dict:
    return _load()


def add_rule(text: str, category: str = "General") -> dict:
    now_str = datetime.now(ET).strftime("%Y-%m-%d %I:%M %p ET")
    if DATABASE_URL:
        try:
            with _get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "INSERT INTO criteria_rules (text, category, active, created_at, notes) "
                        "VALUES (%s, %s, TRUE, %s, '') RETURNING *",
                        (text.strip(), category, now_str),
                    )
                    rule = dict(cur.fetchone())
                conn.commit()
                return rule
        except Exception as e:
            print(f"[Criteria] Error insertando regla: {e}")
            return {}
    else:
        data = _load_from_json()
        rule = {
            "id": len(data["rules"]) + 1,
            "text": text.strip(),
            "category": category,
            "active": True,
            "created_at": now_str,
            "notes": "",
        }
        data["rules"].insert(0, rule)
        data["active_prompt"] = _rebuild_prompt(data["rules"])
        _save_to_json(data)
        return rule


def toggle_rule(rule_id: int, active: bool):
    if DATABASE_URL:
        try:
            with _get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE criteria_rules SET active = %s WHERE id = %s",
                        (active, rule_id),
                    )
                conn.commit()
        except Exception as e:
            print(f"[Criteria] Error toggle: {e}")
    else:
        data = _load_from_json()
        for r in data["rules"]:
            if r["id"] == rule_id:
                r["active"] = active
                break
        data["active_prompt"] = _rebuild_prompt(data["rules"])
        _save_to_json(data)


def delete_rule(rule_id: int):
    if DATABASE_URL:
        try:
            with _get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM criteria_rules WHERE id = %s", (rule_id,))
                conn.commit()
        except Exception as e:
            print(f"[Criteria] Error eliminando regla: {e}")
    else:
        data = _load_from_json()
        data["rules"] = [r for r in data["rules"] if r["id"] != rule_id]
        data["active_prompt"] = _rebuild_prompt(data["rules"])
        _save_to_json(data)


# Initialize table on startup
_ensure_table()
