"""The voice pipeline: audio -> STT -> planner (LLM tool calls) -> ledger tools -> confirmation -> TTS."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from . import messages, rule_parser
from .config import Settings
from .ledger import Ledger
from .llm import Planner, RulePlanner, make_planner
from .speech import MockSTT, MockTTS, SarvamSTT, SarvamTTS
from .tools import run_tool

log = logging.getLogger("kirana.agent")
SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "utterances.json"


def load_samples() -> list[dict]:
    try:
        return json.loads(SAMPLES.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []


class Agent:
    def __init__(self, settings: Settings, ledger: Ledger, planner: Planner | None = None, stt=None, tts=None):
        self.s = settings
        self.ledger = ledger
        self.item_lookup = lambda q: (r["name"] if (r := ledger._find_item(q)) else None)
        self.planner = planner or make_planner(settings, self.item_lookup)
        self.fallback = RulePlanner(self.item_lookup)
        if stt is not None:
            self.stt = stt
        elif settings.mock_audio:
            self.stt = MockSTT([x["text"] for x in load_samples()])
        else:
            self.stt = SarvamSTT(settings)
        self.tts = tts or (MockTTS(settings.tts_sample_rate) if settings.mock_audio else SarvamTTS(settings))

    @property
    def modes(self) -> dict:
        return {
            "stt": "mock" if isinstance(self.stt, MockSTT) else "sarvam",
            "llm": self.planner.name,
            "tts": "mock" if isinstance(self.tts, MockTTS) else "sarvam",
        }

    def _names(self) -> tuple[list[str], list[str]]:
        snap = self.ledger.snapshot(limit=1)
        return [c["name"] for c in snap["customers"]], [i["name"] for i in snap["items"]]

    def handle_text(self, transcript: str, lang_hint: str = "", speak: bool = True) -> dict:
        t0 = time.perf_counter()
        customers, items = self._names()
        warnings = []
        try:
            plan = self.planner.plan(transcript, customers, items)
        except Exception as e:  # network/LLM failure: degrade to offline rules so the shop keeps working
            log.exception("planner failed; falling back to rules")
            warnings.append(f"{self.planner.name} planner failed ({type(e).__name__}); used offline rules")
            plan = self.fallback.plan(transcript, customers, items)

        if self.s.owner_lang in ("hi", "kn", "ta", "en"):
            lang = self.s.owner_lang
        else:
            lang = lang_hint or plan.lang or rule_parser.detect_lang(transcript)

        results = [run_tool(self.ledger, c["tool"], c["args"]) for c in plan.calls]
        if results:
            reply = " ".join(messages.confirm(r, lang) for r in results)
        elif plan.say:
            reply = plan.say
        else:
            reply = messages.not_understood(lang)

        audio = None
        if speak:
            try:
                audio = self.tts.speak(reply, lang)
            except Exception as e:
                log.exception("TTS failed")
                warnings.append(f"TTS failed ({type(e).__name__}); used mock chime")
                audio = MockTTS(self.s.tts_sample_rate).speak(reply, lang)
        return {
            "transcript": transcript,
            "lang": lang,
            "actions": [{"tool": c["tool"], "args": c["args"], "result": r} for c, r in zip(plan.calls, results)],
            "reply": reply,
            "provider": plan.provider,
            "modes": self.modes,
            "warnings": warnings,
            "ms": round((time.perf_counter() - t0) * 1000),
            "_audio": audio,
        }

    def handle_audio(self, audio: bytes, mock_transcript: str | None = None) -> dict:
        t0 = time.perf_counter()
        customers, items = self._names()
        if isinstance(self.stt, MockSTT):
            stt = self.stt.transcribe(audio, hint=mock_transcript)
        else:
            stt = self.stt.transcribe(audio, keyterms=customers + items)
        stt_ms = round((time.perf_counter() - t0) * 1000)
        if not stt.transcript:
            lang = self.s.owner_lang if self.s.owner_lang in ("hi", "kn", "ta", "en") else (stt.lang or "hi")
            reply = messages.not_understood(lang)
            return {"transcript": "", "lang": lang, "actions": [], "reply": reply, "provider": "", "modes": self.modes,
                    "warnings": ["empty transcript"], "ms": stt_ms, "stt_ms": stt_ms, "_audio": self.tts.speak(reply, lang)}
        out = self.handle_text(stt.transcript, lang_hint=stt.lang)
        out["stt_ms"] = stt_ms
        out["ms"] += stt_ms
        return out
