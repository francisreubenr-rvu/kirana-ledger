"""Settings from environment variables. The API key is only ever read from SARVAM_API_KEY."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@dataclass
class Settings:
    sarvam_api_key: str | None = field(default_factory=lambda: _env("SARVAM_API_KEY"))
    force_mock: bool = field(default_factory=lambda: _env("KIRANA_MOCK", "0") in ("1", "true", "yes"))

    # Sarvam endpoints and models (verified against docs.sarvam.ai on 18 Nov 2026)
    sarvam_base: str = field(default_factory=lambda: _env("SARVAM_BASE_URL", "https://api.sarvam.ai"))
    stt_model: str = field(default_factory=lambda: _env("STT_MODEL", "saaras:v4"))
    stt_mode: str = field(default_factory=lambda: _env("STT_MODE", "codemix"))
    stt_language: str = field(default_factory=lambda: _env("STT_LANGUAGE", "unknown"))  # auto-detect
    tts_model: str = field(default_factory=lambda: _env("TTS_MODEL", "bulbul:v4-flash"))
    tts_sample_rate: int = field(default_factory=lambda: int(_env("TTS_SAMPLE_RATE", "16000")))

    # LLM provider: "sarvam" | "openai" (any OpenAI-compatible endpoint) | "rules"
    llm_provider: str | None = field(default_factory=lambda: _env("LLM_PROVIDER"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "sarvam-105b"))
    llm_url: str | None = field(default_factory=lambda: _env("LLM_URL"))  # override chat-completions URL
    llm_reasoning_effort: str | None = field(default_factory=lambda: _env("LLM_REASONING_EFFORT", "low"))
    openai_api_key: str | None = field(default_factory=lambda: _env("OPENAI_API_KEY"))  # only for LLM_PROVIDER=openai

    # Shop
    db_path: str = field(default_factory=lambda: _env("KIRANA_DB", "kirana.db"))
    shop_name: str = field(default_factory=lambda: _env("SHOP_NAME", "Sri Lakshmi Kirana"))
    owner_lang: str = field(default_factory=lambda: _env("OWNER_LANG", "auto"))  # auto|hi|kn|ta|en
    seed_demo: bool = field(default_factory=lambda: _env("SEED_DEMO", "1") == "1")

    @property
    def mock_audio(self) -> bool:
        return self.force_mock or not self.sarvam_api_key

    @property
    def resolved_llm(self) -> str:
        if self.force_mock:
            return "rules"
        if self.llm_provider:
            return self.llm_provider
        return "sarvam" if self.sarvam_api_key else "rules"


# Bulbul v4-flash persona per language (ids from docs.sarvam.ai TTS voices page). Override with TTS_SPEAKER_<LANG>.
SPEAKERS = {
    "hi": _env("TTS_SPEAKER_HI", "shubh_hi_customer"),
    "kn": _env("TTS_SPEAKER_KN", "chaitra_kn_conversation"),
    "ta": _env("TTS_SPEAKER_TA", "gokul_ta_narration"),
    "en": _env("TTS_SPEAKER_EN", "simran_en_customer"),
}
BCP47 = {"hi": "hi-IN", "kn": "kn-IN", "ta": "ta-IN", "en": "en-IN"}
