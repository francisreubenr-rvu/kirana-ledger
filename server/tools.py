"""Tool definitions (OpenAI-compatible function schemas) and a dispatcher onto the Ledger."""
from __future__ import annotations

import json
from typing import Any

from .ledger import AmbiguousCustomer, Ledger, LedgerError, UnknownCustomer

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "add_credit",
            "description": "Customer took goods on credit (udhaar / ಸಾಲ / கடன்). Adds to what they owe.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "description": "Customer name in Latin script, Title Case, e.g. 'Ramesh'"},
                    "amount": {"type": "number", "description": "Amount in rupees"},
                    "note": {"type": "string", "description": "Optional: what was taken"},
                },
                "required": ["customer", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_payment",
            "description": "Customer paid back money they owed (jama / wapas / lautaye / kottru / ಕೊಟ್ಟರು / ವಾಪಸ್ ಕೊಟ್ಟ / கொடுத்தார்).",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "description": "Customer name in Latin script, Title Case"},
                    "amount": {"type": "number", "description": "Amount in rupees"},
                },
                "required": ["customer", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_sale",
            "description": "Goods were sold (bik gaye / becha / ಮಾರಾಟ / விற்றது). Decrements stock. "
                           "Pass customer only if the sale was on credit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item": {"type": "string", "description": "Item name incl. brand and size, e.g. 'Aashirvaad Atta 5kg'"},
                    "qty": {"type": "number", "description": "Quantity sold"},
                    "amount": {"type": "number", "description": "Total rupees, only if the owner said a price"},
                    "customer": {"type": "string", "description": "Only for a credit sale"},
                },
                "required": ["item", "qty"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_stock",
            "description": "New stock arrived (maal aaya / ಬಂದಿದೆ / வந்தது) — positive qty; or remove damaged/expired stock — negative qty.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "qty": {"type": "number", "description": "Positive to add, negative to remove"},
                    "price": {"type": "number", "description": "Optional selling price per unit in rupees"},
                },
                "required": ["item", "qty"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_balance",
            "description": "How much does a customer owe? (kitna baaki / ಎಷ್ಟು ಬಾಕಿ / எவ்வளவு பாக்கி)",
            "parameters": {
                "type": "object",
                "properties": {"customer": {"type": "string"}},
                "required": ["customer"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "daily_summary",
            "description": "Today's totals: sales, credit given, payments, outstanding dues, low stock (aaj ka hisaab / ಇಂದಿನ ಲೆಕ್ಕ / இன்றைய கணக்கு).",
            "parameters": {
                "type": "object",
                "properties": {"day": {"type": "string", "description": "YYYY-MM-DD; omit for today"}},
            },
        },
    },
]

TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


def run_tool(ledger: Ledger, name: str, args: dict[str, Any] | str) -> dict:
    """Execute one tool call; never raises — errors come back as {'ok': False, ...} for the agent to voice."""
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError as e:
            return {"ok": False, "action": name, "error": f"bad arguments JSON: {e}"}
    if name not in TOOL_NAMES:
        return {"ok": False, "action": name, "error": f"unknown tool {name}"}
    allowed = TOOLS[[t["function"]["name"] for t in TOOLS].index(name)]["function"]["parameters"].get("properties", {})
    clean = {k: v for k, v in (args or {}).items() if k in allowed and v is not None and v != ""}
    try:
        return getattr(ledger, name)(**clean)
    except AmbiguousCustomer as e:
        return {"ok": False, "action": name, "args": clean, "error": str(e), "customer": e.name, "ambiguous": e.candidates}
    except UnknownCustomer as e:
        return {"ok": False, "action": name, "args": clean, "error": str(e), "customer": e.name, "unknown_customer": True}
    except LedgerError as e:
        return {"ok": False, "action": name, "args": clean, "error": str(e)}
    except TypeError as e:  # missing required arg
        return {"ok": False, "action": name, "args": clean, "error": f"bad arguments: {e}"}
