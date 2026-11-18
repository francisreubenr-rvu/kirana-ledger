"""FastAPI server.

Device:  POST /voice        body = WAV (raw, Content-Type audio/wav) or multipart field "file"  -> audio/wav
Web:     POST /voice/json   same input -> JSON (transcript, actions, reply, base64 WAV)
Testing: POST /text         {"text": "...", "lang": "hi|kn|ta|en"?, "speak": bool?} -> JSON
Read:    GET /ledger, GET /summary?day=YYYY-MM-DD, GET /reminders?lang=hi, GET /health
Demo:    POST /reset  (wipes and re-seeds demo data)
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from .agent import Agent, load_samples
from .config import Settings
from .ledger import Ledger

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
WEB = Path(__file__).resolve().parent.parent / "web"
MAX_AUDIO = 2 * 1024 * 1024  # ~60 s of 16 kHz mono 16-bit; Sarvam REST STT takes < 30 s


class TextIn(BaseModel):
    text: str
    lang: str | None = None
    speak: bool = True


def create_app(settings: Settings | None = None, ledger: Ledger | None = None, agent: Agent | None = None) -> FastAPI:
    s = settings or Settings()
    led = ledger or Ledger(s.db_path, shop_name=s.shop_name)
    if s.seed_demo and not led.snapshot(1)["items"]:
        led.seed_demo(opening_balances=True)
    ag = agent or Agent(s, led)
    app = FastAPI(title="Kirana Voice Ledger", version="0.1.0")
    app.state.agent, app.state.ledger, app.state.settings = ag, led, s

    async def _read_audio(request: Request) -> tuple[bytes, str | None]:
        ctype = request.headers.get("content-type", "")
        hint = request.headers.get("x-mock-transcript")
        if ctype.startswith("multipart/form-data"):
            form = await request.form()
            f = form.get("file")
            if f is None:
                raise HTTPException(400, "multipart upload needs a 'file' field")
            data = await f.read()
            hint = form.get("mock_transcript") or hint
        else:
            data = await request.body()
        if hint:
            hint = _unquote(hint)
        if not data and not hint:
            raise HTTPException(400, "empty audio")
        if len(data) > MAX_AUDIO:
            raise HTTPException(413, "audio too long; keep utterances under ~30 s")
        return data, hint

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    @app.get("/health")
    def health():
        return {"ok": True, "modes": ag.modes, "shop": s.shop_name, "owner_lang": s.owner_lang}

    @app.post("/voice")
    async def voice(request: Request):
        data, hint = await _read_audio(request)
        out = ag.handle_audio(data, mock_transcript=hint)
        headers = {
            "X-Transcript": quote(out["transcript"]),
            "X-Reply": quote(out["reply"]),
            "X-Lang": out["lang"],
            "X-Actions": str(len(out["actions"])),
        }
        return Response(content=out["_audio"], media_type="audio/wav", headers=headers)

    @app.post("/voice/json")
    async def voice_json(request: Request):
        data, hint = await _read_audio(request)
        return _json(ag.handle_audio(data, mock_transcript=hint))

    @app.post("/text")
    def text(body: TextIn):
        if not body.text.strip():
            raise HTTPException(400, "text is empty")
        return _json(ag.handle_text(body.text.strip(), lang_hint=body.lang or "", speak=body.speak))

    @app.get("/ledger")
    def ledger_view():
        return led.snapshot()

    @app.get("/summary")
    def summary(day: str | None = None):
        return led.daily_summary(day)

    @app.get("/reminders")
    def reminders(lang: str = "hi"):
        return led.reminders(lang)

    @app.get("/samples")
    def samples():
        return load_samples()

    @app.post("/reset")
    def reset():
        led.reset(seed=True)
        return {"ok": True}

    return app


def _unquote(s: str) -> str:
    from urllib.parse import unquote
    return unquote(s)


def _json(out: dict) -> JSONResponse:
    audio = out.pop("_audio", None)
    out["audio_b64"] = base64.b64encode(audio).decode() if audio else None
    return JSONResponse(out)


app = create_app() if os.environ.get("KIRANA_NO_AUTOAPP") != "1" else None
