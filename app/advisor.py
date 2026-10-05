"""The advisory engine: language detection -> retrieval -> grounded answer -> guardrails.

Every answer is traceable to corpus entries (returned as `sources`). Questions the
corpus cannot answer are escalated to a human extension officer instead of being
guessed, and logged as knowledge gaps for MINAGRI / RAB.
"""
import re
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
           max_chars: int | None = None, log: bool = True) -> Advice:
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

    if (top < config.MIN_RETRIEVAL_SCORE or not corpus().is_in_domain(query)) and not wx:
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
            if wx:
                ctx.append(f"7-day forecast advice: {wx['text']}")
            words = 80 if channel in ("sms", "ussd") else 150
            prompt = f"REFERENCE:\n{ref}\n\n{' '.join(ctx)}\n\nQUESTION: {question}"
            try:
                out = llm.chat(
                    SYSTEM_PROMPT.format(lang_name="Kinyarwanda" if lang == "rw" else "English", words=words),
                    prompt,
                )
                if out and "INSUFFICIENT" not in out.upper() and numbers_grounded(out, prompt):
                    text, model = out, llm.model_name()
            except llm.LLMUnavailable:
                pass
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
                 weather=wx["forecast"] if wx else None)
    if log:
        first = hits[0].entry if hits and not escalated else {}
        db.log_interaction(channel=channel, phone=phone, lang=lang, district=district,
                           category=first.get("category"), crop=crop or first.get("crop"),
                           topic=first.get("topic"), query=question, answer=text, sources=sources,
                           confidence=adv.confidence, escalated=escalated, latency_ms=adv.latency_ms,
                           model=model)
    return adv
