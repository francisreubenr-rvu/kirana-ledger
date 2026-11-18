"""Real-provider code paths, exercised against a fake HTTP transport (no key, no network).
They pin the request shapes taken from docs.sarvam.ai so a refactor can't silently break them."""
import base64
import json

import httpx

from server.agent import Agent
from server.audio import silence_wav, tone_wav
from server.config import Settings
from server.llm import ChatToolPlanner, make_planner
from server.speech import SarvamSTT, SarvamTTS

S = Settings(sarvam_api_key="sk_test_dummy", force_mock=False)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_stt_request_shape():
    seen = {}

    def h(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["key"] = req.headers.get("api-subscription-key")
        seen["body"] = req.content
        return httpx.Response(200, json={"transcript": "Ramesh का 240 उधार", "language_code": "hi-IN"})

    r = SarvamSTT(S, _client(h)).transcribe(silence_wav(0.1), keyterms=["Ramesh", "Aashirvaad Atta 5kg"])
    assert seen["url"] == "https://api.sarvam.ai/speech-to-text"
    assert seen["key"] == "sk_test_dummy"
    body = seen["body"]
    for part in (b'name="model"', b"saaras:v4", b'name="mode"', b"codemix", b'name="keyterms"', b'name="file"'):
        assert part in body
    assert r.transcript == "Ramesh का 240 उधार" and r.lang == "hi"


def test_stt_retries_without_mode_on_422():
    calls = []

    def h(req):
        calls.append(req.content)
        if b'name="mode"' in req.content:
            return httpx.Response(422, json={"error": "mode not supported"})
        return httpx.Response(200, json={"transcript": "ok", "language_code": "kn-IN"})

    r = SarvamSTT(S, _client(h)).transcribe(silence_wav(0.1))
    assert len(calls) == 2 and r.lang == "kn"


def test_tts_request_shape():
    wav = tone_wav("hi")
    seen = {}

    def h(req):
        seen["url"] = str(req.url)
        seen["json"] = json.loads(req.content)
        seen["key"] = req.headers.get("api-subscription-key")
        return httpx.Response(200, json={"audios": [base64.b64encode(wav).decode()]})

    out = SarvamTTS(S, _client(h)).speak("ನಮಸ್ಕಾರ", "kn")
    assert out == wav and seen["url"] == "https://api.sarvam.ai/text-to-speech"
    j = seen["json"]
    assert j["model"] == "bulbul:v4-flash" and j["language_code"] == "kn-IN"
    assert j["speaker"] == "chaitra_kn_conversation" and j["speech_sample_rate"] == 16000
    assert seen["key"] == "sk_test_dummy"


def _tool_call_response(*calls):
    return {"choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
            "tool_calls": [{"id": f"call-{i}", "type": "function",
                            "function": {"name": n, "arguments": json.dumps(a)}} for i, (n, a) in enumerate(calls)]}}]}


def test_sarvam_planner_request_and_tool_calls(ledger):
    seen = {}

    def h(req):
        seen["url"] = str(req.url)
        seen["key"] = req.headers.get("api-subscription-key")
        seen["json"] = json.loads(req.content)
        return httpx.Response(200, json=_tool_call_response(
            ("add_credit", {"customer": "Ramesh", "amount": 240}),
            ("record_sale", {"item": "Aashirvaad Atta 5kg", "qty": 2})))

    planner = make_planner(S, client=_client(h))
    assert isinstance(planner, ChatToolPlanner) and planner.name == "sarvam"
    tts_wav = tone_wav("x")
    tts = SarvamTTS(S, _client(lambda r: httpx.Response(200, json={"audios": [base64.b64encode(tts_wav).decode()]})))
    stt = SarvamSTT(S, _client(lambda r: httpx.Response(200, json={"transcript": "Ramesh ka 240 udhaar, 2 Aashirvaad 5kg bik gaye", "language_code": "hi-IN"})))
    ag = Agent(S, ledger, planner=planner, stt=stt, tts=tts)
    out = ag.handle_audio(silence_wav(0.1))
    assert seen["url"] == "https://api.sarvam.ai/v1/chat/completions" and seen["key"] == "sk_test_dummy"
    body = seen["json"]
    assert body["model"] == "sarvam-105b" and body["tool_choice"] == "auto"
    assert {t["function"]["name"] for t in body["tools"]} >= {"add_credit", "record_sale", "daily_summary"}
    assert "Ramesh" in body["messages"][0]["content"]  # known customers injected
    assert [a["tool"] for a in out["actions"]] == ["add_credit", "record_sale"]
    assert out["_audio"] == tts_wav and out["provider"] == "sarvam"
    assert ledger.query_balance("Ramesh")["balance"] == 240


def test_llm_clarifying_question_is_spoken(ledger):
    h = lambda r: httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "Kitne rupaye?"}}]})
    ag = Agent(Settings(force_mock=True), ledger, planner=make_planner(S, client=_client(h)))
    out = ag.handle_text("Ramesh ka udhaar likho")
    assert out["actions"] == [] and out["reply"] == "Kitne rupaye?"


def test_llm_failure_falls_back_to_rules(ledger):
    h = lambda r: httpx.Response(503, json={"error": {"message": "model_overloaded"}})
    ag = Agent(Settings(force_mock=True), ledger, planner=make_planner(S, client=_client(h)))
    out = ag.handle_text("Ramesh ka 240 udhaar")
    assert out["actions"][0]["tool"] == "add_credit" and out["warnings"]


def test_openai_compatible_provider_swap():
    s = Settings(sarvam_api_key=None, llm_provider="openai", llm_url="https://example.test/v1/chat/completions",
                 llm_model="some-model", openai_api_key="k")
    seen = {}

    def h(req):
        seen["auth"] = req.headers.get("authorization")
        seen["model"] = json.loads(req.content)["model"]
        return httpx.Response(200, json=_tool_call_response(("daily_summary", {})))

    p = make_planner(s, client=_client(h))
    plan = p.plan("aaj ka hisaab", [], [])
    assert seen == {"auth": "Bearer k", "model": "some-model"} and plan.calls[0]["tool"] == "daily_summary"


def test_no_key_means_mock_everything():
    s = Settings(sarvam_api_key=None)
    assert s.mock_audio and s.resolved_llm == "rules"
