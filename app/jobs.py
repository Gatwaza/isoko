"""Asynchronous benchmark jobs: submit up to 5,000 questions, poll for progress and results.

Jobs live in the database, so they survive restarts. A background worker processes them on a dedicated
host; on serverless hosting (no background threads), each poll processes the next slice within a time budget.
"""
import hashlib
import json
import threading
import time
import uuid

from . import advisor, config, db

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, ts REAL NOT NULL, key_hash TEXT NOT NULL, run_id TEXT, status TEXT NOT NULL,
    total INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0, finished_ts REAL
);
CREATE TABLE IF NOT EXISTS job_items (
    job_id TEXT NOT NULL, idx INTEGER NOT NULL, item TEXT NOT NULL, result TEXT, PRIMARY KEY (job_id, idx)
);
"""
_ensured = False
_worker_started = False
_lock = threading.Lock()


def _ensure():
    global _ensured
    if not _ensured and not db.PG:
        db.conn().executescript(SCHEMA_SQLITE)
    _ensured = True


def key_hash(key: str) -> str:
    return hashlib.sha256(("job:" + key).encode()).hexdigest()[:16]


def create(items: list[dict], key: str, run_id: str | None) -> str:
    _ensure()
    jid = "job_" + uuid.uuid4().hex[:16]
    db.execute("INSERT INTO jobs (id, ts, key_hash, run_id, status, total, done) VALUES (?, ?, ?, ?, 'queued', ?, 0)",
               (jid, time.time(), key_hash(key), run_id, len(items)))
    for i, it in enumerate(items):
        db.execute("INSERT INTO job_items (job_id, idx, item) VALUES (?, ?, ?)", (jid, i, json.dumps(it, ensure_ascii=False)))
    start_worker()
    return jid


def get(jid: str, key: str) -> dict | None:
    _ensure()
    rows = db.query("SELECT * FROM jobs WHERE id = ? AND key_hash = ?", (jid, key_hash(key)))
    return rows[0] if rows else None


def results(jid: str, offset: int, limit: int) -> list[dict]:
    rows = db.query("SELECT idx, item, result FROM job_items WHERE job_id = ? AND result IS NOT NULL ORDER BY idx "
                    "LIMIT ? OFFSET ?", (jid, limit, offset))
    out = []
    for r in rows:
        item = json.loads(r["item"])
        out.append({"index": r["idx"], "id": item.get("id"), **json.loads(r["result"])})
    return out


def process(jid: str, budget_s: float) -> None:
    """Answer pending items of a job until the time budget is used."""
    t_end = time.time() + budget_s
    job = db.query("SELECT run_id, status FROM jobs WHERE id = ?", (jid,))
    if not job or job[0]["status"] == "done":
        return
    run_id = job[0]["run_id"]
    db.execute("UPDATE jobs SET status = 'running' WHERE id = ? AND status = 'queued'", (jid,))
    while time.time() < t_end:
        pending = db.query("SELECT idx, item FROM job_items WHERE job_id = ? AND result IS NULL ORDER BY idx LIMIT 5", (jid,))
        if not pending:
            db.execute("UPDATE jobs SET status = 'done', finished_ts = ? WHERE id = ?", (time.time(), jid))
            return
        for p in pending:
            it = json.loads(p["item"])
            lang = it.get("language")
            adv = advisor.answer(it["question"], lang=None if lang in (None, "auto") else lang,
                                 district=it.get("district"), crop=it.get("crop"), channel="api", run_id=run_id)
            db.execute("UPDATE job_items SET result = ? WHERE job_id = ? AND idx = ? AND result IS NULL",
                       (json.dumps(adv.to_dict(), ensure_ascii=False), jid, p["idx"]))
            db.execute("UPDATE jobs SET done = (SELECT COUNT(*) FROM job_items WHERE job_id = ? AND result IS NOT NULL) "
                       "WHERE id = ?", (jid, jid))


def _worker():
    while True:
        try:
            _ensure()
            open_jobs = db.query("SELECT id FROM jobs WHERE status IN ('queued', 'running') ORDER BY ts LIMIT 1")
            if open_jobs:
                process(open_jobs[0]["id"], budget_s=30)
                continue
        except Exception as exc:  # keep the worker alive
            print("job worker error:", exc, flush=True)
        time.sleep(2)


def start_worker() -> None:
    global _worker_started
    if config.INLINE_TASKS:  # serverless: no background threads; polls process work instead
        return
    with _lock:
        if not _worker_started:
            threading.Thread(target=_worker, daemon=True, name="isoko-jobs").start()
            _worker_started = True
