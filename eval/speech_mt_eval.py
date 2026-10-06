"""TTS intelligibility (round trip) and NLLB translation quality.

    .venv-ml/bin/python eval/speech_mt_eval.py tts   # MMS-TTS Kinyarwanda -> w2v-BERT ASR -> CER vs input text
    .venv-ml/bin/python eval/speech_mt_eval.py mt    # NLLB-200 distilled 600M chrF on the 60 agriculture pairs

TTS intelligibility: synthesise 20 curated Kinyarwanda advisory sentences from the corpus, transcribe
them with the selected ASR model, and report CER against the input text (lower = more intelligible).
"""
import json
import re
import statistics
import sys
import time
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "ml_service"))
from asr_eval import edits, norm  # noqa: E402
from run_eval import chrf  # noqa: E402

OUT = ROOT / "eval" / "results" / "speech_mt_results.json"
ASR_MODEL = "badrex/w2v-bert-2.0-kinyarwanda-asr"


def sentences(n=20):
    corpus = json.loads((ROOT / "app" / "kb" / "corpus.json").read_text())["entries"]
    out = []
    for e in corpus:
        for s in re.split(r"(?<=[.!?])\s+", e["summary_rw"]):
            if 6 <= len(s.split()) <= 18:
                out.append(s)
                break
        if len(out) >= n:
            break
    return out


def tts_eval(results):
    import torchaudio
    from transformers import AutoTokenizer, VitsModel, pipeline
    tok = AutoTokenizer.from_pretrained("facebook/mms-tts-kin")
    model = VitsModel.from_pretrained("facebook/mms-tts-kin")
    from kin_text import normalize
    asr = pipeline("automatic-speech-recognition", model=ASR_MODEL, device="cpu")
    for cond in ("raw", "normalised"):
        c_err = c_tot = 0
        lat, samples = [], []
        for s in sentences():
            spoken = normalize(s)  # what a listener should hear, numbers and units in words
            inp = s if cond == "raw" else spoken
            t0 = time.perf_counter()
            with torch.no_grad():
                wav = model(**tok(inp, return_tensors="pt")).waveform[0]
            lat.append(time.perf_counter() - t0)
            audio = torchaudio.functional.resample(wav, model.config.sampling_rate, 16000).numpy()
            hyp = asr({"raw": audio, "sampling_rate": 16000})["text"]
            c_err += edits(list(norm(spoken)), list(norm(hyp))); c_tot += len(norm(spoken))
            samples.append({"text": s, "spoken": spoken, "asr_of_tts": hyp})
        results[f"tts:facebook/mms-tts-kin:{cond}"] = {"round_trip_cer": round(100 * c_err / c_tot, 1), "n": len(samples),
                                                      "median_synthesis_s_cpu": round(statistics.median(lat), 2),
                                                      "asr_model": ASR_MODEL, "samples": samples[:6]}
        print(f"TTS round-trip CER ({cond} input):", results[f"tts:facebook/mms-tts-kin:{cond}"]["round_trip_cer"], "%")


def mt_eval(results):
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    mid = "facebook/nllb-200-distilled-600M"
    tok = AutoTokenizer.from_pretrained(mid)
    model = AutoModelForSeq2SeqLM.from_pretrained(mid)
    pairs = json.loads((ROOT / "eval" / "mt_agri_testset.json").read_text())[:60]

    def tr(text, src, tgt):
        tok.src_lang = src
        enc = tok(text, return_tensors="pt")
        with torch.no_grad():
            out = model.generate(**enc, forced_bos_token_id=tok.convert_tokens_to_ids(tgt), max_new_tokens=128, num_beams=4)
        return tok.batch_decode(out, skip_special_tokens=True)[0]

    res = {}
    for d, sk, rk, src, tgt in (("en2rw", "en", "rw", "eng_Latn", "kin_Latn"), ("rw2en", "rw", "en", "kin_Latn", "eng_Latn")):
        scores, samples = [], []
        for p in pairs:
            hyp = tr(p[sk], src, tgt)
            scores.append(chrf(hyp, p[rk]))
            samples.append({"src": p[sk], "ref": p[rk], "hyp": hyp})
        res[d] = {"chrf": round(statistics.mean(scores), 1), "samples": samples[:5]}
        print(f"NLLB {d}: chrF {res[d]['chrf']}")
    results["mt:" + mid] = res


if __name__ == "__main__":
    results = json.loads(OUT.read_text()) if OUT.exists() else {}
    {"tts": tts_eval, "mt": mt_eval}[sys.argv[1]](results)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1))
