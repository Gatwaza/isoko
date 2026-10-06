"""Isôko v0.2 API: voice, photo diagnosis, translation, batch and benchmark-run tooling, promoter tools,
refinement-window knowledge import, and the WhatsApp webhook."""
import base64
import json
import re
import threading
import time
from collections import defaultdict, deque
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from . import advisor, config, db, jobs, ml, weather
from .retrieval import corpus, reload as reload_corpus

router = APIRouter()
MAX_AUDIO = 5_000_000
MAX_IMAGE = 8_000_000
CROPS = ("beans", "cassava", "maize", "potato", "general")

# ---------- rate limiting (per key / per IP, sliding one-minute window) ----------

_hits: dict[str, deque] = defaultdict(deque)
_hits_lock = threading.Lock()


def _limit(bucket: str, per_min: int) -> None:
    now = time.time()
    with _hits_lock:
        q = _hits[bucket]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= per_min:
            raise HTTPException(status_code=429, detail="Rate limit exceeded; retry in a minute",
                                headers={"Retry-After": "60"})
        q.append(now)


def _key_from(x_api_key: str | None, authorization: str | None) -> str | None:
    return x_api_key or (authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None)


def api_key(x_api_key: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> str:
    key = _key_from(x_api_key, authorization)
    if not key or key not in config.API_KEYS:
        raise HTTPException(status_code=401, detail="Missing or invalid API key")
    _limit("key:" + key, config.RATE_LIMIT_KEY)
    return key


def admin_key(x_admin_key: str | None = Header(default=None)) -> str:
    if not config.ADMIN_KEYS or x_admin_key not in config.ADMIN_KEYS:
        raise HTTPException(status_code=401, detail="Admin key required")
    return x_admin_key


def demo_limit(request: Request) -> None:
    """Public demo endpoints (web phone, promoter portal): per-IP limit."""
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    _limit("ip:" + ip, config.RATE_LIMIT_DEMO)


def run_id_header(x_benchmark_run: str | None = Header(default=None)) -> str | None:
    if x_benchmark_run is None:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", x_benchmark_run):
        raise HTTPException(status_code=400, detail="X-Benchmark-Run must be 1-64 chars [A-Za-z0-9_.:-]")
    return x_benchmark_run


def _git_commit() -> str | None:
    import os
    import subprocess
    sha = os.getenv("VERCEL_GIT_COMMIT_SHA") or os.getenv("GIT_COMMIT")
    if sha:
        return sha[:12]
    try:
        return subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, timeout=3,
                              cwd=config.BASE_DIR).stdout.strip() or None
    except Exception:
        return None


_COMMIT = _git_commit()
_ml_cache: dict = {"t": 0.0, "v": None}


def ml_models() -> dict | None:
    """Model ids reported by the model service (cached 60 s); None when it is offline."""
    if not config.ML_SERVICE_URL:
        return None
    if time.time() - _ml_cache["t"] > 60:
        try:
            _ml_cache["v"] = httpx.get(f"{config.ML_SERVICE_URL.rstrip('/')}/health", timeout=3).json().get("models")
        except Exception:
            _ml_cache["v"] = None
        _ml_cache["t"] = time.time()
    return _ml_cache["v"]


def system_info() -> dict:
    import hashlib
    c = corpus()
    corpus_hash = hashlib.sha256(json.dumps(c.entries, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return {
        "version": config.VERSION,
        "commit": _COMMIT,
        "corpus": {"version": c.meta["version"], "entries": len(c.entries), "sha256": corpus_hash,
                   "refinement_entries": c.meta.get("extra_entries", 0)},
        "llm": "none" if config.LLM_PROVIDER == "none" else f"{config.LLM_PROVIDER}:{config.LLM_MODEL}",
        "kinyarwanda_generation": config.GENERATE_KINYARWANDA,
        "speech_and_vision": bool(config.ML_SERVICE_URL),
        "speech_and_vision_models": ml_models(),
    }


def channel_status() -> dict:
    """What is live and what is simulated, stated plainly."""
    ml = ml_models() is not None
    at = bool(config.AT_USERNAME and config.AT_API_KEY)
    wa = bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_ID and config.WHATSAPP_VERIFY_TOKEN)
    return {
        "api": {"status": "live"},
        "ussd": {"status": "live" if at else "simulated",
                 "detail": "Africa's Talking USSD gateway" if at else "web handset simulator; gateway callback POST /ussd ready"},
        "sms": {"status": ("live" if not config.AT_SANDBOX else "sandbox") if at else "simulated",
                "detail": "Africa's Talking SMS" if at else "messages written to the outbox shown in the simulator"},
        "voice": {"status": "live" if ml else "offline",
                  "detail": "Kinyarwanda ASR/TTS via web handset; telco IVR not yet provisioned" if ml else "model service offline"},
        "photo": {"status": "live" if ml else "offline", "detail": "web handset and promoter portal"},
        "whatsapp": {"status": "live" if wa else "not configured", "detail": "webhook POST /whatsapp/webhook ready"},
        "weather": {"status": "live", "detail": "7-day district forecasts (Open-Meteo; Meteo Rwanda planned)"},
    }


async def _read(upload: UploadFile, limit: int, kind: str) -> bytes:
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"empty {kind}")
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"{kind} too large")
    return data


def _ml_guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except ml.MLUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------- system, batch, benchmark runs ----------

@router.get("/v1/channels/status", tags=["benchmark"])
def v1_channels():
    return {"channels": channel_status(), "system": {"version": config.VERSION, "commit": _COMMIT}}


@router.get("/v1/system", tags=["benchmark"])
def v1_system():
    """Component versions, so baseline and final benchmark runs can be compared exactly."""
    return {**system_info(), "endpoints": {
        "advisory": "POST /v1/advisory/query, POST /v1/advisory/batch, POST /v1/chat/completions",
        "speech": "POST /v1/asr (audio -> Kinyarwanda text), POST /v1/tts (Kinyarwanda text -> WAV), POST /v1/voice/ask",
        "translation": "POST /v1/translate (en<->rw)",
        "vision": "POST /v1/diagnose (crop photo -> disease + advice)",
        "runs": "GET /v1/benchmark/runs/{run_id}",
    }, "auth": "X-API-Key or Authorization: Bearer; optional X-Benchmark-Run header tags and freezes a run"}


class BatchItem(BaseModel):
    id: str | None = Field(None, max_length=64)
    question: str = Field(..., min_length=1, max_length=2000)
    language: Literal["rw", "en", "auto"] = "auto"
    district: str | None = None
    crop: str | None = None


class Batch(BaseModel):
    items: list[BatchItem] = Field(..., min_length=1, max_length=50)


@router.post("/v1/advisory/batch", tags=["benchmark"])
def v1_batch(b: Batch, _: str = Depends(api_key), run_id: str | None = Depends(run_id_header)):
    out = []
    for it in b.items:
        adv = advisor.answer(it.question, lang=None if it.language == "auto" else it.language, district=it.district,
                             crop=it.crop, channel="api", run_id=run_id)
        out.append({"id": it.id, **adv.to_dict()})
    return {"run_id": run_id, "system": system_info(), "results": out}


class JobIn(BaseModel):
    items: list[BatchItem] = Field(..., min_length=1, max_length=5000)


@router.post("/v1/jobs", tags=["benchmark"], status_code=202)
def v1_job_create(j: JobIn, key: str = Depends(api_key), run_id: str | None = Depends(run_id_header)):
    """Asynchronous batch (up to 5,000 questions). Poll GET /v1/jobs/{job_id} for progress and results."""
    jid = jobs.create([it.model_dump() for it in j.items], key, run_id)
    return {"job_id": jid, "status": "queued", "total": len(j.items), "run_id": run_id, "poll": f"/v1/jobs/{jid}"}


@router.get("/v1/jobs/{job_id}", tags=["benchmark"])
def v1_job_get(job_id: str, offset: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=1000), key: str = Depends(api_key)):
    if not re.fullmatch(r"job_[0-9a-f]{16}", job_id):
        raise HTTPException(status_code=404, detail="job not found")
    job = jobs.get(job_id, key)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if config.INLINE_TASKS and job["status"] != "done":  # serverless: make progress on each poll
        jobs.process(job_id, budget_s=8)
        job = jobs.get(job_id, key)
    return {"job_id": job_id, "status": job["status"], "total": job["total"], "done": job["done"], "run_id": job["run_id"],
            "system": system_info(), "offset": offset, "results": jobs.results(job_id, offset, limit)}


@router.get("/v1/benchmark/runs/{run_id}", tags=["benchmark"])
def v1_run(run_id: str, _: str = Depends(api_key)):
    rid = run_id_header(run_id)
    rows = db.query(f"SELECT {db.time_expr()} AS time, lang, query, answer, sources, confidence, escalated, latency_ms, model "
                    "FROM interactions WHERE run_id = ? ORDER BY ts", (rid,))
    return {"run_id": rid, "count": len(rows), "results": rows}


# ---------- speech and translation (C4IR audio-script and EN-RW sentence benchmarks) ----------

@router.post("/v1/asr", tags=["speech"])
async def v1_asr(audio: UploadFile = File(...), _: str = Depends(api_key)):
    return _ml_guard(ml.asr, await _read(audio, MAX_AUDIO, "audio"), audio.filename or "audio")


class TTSIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=600)


@router.post("/v1/tts", tags=["speech"], response_class=Response)
def v1_tts(body: TTSIn, _: str = Depends(api_key)):
    return Response(content=_ml_guard(ml.tts, body.text), media_type="audio/wav")


class MTIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    source: Literal["en", "rw"] = "en"
    target: Literal["en", "rw"] = "rw"


@router.post("/v1/translate", tags=["speech"])
def v1_translate(body: MTIn, _: str = Depends(api_key)):
    if body.source == body.target:
        raise HTTPException(status_code=400, detail="source and target must differ")
    return _ml_guard(ml.translate, body.text, body.source, body.target)


def voice_answer(audio: bytes, filename: str, *, district: str | None, phone: str | None, channel: str,
                 run_id: str | None = None, speak: bool = True) -> dict:
    heard = _ml_guard(ml.asr, audio, filename)
    question = heard["text"]
    if not question:
        raise HTTPException(status_code=400, detail="no speech recognised")
    adv = advisor.answer(question, lang="rw", district=district, channel=channel, phone=phone, max_chars=459, run_id=run_id)
    out = {"transcript": question, **adv.to_dict(), "asr_model": heard.get("model")}
    if speak:
        try:
            out["audio_wav_base64"] = base64.b64encode(ml.tts(adv.answer)).decode()
        except ml.MLUnavailable:
            out["audio_wav_base64"] = None
    return out


@router.post("/v1/voice/ask", tags=["speech"])
async def v1_voice(audio: UploadFile = File(...), district: str | None = Form(None),
                   _: str = Depends(api_key), run_id: str | None = Depends(run_id_header)):
    """Spoken Kinyarwanda question -> transcript -> grounded advice -> spoken Kinyarwanda answer."""
    return voice_answer(await _read(audio, MAX_AUDIO, "audio"), audio.filename or "audio", district=district,
                        phone=None, channel="voice", run_id=run_id)


@router.post("/v1/diagnose", tags=["vision"])
async def v1_diagnose(image: UploadFile = File(...), crop: str = Form("general"), language: str = Form("rw"),
                      _: str = Depends(api_key)):
    return diagnose_and_log(await _read(image, MAX_IMAGE, "image"), crop, language, channel="api")


def diagnose_and_log(image: bytes, crop: str, lang: str, channel: str, district: str | None = None,
                     phone: str | None = None) -> dict:
    if crop not in CROPS:
        raise HTTPException(status_code=400, detail=f"crop must be one of {CROPS}")
    lang = lang if lang in ("rw", "en") else "rw"
    out = _ml_guard(ml.diagnose, image, crop if crop != "potato" and crop != "maize" else "general", lang)
    db.log_interaction(channel=channel, phone=phone, lang=lang, district=district, category="pest", crop=crop,
                       topic="photo-diagnosis", query=f"photo:{crop}", answer=f"{out['label']} ({out['confidence']:.2f})",
                       sources=[out["source"]] if out["source"] else [], confidence=out["confidence"],
                       escalated=out["escalated"], model=out["model"])
    return out


# ---------- public demo endpoints (web phone + promoter portal), rate-limited per IP ----------

@router.post("/api/demo/voice", include_in_schema=False, dependencies=[Depends(demo_limit)])
async def demo_voice(audio: UploadFile = File(...), phone: str | None = Form(None)):
    profile = db.get_profile(phone) if phone else {"district": None}
    return voice_answer(await _read(audio, MAX_AUDIO, "audio"), audio.filename or "audio",
                        district=profile.get("district"), phone=phone, channel="voice")


@router.post("/api/demo/diagnose", include_in_schema=False, dependencies=[Depends(demo_limit)])
async def demo_diagnose(image: UploadFile = File(...), crop: str = Form("general"), lang: str = Form("rw"),
                        phone: str | None = Form(None)):
    return diagnose_and_log(await _read(image, MAX_IMAGE, "image"), crop, lang, channel="photo", phone=phone)


class Visit(BaseModel):
    promoter: str | None = Field(None, max_length=32)
    farmer_code: str | None = Field(None, max_length=32)
    district: str | None = Field(None, max_length=40)
    crop: str | None = Field(None, max_length=40)
    issue: str | None = Field(None, max_length=80)
    diagnosis: str | None = Field(None, max_length=120)
    notes: str | None = Field(None, max_length=500)


@router.post("/api/promoter/visit", include_in_schema=False, dependencies=[Depends(demo_limit)])
def promoter_visit(v: Visit):
    district = weather.match_district(v.district) if v.district else None
    db.log_visit(promoter=v.promoter, farmer_code=v.farmer_code, district=district, crop=v.crop, issue=v.issue,
                 diagnosis=v.diagnosis, notes=v.notes)
    if v.issue and v.issue != "none":
        db.log_report(phone=v.promoter, district=district, issue=v.issue, detail=v.notes, channel="promoter")
    return {"status": "saved"}


class Ask(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    district: str | None = Field(None, max_length=40)


@router.post("/api/promoter/ask", include_in_schema=False, dependencies=[Depends(demo_limit)])
def promoter_ask(a: Ask):
    return advisor.answer(a.question, district=a.district, channel="promoter").to_dict()


# ---------- refinement window: import curated knowledge (admin) ----------

class KBItem(BaseModel):
    id: str = Field(..., pattern=r"^[a-z0-9-]{3,64}$")
    question: str = Field(..., min_length=3, max_length=500)
    answer_rw: str = Field(..., min_length=3, max_length=2000)
    answer_en: str = Field("", max_length=2000)
    crop: str = Field("general", max_length=30)
    topic: str = Field("general", max_length=30)
    source: str = Field("C4IR refinement data", max_length=200)


@router.post("/v1/admin/knowledge", tags=["refinement"])
def admin_import(items: list[KBItem], _: str = Depends(admin_key)):
    """Import validated Q&A pairs (e.g. C4IR's refinement data) as corpus entries; live within a minute."""
    if len(items) > 1000:
        raise HTTPException(status_code=413, detail="max 1000 items per call")
    for it in items:
        en = it.answer_en or it.answer_rw
        db.upsert_kb(it.id, {
            "id": it.id, "category": "refinement", "crop": it.crop, "topic": it.topic,
            "title_en": it.question, "title_rw": it.question, "keywords": it.question,
            "summary_en": en[:220], "summary_rw": it.answer_rw[:220], "detail_en": en, "detail_rw": it.answer_rw,
            "source": it.source}, it.source)
    c = reload_corpus()
    return {"imported": len(items), "corpus_entries": len(c.entries)}


@router.get("/v1/admin/knowledge", tags=["refinement"])
def admin_list(_: str = Depends(admin_key)):
    return {"entries": db.kb_extra()}


# ---------- WhatsApp Cloud API webhook (text, voice notes, photos) ----------

@router.get("/whatsapp/webhook", include_in_schema=False, response_class=PlainTextResponse)
def wa_verify(mode: str = Query(None, alias="hub.mode"), token: str = Query(None, alias="hub.verify_token"),
              challenge: str = Query("", alias="hub.challenge")):
    if config.WHATSAPP_VERIFY_TOKEN and mode == "subscribe" and token == config.WHATSAPP_VERIFY_TOKEN:
        return challenge
    raise HTTPException(status_code=403, detail="verification failed")


def _wa_media(media_id: str) -> bytes:
    h = {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}
    meta = httpx.get(f"https://graph.facebook.com/v20.0/{media_id}", headers=h, timeout=20).json()
    return httpx.get(meta["url"], headers=h, timeout=30).content


def _wa_send(to: str, text: str) -> None:
    if not (config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_ID):
        db.queue_sms(to, text, "whatsapp-outbox-only")
        return
    httpx.post(f"https://graph.facebook.com/v20.0/{config.WHATSAPP_PHONE_ID}/messages",
               headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"},
               json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:4000]}}, timeout=20)
    db.queue_sms(to, text, "whatsapp-sent")


@router.post("/whatsapp/webhook", include_in_schema=False)
async def wa_incoming(request: Request):
    if not config.WHATSAPP_VERIFY_TOKEN:
        raise HTTPException(status_code=404, detail="WhatsApp not configured")
    payload = await request.json()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                frm, kind = msg.get("from"), msg.get("type")
                try:
                    if kind == "text":
                        reply = advisor.answer(msg["text"]["body"][:1000], channel="whatsapp", phone=frm).answer
                    elif kind == "audio":
                        reply = voice_answer(_wa_media(msg["audio"]["id"]), "voice.ogg", district=None, phone=frm,
                                             channel="whatsapp", speak=False)["answer"]
                    elif kind == "image":
                        d = diagnose_and_log(_wa_media(msg["image"]["id"]), "general", "rw", channel="whatsapp", phone=frm)
                        reply = f"{d['name']} ({int(d['confidence'] * 100)}%). {d['advice']}"
                    else:
                        reply = "Ohereza ikibazo cyawe mu nyandiko, mu ijwi cyangwa ifoto y'igihingwa."
                except HTTPException as exc:
                    reply = "Serivisi ntiboneka ubu. Ongera ugerageze nyuma." if exc.status_code == 503 else str(exc.detail)
                _wa_send(frm, reply)
    return {"status": "ok"}
