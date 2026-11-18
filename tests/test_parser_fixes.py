"""Regression tests for two bugs:
1. Kannada (and Tamil / Hindi) payment phrases, Indian digit grouping and fuzzy customer names.
2. Stock going negative and the reply speaking a negative number ("सिर्फ -1 बचे हैं").
"""
import re

import pytest

from server import messages, rule_parser
from server.agent import Agent
from server.config import Settings
from server.ledger import AmbiguousCustomer, Ledger, group_in
from server.tools import run_tool


def _lookup(ledger):
    return lambda q: (r["name"] if (r := ledger._find_item(q)) else None)


def _parse(ledger, text):
    customers = [c["name"] for c in ledger.snapshot()["customers"]]
    r = rule_parser.parse(text, customers, _lookup(ledger))
    return r.lang, [(c["tool"], c["args"]) for c in r.calls]


def _agent(ledger, lang="auto"):
    return Agent(Settings(force_mock=True, owner_lang=lang), ledger)


NEG = re.compile(r"(?<![\w])-\s?\d")  # a minus sign in front of a number


# ------------------------------------------------------------- payment phrases
@pytest.mark.parametrize("text,lang", [
    ("Suresh 50 kottru", "kn"), ("Suresh 50 kottaru", "kn"), ("Suresh 50 kotru", "kn"), ("Suresh 50 koTTru", "kn"),
    ("Suresh 50 kottidaare", "kn"), ("Suresh 50 kottide", "kn"), ("Suresh 50 ಕೊಟ್ಟರು", "kn"),
    ("Suresh 50 ಕೊಟ್ಟಿದ್ದಾರೆ", "kn"), ("Suresh 50 ವಾಪಸ್ ಕೊಟ್ಟ", "kn"), ("Suresh 50 vaapas kotta", "kn"),
    ("Suresh 50 koduthaar", "ta"), ("Suresh 50 kuduthaanga", "ta"), ("Suresh 50 கொடுத்தார்", "ta"),
    ("Suresh ne 50 de diye", "hi"), ("Suresh ne 50 diya", "hi"), ("Suresh ne 50 लौटाए", "hi"),
    ("Suresh ने 50 लौटाए", "hi"), ("Suresh ne 50 lautaye", "hi"),
])
def test_payment_verbs(ledger, text, lang):
    got_lang, calls = _parse(ledger, text)
    assert calls == [("record_payment", {"customer": "Suresh", "amount": 50.0})], calls
    assert got_lang == lang


@pytest.mark.parametrize("text,amount", [
    ("Lakshmi 1,200 kottru", 1200), ("Lakshmi 1,20,000 kottru", 120000), ("Lakshmi 12,34,567 kottru", 1234567),
    ("Lakshmi 1,200,000 kottru", 1200000), ("Lakshmi ne ₹1,200 jama kiye", 1200), ("Lakshmi ne Rs 2,500 diye", 2500),
])
def test_indian_number_grouping(ledger, text, amount):
    _, calls = _parse(ledger, text)
    assert calls == [("record_payment", {"customer": "Lakshmi", "amount": float(amount)})]


def test_comma_between_clauses_still_splits(ledger):
    _, calls = _parse(ledger, "Ramesh ka 240 udhaar, 2 Aashirvaad 5kg bik gaye")
    assert [c[0] for c in calls] == ["add_credit", "record_sale"]
    assert rule_parser.normalize_numbers("2 Maggi, 3 Parle-G") == "2 Maggi, 3 Parle-G"


@pytest.mark.parametrize("text", ["Rameshge 60 saala kottru", "Ramesh ge 60 kottru", "Ramesh ko 60 diye",
                                  "Ramesh ka 60 udhaar kottru"])
def test_give_with_credit_word_or_dative_is_credit(ledger, text):
    """Documented ambiguity: kottru/diye TO someone (dative or with saala/udhaar) = given on credit."""
    _, calls = _parse(ledger, text)
    assert calls == [("add_credit", {"customer": "Ramesh", "amount": 60.0})], calls


def test_give_goods_to_customer_is_credit_sale(ledger):
    _, calls = _parse(ledger, "Fatima ko 2 Maggi diye")
    assert calls == [("record_sale", {"item": "Maggi Noodles", "qty": 2.0, "customer": "Fatima"})]


# ------------------------------------------------------------ fuzzy customers
def test_sures_maps_to_suresh(ledger):
    ledger.add_credit("Suresh", 350)
    out = _agent(ledger).handle_text("Sures 50 kottru", speak=False)
    res = out["actions"][0]["result"]
    assert res["ok"] and res["customer"] == "Suresh" and res["balance"] == 300
    assert out["reply"].startswith("Suresh ಅವರಿಂದ 50 ರೂಪಾಯಿ")
    assert ledger.query_balance("Sures")["customer"] == "Suresh"


def test_typo_within_one_edit_maps_for_payments(ledger):
    assert ledger.record_payment("Fatma", 10)["customer"] == "Fatima"
    assert ledger.record_payment("Laksmi", 10)["customer"] == "Lakshmi"


def test_too_far_is_unknown_not_guessed(ledger):
    r = run_tool(ledger, "record_payment", {"customer": "Sur", "amount": 10})
    assert not r["ok"] and r["unknown_customer"]
    assert messages.confirm(r, "hi") == "Sur नाम का कोई खाता नहीं मिला।"


def test_ambiguous_name_asks_back(ledger):
    ledger.add_credit("Rajesh", 100)
    before = ledger.snapshot()["customers"]
    with pytest.raises(AmbiguousCustomer) as e:
        ledger.record_payment("Raesh", 10)
    assert set(e.value.candidates) == {"Ramesh", "Rajesh"}
    out = _agent(ledger).handle_text("Raesh 10 kottru", speak=False)
    assert not out["actions"][0]["result"]["ok"]
    assert "Ramesh" in out["reply"] and "Rajesh" in out["reply"] and "?" in out["reply"]
    assert ledger.snapshot()["customers"] == before  # nothing written


def test_credit_to_near_name_opens_new_account(ledger):
    """Edit-distance matching is only for payments/queries; a new 'Rajesh' must not land on Ramesh's khata."""
    r = ledger.add_credit("Rajesh", 40)
    assert r["customer"] == "Rajesh"
    assert ledger.query_balance("Ramesh")["balance"] == 0


# -------------------------------------------------------------------- stock
def test_sale_beyond_stock_is_recorded_clamped_and_flagged(ledger):
    r = ledger.record_sale("Surf Excel", 7)  # seeded stock 6
    assert r["ok"] and r["stock_left"] == 0 and r["stock_mismatch"] and r["short_by"] == 1
    assert r["amount"] == 980  # the sale and its money are kept
    snap = ledger.snapshot()
    assert {i["name"]: i["stock"] for i in snap["items"]}["Surf Excel 1kg"] == 0
    assert snap["sales"][0]["qty"] == 7


def test_credit_sale_beyond_stock_still_books_udhaar(ledger):
    r = ledger.record_sale("Surf Excel", 8, customer="Fatima")
    assert r["stock_left"] == 0 and r["short_by"] == 2 and r["balance"] == 1120


@pytest.mark.parametrize("lang", ["hi", "kn", "ta", "en"])
def test_no_negative_stock_in_any_language(ledger, lang):
    ag = _agent(ledger, lang)
    replies = [ag.handle_text(t, speak=False)["reply"] for t in
               ["6 Surf Excel bik gaye", "1 Surf Excel bik gaya", "3 Surf Excel bik gaye", "10 Toor dal kharab, stock se hatao"]]
    for r in replies:
        assert not NEG.search(r), r
    assert "-1" not in replies[1]
    recount = {"hi": "दोबारा गिनती", "kn": "ಮತ್ತೆ ಎಣಿಸಿ", "ta": "மீண்டும் எண்ணவும்", "en": "recount"}[lang]
    assert recount in replies[1] and recount in replies[2] and recount in replies[3]
    assert recount not in replies[0]  # exactly sold out: out-of-stock note, no mismatch
    assert {i["name"]: i["stock"] for i in ledger.snapshot()["items"]}["Surf Excel 1kg"] == 0


def test_legacy_negative_stock_is_never_spoken(ledger):
    ledger.db.execute("UPDATE items SET stock_qty = -3 WHERE name = 'Maggi Noodles'")
    r = ledger.record_sale("maggi", 1)
    assert r["stock_left"] == 0 and r["stock_mismatch"]
    for lang in ("hi", "kn", "ta", "en"):
        assert not NEG.search(messages.confirm(r, lang))
    assert ledger.update_stock("maggi", 5)["stock"] == 5  # restock counts from 0, not -3


def test_reply_never_shows_negative_balance(ledger):
    ledger.record_payment("Suresh", 100)  # no dues: becomes an advance
    for lang in ("hi", "kn", "ta", "en"):
        assert not NEG.search(messages.confirm(ledger.query_balance("Suresh"), lang))


def test_golden_run_never_speaks_a_negative_number():
    import json
    from pathlib import Path
    g = json.loads((Path(__file__).parent / "fixtures" / "js_golden.json").read_text(encoding="utf-8"))
    bad = [r["reply"] for r in g["run"] if NEG.search(r["reply"])]
    assert not bad, bad


def test_indian_grouping_in_replies(ledger):
    assert group_in(120000) == "1,20,000" and group_in(1234567.5, 2) == "12,34,567.50" and group_in(999) == "999"
    out = _agent(ledger, "kn").handle_text("Ramesh 1,20,000 kotru", speak=False)
    assert "1,20,000" in out["reply"]
