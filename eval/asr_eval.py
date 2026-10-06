"""Kinyarwanda speech-recognition benchmark: WER/CER of open ASR models on real read speech.

    .venv-ml/bin/python eval/asr_eval.py badrex/w2v-bert-2.0-kinyarwanda-asr mbazaNLP/Whisper-Small-Kinyarwanda

Test audio: 80 clips from KYAGABA/kinyarwanda_cleaned_testset_verified (test split, 8 spread-out
batches of 10), downloaded by the team into data/asr_test (not redistributed).
"""
import json
import re
import sys
import time
from pathlib import Path

import soundfile as sf
import torch
import torchaudio

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "eval" / "results" / "asr_results.json"


def norm(t: str) -> str:
    # Kinyarwanda corpora differ on apostrophes ("k'amafaranga" vs "kamafaranga"); join them so
    # an orthographic convention is not counted as a recognition error.
    t = t.lower().replace("’", "'").replace("'", "")
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def edits(a, b) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def load(path: str):
    wav, sr = sf.read(path, dtype="float32", always_2d=True)
    wav = torch.from_numpy(wav.mean(axis=1))
    if sr != 16000:
        wav = torchaudio.functional.resample(wav, sr, 16000)
    return wav.numpy()


def make_asr(model_id: str, device: str):
    from transformers import pipeline
    kw = {}
    pipe = pipeline("automatic-speech-recognition", model=model_id, device=device)
    return lambda audio: pipe({"raw": audio, "sampling_rate": 16000}, **kw)["text"]


def main():
    items = json.loads((ROOT / "data" / "asr_test" / "manifest.json").read_text())
    results = json.loads(OUT.read_text()) if OUT.exists() else {}
    for model_id in sys.argv[1:]:
        device = "cpu"  # the hosted service runs on CPU, so measure CPU latency
        asr = make_asr(model_id, device)
        w_err = w_tot = c_err = c_tot = 0
        lat, samples = [], []
        for it in items:
            audio = load(it["path"])
            t0 = time.perf_counter()
            hyp = asr(audio)
            lat.append(time.perf_counter() - t0)
            ref_n, hyp_n = norm(it["text"]), norm(hyp)
            w_err += edits(ref_n.split(), hyp_n.split()); w_tot += len(ref_n.split())
            c_err += edits(list(ref_n), list(hyp_n)); c_tot += len(ref_n)
            samples.append({"ref": it["text"], "hyp": hyp})
        results[model_id] = {"wer": round(100 * w_err / w_tot, 1), "cer": round(100 * c_err / c_tot, 1),
                             "median_latency_s_cpu": round(sorted(lat)[len(lat) // 2], 2), "n": len(items),
                             "samples": samples}
        print(f"{model_id}: WER {results[model_id]['wer']}%  CER {results[model_id]['cer']}%  "
              f"median CPU latency {results[model_id]['median_latency_s_cpu']}s")
        OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
