"""CI regression gate: fails (exit 1) if accuracy, safety or Kinyarwanda retrieval regress.

Runs deterministically without an LLM (curated-text mode), so it is fast and reproducible in CI.
Thresholds are the v0.2 baseline minus a small margin; raise them as the system improves.
    .venv/bin/python eval/regression_gate.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
os.environ.update({"DATABASE_URL": "", "DB_PATH": os.path.join(tempfile.mkdtemp(), "gate.db"), "LLM_PROVIDER": "none"})

from app import advisor  # noqa: E402
from run_eval import run_isoko, summarize  # noqa: E402

GATES = {  # metric: (minimum or maximum, threshold)
    "fully_correct": ("min", 88.0),
    "fully_correct_rw": ("min", 77.0),
    "oos_handled": ("min", 100.0),
    "unsupported_number_rate": ("max", 8.0),
    "source_accuracy": ("min", 86.0),
}
DEV_MIN = 19  # of 20 fresh Kinyarwanda questions

items = [json.loads(l) for l in open(ROOT / "eval" / "qa_testset.jsonl") if l.strip()]
summary = summarize(run_isoko(items, None), True)
failures = []
for m, (kind, th) in GATES.items():
    v = summary[m]
    ok = v >= th if kind == "min" else v <= th
    print(f"{'PASS' if ok else 'FAIL'} {m}: {v} ({'>=' if kind == 'min' else '<='} {th})")
    if not ok:
        failures.append(m)

dev = [json.loads(l) for l in open(ROOT / "eval" / "qa_devset.jsonl") if l.strip()]
dev_ok = 0
for it in dev:
    a = advisor.answer(it["question"], lang=it["language"], log=False)
    top = a.sources[0]["id"] if a.sources else None
    dev_ok += (top == it["expected_source"]) if it["expected_source"] else a.escalated
print(f"{'PASS' if dev_ok >= DEV_MIN else 'FAIL'} kinyarwanda dev set: {dev_ok}/{len(dev)} (>= {DEV_MIN})")
if dev_ok < DEV_MIN:
    failures.append("dev")
sys.exit(1 if failures else 0)
