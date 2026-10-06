"""Populate a DEMO database with simulated farmer traffic, driven through the real
USSD handler and advisor, so the dashboard can be demonstrated. Run the server with
DEMO_MODE=true so the dashboard is clearly labelled as simulated.

    DB_PATH=data/demo.db python scripts/seed_demo.py
"""
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DB_PATH", "data/demo.db")
os.environ.setdefault("LLM_PROVIDER", "none")

from app import advisor, db, sms, ussd, weather  # noqa: E402

sms.send = lambda phone, msg: db.queue_sms(phone, msg, "demo")  # never hit a real gateway
random.seed(7)

DISTRICTS = ["Nyagatare", "Gatsibo", "Kayonza", "Bugesera", "Musanze", "Nyabihu", "Huye", "Nyamagabe",
             "Rusizi", "Karongi", "Gicumbi", "Rwamagana", "Ngoma", "Kirehe", "Muhanga"]
MENU_PATHS = [["1", "1", "3"], ["1", "1", "2"], ["1", "1", "1"], ["2", "1"], ["2", "2"], ["2", "3"], ["1", "3", "3"],
              ["4", "1", "2"], ["4", "1", "1"], ["4", "2", "1"], ["1", "2", "1"], ["1", "5", "3"], ["1", "4", "2"],
              ["2", "98", "7"], ["4", "3", "1"]]
QUESTIONS = ["Ibigori byanjye bifite nkongwa nkore iki?", "Inka yanjye ifite uburondwe", "Ibirayi byanjye biraraba",
             "Insina zanjye zirwaye kirabiranya", "Inkoko zanjye zirimo gupfa", "ifumbire y'ibishyimbo",
             "How much DAP for maize?", "Ubutaka bwanjye burasharira", "Nabona nte ifumbire ya Nkunganire?",
             "Igiciro cy'ibirayi ku isoko ni angahe?", "Ese avoka zatewe ryari?", "Ndashaka inguzanyo ya banki",
             "Imbuto z'ibinyomoro nazikura he?"]

phones = {f"+2507900{i:05d}": random.choice(DISTRICTS) for i in range(140)}
for p, d in phones.items():
    db.update_profile(p, district=d, consented_at=time.time())

now = time.time()
n = 0
for day in range(14, -1, -1):
    for _ in range(random.randint(12, 30) + (14 - day) * 2):
        phone = random.choice(list(phones))
        if random.random() < 0.7:
            ussd.handle("demo", phone, "*".join(random.choice(MENU_PATHS)))
        else:
            advisor.answer(random.choice(QUESTIONS), district=phones[phone], channel="sms", phone=phone)
        n += 1
    # back-date this day's rows
    jitter = "random() * 36000" if db.PG else "(abs(random()) % 36000)"
    db.execute(f"UPDATE interactions SET ts = ? - (? * 86400) - {jitter} WHERE ts > ?", (now, day, now - 5))

for district, issue in [("Nyagatare", "crop_pest"), ("Nyagatare", "crop_pest"), ("Gatsibo", "crop_pest"),
                        ("Kayonza", "drought"), ("Bugesera", "drought"), ("Musanze", "crop_pest"),
                        ("Rusizi", "animal_disease"), ("Huye", "inputs"), ("Nyabihu", "flood")]:
    db.log_report(phone=None, district=district, issue=issue, detail="simulated demo report", channel="ussd")
print(f"seeded {n} interactions for {len(phones)} simulated farmers into {os.environ['DB_PATH']}")
