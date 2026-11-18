"""Speech providers: Sarvam Saaras (STT) and Bulbul (TTS), plus offline mocks.

Request shapes follow docs.sarvam.ai (checked 18 Nov 2026):
  STT  POST {base}/speech-to-text     multipart: file, model, mode, language_code, keyterms(JSON array)
       -> {"transcript", "language_code", "request_id", ...}
  TTS  POST {base}/text-to-speech     JSON: text, language_code, speaker, model, speech_sample_rate, output_audio_codec
       -> {"audios": [base64 wav], "request_id"}
  Auth header on both: api-subscription-key: <key>
"""
from __future__ import annotations

import base64
import itertools
import json
import logging
from dataclasses import dataclass

import httpx

from .audio import sniff_mime, tone_wav
from .config import BCP47, SPEAKERS, Settings

log = logging.getLogger("kirana.speech")


@dataclass
class STTResult:
    transcript: str
    lang: str  # hi / kn / ta / en (or "" if unknown)
    raw: dict | None = None


def _short_lang(code: str | None) -> str:
    if not code:
        return ""
    s = code.split("-")[0].lower()
    return s if s in ("hi", "kn", "ta", "en") else ""


class SarvamSTT:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.s = settings
        self.client = client or httpx.Client(timeout=30)

    def transcribe(self, audio: bytes, keyterms: list[str] | None = None) -> STTResult:
        fname, mime = sniff_mime(audio)
        data = {"model": self.s.stt_model, "language_code": self.s.stt_language}
        if self.s.stt_mode:
            data["mode"] = self.s.stt_mode
        if keyterms and self.s.stt_model == "saaras:v4":
            data["keyterms"] = json.dumps([k[:64] for k in keyterms[:50]], ensure_ascii=False)
        url = f"{self.s.sarvam_base}/speech-to-text"
        headers = {"api-subscription-key": self.s.sarvam_api_key or ""}
        r = self.client.post(url, headers=headers, data=data, files={"file": (fname, audio, mime)})
        if r.status_code in (400, 422) and "mode" in data:
            # The docs list `mode` as saaras:v3-only in one place and as supported by v4 in another;
            # if the server rejects it, retry once without it rather than failing the shop owner.
            log.warning("STT rejected mode=%s (%s); retrying without mode", data["mode"], r.text[:200])
            data.pop("mode")
            r = self.client.post(url, headers=headers, data=data, files={"file": (fname, audio, mime)})
        r.raise_for_status()
        j = r.json()
        return STTResult(transcript=(j.get("transcript") or "").strip(), lang=_short_lang(j.get("language_code")), raw=j)


class MockSTT:
    """Offline STT. Uses the transcript the caller supplies (X-Mock-Transcript header or form field),
    otherwise cycles through the canned sample utterances."""

    def __init__(self, canned: list[str]):
        self._cycle = itertools.cycle(canned or ["Ramesh ka 240 udhaar"])

    def transcribe(self, audio: bytes, keyterms: list[str] | None = None, hint: str | None = None) -> STTResult:
        return STTResult(transcript=(hint or next(self._cycle)).strip(), lang="", raw={"mock": True})


class SarvamTTS:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.s = settings
        self.client = client or httpx.Client(timeout=30)

    def speak(self, text: str, lang: str) -> bytes:
        body = {
            "text": text[:2500],
            "language_code": BCP47.get(lang, "hi-IN"),
            "speaker": SPEAKERS.get(lang, SPEAKERS["hi"]),
            "model": self.s.tts_model,
            "speech_sample_rate": self.s.tts_sample_rate,
            "output_audio_codec": "wav",
        }
        r = self.client.post(
            f"{self.s.sarvam_base}/text-to-speech",
            headers={"api-subscription-key": self.s.sarvam_api_key or "", "Content-Type": "application/json"},
            json=body,
        )
        r.raise_for_status()
        audios = r.json().get("audios") or []
        if not audios:
            raise RuntimeError("TTS returned no audio")
        return base64.b64decode(audios[0])


class MockTTS:
    def __init__(self, rate: int = 16000):
        self.rate = rate

    def speak(self, text: str, lang: str) -> bytes:
        return tone_wav(text, self.rate)
