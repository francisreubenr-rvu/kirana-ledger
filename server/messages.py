"""Spoken confirmations, per language. Deterministic templates keep latency low and
make sure the owner hears exactly what was written to the ledger.

NOTE: Kannada and Tamil strings were written by a non-native author; have a native
speaker check them before a public demo.
"""
from __future__ import annotations

T = {
    "add_credit": {
        "hi": "{customer} के खाते में {amount} रुपये उधार लिखा। कुल बाकी {balance} रुपये।",
        "kn": "{customer} ಅವರ ಖಾತೆಗೆ {amount} ರೂಪಾಯಿ ಸಾಲ ಬರೆದಿದೆ. ಒಟ್ಟು ಬಾಕಿ {balance} ರೂಪಾಯಿ.",
        "ta": "{customer} கணக்கில் {amount} ரூபாய் கடன் எழுதப்பட்டது. மொத்த பாக்கி {balance} ரூபாய்.",
        "en": "Wrote {amount} rupees credit for {customer}. Total due {balance} rupees.",
    },
    "record_payment": {
        "hi": "{customer} से {amount} रुपये मिले। अब बाकी {balance} रुपये।",
        "kn": "{customer} ಅವರಿಂದ {amount} ರೂಪಾಯಿ ಬಂದಿದೆ. ಈಗ ಬಾಕಿ {balance} ರೂಪಾಯಿ.",
        "ta": "{customer} இடமிருந்து {amount} ரூபாய் வந்தது. இப்போது பாக்கி {balance} ரூபாய்.",
        "en": "Received {amount} rupees from {customer}. Now due {balance} rupees.",
    },
    "payment_advance": {
        "hi": "{customer} से {amount} रुपये मिले। उनका {advance} रुपये एडवांस जमा है।",
        "kn": "{customer} ಅವರಿಂದ {amount} ರೂಪಾಯಿ ಬಂದಿದೆ. ಅವರ {advance} ರೂಪಾಯಿ ಮುಂಗಡ ಇದೆ.",
        "ta": "{customer} இடமிருந்து {amount} ரூபாய் வந்தது. அவர்களுக்கு {advance} ரூபாய் முன்பணம் உள்ளது.",
        "en": "Received {amount} rupees from {customer}. They now have {advance} rupees in advance.",
    },
    "record_sale": {
        "hi": "{qty} {item} की बिक्री दर्ज, {amount} रुपये।",
        "kn": "{qty} {item} ಮಾರಾಟ ದಾಖಲಾಗಿದೆ, {amount} ರೂಪಾಯಿ.",
        "ta": "{qty} {item} விற்பனை பதிவு, {amount} ரூபாய்.",
        "en": "Sale recorded: {qty} {item}, {amount} rupees.",
    },
    "record_sale_noprice": {
        "hi": "{qty} {item} की बिक्री दर्ज।",
        "kn": "{qty} {item} ಮಾರಾಟ ದಾಖಲಾಗಿದೆ.",
        "ta": "{qty} {item} விற்பனை பதிவு.",
        "en": "Sale recorded: {qty} {item}.",
    },
    "credit_sale": {
        "hi": "{customer} को {qty} {item} उधार, {amount} रुपये। कुल बाकी {balance} रुपये।",
        "kn": "{customer} ಅವರಿಗೆ {qty} {item} ಸಾಲ, {amount} ರೂಪಾಯಿ. ಒಟ್ಟು ಬಾಕಿ {balance} ರೂಪಾಯಿ.",
        "ta": "{customer} க்கு {qty} {item} கடன், {amount} ரூபாய். மொத்த பாக்கி {balance} ரூபாய்.",
        "en": "{qty} {item} on credit to {customer}, {amount} rupees. Total due {balance} rupees.",
    },
    "update_stock": {
        "hi": "{item} का स्टॉक अब {stock}।",
        "kn": "{item} ಸ್ಟಾಕ್ ಈಗ {stock}.",
        "ta": "{item} ஸ்டாக் இப்போது {stock}.",
        "en": "{item} stock is now {stock}.",
    },
    "low_stock": {
        "hi": "ध्यान दें, {item} सिर्फ {stock} बचे हैं।",
        "kn": "ಗಮನಿಸಿ, {item} ಕೇವಲ {stock} ಉಳಿದಿದೆ.",
        "ta": "கவனிக்கவும், {item} {stock} மட்டுமே உள்ளது.",
        "en": "Heads up, only {stock} {item} left.",
    },
    "query_balance": {
        "hi": "{customer} का कुल बाकी {balance} रुपये है।",
        "kn": "{customer} ಅವರ ಒಟ್ಟು ಬಾಕಿ {balance} ರೂಪಾಯಿ.",
        "ta": "{customer} மொத்த பாக்கி {balance} ரூபாய்.",
        "en": "{customer} owes {balance} rupees.",
    },
    "query_unknown": {
        "hi": "{customer} नाम का कोई खाता नहीं मिला।",
        "kn": "{customer} ಹೆಸರಿನ ಖಾತೆ ಸಿಗಲಿಲ್ಲ.",
        "ta": "{customer} பெயரில் கணக்கு இல்லை.",
        "en": "No account found for {customer}.",
    },
    "daily_summary": {
        "hi": "आज {sales_count} बिक्री, कुल {sales_total} रुपये। उधार दिया {credit_given}, वसूली {payments_received}। कुल बाकी {outstanding_total} रुपये।",
        "kn": "ಇಂದು {sales_count} ಮಾರಾಟ, ಒಟ್ಟು {sales_total} ರೂಪಾಯಿ. ಸಾಲ {credit_given}, ವಸೂಲಿ {payments_received}. ಒಟ್ಟು ಬಾಕಿ {outstanding_total} ರೂಪಾಯಿ.",
        "ta": "இன்று {sales_count} விற்பனை, மொத்தம் {sales_total} ரூபாய். கடன் {credit_given}, வசூல் {payments_received}. மொத்த பாக்கி {outstanding_total} ரூபாய்.",
        "en": "Today {sales_count} sales, {sales_total} rupees. Credit given {credit_given}, collected {payments_received}. Total outstanding {outstanding_total} rupees.",
    },
    "error": {
        "hi": "यह दर्ज नहीं हो पाया: {error}",
        "kn": "ಇದನ್ನು ದಾಖಲಿಸಲು ಆಗಲಿಲ್ಲ: {error}",
        "ta": "இதை பதிவு செய்ய முடியவில்லை: {error}",
        "en": "Could not record that: {error}",
    },
    "not_understood": {
        "hi": "माफ़ कीजिए, समझ नहीं आया। फिर से बोलिए।",
        "kn": "ಕ್ಷಮಿಸಿ, ಅರ್ಥವಾಗಲಿಲ್ಲ. ಮತ್ತೊಮ್ಮೆ ಹೇಳಿ.",
        "ta": "மன்னிக்கவும், புரியவில்லை. மீண்டும் சொல்லுங்கள்.",
        "en": "Sorry, I didn't catch that. Please say it again.",
    },
}


def _n(x) -> str:
    if x is None:
        return "?"
    x = float(x)
    # Bulbul guidance: use commas for numbers over 4 digits.
    return f"{x:,.0f}" if x == int(x) else f"{x:,.2f}"


def confirm(result: dict, lang: str) -> str:
    lang = lang if lang in ("hi", "kn", "ta", "en") else "hi"
    if not result.get("ok"):
        return T["error"][lang].format(error=result.get("error", "?"))
    a = result["action"]
    v = {k: (_n(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else val) for k, val in result.items()}
    if a == "record_sale":
        key = "credit_sale" if result.get("customer") else ("record_sale" if result.get("amount") is not None else "record_sale_noprice")
        text = T[key][lang].format(**v)
        if result.get("low_stock") and result.get("stock_left") is not None:
            text += " " + T["low_stock"][lang].format(item=result["item"], stock=_n(result["stock_left"]))
        return text
    if a == "update_stock":
        text = T["update_stock"][lang].format(**v)
        if result.get("low_stock"):
            text += " " + T["low_stock"][lang].format(item=result["item"], stock=_n(result["stock"]))
        return text
    if a == "record_payment" and (result.get("balance") or 0) < 0:
        return T["payment_advance"][lang].format(**v, advance=_n(-result["balance"]))
    if a == "query_balance" and not result.get("known"):
        return T["query_unknown"][lang].format(**v)
    return T[a][lang].format(**v)


def not_understood(lang: str) -> str:
    return T["not_understood"].get(lang, T["not_understood"]["hi"])
