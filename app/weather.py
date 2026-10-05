"""District weather forecasts (Open-Meteo, no key required) turned into farm advice.

Only district-level coordinates leave the server, never farmer data. In production
this would read Meteo Rwanda feeds via the national corpus APIs.
"""
import datetime as dt
import time

import httpx

# Approximate district centroids (lat, lon) for all 30 districts.
DISTRICTS: dict[str, tuple[float, float]] = {
    "Gasabo": (-1.90, 30.11), "Kicukiro": (-1.97, 30.10), "Nyarugenge": (-1.95, 30.06),
    "Burera": (-1.47, 29.83), "Gakenke": (-1.70, 29.78), "Gicumbi": (-1.58, 30.06),
    "Musanze": (-1.50, 29.63), "Rulindo": (-1.73, 30.00),
    "Gisagara": (-2.62, 29.83), "Huye": (-2.60, 29.74), "Kamonyi": (-2.00, 29.90),
    "Muhanga": (-2.08, 29.75), "Nyamagabe": (-2.48, 29.53), "Nyanza": (-2.35, 29.75),
    "Nyaruguru": (-2.70, 29.55), "Ruhango": (-2.22, 29.78),
    "Bugesera": (-2.20, 30.15), "Gatsibo": (-1.58, 30.43), "Kayonza": (-1.90, 30.50),
    "Kirehe": (-2.27, 30.65), "Ngoma": (-2.15, 30.48), "Nyagatare": (-1.30, 30.33),
    "Rwamagana": (-1.95, 30.43),
    "Karongi": (-2.07, 29.35), "Ngororero": (-1.87, 29.53), "Nyabihu": (-1.65, 29.50),
    "Nyamasheke": (-2.33, 29.13), "Rubavu": (-1.68, 29.33), "Rusizi": (-2.48, 28.90),
    "Rutsiro": (-1.93, 29.33),
}

_cache: dict[str, tuple[float, dict]] = {}
_TTL = 3600


def match_district(text: str | None) -> str | None:
    if not text:
        return None
    t = text.strip().lower()
    for name in DISTRICTS:
        if name.lower() == t:
            return name
    for name in DISTRICTS:  # tolerate prefixes / small typos on feature phones
        if len(t) >= 4 and (name.lower().startswith(t[:4]) or t.startswith(name.lower()[:4])):
            return name
    return None


def forecast(district: str) -> dict:
    hit = _cache.get(district)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    lat, lon = DISTRICTS[district]
    r = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat, "longitude": lon, "timezone": "Africa/Kigali", "forecast_days": 7,
            "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        },
        timeout=8,
    )
    r.raise_for_status()
    d = r.json()["daily"]
    rain = [x or 0.0 for x in d["precipitation_sum"]]
    data = {
        "district": district,
        "days": d["time"],
        "rain_mm": rain,
        "tmax": d["temperature_2m_max"],
        "tmin": d["temperature_2m_min"],
        "total_rain_mm": round(sum(rain), 1),
        "rainy_days": sum(1 for x in rain if x >= 1.0),
        "max_day_rain_mm": round(max(rain), 1),
        "max_temp_c": round(max(d["temperature_2m_max"]), 1),
        "source": "Open-Meteo 7-day forecast",
    }
    _cache[district] = (time.time(), data)
    return data


def advice(f: dict, today: dt.date | None = None) -> dict:
    """Rule-based, auditable advisory from a 7-day forecast."""
    today = today or dt.date.today()
    m = today.month
    planting_window = m in (9, 10, 2, 3)
    harvest_window = m in (12, 1, 6, 7)
    total, days, peak, tmax = f["total_rain_mm"], f["rainy_days"], f["max_day_rain_mm"], f["max_temp_c"]
    en, rw, alerts = [], [], []

    if peak >= 40:
        alerts.append("heavy_rain")
        en.append(f"ALERT: heavy rain up to {peak}mm in a day. Clear drainage, protect terraces, delay fertiliser top-dressing.")
        rw.append(f"ICYITONDERWA: imvura nyinshi igera kuri mm {peak} ku munsi. Siba imiyoboro, rinda amaterasi, utinze gushyira ifumbire.")
    if planting_window:
        if total >= 30 and days >= 3:
            en.append(f"Good planting window: {total}mm over {days} days expected. Plant now once soil is moist 15cm deep.")
            rw.append(f"Igihe cyiza cyo gutera: mm {total} mu minsi {days}. Tera ubutaka butose kugeza kuri cm 15.")
        elif total < 10:
            alerts.append("dry_spell")
            en.append(f"Dry week ahead ({total}mm). Wait for reliable rain before planting; mulch and save water.")
            rw.append(f"Icyumweru cy'izuba (mm {total}). Tegereza imvura ikomeye mbere yo gutera; sasira, ubike amazi.")
        else:
            en.append(f"Light rain expected ({total}mm, {days} days). Prepare land and inputs; plant when rains settle.")
            rw.append(f"Imvura nke iteganyijwe (mm {total}, iminsi {days}). Tegura umurima n'inyongeramusaruro; tera imvura imaze gukomera.")
    elif harvest_window:
        if days >= 3:
            en.append(f"Rain on {days} days: harvest in dry spells and dry grain on tarpaulins under cover.")
            rw.append(f"Imvura mu minsi {days}: sarura izuba riva, wanike kuri shitingi ahatagera imvura.")
        else:
            en.append("Mostly dry: good conditions to harvest and dry grain.")
            rw.append("Izuba ryinshi: igihe cyiza cyo gusarura no kumisha.")
    else:
        en.append(f"Next 7 days: {total}mm of rain over {days} days.")
        rw.append(f"Iminsi 7 iri imbere: imvura ya mm {total} mu minsi {days}.")
        if total < 10:
            alerts.append("dry_spell")
            en.append("Mulch and irrigate young crops; water animals well.")
            rw.append("Sasira kandi wuhire ibihingwa bito; uhe amatungo amazi ahagije.")
    if tmax >= 30:
        alerts.append("heat")
        en.append(f"Hot days up to {tmax}C: water in the morning or evening, give animals shade.")
        rw.append(f"Ubushyuhe bugera kuri {tmax}C: uhira mu gitondo cyangwa nimugoroba, uhe amatungo igicucu.")

    return {"en": " ".join(en), "rw": " ".join(rw), "alerts": alerts}


def summary(district: str, lang: str) -> dict:
    f = forecast(district)
    a = advice(f)
    head = (f"{district}: imvura mm {f['total_rain_mm']} mu minsi 7, ubushyuhe ≤{f['max_temp_c']}C. "
            if lang == "rw" else
            f"{district}: {f['total_rain_mm']}mm rain in 7 days, max {f['max_temp_c']}C. ")
    return {"text": head + a[lang], "alerts": a["alerts"], "forecast": f}
