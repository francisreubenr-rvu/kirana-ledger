# Kirana Voice Ledger: pitch

**One line:** a ₹1,000 push-to-talk box that lets a kirana owner keep the udhaar book, stock and sales by speaking
Hinglish, Kannada, Tamil or Hindi, and answers in the same language.

## Problem

- Neighbourhood shops run on **credit (udhaar)**. It lives in a paper khata or the owner's memory. Entries get
  missed during a rush, totals are added by hand, and asking a regular to pay up is awkward. Money leaks quietly.
- Stock is tracked by eye. Reorders happen when a customer asks for something that has already run out.
- Existing apps (digital khata, billing/POS) assume the owner will stop, unlock a phone, find the customer, and type
  amounts. At a busy counter, with one hand on the scale and the other on the change, that step gets skipped.
  The app is only as good as the entries that never got made.

## User

**Primary:** the owner/operator of a small kirana or general store. Speaks one or two Indian languages and mixes
English words naturally ("udhaar", "5kg", "Maggi", "total"). Comfortable with WhatsApp, not with forms. Often
not comfortable typing in English.
**Secondary:** the family member or helper who covers the counter, and the customer, who gets a polite, accurate
reminder instead of an awkward conversation.

## Why voice

- **Zero-step capture.** Pressing a button while talking is the only interaction cheap enough to happen *during* the sale.
  The box's job is to make sure the entry actually gets made.
- **Language is the interface.** The owner already says "Ramesh ka 240 udhaar" out loud. We record that sentence
  instead of translating it into taps. Code-mixed speech is the default, not an edge case. That is why we use
  Saaras v4 in codemix mode, with the shop's own customer and product names passed as keyterms.
- **Ears-free confirmation.** The box reads back what it wrote, with the running balance, in the owner's language.
  Trust comes from hearing "कुल बाकी 240 रुपये" without having to look at a screen.
- **Literacy-neutral.** It works the same for an owner who can't, or won't, type.

## Differentiators

1. **Dedicated counter hardware, not another app.** One physical button, always on, no unlock and no app switching.
   About ₹1,000 BOM, with an ESP32-S3, an I2S mic and an I2S amp.
2. **Multi-action, code-mixed sentences.** One utterance can carry a credit, a sale and a stock change
   ("Fatima ko 3 Parle-G udhaar pe diye" = sale + stock − 3 + udhaar + ₹30). The LLM plans tool calls over a
   typed ledger. It never writes free text into the books.
3. **Deterministic writes, deterministic read-back.** The LLM only chooses tools and arguments. Amounts live in
   SQLite as integer paise, and confirmations come from fixed templates, so what the owner hears is exactly what
   was recorded.
4. **Degrades gracefully.** If the LLM is down or slow, an offline rule parser takes over for common phrasings, and
   the whole pipeline has a mock mode for demos and development.
5. **Closes the loop on money.** Closing-time WhatsApp summary plus one-tap, polite reminders per debtor in the
   owner's chosen language. That is the moment where a ledger turns into recovered cash.
6. **Provider-swappable.** STT, planner and TTS each sit behind one small interface. Sarvam is the default, and any
   OpenAI-compatible LLM can drop in with one environment variable.

## What exists in v0

FastAPI server (device `/voice` WAV in/out, `/text`, ledger/summary/reminder endpoints), web push-to-talk demo,
ESP32-S3 firmware (not yet flashed), six ledger tools on SQLite, mock mode, 88 passing tests, including a
24-utterance Hinglish/Hindi/Kannada/Tamil/English set with expected tool calls.

## Adapting to the 27 Nov problem statement

The core is a domain-agnostic loop: **speech → transcript → LLM picks typed tools → tools change a store →
templated spoken confirmation → shareable text output**. Retargeting means swapping the domain layer and keeping
the voice/hardware/fallback plumbing.

| Layer | File | What to change |
|---|---|---|
| Data model + actions | `server/ledger.py` | New tables and methods (e.g. appointments, orders, inventory batches, complaints) |
| Tool schemas | `server/tools.py` | One JSON schema per method. The dispatcher already maps names to methods and returns errors as data |
| Planner prompt | `server/llm.py` `SYSTEM_PROMPT` | Domain vocabulary and 5–10 example phrasings → tool calls |
| Read-back | `server/messages.py` | One template per tool per language |
| Offline fallback | `server/rule_parser.py` | Keyword sets for the new verbs (optional; the LLM path works without it) |
| Outputs | `daily_summary` / `reminders` | Swap for whatever the PS wants delivered: WhatsApp text, a PDF, an SMS draft |
| Eval set | `samples/utterances.json` | 20–30 utterances with expected tool calls; `tests/test_utterances.py` runs them automatically |

**48-hour playbook for Round 2 (27–29 Nov):**
1. Hour 0–2: read the PS and pick the user and the one action they repeat most. Write 25 sample utterances in at
   least two languages, with expected tool calls, into `samples/`.
2. Hour 2–10: replace the ledger and tools. Keep `run_tool`'s error-as-data contract, so the voice reply can explain failures.
3. Hour 10–16: update the prompt and templates, then get the sample set green with the LLM (and rules if time allows).
4. Hour 16–30: real-voice testing with a key: tune keyterms, speaker voices and `reasoning_effort` for latency.
5. Hour 30–44: demo polish on the web page, the box, and the 2-minute script.
6. Leave a buffer for submission. Record a backup demo video in mock mode.

If the PS is not a small-business one (civic, health, education, access), the same box still fits as
"a one-button, any-language front desk". Examples: a ration-shop queue logger, an ASHA worker's visit log, or a
classroom attendance and homework tracker. Only the domain layer changes.

## Risks and what we'd do next

- **Wrong-name writes** → confirm-before-commit for new names, and an *undo last entry* voice command.
- **Noisy counters** → a directional mic or foam cover, push-to-talk only (no wake word), and a short re-ask on low confidence.
- **Latency** → `sarvam-105b-conversations` or lower `reasoning_effort`, streaming TTS, and starting playback early.
- **Trust and privacy** → data stays on the shop's own server or phone. Reminders are drafted, never auto-sent.
