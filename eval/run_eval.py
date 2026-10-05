"""Isôko evaluation: compares configurations on the held-out Q&A set and an EN-RW translation set.

    python eval/run_eval.py                      # all configurations, writes eval/results/*.json
    python eval/run_eval.py --only qa --models llama3.2

Configurations (Q&A):
  plain-<model>     the open model alone, prompted as a Rwandan farm advisor (no knowledge base)
  isoko-retrieval   Isôko with no generation (curated passages only) - the Vercel/serverless mode
  isoko-<model>     Isôko RAG + guardrails with the model generating English answers

Metrics (per item, then averaged):
  key-fact recall      share of the item's required facts present in the answer
  fully correct        all required facts present (in-scope items)
  unsupported numbers  answer contains a number found neither in the question nor the gold passage
  language match       answer is in the language the farmer used
  out-of-scope handled off-topic question escalated/declined instead of answered
  source accuracy      top cited source is the gold entry (Isôko only)

Translation: chrF (character n-gram F-score, 0-100) of each model on agriculture-domain sentence pairs
filtered from the Digital Umuganda Kinyarwanda-English corpus (CC-BY-4.0), as a proxy for the
EOI's English-Kinyarwanda benchmark set.
"""
import argparse
import json
import os
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("DB_PATH", str(ROOT / "data" / "eval.db"))

from app import advisor, config, llm  # noqa: E402
from app.retrieval import corpus  # noqa: E402

OUT = ROOT / "eval" / "results"
NUM = re.compile(r"\d+(?:[.,]\d+)?")
REFUSAL = re.compile(r"(i don't know|i do not know|i'm not sure|cannot help|can't help|not able to|outside|"
                     r"not related to agriculture|i can only|only help with|sorry|ntabwo nzi|simbizi|nta makuru)", re.I)

# The generic model gets the same information Isôko gets: the target language, stated explicitly.
PLAIN_SYSTEM = ("You are an agricultural extension advisor for smallholder farmers in Rwanda. "
                "Answer the farmer's question with practical, specific advice. If the question is not about "
                "farming, say you can only help with farming. Reply in {lang}, in plain text, at most 120 words.")


def has_fact(answer: str, fact: str) -> bool:
    a = answer.lower()
    return any(alt.strip() and alt.strip() in a for alt in fact.lower().split("|"))


def score_item(item: dict, answer: str, escalated: bool, sources: list[str]) -> dict:
    gold = item["expected_source"]
    lang_ok = advisor.identify_language(answer) == item["language"] if answer.strip() else False
    if gold is None:
        declined = escalated or bool(REFUSAL.search(answer))
        return {"in_scope": False, "oos_handled": declined, "lang_ok": lang_ok}
    e = corpus().by_id[gold]
    evidence = " ".join([item["question"], e["detail_en"], e["detail_rw"], e["summary_en"], e["summary_rw"]])
    allowed = set(NUM.findall(evidence))
    unsupported = sorted(set(NUM.findall(answer)) - allowed)
    facts = item["key_facts"]
    hits = sum(has_fact(answer, f) for f in facts)
    return {
        "in_scope": True,
        "fact_recall": hits / len(facts) if facts else 1.0,
        "fully_correct": hits == len(facts) and not escalated,
        "unsupported_numbers": unsupported,
        "has_unsupported": bool(unsupported),
        "lang_ok": lang_ok,
        "escalated": escalated,
        "source_ok": (sources[:1] == [gold]) if sources else False,
    }


def summarize(rows: list[dict], with_sources: bool) -> dict:
    ins = [r for r in rows if r["score"]["in_scope"]]
    oos = [r for r in rows if not r["score"]["in_scope"]]
    rw = [r for r in rows if r["language"] == "rw"]
    en = [r for r in rows if r["language"] == "en"]

    def pct(xs):
        return round(100 * sum(xs) / len(xs), 1) if xs else None

    s = {
        "n": len(rows),
        "fact_recall": pct([r["score"]["fact_recall"] for r in ins]),
        "fully_correct": pct([r["score"]["fully_correct"] for r in ins]),
        "fully_correct_en": pct([r["score"]["fully_correct"] for r in ins if r["language"] == "en"]),
        "fully_correct_rw": pct([r["score"]["fully_correct"] for r in ins if r["language"] == "rw"]),
        "unsupported_number_rate": pct([r["score"]["has_unsupported"] for r in ins]),
        "language_match": pct([r["score"]["lang_ok"] for r in rows]),
        "language_match_rw": pct([r["score"]["lang_ok"] for r in rw]),
        "oos_handled": pct([r["score"]["oos_handled"] for r in oos]),
        "latency_median_ms": int(statistics.median([r["latency_ms"] for r in rows])),
        "n_in_scope": len(ins), "n_oos": len(oos), "n_rw": len(rw), "n_en": len(en),
    }
    if with_sources:
        s["source_accuracy"] = pct([r["score"]["source_ok"] for r in ins])
    return s


def run_plain(items, model):
    rows = []
    for it in items:
        t0 = time.perf_counter()
        config.LLM_PROVIDER, config.LLM_MODEL = "ollama", model
        try:
            lang = "Kinyarwanda" if it["language"] == "rw" else "English"
            ans = llm.chat(PLAIN_SYSTEM.format(lang=lang), it["question"], max_tokens=300)
        except llm.LLMUnavailable as exc:
            ans = f"[error: {exc}]"
        ms = int((time.perf_counter() - t0) * 1000)
        rows.append({**it, "answer": ans, "latency_ms": ms, "score": score_item(it, ans, False, [])})
        print(f"  plain-{model} {it['id']} {ms}ms")
    return rows


def run_isoko(items, model):
    rows = []
    for it in items:
        if model:
            config.LLM_PROVIDER, config.LLM_MODEL = "ollama", model
        else:
            config.LLM_PROVIDER = "none"
        t0 = time.perf_counter()
        adv = advisor.answer(it["question"], lang=it["language"], channel="api", log=False)
        ms = int((time.perf_counter() - t0) * 1000)
        srcs = [s["id"] for s in adv.sources]
        rows.append({**it, "answer": adv.answer, "engine": adv.model, "sources": srcs, "latency_ms": ms,
                     "score": score_item(it, adv.answer, adv.escalated, srcs)})
        print(f"  isoko-{model or 'retrieval'} {it['id']} {ms}ms {adv.model}")
    return rows


# ---------- chrF (Popović 2015), character 6-grams, beta=2 ----------

def _ngrams(s: str, n: int) -> Counter:
    s = re.sub(r"\s+", " ", s.strip())
    return Counter(s[i:i + n] for i in range(len(s) - n + 1))


def chrf(hyp: str, ref: str, max_n: int = 6, beta: float = 2.0) -> float:
    precs, recs = [], []
    for n in range(1, max_n + 1):
        h, r = _ngrams(hyp, n), _ngrams(ref, n)
        if not h or not r:
            continue
        overlap = sum((h & r).values())
        precs.append(overlap / sum(h.values()))
        recs.append(overlap / sum(r.values()))
    if not precs:
        return 0.0
    p, r = sum(precs) / len(precs), sum(recs) / len(recs)
    if p + r == 0:
        return 0.0
    return 100 * (1 + beta ** 2) * p * r / (beta ** 2 * p + r)


def run_mt(pairs, model):
    config.LLM_PROVIDER, config.LLM_MODEL = "ollama", model
    out = {"en2rw": [], "rw2en": []}
    for d, src_key, ref_key, tgt in (("en2rw", "en", "rw", "Kinyarwanda"), ("rw2en", "rw", "en", "English")):
        for p in pairs:
            try:
                hyp = llm.chat(f"Translate the user's sentence into {tgt}. Output only the translation.",
                               p[src_key], max_tokens=120)
            except llm.LLMUnavailable:
                hyp = ""
            out[d].append({"src": p[src_key], "ref": p[ref_key], "hyp": hyp, "chrf": round(chrf(hyp, p[ref_key]), 1)})
        print(f"  mt {model} {d}: chrF {statistics.mean(x['chrf'] for x in out[d]):.1f}")
    return {d: {"chrf": round(statistics.mean(x["chrf"] for x in v), 1), "samples": v} for d, v in out.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="llama3.2,gemma3:4b")
    ap.add_argument("--only", choices=["qa", "mt", "plain", "rescore"], default=None)
    ap.add_argument("--mt-n", type=int, default=60)
    args = ap.parse_args()
    models = [m for m in args.models.split(",") if m]
    OUT.mkdir(parents=True, exist_ok=True)
    items = [json.loads(line) for line in open(ROOT / "eval" / "qa_testset.jsonl", encoding="utf-8") if line.strip()]

    if args.only == "rescore":  # recompute scores and summary from saved answers (no model calls)
        summary = {}
        for f in sorted(OUT.glob("qa_*.json")):
            if f.name == "qa_summary.json":
                continue
            rows = json.loads(f.read_text())
            for r in rows:
                r["score"] = score_item(r, r["answer"], r.get("score", {}).get("escalated", False), r.get("sources", []))
            f.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
            summary[f.stem[3:].replace("gemma3_4b", "gemma3:4b")] = summarize(rows, f.stem.startswith("qa_isoko"))
        (OUT / "qa_summary.json").write_text(json.dumps(summary, indent=1))
        print(json.dumps(summary, indent=1))
        return

    if args.only == "plain":  # rerun only the generic-model baselines, merge into the summary
        summary = json.loads((OUT / "qa_summary.json").read_text()) if (OUT / "qa_summary.json").exists() else {}
        for m in models:
            rows = run_plain(items, m)
            summary[f"plain-{m}"] = summarize(rows, False)
            (OUT / f"qa_plain-{m.replace(':', '_')}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        (OUT / "qa_summary.json").write_text(json.dumps(summary, indent=1))
        print(json.dumps(summary, indent=1))
        return

    if args.only in (None, "qa"):
        summary = {}
        configs = [("isoko-retrieval", lambda: run_isoko(items, None), True)]
        for m in models:
            configs.append((f"plain-{m}", lambda m=m: run_plain(items, m), False))
            configs.append((f"isoko-{m}", lambda m=m: run_isoko(items, m), True))
        for name, fn, with_src in configs:
            print(name)
            rows = fn()
            summary[name] = summarize(rows, with_src)
            (OUT / f"qa_{name.replace(':', '_')}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        (OUT / "qa_summary.json").write_text(json.dumps(summary, indent=1))
        print(json.dumps(summary, indent=1))

    if args.only in (None, "mt"):
        pairs = json.load(open(ROOT / "eval" / "mt_agri_testset.json", encoding="utf-8"))[: args.mt_n]
        mt = {m: run_mt(pairs, m) for m in models}
        (OUT / "mt_results.json").write_text(json.dumps(mt, ensure_ascii=False, indent=1))
        print(json.dumps({m: {d: v["chrf"] for d, v in r.items()} for m, r in mt.items()}, indent=1))


if __name__ == "__main__":
    main()
