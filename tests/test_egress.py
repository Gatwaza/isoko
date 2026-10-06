"""Data-residency guard: the app may only contact allowlisted hosts, and never sends phone numbers out.

Every outbound connection is intercepted while USSD, SMS, voice, photo, API and dashboard flows run.
Allowlist: localhost services (LLM, model service, database) and the weather API, which only ever
receives district coordinates.
"""
import os
import socket
import tempfile

import httpx
import pytest

os.environ["DATABASE_URL"] = ""
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "egress.db")
os.environ["LLM_PROVIDER"] = "ollama"
os.environ["LLM_BASE_URL"] = "http://127.0.0.1:9"      # unreachable on purpose: must degrade, not leak
os.environ["ML_SERVICE_URL"] = "http://127.0.0.1:9"
os.environ["API_KEYS"] = "test-key"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ALLOWED = {"127.0.0.1", "localhost", "::1", "testserver", "api.open-meteo.com"}
PHONE = "+250788555123"
seen_hosts: set[str] = set()
seen_requests: list[str] = []


@pytest.fixture(autouse=True)
def guard(monkeypatch):
    real_connect = socket.create_connection

    def connect(address, *a, **kw):
        host = address[0]
        seen_hosts.add(host)
        if host not in ALLOWED:
            raise AssertionError(f"outbound connection to non-allowlisted host {host}")
        if host == "api.open-meteo.com":  # no real network in tests
            raise OSError("network disabled in test")
        return real_connect(address, *a, **kw)

    real_send = httpx.Client.send

    def send(self, request, *a, **kw):
        try:
            body = request.read().decode("utf-8", "ignore")
        except Exception:
            body = ""
        seen_requests.append(str(request.url) + " " + body)
        return real_send(self, request, *a, **kw)

    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(httpx.Client, "send", send)
    yield


def test_no_disallowed_egress_and_no_phone_numbers_leave():
    c = TestClient(app)
    H = {"X-API-Key": "test-key"}
    for text in ["", "1*1*3*1", "3*Nyagatare", "5*inka yanjye irwaye", "6*1*Huye", "7*Musanze*2"]:
        assert c.post("/ussd", data={"sessionId": "e", "phoneNumber": PHONE, "text": text}).status_code == 200
    c.post("/sms/inbound", data={"from": PHONE, "text": "ibigori nkongwa"})
    c.post("/v1/advisory/query", headers=H, json={"question": "How much DAP for maize?", "district": "Huye"})
    c.post("/api/demo/voice", files={"audio": ("a.wav", b"RIFF0000")}, data={"phone": PHONE})
    c.post("/api/demo/diagnose", files={"image": ("p.jpg", b"\xff\xd8\xff")}, data={"crop": "beans", "phone": PHONE})
    c.get("/api/dashboard/stats")
    c.get("/v1/channels/status")
    assert seen_hosts <= ALLOWED, seen_hosts - ALLOWED
    leaked = [r for r in seen_requests if "testserver" not in r and (PHONE in r or PHONE.lstrip("+") in r)]
    assert not leaked, leaked
