"""End-to-end voice evaluation: each Kinyarwanda test question is synthesised (MMS-TTS), sent as audio to
/v1/voice/ask (ASR -> advisor -> TTS), and scored like the text pipeline (top source = expected entry).

    ML_SERVICE_URL=http://localhost:7860 ML_TOKEN=... .venv/bin/python eval/voice_e2e_eval.py
Synthetic speech is easier than real farmers' speech; real-voice testing uses C4IR's 20 h audio set.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.update({"DATABASE_URL": "", "DB_PATH": os.path.join(tempfile.mkdtemp(), "v.db"), "API_KEYS": "k", "LLM_PROVIDER": "none"})
from fastapi.testclient import TestClient  # noqa: E402

from app import ml  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)
items = [json.loads(l) for l in open(ROOT / "eval" / "qa_testset.jsonl") if l.strip()]
items = [i for i in items if i["language"] == "rw"]
rows, ok_voice, ok_text = [], 0, 0
for it in items:
    audio = ml.tts(it["question"])
    t0 = time.perf_counter()
    d = c.post("/v1/voice/ask", headers={"X-API-Key": "k"}, files={"audio": ("q.wav", audio)}).json()
    lat = time.perf_counter() - t0
    t = c.post("/v1/advisory/query", headers={"X-API-Key": "k"}, json={"question": it["question"], "language": "rw"}).json()
    exp = it["expected_source"]
    good_v = (d["sources"][:1] and d["sources"][0]["id"] == exp) if exp else d["escalated"]
    good_t = (t["sources"][:1] and t["sources"][0]["id"] == exp) if exp else t["escalated"]
    ok_voice += bool(good_v); ok_text += bool(good_t)
    rows.append({"id": it["id"], "question": it["question"], "heard": d["transcript"], "voice_ok": bool(good_v),
                 "text_ok": bool(good_t), "latency_s": round(lat, 2)})
    print(f"{'OK ' if good_v else 'MISS'} {it['question'][:45]:45} | heard: {d['transcript'][:45]}")
summary = {"n": len(items), "voice_correct_pct": round(100 * ok_voice / len(items), 1),
           "text_correct_pct": round(100 * ok_text / len(items), 1),
           "median_latency_s": sorted(r["latency_s"] for r in rows)[len(rows) // 2]}
(ROOT / "eval" / "results" / "voice_e2e.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1))
print(summary)
