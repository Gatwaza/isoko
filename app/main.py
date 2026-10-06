"""Isôko - AI-enabled agricultural advisory for Rwanda (USSD / SMS / API)."""
import json
import time
import uuid
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import advisor, config, db, llm, sms, ussd, weather
from .api_v2 import api_key, router as v2_router, run_id_header, system_info
from .retrieval import corpus

app = FastAPI(
    title="Isôko Agricultural Advisory API",
    version=config.VERSION,
    description="Kinyarwanda-first agricultural advisory for smallholder farmers over USSD, SMS and API. "
                "Grounded in a curated corpus; open-source models only; designed for in-country hosting.",
)
STATIC = config.BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(v2_router)


_last_purge = {"t": 0.0}


def _maybe_purge() -> None:
    """Retention policy, applied at most hourly (works on serverless and dedicated hosts)."""
    if time.time() - _last_purge["t"] > 3600:
        _last_purge["t"] = time.time()
        try:
            db.purge_old(config.RETENTION_DAYS)
        except Exception as exc:
            print("retention purge failed:", exc, flush=True)


@app.on_event("startup")
def _startup():
    _maybe_purge()


def _suppress(rows: list[dict], label_keys: tuple[str, ...]) -> list[dict]:
    """Dashboard privacy: groups smaller than MIN_GROUP_SIZE are merged into one 'other' row."""
    k = config.MIN_GROUP_SIZE
    big = [r for r in rows if r["n"] >= k]
    small = sum(r["n"] for r in rows if r["n"] < k)
    if small:
        big.append({**{key: f"other (<{k} each)" for key in label_keys}, "n": small})
    return big


@app.middleware("http")
async def version_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Isoko-Version"] = config.VERSION
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _schedule(background: BackgroundTasks, task) -> None:
    if config.INLINE_TASKS:
        task()
    else:
        background.add_task(task)


# ---------- auth ----------

require_api_key = api_key  # rate-limited key check (see api_v2)


def require_dashboard(token: str | None = None, x_dashboard_token: str | None = Header(default=None)) -> None:
    if config.DASHBOARD_TOKEN and config.DASHBOARD_TOKEN not in (token, x_dashboard_token):
        raise HTTPException(status_code=401, detail="Dashboard token required")


# ---------- pages ----------

@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/simulator")


@app.get("/simulator", include_in_schema=False)
def simulator():
    return FileResponse(STATIC / "simulator.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC / "dashboard.html")


@app.get("/promoter", include_in_schema=False)
def promoter_page():
    return FileResponse(STATIC / "promoter.html")


@app.get("/compare", include_in_schema=False)
def compare_page():
    return FileResponse(STATIC / "compare.html")


@app.get("/evaluation", include_in_schema=False)
def evaluation_page():
    return FileResponse(STATIC / "evaluation.html")


@app.get("/health")
def health():
    return {"status": "ok", "model": llm.model_name(), "corpus_entries": len(corpus().entries),
            "corpus_version": corpus().meta["version"], "demo_mode": config.DEMO_MODE, "system": system_info()}


# ---------- USSD (Africa's Talking callback) ----------

@app.post("/ussd", response_class=PlainTextResponse)
def ussd_callback(background: BackgroundTasks, sessionId: str = Form(...), phoneNumber: str = Form(...),
                  text: str = Form(""), serviceCode: str = Form(""), networkCode: str = Form("")):
    reply = ussd.handle(sessionId, phoneNumber, text)
    for task in reply.tasks:
        _schedule(background, task)
    return reply.render()


# ---------- SMS (two-way: farmers text a question, get an answer) ----------

@app.post("/sms/inbound", response_class=PlainTextResponse)
def sms_inbound(background: BackgroundTasks, from_: str = Form(..., alias="from"), text: str = Form(...)):
    profile = db.get_profile(from_)

    def task():
        adv = advisor.answer(text, district=profile["district"], crop=profile["main_crop"], channel="sms",
                             phone=from_, max_chars=459)
        sms.send(from_, adv.answer)

    _schedule(background, task)
    return "OK"


# ---------- Partner / benchmark API ----------

class Query(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, examples=["Ibigori byanjye bifite nkongwa, nkore iki?"])
    language: Literal["rw", "en", "auto"] = "auto"
    district: str | None = Field(None, examples=["Nyagatare"])
    crop: str | None = Field(None, examples=["maize"])
    channel: Literal["api", "sms", "ussd"] = "api"


@app.post("/v1/advisory/query", tags=["benchmark"])
def advisory_query(q: Query, _: str = Depends(require_api_key), run_id: str | None = Depends(run_id_header)):
    adv = advisor.answer(q.question, lang=None if q.language == "auto" else q.language, district=q.district,
                         crop=q.crop, channel=q.channel, max_chars=459 if q.channel != "api" else None, run_id=run_id)
    return {"id": f"adv_{uuid.uuid4().hex[:12]}", "run_id": run_id, **adv.to_dict(), "system": system_info()}


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]


@app.post("/v1/chat/completions", tags=["benchmark"])
def chat_completions(req: ChatRequest, _: str = Depends(require_api_key), run_id: str | None = Depends(run_id_header)):
    """OpenAI-compatible wrapper so standard evaluation harnesses can call the full solution."""
    user_msgs = [m.content for m in req.messages if m.role == "user"]
    if not user_msgs:
        raise HTTPException(status_code=400, detail="At least one user message is required")
    if len(user_msgs[-1]) > 2000:
        raise HTTPException(status_code=413, detail="message too long (max 2000 characters)")
    adv = advisor.answer(user_msgs[-1], run_id=run_id)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": f"isoko-{config.VERSION}",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": adv.answer}}],
        "isoko": {k: v for k, v in adv.to_dict().items() if k != "answer"},
    }


@app.get("/v1/weather/{district}")
def weather_advice(district: str, lang: Literal["rw", "en"] = "rw", _: str = Depends(require_api_key)):
    name = weather.match_district(district)
    if not name:
        raise HTTPException(status_code=404, detail=f"Unknown district. Known: {', '.join(weather.DISTRICTS)}")
    return weather.summary(name, lang)


class Report(BaseModel):
    district: str
    issue: str = Field(..., examples=["crop_pest"])
    detail: str | None = None


@app.post("/v1/reports")
def submit_report(r: Report, _: str = Depends(require_api_key)):
    """For extension officers / farmer promoters to escalate field issues."""
    db.log_report(phone=None, district=weather.match_district(r.district) or r.district, issue=r.issue,
                  detail=r.detail, channel="api")
    return {"status": "received"}


@app.get("/v1/corpus")
def corpus_index():
    """Transparency: everything the advisor can say is listed here with its source."""
    c = corpus()
    return {"meta": c.meta, "entries": [{k: e[k] for k in ("id", "category", "crop", "topic", "title_en", "title_rw", "source")}
                                        for e in c.entries]}


# ---------- Live demo: generic model vs Isôko, and evaluation results ----------

EVAL_DIR = config.BASE_DIR.parent / "eval" / "results"
PLAIN_SYSTEM = ("You are an agricultural extension advisor for smallholder farmers in Rwanda. Answer the farmer's "
                "question with practical, specific advice. If the question is not about farming, say you can only "
                "help with farming. Reply in the same language as the question, plain text, at most 120 words.")


class CompareQuery(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)


@app.post("/api/compare")
def compare(q: CompareQuery):
    """Side-by-side for demos: the same open model with and without Isôko's grounding and guardrails."""
    if not config.DEMO_MODE or config.LLM_PROVIDER == "none":
        raise HTTPException(status_code=503, detail="Live comparison needs DEMO_MODE and a local model (Ollama).")
    t0 = time.perf_counter()
    try:
        plain = llm.chat(PLAIN_SYSTEM, q.question, max_tokens=300)
    except llm.LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Model unavailable: {exc}")
    plain_ms = int((time.perf_counter() - t0) * 1000)
    adv = advisor.answer(q.question, channel="api", log=False)
    return {"model": config.LLM_MODEL,
            "plain": {"answer": plain, "latency_ms": plain_ms},
            "isoko": adv.to_dict()}


@app.get("/api/eval")
def eval_results():
    def load(*parts):
        f = EVAL_DIR.joinpath(*parts)
        return json.loads(f.read_text()) if f.exists() else None

    def mt(raw):
        return {m: {d: v["chrf"] for d, v in r.items()} for m, r in (raw or {}).items()}
    sm = load("speech_mt_results.json") or {}
    nllb = sm.get("mt:facebook/nllb-200-distilled-600M")
    mt_all = {**mt(load("v0.1", "mt_results.json")), **({"nllb-200-600M": {d: nllb[d]["chrf"] for d in ("en2rw", "rw2en")}} if nllb else {})}
    asr = {k: {m: v[m] for m in ("wer", "cer", "median_latency_s_cpu", "n")} for k, v in (load("asr_results.json") or {}).items()}
    tts = {k.split(":", 2)[-1]: v["round_trip_cer"] for k, v in sm.items() if k.startswith("tts:") and k.count(":") >= 2}
    vision = {k: {m: v[m] for m in ("accuracy", "accuracy_when_confident", "share_confident", "n")} for k, v in (load("vision_results.json") or {}).items()}
    threat = (load("threat_report.json") or {}).get("summary")
    return {"qa": load("qa_summary.json"), "qa_baseline": load("v0.1", "qa_summary.json"), "mt": mt_all,
            "asr": asr, "tts": tts, "vision": vision, "threat": threat,
            "testset": {"qa_items": 70, "mt_pairs": 60, "asr_clips": 80}}


# ---------- MINAGRI / RAB feedback dashboard ----------

@app.get("/api/dashboard/stats", dependencies=[Depends(require_dashboard)])
def dashboard_stats(days: int = 30):
    _maybe_purge()
    since = time.time() - days * 86400
    q = db.query
    day, tm = db.day_expr(), db.time_expr()
    return {
        "totals": q("""SELECT COUNT(*) AS interactions, COUNT(DISTINCT user_hash) AS farmers,
                       SUM(escalated) AS escalated, ROUND(AVG(latency_ms)) AS avg_latency_ms
                       FROM interactions WHERE ts >= ?""", (since,))[0],
        "reports_total": q("SELECT COUNT(*) AS n FROM reports WHERE ts >= ?", (since,))[0]["n"],
        "visits_total": q("SELECT COUNT(*) AS n FROM farm_visits WHERE ts >= ?", (since,))[0]["n"],
        "photos_total": q("SELECT COUNT(*) AS n FROM interactions WHERE ts >= ? AND topic = 'photo-diagnosis'", (since,))[0]["n"],
        "voice_total": q("SELECT COUNT(*) AS n FROM interactions WHERE ts >= ? AND channel = 'voice'", (since,))[0]["n"],
        "by_channel": q("SELECT channel, COUNT(*) AS n FROM interactions WHERE ts >= ? GROUP BY channel ORDER BY n DESC", (since,)),
        "by_topic": _suppress(q("""SELECT COALESCE(crop,'general') AS crop, COALESCE(topic,'other') AS topic, COUNT(*) AS n
                         FROM interactions WHERE ts >= ? AND escalated = 0 GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 12""", (since,)), ("crop", "topic")),
        "by_district": _suppress(q("""SELECT district, COUNT(*) AS n FROM interactions WHERE ts >= ? AND district IS NOT NULL
                            GROUP BY district ORDER BY n DESC""", (since,)), ("district",)),
        "by_language": q("SELECT lang, COUNT(*) AS n FROM interactions WHERE ts >= ? GROUP BY lang", (since,)),
        "daily": q(f"""SELECT {day} AS day, COUNT(*) AS n, SUM(escalated) AS escalated
                       FROM interactions WHERE ts >= ? GROUP BY 1 ORDER BY 1""", (since,)),
        "reports": q(f"""SELECT {tm} AS time, district, issue, detail, channel
                        FROM reports WHERE ts >= ? ORDER BY ts DESC LIMIT 25""", (since,)),
        "knowledge_gaps": q(f"""SELECT {tm} AS time, lang, district, query
                               FROM interactions WHERE ts >= ? AND escalated = 1 ORDER BY ts DESC LIMIT 25""", (since,)),
        "recent": q(f"""SELECT {tm} AS time, channel, lang, district, query, answer, model
                       FROM interactions WHERE ts >= ? AND query NOT LIKE 'menu:%' ORDER BY ts DESC LIMIT 15""", (since,)),
    }


@app.get("/api/dashboard/export.csv", dependencies=[Depends(require_dashboard)], include_in_schema=False)
def dashboard_export(days: int = 90):
    """Aggregate counts for MINAGRI/RAB (day x district x crop x topic), small groups suppressed, no raw text."""
    import csv
    import io
    since = time.time() - days * 86400
    rows = db.query(f"""SELECT {db.day_expr()} AS day, COALESCE(district,'unknown') AS district, COALESCE(crop,'general') AS crop,
                        COALESCE(topic,'other') AS topic, channel, lang, COUNT(*) AS n, SUM(escalated) AS escalated
                        FROM interactions WHERE ts >= ? AND run_id IS NULL GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY 1, 2""", (since,))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["day", "district", "crop", "topic", "channel", "language", "interactions", "escalated"])
    for r in rows:
        if r["n"] >= config.MIN_GROUP_SIZE:
            w.writerow([r["day"], r["district"], r["crop"], r["topic"], r["channel"], r["lang"], r["n"], r["escalated"]])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=isoko_needs.csv"})


@app.get("/api/sms/outbox", dependencies=[Depends(require_dashboard)])
def sms_outbox(phone: str | None = None, after_id: int = 0):
    """Used by the USSD simulator to show the SMS a farmer would receive."""
    tm = db.time_expr()
    if phone:
        return db.query(f"SELECT id, {tm} AS time, phone, message, status FROM sms_outbox "
                        "WHERE phone = ? AND id > ? ORDER BY id", (phone, after_id))
    return db.query(f"SELECT id, {tm} AS time, phone, message, status FROM sms_outbox "
                    "WHERE id > ? ORDER BY id DESC LIMIT 50", (after_id,))


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):  # never show a stack trace on a farmer's phone
    if request.url.path == "/ussd":
        return PlainTextResponse("END Habaye ikibazo. Ongera ugerageze nyuma. / Something went wrong, please retry.")
    raise exc
