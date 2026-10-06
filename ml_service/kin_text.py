"""Kinyarwanda text normalisation for speech synthesis.

MMS-TTS (and most Kinyarwanda TTS) only knows letters: digits, units and symbols are dropped, so
"cm 75" would be spoken as "cm". This verbalises numbers (counting forms), ranges, decimals and units.
Draft forms: to be reviewed by native speakers (see submission/Kinyarwanda_review_sheet.csv).
"""
import re

UNITS = {1: "rimwe", 2: "kabiri", 3: "gatatu", 4: "kane", 5: "gatanu", 6: "gatandatu", 7: "karindwi",
         8: "umunani", 9: "icyenda"}
TENS = {1: "icumi", 2: "makumyabiri", 3: "mirongo itatu", 4: "mirongo ine", 5: "mirongo itanu",
        6: "mirongo itandatu", 7: "mirongo irindwi", 8: "mirongo inani", 9: "mirongo icyenda"}
HUNDREDS = {1: "ijana", 2: "magana abiri", 3: "magana atatu", 4: "magana ane", 5: "magana atanu",
            6: "magana atandatu", 7: "magana arindwi", 8: "magana inani", 9: "magana cyenda"}
THOUSANDS = {1: "igihumbi", 2: "ibihumbi bibiri", 3: "ibihumbi bitatu", 4: "ibihumbi bine", 5: "ibihumbi bitanu",
             6: "ibihumbi bitandatu", 7: "ibihumbi birindwi", 8: "ibihumbi umunani", 9: "ibihumbi icyenda"}


def number(n: int) -> str:
    if n == 0:
        return "zeru"
    if n >= 10000:
        return " ".join(number(int(d)) for d in str(n))  # read long numbers digit by digit
    parts = []
    th, n = divmod(n, 1000)
    hu, n = divmod(n, 100)
    te, un = divmod(n, 10)
    if th:
        parts.append(THOUSANDS[th])
    if hu:
        parts.append(HUNDREDS[hu])
    if te:
        parts.append(TENS[te])
    if un:
        parts.append(UNITS[un])
    return " na ".join(parts)


def decimal(s: str) -> str:
    whole, frac = s.replace(",", ".").split(".")
    w = int(whole) if whole else 0
    if frac in ("5", "50"):
        return "igice" if w == 0 else f"{number(w)} n'igice"
    return f"{number(w)} akadomo {' '.join(number(int(d)) for d in frac)}"


UNIT_WORDS = [  # (pattern, words); applied before numbers are verbalised
    (r"\bkg/ha\b", "ibiro kuri hegitari"), (r"\bt/ha\b", "toni kuri hegitari"), (r"\bm2\b", "metero kare"),
    (r"\bcm\b", "santimetero"), (r"\bmm\b", "milimetero"), (r"\bkg\b", "ibiro"), (r"\bml\b", "mililitiro"),
    (r"/ha\b", " kuri hegitari"), (r"\bha\b", "hegitari"), (r"\bm\b", "metero"), (r"(?<=\d)C\b", " dogere"), (r"\bC\b", "dogere"), (r"%", " ku ijana"), (r"~", "hafi "),
    (r"≤", "kugeza kuri "), (r"\+", " na "), (r"\bDAP\b", "di ey pi"), (r"\bNPK\b", "en pi ke"),
    (r"\bRAB\b", "ra bu"), (r"\bNAEB\b", "na ebu"), (r"\bSMS\b", "es em es"),
]


def normalize(text: str) -> str:
    t = text
    for pat, rep in UNIT_WORDS:
        t = re.sub(pat, rep, t)
    t = re.sub(r"\b(\d+)-(\d+)-(\d+)\b", lambda m: ", ".join(number(int(g)) for g in m.groups()), t)  # NPK grades
    t = re.sub(r"(\d+)\.0\b", r"\1", t)
    t = re.sub(r"(\d+)\s*[x×]\s*(\d+)", lambda m: f"{number(int(m.group(1)))} kuri {number(int(m.group(2)))}", t)
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s*-\s*(\d+(?:[.,]\d+)?)",
               lambda m: f"{_num(m.group(1))} kugeza kuri {_num(m.group(2))}", t)
    t = re.sub(r"\d+[.,]\d+", lambda m: decimal(m.group(0)), t)
    t = re.sub(r"\d+", lambda m: number(int(m.group(0))), t)
    t = re.sub(r"[()/:;…*#]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _num(s: str) -> str:
    return decimal(s) if re.search(r"[.,]", s) else number(int(s))
