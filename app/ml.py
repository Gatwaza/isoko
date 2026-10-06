"""Client for the Isôko model service (speech, photo diagnosis, translation) + diagnosis-to-advice mapping."""
import httpx

from . import config
from .retrieval import corpus


class MLUnavailable(Exception):
    pass


def _post(path: str, **kw) -> httpx.Response:
    if not config.ML_SERVICE_URL:
        raise MLUnavailable("model service not configured (ML_SERVICE_URL)")
    try:
        r = httpx.post(f"{config.ML_SERVICE_URL.rstrip('/')}{path}", headers={"X-ML-Token": config.ML_TOKEN},
                       timeout=config.ML_TIMEOUT_S, **kw)
    except httpx.HTTPError as exc:
        raise MLUnavailable(f"model service unreachable: {exc}") from exc
    if r.status_code >= 500 or r.status_code == 401:
        raise MLUnavailable(f"model service error {r.status_code}")
    return r


def asr(audio: bytes, filename: str = "audio.wav") -> dict:
    r = _post("/asr", files={"audio": (filename, audio)})
    if r.status_code != 200:
        raise ValueError(r.json().get("detail", "audio rejected"))
    return r.json()


def tts(text: str) -> bytes:
    r = _post("/tts", json={"text": text[:600]})
    r.raise_for_status()
    return r.content


def translate(text: str, source: str, target: str) -> dict:
    r = _post("/translate", json={"text": text, "source": source, "target": target})
    if r.status_code != 200:
        raise ValueError(r.json().get("detail", "translation rejected"))
    return r.json()


def classify(image: bytes, crop: str) -> dict:
    r = _post("/diagnose", files={"image": ("photo.jpg", image)}, data={"crop": crop})
    if r.status_code != 200:
        raise ValueError(r.json().get("detail", "image rejected"))
    return r.json()


# Model label -> (corpus entry, Kinyarwanda name, English name). Keys are matched as substrings, lowercased.
DIAGNOSES = [
    ("angular", "beans-leaf-diseases", "Indwara y'ibibara ku bishyimbo", "Bean angular leaf spot"),
    ("bean_rust", "beans-leaf-diseases", "Ingese y'ibishyimbo", "Bean rust"),
    ("rust", "maize-leaf-diseases", "Ingese", "Rust"),
    ("cbb", "cassava-cbb-cgm", "Kuma kw'imyumbati guterwa na bagiteri", "Cassava bacterial blight"),
    ("bacterial blight", "cassava-cbb-cgm", "Kuma kw'imyumbati guterwa na bagiteri", "Cassava bacterial blight"),
    ("cgm", "cassava-cbb-cgm", "Udusimba tw'icyatsi ku myumbati", "Cassava green mite"),
    ("green mottle", "cassava-cbb-cgm", "Udusimba tw'icyatsi ku myumbati", "Cassava green mite"),
    ("cbsd", "cassava-diseases", "Indwara y'imirongo y'ikigina", "Cassava brown streak"),
    ("brown streak", "cassava-diseases", "Indwara y'imirongo y'ikigina", "Cassava brown streak"),
    ("cmd", "cassava-diseases", "Ububembe bw'imyumbati", "Cassava mosaic"),
    ("mosaic", "cassava-diseases", "Ububembe bw'imyumbati", "Cassava mosaic"),
    ("late_blight", "potato-lateblight", "Mildiyu y'ibirayi", "Potato late blight"),
    ("late blight", "potato-lateblight", "Mildiyu y'ibirayi", "Potato late blight"),
    ("early_blight", "potato-earlyblight", "Ibibara bifite uruziga ku birayi", "Potato early blight"),
    ("early blight", "potato-earlyblight", "Ibibara bifite uruziga ku birayi", "Potato early blight"),
    ("northern_leaf_blight", "maize-leaf-diseases", "Indwara y'amababi y'ibigori", "Maize northern leaf blight"),
    ("northern leaf blight", "maize-leaf-diseases", "Indwara y'amababi y'ibigori", "Maize northern leaf blight"),
    ("cercospora", "maize-leaf-diseases", "Ibibara by'ivu ku bigori", "Maize grey leaf spot"),
    ("gray_leaf", "maize-leaf-diseases", "Ibibara by'ivu ku bigori", "Maize grey leaf spot"),
    ("healthy", None, "Nta ndwara igaragara", "No disease visible"),
]
CONFIDENT = 0.6


def diagnose(image: bytes, crop: str, lang: str = "rw") -> dict:
    out = classify(image, crop)
    top = out["predictions"][0]
    label = top["label"].lower()
    if label == "h":  # some cassava models use "H" for healthy
        label = "healthy"
    entry_id, name_rw, name_en = None, None, None
    for key, eid, rw, en in DIAGNOSES:
        if key in label:
            entry_id, name_rw, name_en = eid, rw, en
            break
    confident = top["score"] >= CONFIDENT and (entry_id is not None or "healthy" in label)
    advice, source = None, None
    if entry_id and confident:
        e = corpus().by_id[entry_id]
        advice, source = e[f"summary_{lang}"], {"id": e["id"], "title": e[f"title_{lang}"], "source": e["source"]}
    elif "healthy" in label and confident:
        advice = ("Nta ndwara igaragara kuri iyi foto. Komeza ugenzure umurima buri cyumweru." if lang == "rw"
                  else "No disease is visible in this photo. Keep scouting your field weekly.")
    else:
        advice = ("Ntitwizeye neza icyo iyi foto yerekana. Yoherejwe ku mujyanama w'ubuhinzi ngo ayisuzume."
                  if lang == "rw" else "We are not confident about this photo. It has been sent to an extension officer.")
    return {"crop": out["crop"], "model": out["model"], "label": top["label"], "confidence": top["score"],
            "name": (name_rw if lang == "rw" else name_en) or top["label"], "confident": confident,
            "escalated": not confident, "advice": advice, "source": source, "alternatives": out["predictions"][1:]}
