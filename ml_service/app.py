"""Isôko model service: Kinyarwanda speech (ASR/TTS), crop-disease photo diagnosis, translation.

Runs on CPU (Hugging Face Space or any server in Rwanda). Open models only, chosen by measured
accuracy (see eval/ in the main repo). Protected by a shared token in the X-ML-Token header.
"""
import io
import os
import subprocess
import threading
import time

import numpy as np
import soundfile as sf
import torch
import torchaudio
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field

from kin_text import normalize
from vision_loader import image_classifier

# Most accurate on our Kinyarwanda benchmark (CER 6.7%); fast on GPU/Apple silicon. On a CPU-only host use
# ASR_MODEL=badrex/w2v-bert-2.0-kinyarwanda-asr (CER 10.4%, 5x faster on CPU, CC-BY-4.0).
ASR_MODEL = os.getenv("ASR_MODEL", "DigitalUmuganda/whisper_small_kinyarwanda")
TTS_MODEL = os.getenv("TTS_MODEL", "facebook/mms-tts-kin")
MT_MODEL = os.getenv("MT_MODEL", "facebook/nllb-200-distilled-600M")
VISION_MODELS = {  # crop -> image classifier (field-tested where marked in eval/results)
    "beans": os.getenv("BEANS_MODEL", "ayoubkirouane/VIT_Beans_Leaf_Disease_Classifier"),
    "cassava": os.getenv("CASSAVA_MODEL", "siddharth963/vit-base-patch16-224-in21k-finetuned-cassava"),
    "general": os.getenv("GENERAL_MODEL", "linkanjarad/mobilenet_v2_1.0_224-plant-disease-identification"),
}
TOKEN = os.getenv("ML_TOKEN", "")
_dev = os.getenv("DEVICE", "auto")
DEVICE = ("mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu") if _dev == "auto" else _dev
MAX_AUDIO_S = 30
torch.set_num_threads(max(1, os.cpu_count() or 1))

app = FastAPI(title="Isôko model service", version="0.2.0")
_models: dict = {}
_lock = threading.Lock()


def auth(x_ml_token: str | None = Header(default=None)):
    if TOKEN and x_ml_token != TOKEN:
        raise HTTPException(status_code=401, detail="invalid token")


def get(name: str):
    with _lock:
        if name in _models:
            return _models[name]
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, VitsModel, pipeline
        if name == "asr":
            _models[name] = pipeline("automatic-speech-recognition", model=ASR_MODEL, device=DEVICE)
        elif name == "tts":  # VITS is fast on CPU and some ops are unsupported on MPS
            _models[name] = (AutoTokenizer.from_pretrained(TTS_MODEL), VitsModel.from_pretrained(TTS_MODEL).eval())
        elif name == "mt":
            _models[name] = (AutoTokenizer.from_pretrained(MT_MODEL), AutoModelForSeq2SeqLM.from_pretrained(MT_MODEL).eval().to(DEVICE))
        elif name.startswith("vision:"):
            _models[name] = image_classifier(VISION_MODELS[name.split(":", 1)[1]], DEVICE)
        return _models[name]


@app.on_event("startup")
def warm():
    # Load in the background so the Space reports healthy quickly.
    def _load():
        for n in ["asr", "tts", "vision:beans", "vision:cassava", "vision:general", "mt"]:
            try:
                get(n)
            except Exception as exc:  # keep the service up even if one model fails to load
                print("model load failed", n, exc, flush=True)
    threading.Thread(target=_load, daemon=True).start()


@app.get("/health")
def health():
    return {"status": "ok", "device": DEVICE, "loaded": sorted(_models), "models": {"asr": ASR_MODEL, "tts": TTS_MODEL, "mt": MT_MODEL, **VISION_MODELS}}


def decode_audio(data: bytes) -> np.ndarray:
    """Any container (wav, ogg/opus from WhatsApp, webm from browsers) -> 16 kHz mono float32."""
    try:
        wav, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        wav = torch.from_numpy(wav.mean(axis=1))
    except Exception:
        proc = subprocess.run(["ffmpeg", "-v", "quiet", "-i", "pipe:0", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"],
                              input=data, capture_output=True, timeout=30)
        if proc.returncode != 0 or not proc.stdout:
            raise HTTPException(status_code=400, detail="unsupported or empty audio")
        return np.frombuffer(proc.stdout, dtype=np.float32)
    if sr != 16000:
        wav = torchaudio.functional.resample(wav, sr, 16000)
    return wav.numpy()


@app.post("/asr", dependencies=[Depends(auth)])
async def asr(audio: UploadFile = File(...)):
    data = await audio.read()
    if len(data) > 5_000_000:
        raise HTTPException(status_code=413, detail="audio too large")
    wav = decode_audio(data)
    if len(wav) < 1600:
        raise HTTPException(status_code=400, detail="audio too short")
    wav = wav[: MAX_AUDIO_S * 16000]
    t0 = time.perf_counter()
    text = get("asr")({"raw": wav, "sampling_rate": 16000})["text"].strip()
    return {"text": text, "language": "rw", "model": ASR_MODEL, "duration_s": round(len(wav) / 16000, 2),
            "latency_ms": int((time.perf_counter() - t0) * 1000)}


class TTSIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=600)


@app.post("/tts", dependencies=[Depends(auth)])
def tts(body: TTSIn):
    tok, model = get("tts")
    with torch.no_grad():
        wav = model(**tok(normalize(body.text), return_tensors="pt")).waveform[0].numpy()
    buf = io.BytesIO()
    sf.write(buf, wav, model.config.sampling_rate, format="WAV", subtype="PCM_16")
    return Response(content=buf.getvalue(), media_type="audio/wav", headers={"X-Model": TTS_MODEL})


@app.post("/diagnose", dependencies=[Depends(auth)])
async def diagnose(image: UploadFile = File(...), crop: str = Form("general")):
    data = await image.read()
    if len(data) > 8_000_000:
        raise HTTPException(status_code=413, detail="image too large")
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="not an image")
    crop = crop if crop in VISION_MODELS else "general"
    preds = get("vision:" + crop)(img, top_k=3)
    return {"crop": crop, "model": VISION_MODELS[crop],
            "predictions": [{"label": p["label"], "score": round(float(p["score"]), 3)} for p in preds]}


class MTIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    source: str = "en"
    target: str = "rw"


CODES = {"en": "eng_Latn", "rw": "kin_Latn", "fr": "fra_Latn", "sw": "swh_Latn"}


@app.post("/translate", dependencies=[Depends(auth)])
def translate(body: MTIn):
    if body.source not in CODES or body.target not in CODES:
        raise HTTPException(status_code=400, detail=f"languages: {sorted(CODES)}")
    tok, model = get("mt")
    tok.src_lang = CODES[body.source]
    enc = tok(body.text, return_tensors="pt", truncation=True, max_length=400).to(DEVICE)
    with torch.no_grad():
        out = model.generate(**enc, forced_bos_token_id=tok.convert_tokens_to_ids(CODES[body.target]),
                             max_new_tokens=400, num_beams=4)
    return {"translation": tok.batch_decode(out, skip_special_tokens=True)[0], "model": MT_MODEL}
