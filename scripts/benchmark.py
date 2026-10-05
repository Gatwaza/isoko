"""Run a Q&A benchmark against a running Umujyanama API.

Input: JSONL with {"question": ..., "reference": ..., "language": "rw"|"en" (optional)}
       (the format C4IR's golden dataset can be converted to).
Output: per-item results JSONL + summary (latency, escalation rate, token-F1 vs reference).

    python scripts/benchmark.py scripts/sample_eval.jsonl --url http://localhost:8000 --key demo-benchmark-key
"""
import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.retrieval import tokenize  # noqa: E402


def f1(pred: str, ref: str) -> float:
    p, r = Counter(tokenize(pred)), Counter(tokenize(ref))
    common = sum((p & r).values())
    if not common:
        return 0.0
    prec, rec = common / sum(p.values()), common / sum(r.values())
    return 2 * prec * rec / (prec + rec)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--key", default="demo-benchmark-key")
    ap.add_argument("--out", default="data/benchmark_results.jsonl")
    args = ap.parse_args()

    items = [json.loads(line) for line in open(args.dataset, encoding="utf-8") if line.strip()]
    results = []
    with httpx.Client(base_url=args.url, headers={"X-API-Key": args.key}, timeout=90) as c:
        for it in items:
            t0 = time.perf_counter()
            r = c.post("/v1/advisory/query", json={"question": it["question"], "language": it.get("language", "auto")})
            r.raise_for_status()
            d = r.json()
            res = {**it, "answer": d["answer"], "escalated": d["escalated"], "sources": [s["id"] for s in d["sources"]],
                   "model": d["model"], "latency_ms": int((time.perf_counter() - t0) * 1000),
                   "f1": round(f1(d["answer"], it.get("reference", "")), 3) if it.get("reference") else None}
            if "expected_source" in it:
                res["source_hit"] = it["expected_source"] in res["sources"][:1]
            results.append(res)
            print(f"[{'ESC' if res['escalated'] else 'ok '}] {res['latency_ms']:>5}ms f1={res['f1']}  {it['question'][:70]}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    lat = [r["latency_ms"] for r in results]
    f1s = [r["f1"] for r in results if r["f1"] is not None]
    hits = [r["source_hit"] for r in results if "source_hit" in r]
    print("\n=== summary ===")
    print(f"items: {len(results)}   escalated: {sum(r['escalated'] for r in results)}")
    print(f"latency ms: median {statistics.median(lat):.0f}, p95 {sorted(lat)[int(0.95 * (len(lat) - 1))]}")
    if f1s:
        print(f"token-F1 vs reference: mean {statistics.mean(f1s):.3f}")
    if hits:
        print(f"top-1 source accuracy: {sum(hits) / len(hits):.0%}")


if __name__ == "__main__":
    main()
