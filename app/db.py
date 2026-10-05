"""SQLite persistence: farmer profiles, interaction log, field reports, SMS outbox.

Phone numbers are stored only in `profiles` (needed to send SMS); every analytics
table stores a salted hash instead.
"""
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

from . import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    phone TEXT PRIMARY KEY,
    lang TEXT NOT NULL DEFAULT 'rw',
    district TEXT,
    main_crop TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    channel TEXT NOT NULL,
    user_hash TEXT,
    lang TEXT,
    district TEXT,
    category TEXT,
    crop TEXT,
    topic TEXT,
    query TEXT,
    answer TEXT,
    sources TEXT,
    confidence REAL,
    escalated INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER,
    model TEXT
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    user_hash TEXT,
    district TEXT,
    issue TEXT NOT NULL,
    detail TEXT,
    channel TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sms_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    phone TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_interactions_ts ON interactions(ts);
CREATE INDEX IF NOT EXISTS idx_reports_ts ON reports(ts);
"""


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
    return _conn


def hash_user(phone: str | None) -> str | None:
    if not phone:
        return None
    return hashlib.sha256((config.PHONE_HASH_SALT + phone).encode()).hexdigest()[:16]


def get_profile(phone: str) -> dict:
    row = conn().execute("SELECT * FROM profiles WHERE phone = ?", (phone,)).fetchone()
    if row:
        return dict(row)
    now = time.time()
    with _lock:
        conn().execute(
            "INSERT OR IGNORE INTO profiles (phone, lang, created_at, updated_at) VALUES (?, 'rw', ?, ?)",
            (phone, now, now),
        )
        conn().commit()
    return {"phone": phone, "lang": "rw", "district": None, "main_crop": None}


def update_profile(phone: str, **fields) -> None:
    get_profile(phone)
    allowed = {k: v for k, v in fields.items() if k in {"lang", "district", "main_crop"}}
    if not allowed:
        return
    sets = ", ".join(f"{k} = ?" for k in allowed)
    with _lock:
        conn().execute(
            f"UPDATE profiles SET {sets}, updated_at = ? WHERE phone = ?",
            (*allowed.values(), time.time(), phone),
        )
        conn().commit()


def log_interaction(*, channel: str, phone: str | None = None, lang: str | None = None,
                    district: str | None = None, category: str | None = None,
                    crop: str | None = None, topic: str | None = None, query: str | None = None,
                    answer: str | None = None, sources: list | None = None,
                    confidence: float | None = None, escalated: bool = False,
                    latency_ms: int | None = None, model: str | None = None) -> None:
    with _lock:
        conn().execute(
            """INSERT INTO interactions (ts, channel, user_hash, lang, district, category, crop, topic,
               query, answer, sources, confidence, escalated, latency_ms, model)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (time.time(), channel, hash_user(phone), lang, district, category, crop, topic, query,
             answer, json.dumps(sources or []), confidence, int(escalated), latency_ms, model),
        )
        conn().commit()


def log_report(*, phone: str | None, district: str | None, issue: str, detail: str | None, channel: str) -> None:
    with _lock:
        conn().execute(
            "INSERT INTO reports (ts, user_hash, district, issue, detail, channel) VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), hash_user(phone), district, issue, detail, channel),
        )
        conn().commit()


def queue_sms(phone: str, message: str, status: str) -> None:
    with _lock:
        conn().execute(
            "INSERT INTO sms_outbox (ts, phone, message, status) VALUES (?, ?, ?, ?)",
            (time.time(), phone, message, status),
        )
        conn().commit()


def query(sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, params).fetchall()]
