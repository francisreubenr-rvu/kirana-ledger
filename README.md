# Kirana Voice Ledger (v0)

A push-to-talk box for the kirana counter. The owner holds a button and says
*"Ramesh ka 240 udhaar, 2 Aashirvaad 5kg bik gaye"*. The box updates the credit book (udhaar), stock and sales,
says a confirmation back in the owner's language, and at closing time produces a WhatsApp-ready day summary
plus one-tap credit-reminder messages.

Built for **India Runs on Voice** (Scaler × Wispr Flow), Small Business track. v0 is a reusable voice → tools
pipeline that can be pointed at the Round 2 problem statement (released 27 Nov 2026); see `PITCH.md` for how.

```
                 ┌──────────────────────── counter box (ESP32-S3, ≈₹1,000) ────────────────────────┐
  owner speaks → │ INMP441 mic ─I2S→ ESP32-S3 ── record while button held (16 kHz PCM16 WAV) ──┐  │
                 │ MAX98357A amp ←I2S─ ESP32-S3 ←───────────────── reply WAV ─────────────────┐ │  │
                 └──────────────────────────────────────────────────────────────────────────── │ ─│ ─┘
                                                                          Wi-Fi, HTTP POST /voice│ │
┌──────────────────────────────── server (FastAPI, laptop or any small VM) ─────────────────────┐│ │
│                                                                                                ▼ │
│  1 STT     Sarvam Saaras v4, mode=codemix, keyterms = known customers + items  ─→ transcript     │
│  2 Plan    LLM with tool calls (Sarvam 105B by default; any OpenAI-compatible model; or offline │
│            rules)  ─→ [add_credit(Ramesh, 240), record_sale(Aashirvaad Atta 5kg, 2)]            │
│  3 Act     tools on SQLite: add_credit · record_payment · record_sale · update_stock ·          │
│            query_balance · daily_summary                                                        │
│  4 Confirm deterministic template in hi / kn / ta / en (owner hears exactly what was written)  │
│  5 TTS     Sarvam Bulbul v4-flash, 16 kHz WAV  ──────────────────────────────────────────────────┘
│                                                                                                 │
│  Web demo page (/)   browser mic → /voice/json, shows transcript, parsed actions, ledger tables │
│  /summary  WhatsApp day summary      /reminders  wa.me links with a polite udhaar reminder      │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
   Any stage can be swapped to its offline mock: canned STT · rule parser · chime TTS.
```

## Quick start (offline, no key)

```bash
cd kirana-ledger
python3 -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q                                          # 85 tests
./run.sh                                           # or: python -m uvicorn server.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000. With no `SARVAM_API_KEY` everything runs in **mock mode**:
- STT returns the utterance picked in the page's dropdown (or the `X-Mock-Transcript` header / `mock_transcript`
  form field), otherwise it cycles through `samples/utterances.json`.
- The LLM is replaced by the rule parser in `server/rule_parser.py` (Hinglish, Latin-script Kannada/Tamil,
  common Devanagari/Kannada/Tamil keywords).
- TTS returns a short chime WAV, so the device/web audio path is still exercised.

The terminal walkthrough of the demo (useful as a backup if the venue Wi-Fi dies):

```bash
python scripts/demo.py http://127.0.0.1:8000
```

## With Sarvam (real voice)

```bash
cp .env.example .env      # set SARVAM_API_KEY=sk_...   (never commit .env; it's git-ignored)
./run.sh
```

`/health` shows what's live, e.g. `{"stt":"sarvam","llm":"sarvam","tts":"sarvam"}`.

API details used (checked against docs.sarvam.ai on 18 Nov 2026):

| Stage | Endpoint | Model / key params |
|---|---|---|
| STT | `POST https://api.sarvam.ai/speech-to-text` (multipart) | `model=saaras:v4`, `mode=codemix`, `language_code=unknown` (auto-detect), `keyterms=[...]` (v4 only, ≤50) |
| LLM | `POST https://api.sarvam.ai/v1/chat/completions` | `model=sarvam-105b`, OpenAI-style `tools` + `tool_choice:"auto"`, `reasoning_effort=low` |
| TTS | `POST https://api.sarvam.ai/text-to-speech` | `model=bulbul:v4-flash`, `speaker` per language, `speech_sample_rate=16000`, response `audios[0]` base64 WAV |

Auth on all three: header `api-subscription-key: <SARVAM_API_KEY>`.

Notes from the docs:
- The STT page lists `mode` as "only applicable when using saaras:v3" in one place, but describes v4 as supporting
  all modes including codemix. The client sends `mode=codemix` and, if the API rejects it with 400/422, retries once
  without it.
- "Bulbul V4" is `bulbul:v4-flash`. Its voices are persona ids (`shubh_hi_customer`, `chaitra_kn_conversation`,
  `gokul_ta_narration`, `simran_en_customer` are the defaults here). Override with `TTS_SPEAKER_HI/KN/TA/EN`.
- Sarvam also has `/v2/chat/completions` (same shape, more models). Point `LLM_URL` at it to use it.

### Swapping the LLM

```bash
LLM_PROVIDER=sarvam   LLM_MODEL=sarvam-105b-conversations                 # lower-latency Sarvam variant
LLM_PROVIDER=openai   LLM_URL=https://openrouter.ai/api/v1/chat/completions LLM_MODEL=<id> OPENAI_API_KEY=<key>
LLM_PROVIDER=rules                                                          # offline parser even with a key
```

If the LLM call fails (timeout, 5xx, quota), the agent falls back to the rule parser for that utterance and
reports it under `warnings`, so the counter never goes silent.

## HTTP API

| Method | Path | In | Out |
|---|---|---|---|
| POST | `/voice` | raw WAV body (`Content-Type: audio/wav`) or multipart `file` | `audio/wav` + headers `X-Transcript`, `X-Reply` (URL-encoded), `X-Lang`, `X-Actions` |
| POST | `/voice/json` | same | JSON: transcript, lang, actions (tool, args, result), reply, `audio_b64`, timings |
| POST | `/text` | `{"text": "...", "lang": "kn"?, "speak": true}` | same JSON as above |
| GET | `/ledger` | | customers + balances, items + stock, recent sales and credit entries |
| GET | `/summary?day=YYYY-MM-DD` | | day totals + `whatsapp_text` |
| GET | `/reminders?lang=hi\|kn\|ta\|en` | | one reminder per customer who owes, with a `wa.me` share link |
| GET | `/health`, `/samples` · POST `/reset` | | modes · sample utterances · wipe and re-seed demo data |

v0 has no auth. Run it on a trusted LAN only.

## Hardware

### BOM (rough INR, Nov 2026, incl. GST, before shipping)

| Part | Price | Source checked |
|---|---|---|
| ESP32-S3 DevKitC-1 **N16R8** (8 MB PSRAM) | ₹620 | Robosap listing ₹619.50; other shops ₹699–839 |
| INMP441 I2S MEMS mic module | ₹150–180 | techiesms ₹150, Robokits ₹182 |
| MAX98357A I2S 3 W class-D amp | ₹134 | Hubtronics ₹134 |
| 3 W 4 Ω speaker (40–50 mm) | ~₹50 | estimate |
| Tactile push button (or ₹40 arcade button) | ₹10–40 | estimate |
| Jumper wires / perfboard | ~₹30 | estimate |
| **Total** | **≈₹995–1,055** | |

Getting it reliably under ₹1,000: take the cheaper mic listing and a tactile button (≈₹995), or use a
no-PSRAM ESP32-S3 board. Without PSRAM the firmware caps recording at ~4 s (it detects this at boot).
Power from any USB phone charger. A cardboard or 3D-printed box is enough for the demo.

### Wiring (defaults in `firmware/kirana_box/config.h.example`)

```
INMP441   VDD→3V3  GND→GND  L/R→GND  SCK→GPIO4   WS→GPIO5   SD→GPIO6
MAX98357A VIN→5V   GND→GND           BCLK→GPIO15 LRC→GPIO16 DIN→GPIO7    (+/− → speaker)
Button    GPIO1 ↔ GND   (internal pull-up; pressed = LOW)
```

### Flashing

1. Arduino IDE 2.x → Boards Manager → **esp32 by Espressif ≥ 3.0** (the firmware uses `ESP_I2S.h`).
2. Board: *ESP32S3 Dev Module*; **PSRAM: OPI PSRAM**; USB CDC On Boot: Enabled.
3. `cp firmware/kirana_box/config.h.example firmware/kirana_box/config.h`, then set Wi-Fi, `SERVER_URL`
   (`http://<laptop-LAN-IP>:8000/voice`) and pins.
4. Upload, open Serial Monitor at 115200, hold the button and speak. LED colours: blue idle · red listening ·
   amber thinking · green speaking · purple error (plus a low beep).

Tuning: if the server hears clipping or near-silence, change `MIC_SHIFT` (12 = louder, 16 = quieter).

## Repo layout

```
server/        FastAPI app (main), pipeline (agent), ledger (SQLite), tools (schemas + dispatch),
               llm (swappable planners), speech (Sarvam STT/TTS + mocks), rule_parser, messages, config, audio
web/           index.html: push-to-talk demo page (records → 16 kHz WAV in-browser → /voice/json)
firmware/      kirana_box/kirana_box.ino + config.h.example
samples/       utterances.json: Hinglish / Hindi / Kannada / Tamil / English utterances + expected tool calls
tests/         ledger, utterance set (parser + full agent), API (mock mode), provider request shapes (fake HTTP)
scripts/       demo.py: the demo sequence over HTTP
```

## 2-minute demo script

Set up beforehand: server running, box on Wi-Fi, web page on the projector showing the ledger, `POST /reset`.

| Time | Do / say | Audience sees / hears |
|---|---|---|
| 0:00–0:15 | "Ramesh-bhai runs a kirana. His credit book is a paper khata, and his hands are always busy. Meet the box." Hold up the box. | |
| 0:15–0:35 | Hold button: **"Ramesh ka 240 udhaar, 2 Aashirvaad 5kg bik gaye."** | Box: *"Ramesh के खाते में 240 रुपये उधार लिखा… 2 Aashirvaad Atta 5kg की बिक्री दर्ज, 570 रुपये।"* Page: two parsed actions, Ramesh ₹240, atta stock 12→10. |
| 0:35–0:50 | Switch language: **"Lakshmi 300 kottru."** | Kannada reply; Lakshmi's ₹1,200 opening due drops to ₹900. |
| 0:50–1:05 | **"Murugan ku 200 kadan."** | Tamil reply. "Same box, the owner's own language, no menu." |
| 1:05–1:20 | **"Fatima ko 3 Parle-G udhaar pe diye."** | One sentence = a credit sale: stock down and udhaar up together. |
| 1:20–1:35 | **"Suresh ka kitna baaki hai?"** | *"Suresh का कुल बाकी 350 रुपये है।"* (lookup without touching a phone) |
| 1:35–1:55 | **"Aaj ka hisaab."** Click *Share summary on WhatsApp*, then one *Remind* link. | Spoken day total; WhatsApp opens with the summary and a polite pre-filled reminder. |
| 1:55–2:00 | "About ₹1,000 of hardware, four languages, and if the AI is down it falls back to offline rules so the counter keeps working." | |

Backup if the network fails: `KIRANA_MOCK=1 ./run.sh` and run the same lines through the page's mock dropdown or
`scripts/demo.py`. The parse → ledger → reply path is identical, only speech is canned.

## Known limits (v0)

- The firmware has **not been compiled or run on hardware** yet. It targets the arduino-esp32 3.x `ESP_I2S` API.
- Real Sarvam calls are untested without a key. Request shapes are pinned by tests against a fake HTTP transport.
- Customer names are matched by spelling plus a crude phonetic key (Laxmi≈Lakshmi). Two different Rameshes need
  a surname or a phone number. Names in native script (रमेश) are stored as heard by the rule parser; the LLM path
  is told to write them in Latin script.
- The Kannada and Tamil confirmation/reminder strings need a native-speaker check.
- No undo yet ("galti, cancel karo"). It's the obvious next tool.
- Single shop, single device, no auth. Use on a LAN only.
