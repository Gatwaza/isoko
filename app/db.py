"""Persistence: farmer profiles, interaction log, field reports, SMS outbox.

Two interchangeable backends behind one small API:
  - Postgres (Supabase, or any Postgres in a Rwandan data centre) when DATABASE_URL is set
  - SQLite otherwise (local development, single-server Docker)

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
_conn = None
PG = bool(config.DATABASE_URL)

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    phone TEXT PRIMARY KEY, lang TEXT NOT NULL DEFAULT 'rw', district TEXT, main_crop TEXT,
    created_at REAL NOT NULL, updated_at REAL NOT NULL, consented_at REAL, consent_session TEXT
);
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, channel TEXT NOT NULL, user_hash TEXT,
    lang TEXT, district TEXT, category TEXT, crop TEXT, topic TEXT, query TEXT, answer TEXT, sources TEXT,
    confidence REAL, escalated INTEGER NOT NULL DEFAULT 0, latency_ms INTEGER, model TEXT
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, user_hash TEXT, district TEXT,
    issue TEXT NOT NULL, detail TEXT, channel TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sms_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, phone TEXT NOT NULL, message TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS farm_visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, promoter_hash TEXT, farmer_code TEXT, district TEXT,
    crop TEXT, issue TEXT, diagnosis TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS kb_extra (
    id TEXT PRIMARY KEY, ts REAL NOT NULL, entry TEXT NOT NULL, source TEXT, active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_interactions_ts ON interactions(ts);
CREATE INDEX IF NOT EXISTS idx_reports_ts ON reports(ts);
"""


def conn():
    global _conn
    if _conn is None:
        if PG:
            import psycopg
            from psycopg.rows import dict_row
            # prepare_threshold=None: required behind Supabase's transaction pooler (pgbouncer).
            _conn = psycopg.connect(config.DATABASE_URL, autocommit=True, row_factory=dict_row,
                                    prepare_threshold=None)
        else:
            Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SQLITE_SCHEMA)
            cols = {r[1] for r in _conn.execute("PRAGMA table_info(interactions)")}
            if "run_id" not in cols:  # databases created before v0.2
                _conn.execute("ALTER TABLE interactions ADD COLUMN run_id TEXT")
                _conn.commit()
            pcols = {r[1] for r in _conn.execute("PRAGMA table_info(profiles)")}
            for col, typ in (("consented_at", "REAL"), ("consent_session", "TEXT")):
                if col not in pcols:  # databases created before v0.3
                    _conn.execute(f"ALTER TABLE profiles ADD COLUMN {col} {typ}")
            _conn.commit()
    return _conn


def _sql(sql: str) -> str:
    return sql.replace("%", "%%").replace("?", "%s") if PG else sql


def execute(sql: str, params: tuple = ()) -> None:
    global _conn
    with _lock:
        try:
            conn().execute(_sql(sql), params)
        except Exception:
            if not PG:
                raise
            _conn = None  # serverless: the pooled connection may have been dropped; retry once
            conn().execute(_sql(sql), params)
        if not PG:
            conn().commit()


def query(sql: str, params: tuple = ()) -> list[dict]:
    global _conn
    with _lock:
        try:
            rows = conn().execute(_sql(sql), params).fetchall()
        except Exception:
            if not PG:
                raise
            _conn = None
            rows = conn().execute(_sql(sql), params).fetchall()
    return [dict(r) for r in rows]


# Dialect helpers for the dashboard (timestamps are stored as epoch seconds in both backends).
def day_expr(col: str = "ts") -> str:
    return (f"to_char(to_timestamp({col}) AT TIME ZONE 'Africa/Kigali', 'YYYY-MM-DD')" if PG
            else f"date({col}, 'unixepoch', '+2 hours')")


def time_expr(col: str = "ts") -> str:
    return (f"to_char(to_timestamp({col}) AT TIME ZONE 'Africa/Kigali', 'YYYY-MM-DD HH24:MI:SS')" if PG
            else f"datetime({col}, 'unixepoch', '+2 hours')")


def hash_user(phone: str | None) -> str | None:
    if not phone:
        return None
    return hashlib.sha256((config.PHONE_HASH_SALT + phone).encode()).hexdigest()[:16]


def get_profile(phone: str) -> dict:
    rows = query("SELECT * FROM profiles WHERE phone = ?", (phone,))
    if rows:
        return rows[0]
    now = time.time()
    execute("INSERT INTO profiles (phone, lang, created_at, updated_at) VALUES (?, 'rw', ?, ?) "
            "ON CONFLICT (phone) DO NOTHING", (phone, now, now))
    return {"phone": phone, "lang": "rw", "district": None, "main_crop": None, "consented_at": None, "consent_session": None}


def update_profile(phone: str, **fields) -> None:
    get_profile(phone)
    allowed = {k: v for k, v in fields.items() if k in {"lang", "district", "main_crop", "consented_at", "consent_session"}}
    if not allowed:
        return
    sets = ", ".join(f"{k} = ?" for k in allowed)
    execute(f"UPDATE profiles SET {sets}, updated_at = ? WHERE phone = ?", (*allowed.values(), time.time(), phone))


def log_interaction(*, channel: str, phone: str | None = None, lang: str | None = None,
                    district: str | None = None, category: str | None = None,
                    crop: str | None = None, topic: str | None = None, query: str | None = None,
                    answer: str | None = None, sources: list | None = None,
                    confidence: float | None = None, escalated: bool = False,
                    latency_ms: int | None = None, model: str | None = None, run_id: str | None = None) -> None:
    execute(
        """INSERT INTO interactions (ts, channel, user_hash, lang, district, category, crop, topic,
           query, answer, sources, confidence, escalated, latency_ms, model, run_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (time.time(), channel, hash_user(phone), lang, district, category, crop, topic, query,
         answer, json.dumps(sources or []), confidence, int(escalated), latency_ms, model, run_id),
    )


def log_visit(*, promoter: str | None, farmer_code: str | None, district: str | None, crop: str | None,
              issue: str | None, diagnosis: str | None, notes: str | None) -> None:
    execute("""INSERT INTO farm_visits (ts, promoter_hash, farmer_code, district, crop, issue, diagnosis, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (time.time(), hash_user(promoter), farmer_code, district, crop, issue, diagnosis, notes))


def upsert_kb(entry_id: str, entry: dict, source: str) -> None:
    execute("DELETE FROM kb_extra WHERE id = ?", (entry_id,))
    execute("INSERT INTO kb_extra (id, ts, entry, source, active) VALUES (?, ?, ?, ?, 1)",
            (entry_id, time.time(), json.dumps(entry, ensure_ascii=False), source))


def kb_extra() -> list[dict]:
    try:
        return [json.loads(r["entry"]) for r in query("SELECT entry FROM kb_extra WHERE active = 1 ORDER BY ts")]
    except Exception:  # table missing on an older Postgres schema: run the migration
        return []


def log_report(*, phone: str | None, district: str | None, issue: str, detail: str | None, channel: str) -> None:
    execute("INSERT INTO reports (ts, user_hash, district, issue, detail, channel) VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), hash_user(phone), district, issue, detail, channel))


def queue_sms(phone: str, message: str, status: str) -> None:
    execute("INSERT INTO sms_outbox (ts, phone, message, status) VALUES (?, ?, ?, ?)",
            (time.time(), phone, message, status))


def purge_old(days: int) -> int:
    """Retention policy: delete interactions, reports, SMS and visits older than `days`."""
    if days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    n = query("SELECT COUNT(*) AS n FROM interactions WHERE ts < ?", (cutoff,))[0]["n"]
    for table in ("interactions", "reports", "sms_outbox", "farm_visits"):
        try:
            execute(f"DELETE FROM {table} WHERE ts < ?", (cutoff,))
        except Exception:
            pass
    return n
