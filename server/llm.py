"""Swappable "planner" that turns a transcript into tool calls.

- ChatToolPlanner: any OpenAI-compatible /chat/completions endpoint with `tools`.
  * Sarvam: POST https://api.sarvam.ai/v1/chat/completions, header api-subscription-key,
    model sarvam-105b (or sarvam-105b-conversations). V2 (/v2/chat/completions) also works via LLM_URL.
  * Anything else OpenAI-compatible (OpenRouter, Groq, OpenAI, a local vLLM/Ollama): LLM_PROVIDER=openai,
    LLM_URL=<.../chat/completions>, LLM_MODEL=<id>, OPENAI_API_KEY=<key> (sent as Bearer).
- RulePlanner: offline rule-based parser (mock mode / fallback).

All planners return the same Plan, so the agent does not care which one ran.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Protocol

import httpx

from . import rule_parser
from .config import Settings
from .ledger import IST
from .tools import TOOLS

log = logging.getLogger("kirana.llm")

SYSTEM_PROMPT = """You are the bookkeeper inside a voice ledger on an Indian kirana shop counter.
The shop owner speaks Hinglish, Hindi, Kannada or Tamil (often code-mixed). Each message is one
speech transcript. Turn it into ledger tool calls.

Rules:
- Call one tool per distinct action; a single sentence can contain several (e.g. a credit AND a sale).
- "X ka 240 udhaar" / "X ge 240 saala" / "X ku 240 kadan" = add_credit(X, 240).
- "X ne 100 diye / jama" / "X 100 kottru / kottidaare / ಕೊಟ್ಟರು" / "X 100 kuduthaar / koduthaar" / "X ne 100 lautaye"
  = record_payment(X, 100). Amounts may use Indian grouping: "1,20,000" = 120000.
- But "gave" TO a customer is credit: "Xge 60 saala kottru" / "X ko 60 diye" / "Xukku 60 kadan kuduthaar" = add_credit(X, 60).
- "2 Aashirvaad 5kg bik gaye" = record_sale(item="Aashirvaad Atta 5kg", qty=2). Sizes like 5kg are part of the item, not quantities.
- If goods were given to a named customer on credit, use record_sale with customer set (do NOT also call add_credit).
- "20 Maggi aaye / maal aaya" = update_stock(item, +20). Damaged/expired = negative qty.
- "X ka kitna baaki" = query_balance(X). "Aaj ka hisaab" = daily_summary().
- Customer names: Latin script, Title Case (रमेश -> Ramesh). Amounts are rupees as numbers.
- Prefer names from the known lists below when the transcript is close to one (e.g. "Sures" = Suresh). If it is
  close to two of them, call no tool and ask which one.
- Never invent amounts. If something essential is missing or unclear, call no tool and reply with ONE short
  question in the owner's language.
Known customers: {customers}
Known items: {items}
Today (IST): {today}"""


@dataclass
class Plan:
    calls: list[dict] = field(default_factory=list)  # [{"tool", "args"}]
    say: str | None = None  # model text when it asked a question instead of acting
    lang: str = ""
    provider: str = ""
    raw: dict | None = None


class Planner(Protocol):
    name: str

    def plan(self, transcript: str, customers: list[str], items: list[str]) -> Plan: ...


class RulePlanner:
    name = "rules"

    def __init__(self, item_lookup: Callable[[str], str | None] | None = None):
        self.item_lookup = item_lookup

    def plan(self, transcript: str, customers: list[str], items: list[str]) -> Plan:
        r = rule_parser.parse(transcript, customers, self.item_lookup)
        return Plan(calls=r.calls, lang=r.lang, provider=self.name)


class ChatToolPlanner:
    def __init__(self, url: str, model: str, headers: dict[str, str], name: str,
                 reasoning_effort: str | None = None, client: httpx.Client | None = None):
        self.url, self.model, self.headers, self.name = url, model, headers, name
        self.reasoning_effort = reasoning_effort
        self.client = client or httpx.Client(timeout=45)

    def plan(self, transcript: str, customers: list[str], items: list[str]) -> Plan:
        sys = SYSTEM_PROMPT.format(
            customers=", ".join(customers) or "(none yet)",
            items=", ".join(items) or "(none yet)",
            today=datetime.now(IST).date().isoformat(),
        )
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": sys}, {"role": "user", "content": transcript}],
            "tools": TOOLS,
            "tool_choice": "auto",
            "temperature": 0.1,
            "max_tokens": 1024,
        }
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        r = self.client.post(self.url, headers={**self.headers, "Content-Type": "application/json"}, json=body)
        r.raise_for_status()
        j = r.json()
        msg = (j.get("choices") or [{}])[0].get("message") or {}
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments") or "{}"
            try:
                args = json.loads(args) if isinstance(args, str) else args
            except json.JSONDecodeError:
                log.warning("unparseable tool args: %r", args)
                continue
            calls.append({"tool": fn.get("name"), "args": args, "id": tc.get("id")})
        return Plan(calls=calls, say=(msg.get("content") or None) if not calls else None, provider=self.name, raw=j)


def make_planner(s: Settings, item_lookup=None, client: httpx.Client | None = None) -> Planner:
    p = s.resolved_llm
    if p == "sarvam":
        url = s.llm_url or f"{s.sarvam_base}/v1/chat/completions"
        return ChatToolPlanner(url, s.llm_model, {"api-subscription-key": s.sarvam_api_key or ""}, "sarvam",
                               s.llm_reasoning_effort, client)
    if p == "openai":
        if not s.llm_url:
            raise ValueError("LLM_PROVIDER=openai needs LLM_URL (full .../chat/completions URL)")
        return ChatToolPlanner(s.llm_url, s.llm_model, {"Authorization": f"Bearer {s.openai_api_key or ''}"}, "openai",
                               None, client)
    return RulePlanner(item_lookup)
