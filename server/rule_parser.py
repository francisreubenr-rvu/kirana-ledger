"""Rule-based parser used in mock/offline mode (and as a fallback if the LLM is down).

Turns a shop-owner utterance (Hinglish, Kannada/Tamil in Latin script, or simple
Devanagari / Kannada / Tamil keywords) into a list of tool calls. It is
deliberately simple and predictable: the LLM path handles anything fancier.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

# ---------------------------------------------------------------- vocabulary
NATIVE = {
    # Devanagari
    "उधार": "udhaar", "उधारी": "udhaar", "का": "ka", "के": "ke", "की": "ki", "को": "ko", "ने": "ne", "से": "se",
    "दिए": "diye", "दिये": "diye", "दिया": "diya", "जमा": "jama", "वापस": "wapas", "बिक": "bik", "गए": "gaye",
    "गये": "gaye", "गया": "gaya", "बिके": "bike", "बेचा": "becha", "बेचे": "beche", "आया": "aaya", "आए": "aaye",
    "आये": "aaye", "बाकी": "baaki", "बाक़ी": "baaki", "कितना": "kitna", "कितने": "kitne", "हिसाब": "hisaab",
    "आज": "aaj", "और": "aur", "रुपये": "rupaye", "रुपए": "rupaye", "है": "hai", "हैं": "hain", "स्टॉक": "stock",
    "माल": "maal", "लिख": "likh", "दो": "do", "लिखो": "likho", "लौटाए": "lautaye", "लौटाये": "lautaye",
    "लौटाया": "lautaya", "लौटा": "lauta", "दे": "de", "चुकाए": "chukaye", "चुकाया": "chukaya", "चुका": "chuka",
    # Kannada
    "ಸಾಲ": "saala", "ಕೊಟ್ಟರು": "kottru", "ಕೊಟ್ಟಿದ್ದಾರೆ": "kottidaare", "ಮಾರಾಟ": "maarata",
    "ಮಾರಾಟವಾಯಿತು": "maarata", "ಮಾರಿದೆ": "maaride", "ಬಾಕಿ": "baaki", "ಎಷ್ಟು": "eshtu", "ಬಂದಿದೆ": "bandide",
    "ಇಂದಿನ": "indina", "ಲೆಕ್ಕ": "lekka", "ಮತ್ತು": "mattu", "ರೂಪಾಯಿ": "rupaye", "ಅವರಿಗೆ": "avarige",
    "ಸ್ಟಾಕ್": "stock", "ಬರೆಯಿರಿ": "bareyiri", "ಕೊಟ್ರು": "kotru", "ಕೊಟ್ಟಿದೆ": "kottide", "ಕೊಟ್ಟ": "kotta",
    "ವಾಪಸ್": "vaapas", "ವಾಪಾಸ್": "vaapas", "ವಾಪಸು": "vaapas",
    # Tamil
    "கடன்": "kadan", "கொடுத்தார்": "kuduthaar", "கொடுத்தாங்க": "kuduthanga", "விற்றது": "vithuchu",
    "வித்துச்சு": "vithuchu", "பாக்கி": "baaki", "எவ்வளவு": "evvalavu", "வந்தது": "vandhuchu",
    "வந்துச்சு": "vandhuchu", "இன்றைய": "indraiya", "கணக்கு": "kanakku", "ரூபாய்": "rupaye", "மற்றும்": "and",
    "ஸ்டாக்": "stock", "கொடுத்தார்கள்": "kuduthaanga", "கொடுத்தாரு": "kuduthaar",
    "திருப்பி": "thiruppi",
}

SUMMARY_KW = {"hisaab", "hisab", "summary", "lekka", "kanakku", "report", "total"}
DAY_KW = {"aaj", "today", "indina", "indu", "ivattu", "indraiya", "inniki", "din", "day"}
QUERY_KW = {"kitna", "kitne", "baaki", "baki", "balance", "eshtu", "evvalavu", "owes", "owe", "due", "paakki"}
# "Give" verbs. Said after a bare name ("Suresh 50 kottru", "Murugan 50 kuduthaar", "Ramesh ne 50 diye") they mean the
# customer GAVE the shop money = a payment. But the same verbs also mean the shop gave goods/money TO someone: with a
# credit word ("saala kottru", "udhaar pe diye", "kadan kuduthaar") or a dative ("Rameshge", "Ramesh ko",
# "Muruganukku") they are treated as credit instead. See README "Payment phrases".
GIVE_KW = {"diye", "diya", "de", "kottru", "kottaru", "kotru", "kottidaare", "kottidare", "kottiddare", "kottide",
           "kotta", "kottu", "kuduthaar", "kuduthar", "kuduthaaru", "kuduthanga", "kuduthaanga", "koduthaar",
           "koduthar", "koduthaanga", "koduthanga", "kuduthutaar", "kuduthuttaar"}
# Return/repay verbs: a payment whatever else is in the sentence.
REPAY_KW = {"jama", "wapas", "vapas", "vaapas", "vaapasu", "paid", "pay", "chukaya", "chukaye", "chuka", "returned",
            "lautaye", "lautaya", "lauta", "lautaaye", "thiruppi", "tiruppi"}
PAYMENT_KW = GIVE_KW | REPAY_KW
DATIVE = {"ko", "ge", "ige", "avarige", "kku", "ku", "ukku"}
CREDIT_KW = {"udhaar", "udhar", "udhari", "udhaari", "credit", "likh", "likho", "khata", "khate", "saala", "saal",
             "kadan", "bareyiri", "bari"}
STOCK_KW = {"aaya", "aaye", "aayi", "stock", "maal", "restock", "bandide", "bandhide", "banthu", "bantu",
            "vandhuchu", "vanthuchu", "vandhathu", "arrived", "received", "came"}
STOCK_REMOVE_KW = {"hatao", "hata", "nikalo", "remove", "kharab", "expired", "expire", "damage", "damaged", "toota", "tooti", "phenk", "waste"}
SALE_KW = {"bik", "bika", "biki", "bike", "becha", "bechi", "beche", "bech", "sold", "sale", "maaratu", "maaride",
           "maarata", "maaraata", "vittachu", "vithuchu", "vitrom", "vithom", "vikkapattathu", "gaya", "gaye"}
SALE_STRONG = SALE_KW - {"gaya", "gaye"}

PARTICLES = {"ka", "ke", "ki", "ko", "ne", "se", "ge", "ige", "avarige", "avru", "avaru", "kku", "ku", "ukku",
             "oda", "udaya", "du", "dhu", "avanga", "ji", "anna", "bhai", "akka", "amma", "sir", "madam", "to", "for",
             "from", "has", "of"}
FILLER = {"hai", "hain", "ho", "hua", "hue", "kar", "karo", "kiya", "kiye", "do", "de", "diya", "the", "tha", "mein",
          "me", "aur", "and", "mattu", "matthu", "um", "a", "an", "is", "packet", "pack", "pcs", "piece", "pieces",
          "rupaye", "rupees", "rupay", "rs", "inr", "ne", "gaye", "gaya", "ge", "mein", "naya", "new", "add", "ide",
          "aagide", "aaytu", "achu", "irukku", "kodi", "kudu", "please", "bhi", "agaya", "liya", "li", "le", "liye",
          "now", "ab", "abhi", "bareyiri", "likh", "likho", "become", "today", "aaj"}

NUM_WORDS = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "chhah": 6, "saat": 7,
    "aath": 8, "nau": 9, "das": 10, "ondu": 1, "eradu": 2, "mooru": 3, "naalku": 4, "aidu": 5, "elu": 7, "entu": 8,
    "hattu": 10, "onnu": 1, "rendu": 2, "moonu": 3, "naalu": 4, "anju": 5, "ezhu": 7, "ettu": 8, "pathu": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

KN_HINTS = {"saala", "kottru", "kottaru", "kotru", "kottide", "kotta", "kottiddare", "vaapasu", "kottidaare", "maaratu", "maaride", "maarata", "eshtu", "bandide", "ge",
            "avarige", "indina", "lekka", "mattu", "matthu", "bareyiri", "ige", "avru"}
TA_HINTS = {"kadan", "kuduthaar", "kuduthanga", "kuduthaanga", "koduthaar", "koduthar", "koduthaanga", "thiruppi", "vittachu", "vithuchu", "evvalavu", "vandhuchu", "ukku", "kku",
            "kanakku", "indraiya", "paakki", "inniki"}
HI_HINTS = {"ka", "ke", "ki", "ko", "ne", "udhaar", "udhar", "diye", "jama", "lautaye", "lautaya", "bik", "gaye", "aaya", "kitna", "hisaab",
            "aaj", "hai"}
EN_HINTS = {"sold", "paid", "credit", "owes", "arrived", "received", "how", "much", "summary", "today"}

SIZE_RE = re.compile(r"^\d+(?:\.\d+)?(?:kg|g|gm|gms|gram|grams|ml|l|ltr|litre|liter|lt)$")
NUM_RE = re.compile(r"^\d+(?:\.\d+)?$")
TOKEN_RE = r"[^\s,;:!?।()\"']+"
CURRENCY_TOKENS = {"rs", "rs.", "₹", "rupaye", "rupees", "rupay", "inr", "rupaiye"}
# Digit grouping: Indian 1,200 / 1,20,000 / 12,34,567 and Western 1,200,000. Commas inside a number are removed
# before the utterance is split into clauses (a bare comma is still a clause break: "2 Maggi, 3 Parle-G").
GROUPED_NUM_RE = re.compile(r"(?<![\d,])(?:\d{1,3}(?:,\d{3}){2,}|\d{1,3}(?:,\d{2})*,\d{3})(?!,?\d)")


def normalize_numbers(text: str) -> str:
    return GROUPED_NUM_RE.sub(lambda m: m.group(0).replace(",", ""), text)


@dataclass
class ParseResult:
    lang: str
    calls: list[dict] = field(default_factory=list)  # [{"tool": name, "args": {...}}]


def detect_lang(text: str) -> str:
    """Return hi / kn / ta / en from script, then from Latin keyword hints."""
    text = normalize_numbers(text)
    if re.search(r"[\u0C80-\u0CFF]", text):
        return "kn"
    if re.search(r"[\u0B80-\u0BFF]", text):
        return "ta"
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"
    toks = set(_tokens(text))
    for t in list(toks):  # attached suffixes: "rameshge", "murugankku"
        if re.match(r"^[a-z]{3,}(ge|ige)$", t):
            toks.add("ge")
        if re.match(r"^[a-z]{3,}(kku|ukku)$", t):
            toks.add("kku")
    scores = {"kn": len(toks & KN_HINTS), "ta": len(toks & TA_HINTS), "hi": len(toks & HI_HINTS), "en": len(toks & EN_HINTS)}
    best = max(scores, key=lambda k: (scores[k], k == "hi"))
    return best if scores[best] > 0 else "hi"


def _tokens(text: str) -> list[str]:
    text = text.replace("₹", " ₹ ")
    raw = re.findall(TOKEN_RE, text)
    out = []
    for t in raw:
        t = t.strip(".-")
        if not t:
            continue
        t = NATIVE.get(t, t)
        out.append(t.lower())
    return out


def _split_clauses(text: str) -> list[str]:
    parts = re.split(r"[,;।\n]|\.(?!\d)|\s(?:aur|and|mattu|matthu|innu|phir|then|अउर|और|ಮತ್ತು|மற்றும்)\s", text, flags=re.I)
    return [p.strip() for p in parts if p and p.strip()]


def _numbers(toks: list[str]) -> tuple[list[tuple[int, float]], float | None]:
    """Standalone numbers (index, value) excluding sizes like 5kg; plus a currency-marked amount if any."""
    nums, amount = [], None
    for i, t in enumerate(toks):
        if t.startswith("₹") and NUM_RE.match(t[1:] or "x"):
            amount = float(t[1:])
            continue
        if NUM_RE.match(t):
            if i + 1 < len(toks) and toks[i + 1] in {"kg", "g", "gm", "ml", "l", "ltr", "litre", "liter", "gram"}:
                continue
            prev_cur = i > 0 and toks[i - 1] in CURRENCY_TOKENS
            next_cur = i + 1 < len(toks) and toks[i + 1] in CURRENCY_TOKENS
            if prev_cur or next_cur:
                amount = float(t)
            else:
                nums.append((i, float(t)))
    return nums, amount


def _find_name(toks: list[str], orig: list[str], known: Iterable[str], skip: set[str]) -> str | None:
    known_l = {k.lower(): k for k in known}
    vocab = SUMMARY_KW | QUERY_KW | PAYMENT_KW | CREDIT_KW | STOCK_KW | SALE_KW | PARTICLES | FILLER | DAY_KW | skip
    # 1) known customer anywhere (also with attached Kannada/Tamil suffix)
    for t in toks:
        if t in known_l:
            return known_l[t]
        m = re.match(r"^([a-z]{3,}?)-?(ge|ige|kku|ukku|ku|ka|ki|ke|ko|ne|du|dhu|oda)$", t)
        if m and m.group(1) in known_l:
            return known_l[m.group(1)]
    # 2) word directly before a possessive / dative particle
    for i, t in enumerate(toks[1:], start=1):
        if t in {"ka", "ke", "ki", "ko", "ne", "se", "ge", "ige", "avarige", "avru", "avaru", "kku", "ku", "ukku", "oda",
                 "du", "dhu", "avanga", "ji"}:
            cand = toks[i - 1]
            if cand not in vocab and not NUM_RE.match(cand) and not cand.startswith("₹"):
                return _title(orig[i - 1])
    # 3) attached suffix on an unknown name: "rameshge", "murugankku"
    for i, t in enumerate(toks):
        m = re.match(r"^([a-z]{3,}?)-?(ige|ge|ukku|kku)$", t)
        if m and t not in vocab:
            return _title(m.group(1))
    return None


def _leading_name(toks: list[str], orig: list[str], item_lookup) -> str | None:
    """Bare "<name> <amount> <verb>" ("Sures 50 kottru"): the first word, if it is not vocabulary, a number or an item.
    The ledger then maps it onto an existing customer (conservative fuzzy match, asks back when ambiguous)."""
    if not toks:
        return None
    t = toks[0]
    vocab = SUMMARY_KW | QUERY_KW | PAYMENT_KW | CREDIT_KW | STOCK_KW | SALE_KW | STOCK_REMOVE_KW | PARTICLES | FILLER | DAY_KW
    if t in vocab or t in CURRENCY_TOKENS or t in NUM_WORDS or t.startswith("₹") or re.search(r"\d", t):
        return None
    if not re.search(r"[A-Za-z\u0900-\u0D7F]", t) or len(t) < 2:
        return None
    if item_lookup and item_lookup(t):
        return None
    return _title(orig[0])


def _is_dative(toks: list[str], name: str) -> bool:
    if set(toks) & DATIVE:
        return True
    n = name.lower()
    return any(t != n and t.startswith(n) and t[len(n):].lstrip("-") in {"ge", "ige", "kku", "ukku", "ku", "ko"} for t in toks)


def _title(s: str) -> str:
    return s[:1].upper() + s[1:] if s.isascii() else s


def _item_text(toks: list[str], orig: list[str], drop_idx: set[int], name: str | None) -> str:
    vocab = SUMMARY_KW | QUERY_KW | PAYMENT_KW | CREDIT_KW | STOCK_KW | SALE_KW | STOCK_REMOVE_KW | PARTICLES | FILLER
    words = []
    for i, t in enumerate(toks):
        if i in drop_idx or t in vocab or t in CURRENCY_TOKENS or t.startswith("₹"):
            continue
        if name and t == name.lower():
            continue
        if NUM_RE.match(t) and not (i + 1 < len(toks) and toks[i + 1] in {"kg", "g", "ml", "l", "ltr", "gm"}):
            continue
        words.append(orig[i])
    return " ".join(words).strip()


def parse(text: str, known_customers: Iterable[str] = (), item_lookup: Callable[[str], str | None] | None = None) -> ParseResult:
    text = normalize_numbers(text)
    lang = detect_lang(text)
    known = list(known_customers)
    calls: list[dict] = []
    for clause in _split_clauses(text):
        orig = [o.strip(".-") for o in re.findall(TOKEN_RE, clause.replace("₹", " ₹ ")) if o.strip(".-")]
        toks = _tokens(clause)
        if len(orig) != len(toks):  # keep indices aligned
            orig = toks[:]
        orig = [NATIVE.get(o, o) if o in NATIVE else o for o in orig]
        tset = set(toks)
        nums, cur_amount = _numbers(toks)
        name = _find_name(toks, orig, known, set())

        # summary
        if (tset & SUMMARY_KW and (tset & DAY_KW or not name)) or ("summary" in tset):
            calls.append({"tool": "daily_summary", "args": {}})
            continue
        # balance query (no amount spoken)
        if tset & QUERY_KW and name and not nums and cur_amount is None and not (tset & CREDIT_KW - {"baaki"}):
            calls.append({"tool": "query_balance", "args": {"customer": name}})
            continue

        if name is None and tset & (PAYMENT_KW | CREDIT_KW | QUERY_KW):
            name = _leading_name(toks, orig, item_lookup)
            if name and tset & QUERY_KW and not nums and cur_amount is None and not (tset & CREDIT_KW - {"baaki"}):
                calls.append({"tool": "query_balance", "args": {"customer": name}})
                continue

        amount = cur_amount if cur_amount is not None else (nums[0][1] if nums else None)

        # payment. Repay verbs (jama, wapas, ...) always mean a payment. Give verbs (diye, kottru, kuduthaar) are a
        # payment only without a credit word or a dative: "udhaar pe diye" / "Rameshge 50 kottru" = given on credit.
        give_to = bool(name and tset & GIVE_KW and not tset & REPAY_KW and _is_dative(toks, name))
        if name and amount is not None and (tset & REPAY_KW or (tset & GIVE_KW and not tset & CREDIT_KW and not give_to)):
            calls.append({"tool": "record_payment", "args": {"customer": name, "amount": amount}})
            continue

        is_credit = bool(tset & CREDIT_KW) or give_to
        is_sale = bool(tset & SALE_STRONG) or (bool(tset & {"gaya", "gaye"}) and not tset & STOCK_KW)
        is_stock = bool(tset & STOCK_KW) or bool(tset & STOCK_REMOVE_KW)

        # quantity + item for sale / stock / credit-sale
        qty, drop = None, set()
        if cur_amount is not None and nums:
            qty, drop = nums[0][1], {nums[0][0]}
        elif nums and (is_sale or is_stock or (is_credit and len(nums) > 0)):
            qty, drop = nums[0][1], {nums[0][0]}
        if qty is None:
            for i, t in enumerate(toks):
                if t in NUM_WORDS and i + 1 < len(toks) and toks[i + 1] not in (FILLER | CREDIT_KW | PARTICLES):
                    qty, drop = float(NUM_WORDS[t]), {i}
                    break
        item = _item_text(toks, orig, drop, name)
        known_item = item_lookup(item) if (item and item_lookup) else None

        if is_credit and name:
            if known_item and (cur_amount is not None or (qty is not None and qty < 50)):
                args = {"item": known_item, "qty": qty or 1, "customer": name}
                if cur_amount is not None:
                    args["amount"] = cur_amount
                calls.append({"tool": "record_sale", "args": args})
            elif amount is not None:
                calls.append({"tool": "add_credit", "args": {"customer": name, "amount": amount}})
            continue
        if is_stock and item:
            q = qty if qty is not None else 1
            if tset & STOCK_REMOVE_KW:
                q = -abs(q)
            calls.append({"tool": "update_stock", "args": {"item": known_item or item, "qty": q}})
            continue
        if is_sale and item:
            args = {"item": known_item or item, "qty": qty if qty is not None else 1}
            if cur_amount is not None:
                args["amount"] = cur_amount
            calls.append({"tool": "record_sale", "args": args})
            continue
    return ParseResult(lang=lang, calls=calls)
