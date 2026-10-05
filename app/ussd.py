"""USSD menu (Africa's Talking callback format), Kinyarwanda first.

USSD is stateless from our side: the gateway sends the full input path as
`text` ("1*2*3"). We rebuild the screen from that path, so the flow survives
restarts and scales horizontally. Conventions: "0" = back, "00" = home, "98" = more.
Screens are kept under 182 characters; full answers follow by SMS.
"""
from dataclasses import dataclass, field
from typing import Callable

from . import advisor, db, sms, weather
from .retrieval import corpus

USSD_LIMIT = 182

T = {
    "rw": {
        "home": "Isoko ry'Umuhinzi\n1.Ibihingwa\n2.Indwara n'ibyonnyi\n3.Iteganyagihe\n4.Amatungo\n5.Baza ikibazo\n6.Tanga raporo\n7.Umwirondoro\n8.English",
        "choose_crop": "Hitamo igihingwa:",
        "choose_topic": "{crop}: hitamo:",
        "choose_problem": "Hitamo ikibazo:",
        "choose_animal": "Hitamo itungo:",
        "choose_issue": "Raporo: ikibazo ki?",
        "ask_district": "Andika izina ry'akarere kawe (urugero: Nyagatare):",
        "bad_district": "Akarere ntikabonetse. Ongera wandike (urugero: Huye):",
        "ask_question": "Andika ikibazo cyawe:",
        "question_received": "Twakiriye ikibazo cyawe. Igisubizo kirakugeraho kuri SMS mu kanya gato. Murakoze!",
        "sms_follows": "\n(Ibisobanuro birambuye kuri SMS)",
        "report_thanks": "Murakoze! Raporo yanyu ({issue}, {district}) yageze ku bajyanama b'ubuhinzi.",
        "profile_saved": "Umwirondoro wabitswe: {district}, {crop}. Murakoze!",
        "more": "98.Ibindi",
        "back": "0.Subira inyuma",
        "invalid": "Ihitamo ritemewe. Ongera ugerageze.",
        "wx_error": "Iteganyagihe ntiriboneka ubu. Ongera ugerageze nyuma.",
        "lang_switched": "Ururimi: Ikinyarwanda",
        "no_answer": "Nta nama ihari kuri iki ubu. Baza agronome w'umurenge.",
    },
    "en": {
        "home": "Isoko Farm Advisor\n1.Crops\n2.Pests & diseases\n3.Weather\n4.Livestock\n5.Ask a question\n6.Send a report\n7.My profile\n8.Kinyarwanda",
        "choose_crop": "Choose a crop:",
        "choose_topic": "{crop}: choose:",
        "choose_problem": "Choose a problem:",
        "choose_animal": "Choose an animal:",
        "choose_issue": "Report: what is the issue?",
        "ask_district": "Type your district name (e.g. Nyagatare):",
        "bad_district": "District not found. Type it again (e.g. Huye):",
        "ask_question": "Type your question:",
        "question_received": "We received your question. The answer will reach you by SMS shortly. Thank you!",
        "sms_follows": "\n(Full details by SMS)",
        "report_thanks": "Thank you! Your report ({issue}, {district}) has reached extension officers.",
        "profile_saved": "Profile saved: {district}, {crop}. Thank you!",
        "more": "98.More",
        "back": "0.Back",
        "invalid": "Invalid choice. Please try again.",
        "wx_error": "Weather is unavailable right now. Please try later.",
        "lang_switched": "Language: English",
        "no_answer": "No advice available on this yet. Ask your sector agronomist.",
    },
}

CROPS = [("maize", "Ibigori", "Maize"), ("beans", "Ibishyimbo", "Beans"), ("potato", "Ibirayi", "Irish potato"),
         ("rice", "Umuceri", "Rice"), ("cassava", "Imyumbati", "Cassava"), ("banana", "Urutoki", "Banana"),
         ("coffee", "Ikawa", "Coffee")]
TOPICS = [("planting", "Gutera", "Planting"), ("fertiliser", "Ifumbire", "Fertiliser"),
          ("pests", "Indwara n'ibyonnyi", "Pests & disease"), ("harvest", "Gusarura no guhunika", "Harvest & storage")]
ANIMALS = [("cattle", "Inka", "Cattle"), ("poultry", "Inkoko", "Chickens"), ("pig", "Ingurube", "Pigs"),
           ("goat", "Ihene", "Goats")]
PROBLEMS = [  # entry id, rw label, en label
    ("maize-faw", "Nkongwa (ibigori)", "Armyworm (maize)"),
    ("banana-bxw", "Kirabiranya (urutoki)", "Banana wilt (BXW)"),
    ("potato-lateblight", "Mildiyu (ibirayi)", "Late blight (potato)"),
    ("potato-bacterialwilt", "Kuma (ibirayi)", "Bacterial wilt (potato)"),
    ("cassava-diseases", "Ububembe (imyumbati)", "Mosaic/CBSD (cassava)"),
    ("beans-rootrot", "Kubora imizi (ibishyimbo)", "Root rot (beans)"),
    ("rice-blast", "Bulasite (umuceri)", "Blast (rice)"),
    ("coffee-pests", "Antestiya (ikawa)", "Antestia (coffee)"),
    ("pesticide-safety", "Gukoresha imiti neza", "Safe pesticide use"),
]
ISSUES = [("crop_pest", "Ibyonnyi/indwara z'ibihingwa", "Crop pest/disease"),
          ("animal_disease", "Indwara z'amatungo", "Animal disease"),
          ("drought", "Izuba/amapfa", "Drought/dry spell"),
          ("flood", "Imvura nyinshi/imyuzure", "Heavy rain/flood"),
          ("inputs", "Kubura inyongeramusaruro", "Inputs not available"),
          ("other", "Ibindi", "Other")]


@dataclass
class Reply:
    text: str
    end: bool
    tasks: list[Callable[[], None]] = field(default_factory=list)

    def render(self) -> str:
        return ("END " if self.end else "CON ") + self.text


def normalize(text: str) -> list[str]:
    path: list[str] = []
    for tok in (text or "").split("*") if text else []:
        tok = tok.strip()
        if tok == "00":
            path = []
        elif tok == "0":
            if path:
                path.pop()
            while path and path[-1] == "98":  # "back" from a paged list returns to its first page
                path.pop()
        else:
            path.append(tok)
    return path


def _label(item: tuple, lang: str) -> str:
    return item[1] if lang == "rw" else item[2]


def _select(path: list[str], items: list, title: str, lang: str, label=_label):
    """Paged numbered list. Returns (Reply, None, []) to show a screen, or (None, item, rest)."""
    page = 0
    while path and path[0] == "98":
        page += 1
        path = path[1:]
    pages, cur, size = [], [], len(title) + len(T[lang]["more"]) + len(T[lang]["back"]) + 4
    for idx, it in enumerate(items):
        line = f"{idx + 1}.{label(it, lang)}"
        if cur and size + len(line) + 1 > USSD_LIMIT:
            pages.append(cur)
            cur, size = [], len(title) + len(T[lang]["more"]) + len(T[lang]["back"]) + 4
        cur.append(line)
        size += len(line) + 1
    pages.append(cur)
    if not path:
        page = min(page, len(pages) - 1)
        lines = [title, *pages[page]]
        if page < len(pages) - 1:
            lines.append(T[lang]["more"])
        lines.append(T[lang]["back"])
        return Reply("\n".join(lines), end=False), None, []
    choice = path[0]
    if choice.isdigit() and 1 <= int(choice) <= len(items):
        return None, items[int(choice) - 1], path[1:]
    return Reply(T[lang]["invalid"] + "\n" + T[lang]["back"], end=False), None, []


def _entry_reply(entry: dict, lang: str, phone: str, channel_meta: dict) -> Reply:
    s = T[lang]["sms_follows"]
    body = advisor._clip(entry[f"summary_{lang}"], USSD_LIMIT - len(s))
    detail = advisor._clip(f"{entry[f'title_{lang}']}: {entry[f'detail_{lang}']}", 459)
    db.log_interaction(channel="ussd", phone=phone, lang=lang, district=channel_meta.get("district"),
                       category=entry["category"], crop=entry["crop"], topic=entry["topic"],
                       query=f"menu:{entry['id']}", answer=body, sources=[{"id": entry["id"]}],
                       confidence=1.0, model="curated")
    return Reply(body + s, end=True, tasks=[lambda: sms.send(phone, detail)])


def _entries_menu(path, entries, title, lang, phone, profile) -> Reply:
    if not entries:
        return Reply(T[lang]["no_answer"], end=True)
    if len(entries) == 1:
        return _entry_reply(entries[0], lang, phone, profile)
    def short(title: str) -> str:
        s = title.split(": ", 1)[-1]
        return s[:1].upper() + s[1:]
    items = [(e["id"], short(e["title_rw"]), short(e["title_en"])) for e in entries]
    r, item, _ = _select(path, items, title, lang)
    return r or _entry_reply(corpus().by_id[item[0]], lang, phone, profile)


def _answer_question_by_sms(phone: str, question: str, lang: str, district: str | None, crop: str | None):
    def task():
        adv = advisor.answer(question, lang=lang, district=district, crop=crop, channel="sms",
                             phone=phone, max_chars=459)
        sms.send(phone, adv.answer)
    return task


def handle(session_id: str, phone: str, text: str) -> Reply:
    profile = db.get_profile(phone)
    lang = profile["lang"]
    t = T[lang]
    path = normalize(text)
    if not path:
        return Reply(t["home"], end=False)
    head, rest = path[0], path[1:]

    if head == "1":  # crops -> topic -> entry
        r, crop, rest = _select(rest, CROPS, t["choose_crop"], lang)
        if r:
            return r
        topics = [tp for tp in TOPICS if corpus().find(crop=crop[0], topic=tp[0])]
        r, topic, rest = _select(rest, topics, t["choose_topic"].format(crop=_label(crop, lang)), lang)
        if r:
            return r
        return _entries_menu(rest, corpus().find(crop=crop[0], topic=topic[0]), t["choose_problem"], lang, phone, profile)

    if head == "2":  # common pests & diseases
        r, item, _ = _select(rest, PROBLEMS, t["choose_problem"], lang)
        return r or _entry_reply(corpus().by_id[item[0]], lang, phone, profile)

    if head == "3":  # weather for the farmer's district
        district = profile["district"]
        if not district:
            if not rest:
                return Reply(t["ask_district"], end=False)
            district = weather.match_district(rest[0])
            if not district:
                return Reply(t["bad_district"], end=False) if len(rest) == 1 else Reply(t["invalid"], end=True)
            db.update_profile(phone, district=district)
        try:
            wx = weather.summary(district, lang)
        except Exception:
            return Reply(t["wx_error"], end=True)
        db.log_interaction(channel="ussd", phone=phone, lang=lang, district=district, category="climate",
                           topic="weather", query="menu:weather", answer=wx["text"], confidence=1.0,
                           model="rules+open-meteo")
        if wx["alerts"]:
            db.log_report(phone=None, district=district, issue="forecast:" + ",".join(wx["alerts"]),
                          detail=wx["text"], channel="system")
        return Reply(advisor._clip(wx["text"], USSD_LIMIT - len(t["sms_follows"])) + t["sms_follows"], end=True,
                     tasks=[lambda: sms.send(phone, advisor._clip(wx["text"], 459))])

    if head == "4":  # livestock -> animal -> entry
        r, animal, rest = _select(rest, ANIMALS, t["choose_animal"], lang)
        if r:
            return r
        return _entries_menu(rest, corpus().find(crop=animal[0]), t["choose_problem"], lang, phone, profile)

    if head == "5":  # free-text question, answered asynchronously by SMS
        if not rest:
            return Reply(t["ask_question"], end=False)
        question = "*".join(rest)  # a farmer may type '*' inside the question
        return Reply(t["question_received"], end=True,
                     tasks=[_answer_question_by_sms(phone, question, lang, profile["district"], profile["main_crop"])])

    if head == "6":  # field report from farmers / farmer promoters -> MINAGRI dashboard
        r, issue, rest = _select(rest, ISSUES, t["choose_issue"], lang)
        if r:
            return r
        district = profile["district"]
        if not district:
            if not rest:
                return Reply(t["ask_district"], end=False)
            district = weather.match_district(rest[0])
            if not district:
                return Reply(t["bad_district"], end=False)
        db.log_report(phone=phone, district=district, issue=issue[0], detail=None, channel="ussd")
        return Reply(t["report_thanks"].format(issue=_label(issue, lang), district=district), end=True)

    if head == "7":  # profile: district + main crop, used to personalise advice
        if not rest:
            return Reply(t["ask_district"], end=False)
        district = weather.match_district(rest[0])
        if not district:
            return Reply(t["bad_district"], end=False)
        r, crop, _ = _select(rest[1:], CROPS + ANIMALS, t["choose_crop"], lang)
        if r:
            return r
        db.update_profile(phone, district=district, main_crop=crop[0])
        return Reply(t["profile_saved"].format(district=district, crop=_label(crop, lang)), end=True)

    if head == "8":  # toggle language and show home again
        if rest or text.strip() != "8":  # toggled earlier this session (incl. "back" to here); don't re-toggle  # already toggled when "8" was first sent this session; continue from home
            return handle(session_id, phone, "*".join(rest))
        new = "en" if lang == "rw" else "rw"
        db.update_profile(phone, lang=new)
        return Reply(T[new]["home"], end=False)

    return Reply(t["invalid"] + "\n" + t["home"], end=False)
