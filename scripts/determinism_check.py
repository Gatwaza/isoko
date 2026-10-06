"""Benchmark determinism check: submit the same N questions twice as tagged runs (async jobs API) and
verify identical answers and sources.

    .venv/bin/python scripts/determinism_check.py --url http://localhost:8000 --key <api key> --n 500
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def questions(n: int) -> list[dict]:
    base = [json.loads(l) for f in ("qa_testset.jsonl", "qa_devset.jsonl") for l in open(ROOT / "eval" / f) if l.strip()]
    districts = [None, "Nyagatare", "Musanze", "Huye", "Rusizi", "Bugesera"]
    out = []
    i = 0
    while len(out) < n:  # cycle through the question bank with different district contexts
        q = base[i % len(base)]
        out.append({"id": f"d{len(out)}", "question": q["question"], "language": q.get("language", "auto"),
                    "district": districts[(i // len(base)) % len(districts)]})
        i += 1
    return out


def run_job(c: httpx.Client, items: list[dict], run_id: str) -> list[dict]:
    r = c.post("/v1/jobs", json={"items": items}, headers={"X-Benchmark-Run": run_id})
    r.raise_for_status()
    jid = r.json()["job_id"]
    t0 = time.time()
    while True:
        d = c.get(f"/v1/jobs/{jid}", params={"limit": 1}).json()
        print(f"  {run_id}: {d['done']}/{d['total']}  ({time.time() - t0:.0f}s)", end="\r")
        if d["status"] == "done":
            break
        time.sleep(3)
    print()
    res = []
    for off in range(0, len(items), 1000):
        res += c.get(f"/v1/jobs/{jid}", params={"offset": off, "limit": 1000}).json()["results"]
    return sorted(res, key=lambda r: r["index"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--key", required=True)
    ap.add_argument("--n", type=int, default=500)
    a = ap.parse_args()
    items = questions(a.n)
    tag = uuid.uuid4().hex[:6]
    with httpx.Client(base_url=a.url, headers={"X-API-Key": a.key}, timeout=60) as c:
        system = c.get("/v1/system").json()
        r1 = run_job(c, items, f"determinism-{tag}-a")
        r2 = run_job(c, items, f"determinism-{tag}-b")
    diffs = [(x["id"], x["answer"][:80], y["answer"][:80]) for x, y in zip(r1, r2)
             if x["answer"] != y["answer"] or [s["id"] for s in x["sources"]] != [s["id"] for s in y["sources"]]]
    generated = sum(1 for x in r1 if x["model"] not in ("retrieval", "overview"))
    report = {"n": len(items), "identical": len(items) - len(diffs), "differences": diffs[:20],
              "generated_by_llm": generated, "system": system}
    out = ROOT / "eval" / "results" / "determinism.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"{report['identical']}/{report['n']} identical across two runs ({generated} answers LLM-generated). -> {out}")
    sys.exit(0 if not diffs else 1)


if __name__ == "__main__":
    main()
