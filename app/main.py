"""Isôko - AI-enabled agricultural advisory for Rwanda (USSD / SMS / API)."""
import time
import uuid
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import advisor, config, db, llm, sms, ussd, weather
from .retrieval import corpus

app = FastAPI(
    title="Isôko Agricultural Advisory API",
    version="0.1.0",
    description="Kinyarwanda-first agricultural advisory for smallholder farmers over USSD, SMS and API. "
                "Grounded in a curated corpus; open-source models only; designed for in-country hosting.",
)
STATIC = config.BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _schedule(background: BackgroundTasks, task) -> None:
    if config.INLINE_TASKS:
        task()
    else:
        background.add_task(task)


# ---------- auth ----------

def require_api_key(x_api_key: str | None = Header(default=None),
                    authorization: str | None = Header(default=None)) -> str:
    key = x_api_key or (authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None)
    if not key or key not in config.API_KEYS:
        raise HTTPException(status_code=401, detail="Missing or invalid API key")
    return key


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


@app.get("/health")
def health():
    return {"status": "ok", "model": llm.model_name(), "corpus_entries": len(corpus().entries),
            "corpus_version": corpus().meta["version"], "demo_mode": config.DEMO_MODE}


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


@app.post("/v1/advisory/query")
def advisory_query(q: Query, _: str = Depends(require_api_key)):
    adv = advisor.answer(q.question, lang=None if q.language == "auto" else q.language, district=q.district,
                         crop=q.crop, channel=q.channel, max_chars=459 if q.channel != "api" else None)
    return {"id": f"adv_{uuid.uuid4().hex[:12]}", **adv.to_dict()}


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest, _: str = Depends(require_api_key)):
    """OpenAI-compatible wrapper so standard evaluation harnesses can call the full solution."""
    user_msgs = [m.content for m in req.messages if m.role == "user"]
    if not user_msgs:
        raise HTTPException(status_code=400, detail="At least one user message is required")
    adv = advisor.answer(user_msgs[-1])
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "isoko-0.1",
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


# ---------- MINAGRI / RAB feedback dashboard ----------

@app.get("/api/dashboard/stats", dependencies=[Depends(require_dashboard)])
def dashboard_stats(days: int = 30):
    since = time.time() - days * 86400
    q = db.query
    day, tm = db.day_expr(), db.time_expr()
    return {
        "totals": q("""SELECT COUNT(*) AS interactions, COUNT(DISTINCT user_hash) AS farmers,
                       SUM(escalated) AS escalated, ROUND(AVG(latency_ms)) AS avg_latency_ms
                       FROM interactions WHERE ts >= ?""", (since,))[0],
        "reports_total": q("SELECT COUNT(*) AS n FROM reports WHERE ts >= ?", (since,))[0]["n"],
        "by_channel": q("SELECT channel, COUNT(*) AS n FROM interactions WHERE ts >= ? GROUP BY channel ORDER BY n DESC", (since,)),
        "by_topic": q("""SELECT COALESCE(crop,'general') AS crop, COALESCE(topic,'other') AS topic, COUNT(*) AS n
                         FROM interactions WHERE ts >= ? AND escalated = 0 GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 12""", (since,)),
        "by_district": q("""SELECT district, COUNT(*) AS n FROM interactions WHERE ts >= ? AND district IS NOT NULL
                            GROUP BY district ORDER BY n DESC""", (since,)),
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
