import base64
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from server.audio import silence_wav
from server.config import Settings
from server.ledger import Ledger
from server.main import create_app


@pytest.fixture
def client():
    s = Settings(force_mock=True, db_path=":memory:")
    L = Ledger(":memory:", shop_name="Test Kirana")
    return TestClient(create_app(s, L))


def test_health_reports_mock(client):
    j = client.get("/health").json()
    assert j["modes"] == {"stt": "mock", "llm": "rules", "tts": "mock"}


def test_text_endpoint_end_to_end(client):
    j = client.post("/text", json={"text": "Ramesh ka 240 udhaar, 2 Aashirvaad 5kg bik gaye"}).json()
    assert [a["tool"] for a in j["actions"]] == ["add_credit", "record_sale"]
    assert "240" in j["reply"] and j["lang"] == "hi"
    assert base64.b64decode(j["audio_b64"])[:4] == b"RIFF"
    led = client.get("/ledger").json()
    assert {c["name"]: c["balance"] for c in led["customers"]}["Ramesh"] == 240


def test_voice_raw_wav_returns_wav(client):
    r = client.post("/voice", content=silence_wav(0.3), headers={"Content-Type": "audio/wav",
                                                                  "X-Mock-Transcript": "Lakshmi%20300%20kottru"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF"
    assert unquote(r.headers["x-transcript"]) == "Lakshmi 300 kottru"
    assert r.headers["x-lang"] == "kn" and "ಬಂದಿದೆ" in unquote(r.headers["x-reply"])


def test_voice_multipart_json(client):
    r = client.post("/voice/json", files={"file": ("a.webm", b"\x1aE\xdf\xa3fake", "audio/webm")},
                    data={"mock_transcript": "Murugan ku 200 kadan"})
    j = r.json()
    assert j["actions"][0]["tool"] == "add_credit" and j["lang"] == "ta"


def test_voice_without_hint_uses_canned_samples(client):
    j = client.post("/voice/json", content=silence_wav(0.2), headers={"Content-Type": "audio/wav"}).json()
    assert j["transcript"] and j["actions"]


def test_not_understood(client):
    j = client.post("/text", json={"text": "mausam kaisa hai"}).json()
    assert j["actions"] == [] and "समझ" in j["reply"]


def test_summary_and_reminders(client):
    client.post("/text", json={"text": "Ramesh ka 240 udhaar", "speak": False})
    s = client.get("/summary").json()
    assert s["credit_given"] == 240 and "whatsapp_text" in s
    rem = {r["customer"]: r for r in client.get("/reminders?lang=en").json()}
    assert "Ramesh" in rem and "wa.me" in rem["Ramesh"]["whatsapp_url"]
    assert s["outstanding_total"] == 240 + 1200 + 350  # incl. opening balances, which are not "today"


def test_reset_and_index(client):
    client.post("/text", json={"text": "Ramesh ka 240 udhaar", "speak": False})
    assert client.post("/reset").json()["ok"]
    bal = {c["name"]: c["balance"] for c in client.get("/ledger").json()["customers"]}
    assert bal["Ramesh"] == 0 and bal["Lakshmi"] == 1200  # demo opening balance restored
    assert "Kirana Voice Ledger" in client.get("/").text


def test_empty_audio_rejected(client):
    assert client.post("/voice", content=b"", headers={"Content-Type": "audio/wav"}).status_code == 400
