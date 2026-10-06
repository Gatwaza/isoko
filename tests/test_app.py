import os
import tempfile

os.environ["DATABASE_URL"] = ""  # never touch a real database from tests
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["LLM_PROVIDER"] = "none"  # deterministic: curated text only
os.environ["API_KEYS"] = "test-key"

from fastapi.testclient import TestClient  # noqa: E402

from app import advisor, ussd  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
H = {"X-API-Key": "test-key"}


def dial(phone, *inputs):
    from app import db
    if not db.get_profile(phone).get("consented_at"):
        db.update_profile(phone, consented_at=1.0)
    return client.post("/ussd", data={"sessionId": "t", "phoneNumber": phone, "serviceCode": "*1#",
                                      "text": "*".join(inputs)}).text


def test_home_is_kinyarwanda_and_fits_ussd():
    r = dial("+250780000001")
    assert r.startswith("CON Isoko ry'Umuhinzi")
    assert len(r) - 4 <= ussd.USSD_LIMIT


def test_crop_topic_answer_ends_session_and_queues_sms():
    r = dial("+250780000002", "1", "1", "3", "1")
    assert r.startswith("END ") and "nkongwa" in r.lower()
    out = client.get("/api/sms/outbox", params={"phone": "+250780000002"}).json()
    assert out and "Nkongwa" in out[0]["message"]


def test_every_ussd_screen_fits_limit():
    paths = [[], ["1"], ["2"], ["2", "98"], ["4"], ["4", "1"], ["6"], ["5"], ["8"], ["8", "1"]]
    for p in paths:
        r = dial("+250780000003", *p)
        assert len(r) - 4 <= ussd.USSD_LIMIT, (p, len(r))


def test_back_and_language_toggle():
    assert dial("+250780000004", "1", "0").startswith("CON Isoko ry'Umuhinzi")
    assert "Crops" in dial("+250780000004", "8")
    assert "Crops" in dial("+250780000004", "8", "1", "0")  # back must not flip language again


def test_api_requires_key():
    assert client.post("/v1/advisory/query", json={"question": "maize"}).status_code == 401


def test_api_answers_kinyarwanda_from_curated_text():
    r = client.post("/v1/advisory/query", headers=H, json={"question": "Insina zanjye zirwaye kirabiranya"}).json()
    assert r["language"] == "rw" and not r["escalated"]
    assert r["sources"][0]["id"] == "banana-bxw"


def test_out_of_scope_is_escalated_not_guessed():
    r = client.post("/v1/advisory/query", headers=H, json={"question": "How do I fix my car engine?"}).json()
    assert r["escalated"] and r["sources"] == []


def test_openai_compatible_endpoint():
    r = client.post("/v1/chat/completions", headers={"Authorization": "Bearer test-key"},
                    json={"messages": [{"role": "user", "content": "How do I control fall armyworm in maize?"}]}).json()
    assert r["choices"][0]["message"]["content"]
    assert r["isoko"]["sources"][0]["id"] == "maize-faw"


def test_plural_query_hits_right_crop():
    assert advisor.answer("fertiliser for potatoes", log=False).sources[0]["id"] == "potato-fertiliser"


def test_numbers_guardrail():
    assert advisor.numbers_grounded("Use 3kg per are", "about 3kg per are (300kg/ha)")
    assert not advisor.numbers_grounded("Use 5kg per are", "about 3kg per are (300kg/ha)")


def test_report_reaches_dashboard():
    dial("+250780000005", "6", "1", "Huye")
    stats = client.get("/api/dashboard/stats").json()
    assert any(r["district"] == "Huye" and r["issue"] == "crop_pest" for r in stats["reports"])


def test_first_use_asks_for_consent():
    r = client.post("/ussd", data={"sessionId": "c1", "phoneNumber": "+250780000099", "text": ""}).text
    assert r.startswith("CON Murakaza neza kuri Isoko")
    assert "Isoko ry'Umuhinzi" in client.post("/ussd", data={"sessionId": "c1", "phoneNumber": "+250780000099", "text": "1"}).text
    crops = client.post("/ussd", data={"sessionId": "c1", "phoneNumber": "+250780000099", "text": "1*1"}).text
    assert "Ibigori" in crops  # the consent "1" is not misread as a menu choice in the same session


def test_broad_crop_question_gets_overview():
    from app import advisor
    a = advisor.answer("Mwaramutse, mwambwira amakuru ki ku bijyanye n'ibirayi", log=False)
    assert a.model == "overview" and all(s["id"].startswith("potato") for s in a.sources)
    assert advisor.answer("Insina zanjye ziruma kandi ibitoki biraboha", log=False).sources[0]["id"] == "banana-bxw"


def test_async_job_and_system_pinning():
    import time
    r = client.post("/v1/jobs", headers={**H, "X-Benchmark-Run": "t-job"},
                    json={"items": [{"id": "a", "question": "nkongwa mu bigori"}, {"id": "b", "question": "football"}]})
    assert r.status_code == 202
    jid = r.json()["job_id"]
    for _ in range(40):
        d = client.get(f"/v1/jobs/{jid}", headers=H).json()
        if d["status"] == "done":
            break
        time.sleep(0.25)
    assert d["done"] == 2 and d["results"][1]["escalated"]
    sysinfo = client.get("/v1/system").json()
    assert sysinfo["corpus"]["sha256"] and "commit" in sysinfo
    assert client.get("/v1/channels/status").json()["channels"]["ussd"]["status"] in ("live", "simulated")
