"""Import C4IR's curated Q&A pairs for the refinement window, with a frozen 20% holdout.

    .venv/bin/python scripts/import_c4ir.py data/c4ir_qa.csv --dry-run
    .venv/bin/python scripts/import_c4ir.py data/c4ir_qa.csv --url http://localhost:8000 --admin-key $ADMIN_KEYS

Accepts CSV or JSONL with at least a question and an answer column (names are matched flexibly, e.g.
question/query/ikibazo and answer/response/igisubizo; optional language, crop, topic, answer_en, answer_rw).
- Schema check: rows without a question or answer are reported and skipped.
- Deduplication: normalised question text (case, punctuation, spacing) keeps the first occurrence.
- Holdout: 20% of questions, chosen by a stable hash of the normalised question, are written to
  eval/c4ir_holdout.jsonl and NEVER imported or tuned on. Improvement claims are measured on it.
- The other 80% is imported through POST /v1/admin/knowledge in batches.
"""
import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
Q_COLS = ("question", "query", "prompt", "ikibazo", "q")
A_COLS = ("answer", "response", "reference", "igisubizo", "a")


def norm(q: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", q.lower())).strip()


def pick(row: dict, names) -> str:
    for k, v in row.items():
        if k and k.strip().lower() in names and v and str(v).strip():
            return str(v).strip()
    return ""


def load(path: Path) -> list[dict]:
    if path.suffix == ".jsonl":
        return [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def detect_lang(text: str) -> str:
    sys.path.insert(0, str(ROOT))
    from app.advisor import detect_language
    return detect_language(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--admin-key")
    ap.add_argument("--holdout", type=float, default=0.2)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    rows = load(Path(a.file))
    seen, items, holdout, bad, dup = set(), [], [], 0, 0
    for i, r in enumerate(rows):
        q, ans = pick(r, Q_COLS), pick(r, A_COLS)
        if not q or not ans:
            bad += 1
            continue
        key = norm(q)
        if key in seen:
            dup += 1
            continue
        seen.add(key)
        h = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        lang = (r.get("language") or r.get("lang") or detect_lang(q)).strip().lower()[:2]
        rec = {"question": q, "reference": ans, "language": "rw" if lang.startswith("rw") or lang.startswith("ki") else "en",
               "crop": (r.get("crop") or "general").strip().lower(), "topic": (r.get("topic") or "general").strip().lower()}
        if h < a.holdout:
            holdout.append(rec)
        else:
            rec_id = "c4ir-" + hashlib.sha256(key.encode()).hexdigest()[:12]
            items.append({"id": rec_id, "question": q[:500], "crop": rec["crop"][:30], "topic": rec["topic"][:30],
                          "answer_rw": (r.get("answer_rw") or (ans if rec["language"] == "rw" else ans))[:2000],
                          "answer_en": (r.get("answer_en") or (ans if rec["language"] == "en" else ""))[:2000],
                          "source": "C4IR refinement data"})

    out = ROOT / "eval" / "c4ir_holdout.jsonl"
    out.write_text("".join(json.dumps(h, ensure_ascii=False) + "\n" for h in holdout), encoding="utf-8")
    print(f"rows {len(rows)} | skipped (missing fields) {bad} | duplicates {dup} | import {len(items)} | holdout {len(holdout)} -> {out}")
    if a.dry_run:
        return
    if not a.admin_key:
        sys.exit("--admin-key required to import")
    with httpx.Client(base_url=a.url, headers={"X-Admin-Key": a.admin_key}, timeout=120) as c:
        for i in range(0, len(items), 500):
            r = c.post("/v1/admin/knowledge", json=items[i:i + 500])
            r.raise_for_status()
            print("imported", i + len(items[i:i + 500]), "->", r.json())
    print("Measure on the holdout: .venv/bin/python scripts/benchmark.py eval/c4ir_holdout.jsonl --url", a.url)


if __name__ == "__main__":
    main()
