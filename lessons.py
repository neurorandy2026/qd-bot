"""
Persistent lessons store for continuous learning system.
PostgreSQL (Railway) with JSON fallback — same pattern as criteria.py

Each lesson captures a market observation from Randy with:
- Original image + description
- Claude's extracted rule, category, summary
- Optional Q&A for clarification
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
LESSONS_PATH = os.path.join(DATA_DIR, "lessons.json")
MAX_ACTIVE_LESSONS = 5

CATEGORIES = ["DEX", "GEX", "Formato", "Error detectado", "Ejemplo bueno", "General"]


def _get_conn():
    return psycopg2.connect(DATABASE_URL)


def _ensure_table():
    if not DATABASE_URL:
        return
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS lessons (
                        id SERIAL PRIMARY KEY,
                        image_b64 TEXT DEFAULT '',
                        image_type VARCHAR(30) DEFAULT 'image/png',
                        text TEXT NOT NULL,
                        rule TEXT DEFAULT '',
                        category VARCHAR(50) DEFAULT 'General',
                        summary TEXT DEFAULT '',
                        question TEXT DEFAULT '',
                        answer TEXT DEFAULT '',
                        active BOOLEAN DEFAULT TRUE,
                        created_at VARCHAR(50)
                    )
                """)
            conn.commit()
    except Exception as e:
        print(f"[Lessons] Error creando tabla: {e}")


def _load_from_pg_no_images() -> list:
    """Load all lessons without image data (for display)."""
    try:
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, image_type, text, rule, category, summary, question, answer, active, created_at "
                    "FROM lessons ORDER BY id DESC"
                )
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[Lessons] Error leyendo DB: {e}")
        return []


def _load_from_json() -> list:
    if os.path.exists(LESSONS_PATH):
        try:
            with open(LESSONS_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_to_json(lessons: list):
    os.makedirs(os.path.dirname(LESSONS_PATH) or ".", exist_ok=True)
    with open(LESSONS_PATH, "w") as f:
        json.dump(lessons, f, indent=2, ensure_ascii=False)


def get_all() -> list:
    """Returns all lessons without image data (for dashboard display)."""
    if DATABASE_URL:
        return _load_from_pg_no_images()
    lessons = _load_from_json()
    return [{k: v for k, v in l.items() if k != "image_b64"} for l in lessons]


def get_active_lessons(limit: int = MAX_ACTIVE_LESSONS) -> list:
    """Returns most recent active lessons WITH image data for Claude context."""
    if DATABASE_URL:
        try:
            with _get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT * FROM lessons WHERE active = TRUE ORDER BY id DESC LIMIT %s",
                        (limit,)
                    )
                    return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            print(f"[Lessons] Error leyendo activas: {e}")
            return []
    else:
        lessons = _load_from_json()
        return [l for l in lessons if l.get("active", True)][:limit]


def get_image(lesson_id: int) -> tuple:
    """Returns (image_b64, image_type) for serving via /lesson-image/{id}."""
    if DATABASE_URL:
        try:
            with _get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT image_b64, image_type FROM lessons WHERE id = %s",
                        (lesson_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        return row[0] or "", row[1] or "image/png"
        except Exception as e:
            print(f"[Lessons] Error obteniendo imagen: {e}")
    else:
        for l in _load_from_json():
            if l["id"] == lesson_id:
                return l.get("image_b64", ""), l.get("image_type", "image/png")
    return "", "image/png"


def add_lesson(
    text: str,
    rule: str,
    category: str,
    summary: str,
    question: str,
    answer: str,
    image_b64: str = "",
    image_type: str = "image/png",
) -> dict:
    now_str = datetime.now(ET).strftime("%Y-%m-%d %I:%M %p ET")
    if DATABASE_URL:
        try:
            with _get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "INSERT INTO lessons "
                        "(image_b64, image_type, text, rule, category, summary, question, answer, active, created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,TRUE,%s) "
                        "RETURNING id, image_type, text, rule, category, summary, question, answer, active, created_at",
                        (image_b64, image_type, text.strip(), rule, category, summary, question, answer, now_str),
                    )
                    lesson = dict(cur.fetchone())
                conn.commit()
                return lesson
        except Exception as e:
            print(f"[Lessons] Error insertando: {e}")
            return {}
    else:
        lessons = _load_from_json()
        lesson = {
            "id": max((l["id"] for l in lessons), default=0) + 1,
            "image_b64": image_b64,
            "image_type": image_type,
            "text": text.strip(),
            "rule": rule,
            "category": category,
            "summary": summary,
            "question": question,
            "answer": answer,
            "active": True,
            "created_at": now_str,
        }
        lessons.insert(0, lesson)
        _save_to_json(lessons)
        return lesson


def toggle_lesson(lesson_id: int, active: bool):
    if DATABASE_URL:
        try:
            with _get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE lessons SET active = %s WHERE id = %s",
                        (active, lesson_id)
                    )
                conn.commit()
        except Exception as e:
            print(f"[Lessons] Error toggle: {e}")
    else:
        lessons = _load_from_json()
        for l in lessons:
            if l["id"] == lesson_id:
                l["active"] = active
                break
        _save_to_json(lessons)


def delete_lesson(lesson_id: int):
    if DATABASE_URL:
        try:
            with _get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM lessons WHERE id = %s", (lesson_id,))
                conn.commit()
        except Exception as e:
            print(f"[Lessons] Error eliminando: {e}")
    else:
        lessons = _load_from_json()
        _save_to_json([l for l in lessons if l["id"] != lesson_id])


_ensure_table()
