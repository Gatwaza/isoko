"""The advisory engine: language detection -> retrieval -> grounded answer -> guardrails.

Every answer is traceable to corpus entries (returned as `sources`). Questions the
corpus cannot answer are escalated to a human extension officer instead of being
guessed, and logged as knowledge gaps for MINAGRI / RAB.
"""
import re
import threading
import time
from dataclasses import asdict, dataclass, field

from . import config, db, llm, weather
from .retrieval import corpus, tokenize

_RW_MARKERS = {
    "ese", "ndashaka", "nshaka", "gute", "iki", "ibihe", "nkore", "nte", "umuti", "ibigori",
    "ibishyimbo", "ibirayi", "umuceri", "imyumbati", "urutoki", "insina", "ikawa", "inka", "inkoko",
    "ingurube", "ihene", "indwara", "ifumbire", "imvura", "gutera", "gusarura", "umurima", "amata",
    "kandi", "cyane", "ryari", "bite", "mbese", "nabona", "naba", "yanjye", "zanjye", "byanjye",
    "rwanjye", "zirwaye", "irwaye", "zipfa", "amababi", "udukoko", "nkongwa", "kirabiranya",
}
_WEATHER = {"weather", "rain", "forecast", "drought", "imvura", "iteganyagihe", "izuba", "amapfa", "ikirere"}

# Intents the knowledge base does not cover yet (market prices, credit, machinery). Escalated with a
# specific message instead of returning a loosely related agronomy answer.
UNSUPPORTED = re.compile(r"\b(igiciro|ibiciro|price|prices|cost|costs|market|isoko ry|ku isoko|inguzanyo|loan|loans|"
                         r"credit|banki|bank|imashini|tractor|machine|machinery)\b", re.I)
UNSUPPORTED_MSG = {
    "en": "Market prices, credit and machinery are not covered yet. Your question has been passed to an "
          "extension officer; for prices ask your cooperative or sector agronomist.",
    "rw": "Amakuru y'ibiciro, inguzanyo n'imashini ntaraboneka muri serivisi. Ikibazo cyawe cyoherejwe ku mujyanama "
          "w'ubuhinzi; ku biciro baza koperative yawe cyangwa agronome w'umurenge.",
}

# A question that names only a crop or animal ("tell me about potatoes") gets an overview of that
# crop rather than whichever single entry happens to score highest.
CROP_WORDS = {
    "maize": {"ibigori", "maize", "corn"}, "beans": {"ibishyimbo", "bean"}, "potato": {"ibirayi", "potato", "irish"},
    "rice": {"umuceri", "rice"}, "cassava": {"imyumbati", "cassava"}, "banana": {"urutoki", "insina", "ibitoki", "banana"},
    "coffee": {"ikawa", "coffee"}, "cattle": {"inka", "cattle", "cow", "dairy"}, "poultry": {"inkoko", "chicken", "poultry"},
    "pig": {"ingurube", "pig"}, "goat": {"ihene", "goat"},
}
GENERAL_ASK = re.compile(r"\b(amakuru|mwambwira|mumbwire|nimumbwire|mbwira|ambwira|bijyanye|ibijyanye|byerekeye|"
                         r"ibyerekeye|kubyerekeye|tell me about|information|overview|in general|general advice)\b", re.I)
TOPIC_ORDER = ["planting", "fertiliser", "feeding", "pests", "disease", "harvest"]
OVERVIEW_HINT = {"rw": "Baza ku: gutera, ifumbire, indwara n'ibyonnyi, cyangwa gusarura.",
                 "en": "Ask about: planting, fertiliser, pests and diseases, or harvest."}


def crop_overview(question: str, lang: str) -> tuple[str, list[dict]] | None:
    toks = set(tokenize(question))
    toks |= {a + t for t in toks for a in "iua"}  # initial-vowel elision: "ku bigori" -> "ibigori"
    crops = [c for c, words in CROP_WORDS.items() if toks & words]
    if len(crops) != 1:
        return None
    rest = {t for t in set(tokenize(question)) if t not in CROP_WORDS[crops[0]] and not any(a + t in CROP_WORDS[crops[0]] for a in "iua")}
    asks_general = bool(GENERAL_ASK.search(question))
    if rest and not asks_general:
        return None  # e.g. a symptom description: let retrieval find the specific problem
    if any(t in corpus().anchors for t, w in corpus().expand(sorted(rest)) if w >= 0.8):
        return None  # the question names a specific topic too
    entries = sorted(corpus().find(crop=crops[0]),
                     key=lambda e: TOPIC_ORDER.index(e["topic"]) if e["topic"] in TOPIC_ORDER else 99)[:3]
    if not entries:
        return None
    first = lambda t: re.split(r"(?<=[.!?])\s", t)[0]
    text = " ".join(first(e[f"summary_{lang}"]) for e in entries) + " " + OVERVIEW_HINT[lang]
    return text, entries


ESCALATION = {
    "en": "I don't have a validated answer for this yet. Your question has been sent to an extension "
          "officer. For urgent help contact your sector agronomist, or the sector vet for animals.",
    "rw": "Nta gisubizo cyemejwe dufite kuri iki kibazo ubu. Ikibazo cyawe cyoherejwe ku mujyanama "
          "w'ubuhinzi. Ku bufasha bwihuse baza agronome w'umurenge, cyangwa veterineri ku matungo.",
}


_RW_FUNCTION = {"ni", "na", "ku", "mu", "kuri", "ya", "yo", "wa", "za", "iki", "ese", "nte", "gute", "nki",
                "kandi", "cyangwa", "ndashaka", "nshaka", "ryari", "he", "angahe", "zanjye", "yanjye"}


_EN_FUNCTION = {"the", "and", "of", "to", "is", "are", "with", "your", "for", "in", "on", "my", "how", "what",
                "when", "do", "it", "this", "be", "at", "from", "not", "should", "can", "have", "has", "per",
                "about", "which", "or", "if", "by", "an", "as", "use", "they", "their", "after", "before"}


# Distinctive Swahili words: Swahili shares Bantu prefixes with Kinyarwanda and would otherwise be
# mistaken for it (small open models often drift into Swahili when asked for Kinyarwanda).
_SW_MARKERS = {"kwa", "hii", "kuna", "lakini", "unahitaji", "ninaweza", "sana", "hivyo", "kuhusu",
               "mazao", "maji", "kufanya", "kutoka", "pia", "baada", "kabla", "wakati", "ambayo", "katika",
               "hiyo", "yako", "wako", "mimi", "ninahitaji", "inaweza", "kila", "ndiyo", "hapana", "tu",
               "ikiwa", "unachukua", "basi", "inamaanisha", "kiasi", "fulani", "kati", "hivi", "ili", "hadi",
               "sasa", "bila", "yake", "yao", "zao", "hizi", "huu", "huo", "wewe", "sisi", "kuweka", "kubwa",
               "nzuri", "msaada", "mkulima", "wakulima", "mbegu", "mbolea", "shamba", "mashamba", "mvua",
               "udongo", "mahindi", "maharagwe", "ombe", "ninakidhi", "kawaida", "unaweza", "hakuna", "mafuta",
               "muhimu", "zaidi", "unafanana", "kuhakikisha", "kuwa", "uzalishaji", "mboga", "hali", "mazingira",
               "kujaribu", "kubadilisha", "kipengele", "kwamba", "unapaswa", "kupanda", "mimea", "magonjwa"}


def identify_language(text: str) -> str:
    """'rw', 'en' or 'other' (e.g. Swahili). Used to score answers."""
    toks = re.findall(r"[a-z]+", text.lower().replace("'", " "))
    if not toks:
        return "other"
    sw = sum(1 for t in toks if t in _SW_MARKERS)
    if sw >= 2:  # genuine Kinyarwanda or English practically never contains two of these
        return "other"
    return detect_language(text)


def season_of(ts: float | None = None) -> str:
    """Rwanda's agricultural seasons: A Sept-Jan, B Feb-May/June, C June-Aug (marshlands, irrigation)."""
    m = time.localtime(ts).tm_mon
    return "A" if m in (9, 10, 11, 12, 1) else "B" if m in (2, 3, 4, 5) else "C"


def detect_language(text: str) -> str:
    toks = re.findall(r"[a-z]+", text.lower().replace("'", " "))
    if not toks:
        return "rw"
    rw = sum(1 for t in toks if t in _RW_MARKERS or t in _RW_FUNCTION or t.startswith(
        ("ibi", "imi", "ama", "uru", "aka", "utu", "ubu", "uku", "nda", "ntu")))
    en = sum(1 for t in toks if t in _EN_FUNCTION or t == "i")
    if rw == en:
        return "rw" if rw / len(toks) >= 0.4 else "en"
    return "rw" if rw > en else "en"


@dataclass
class Advice:
    answer: str
    language: str
    sources: list = field(default_factory=list)
    confidence: float = 0.0
    escalated: bool = False
    model: str = "none"
    latency_ms: int = 0
    weather: dict | None = None
    context: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


SYSTEM_PROMPT = """You are Isôko, an agricultural advisor for smallholder farmers in Rwanda.
Rules:
- Answer ONLY with information found in the REFERENCE passages. Do not add facts, products or doses that are not in them.
- If the passages do not answer the question, or are about a different crop or animal than the one asked about, reply exactly: INSUFFICIENT
- Give practical steps a farmer can act on today. Prefer quantities per are (100 m2).
- Only mention pesticides as "RAB-approved"; never name a product that is not in the passages.
- For sick animals or notifiable diseases always tell the farmer to call the sector veterinarian.
- Reply in plain {lang_name}, no markdown, at most {words} words."""


_GEN_SLOTS = threading.BoundedSemaphore(max(1, config.LLM_MAX_CONCURRENCY))

_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def numbers_grounded(output: str, *evidence: str) -> bool:
    """Reject generations containing any number (dose, spacing, interval) not present in the evidence."""
    allowed = set(_NUM.findall(" ".join(evidence)))
    return set(_NUM.findall(output)) <= allowed


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    stop = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[: stop + 1] if stop > limit * 0.5 else cut.rsplit(" ", 1)[0]) + "…"


def answer(question: str, *, lang: str | None = None, district: str | None = None,
           crop: str | None = None, channel: str = "api", phone: str | None = None,
           max_chars: int | None = None, log: bool = True, run_id: str | None = None) -> Advice:
    t0 = time.perf_counter()
    lang = lang if lang in ("en", "rw") else detect_language(question)
    district = weather.match_district(district) if district else None

    query = f"{question} {crop or ''}".strip()
    hits = corpus().search(query, k=3)
    top = hits[0].score if hits else 0.0
    confidence = round(min(1.0, top / (config.MIN_RETRIEVAL_SCORE * 4)), 2)

    wx = None
    if district and set(tokenize(question)) & _WEATHER:
        try:
            wx = weather.summary(district, lang)
        except Exception:  # weather is best-effort; never block advice on it
            wx = None

    sources = [{"id": h.entry["id"], "title": h.entry[f"title_{lang}"], "source": h.entry["source"],
                "score": round(h.score, 2)} for h in hits]
    escalated = False
    model = "retrieval"

    overview = None if wx else crop_overview(question, lang)
    if UNSUPPORTED.search(question) and not wx:
        text, escalated, sources = UNSUPPORTED_MSG[lang], True, []
    elif overview:
        text, model = overview[0], "overview"
        sources = [{"id": e["id"], "title": e[f"title_{lang}"], "source": e["source"], "score": None} for e in overview[1]]
        hits = [h for h in hits if h.entry["id"] in {e["id"] for e in overview[1]}] or hits
        confidence = 1.0
    elif (top < config.MIN_RETRIEVAL_SCORE or not corpus().is_in_domain(query)) and not wx:
        text, escalated, sources = ESCALATION[lang], True, []
    else:
        relevant = [h for h in hits if h.score >= max(config.MIN_RETRIEVAL_SCORE, top * 0.6)]
        text = None
        can_generate = config.LLM_PROVIDER != "none" and (lang == "en" or config.GENERATE_KINYARWANDA)
        if can_generate and relevant:
            ref = "\n\n".join(f"[{h.entry['id']}] {h.entry['title_en']}\n{h.entry['detail_en']}"
                              + (f"\n{h.entry['detail_rw']}" if lang == "rw" else "") for h in relevant)
            ctx = []
            if district:
                ctx.append(f"Farmer's district: {district}.")
            if crop:
                ctx.append(f"Farmer's crop: {crop}.")
            ctx.append(f"Current season: {season_of()}.")
            if wx:
                ctx.append(f"7-day forecast advice: {wx['text']}")
            words = 80 if channel in ("sms", "ussd") else 150
            prompt = f"REFERENCE:\n{ref}\n\n{' '.join(ctx)}\n\nQUESTION: {question}"
            # Back-pressure: benchmark runs wait for a slot (determinism); live traffic falls back to curated text.
            if _GEN_SLOTS.acquire(blocking=bool(run_id), timeout=config.LLM_TIMEOUT_S if run_id else None):
                try:
                    out = llm.chat(
                        SYSTEM_PROMPT.format(lang_name="Kinyarwanda" if lang == "rw" else "English", words=words),
                        prompt, temperature=0.0 if run_id else 0.1,
                    )
                    if out and "INSUFFICIENT" not in out.upper() and numbers_grounded(out, prompt):
                        text, model = out, llm.model_name()
                except llm.LLMUnavailable:
                    pass
                finally:
                    _GEN_SLOTS.release()
        if text is None:
            # Curated text, verbatim. Short answers for SMS/USSD, full detail for API.
            if relevant:
                e = relevant[0].entry
                text = e[f"summary_{lang}"] if channel in ("sms", "ussd") else e[f"detail_{lang}"]
            else:
                text = ""
        if wx:
            text = (wx["text"] + " " + text).strip()
        sources = [s for s in sources if s["score"] >= max(config.MIN_RETRIEVAL_SCORE, top * 0.6)]

    text = re.sub(r"\s+", " ", text).strip()
    if max_chars:
        text = _clip(text, max_chars)

    adv = Advice(answer=text, language=lang, sources=sources, confidence=0.0 if escalated else confidence,
                 escalated=escalated, model=model, latency_ms=int((time.perf_counter() - t0) * 1000),
                 weather=wx["forecast"] if wx else None,
                 context={"district": district, "crop": crop, "season": season_of(),
                          "personalised": bool(district or crop)})
    if log:
        first = hits[0].entry if hits and not escalated else {}
        db.log_interaction(channel=channel, phone=phone, lang=lang, district=district,
                           category=first.get("category"), crop=crop or first.get("crop"),
                           topic=first.get("topic"), query=question, answer=text, sources=sources,
                           confidence=adv.confidence, escalated=escalated, latency_ms=adv.latency_ms,
                           model=model, run_id=run_id)
    return adv
