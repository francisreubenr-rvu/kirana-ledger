from datetime import datetime, timedelta

from server.ledger import IST, Ledger
from server.tools import TOOLS, run_tool


def test_credit_and_payment_balance(ledger):
    r = ledger.add_credit("Ramesh", 240)
    assert r["balance"] == 240.0
    ledger.add_credit("ramesh", 60.5)  # case-insensitive
    r = ledger.record_payment("Ramesh", 100)
    assert r["balance"] == 200.5
    assert ledger.query_balance("Ramesh")["balance"] == 200.5


def test_new_customer_created_on_credit(ledger):
    r = ledger.add_credit("Vikram", 150)
    assert r["customer"] == "Vikram" and r["balance"] == 150


def test_fuzzy_customer_match(ledger):
    ledger.add_credit("Lakshmi", 100)
    r = ledger.record_payment("Laxmi", 40)  # STT spelling drift
    assert r["customer"] == "Lakshmi" and r["balance"] == 60


def test_payment_unknown_customer_is_error(ledger):
    r = run_tool(ledger, "record_payment", {"customer": "Nobody Xyz", "amount": 10})
    assert r["ok"] is False and "no customer" in r["error"]


def test_overpayment_goes_negative_as_advance(ledger):
    ledger.add_credit("Suresh", 50)
    assert ledger.record_payment("Suresh", 80)["balance"] == -30


def test_rejects_non_positive_amounts(ledger):
    assert run_tool(ledger, "add_credit", {"customer": "Ramesh", "amount": 0})["ok"] is False
    assert run_tool(ledger, "add_credit", {"customer": "Ramesh", "amount": "abc"})["ok"] is False


def test_sale_uses_catalogue_price_and_decrements_stock(ledger):
    before = {i["name"]: i["stock"] for i in ledger.snapshot()["items"]}["Aashirvaad Atta 5kg"]
    r = ledger.record_sale("aashirvaad 5kg", 2)
    assert r["item"] == "Aashirvaad Atta 5kg" and r["amount"] == 570.0 and r["stock_left"] == before - 2


def test_sale_with_explicit_amount_and_unknown_item(ledger):
    r = ledger.record_sale("Haldiram Bhujia", 1, amount=55)
    assert r["known_item"] is False and r["amount"] == 55 and r["stock_left"] is None


def test_credit_sale_adds_udhaar(ledger):
    r = ledger.record_sale("Parle-G", 3, customer="Fatima")
    assert r["amount"] == 30 and r["balance"] == 30
    assert ledger.query_balance("Fatima")["balance"] == 30


def test_low_stock_flag(ledger):
    r = ledger.record_sale("Surf Excel", 5)  # demo stock 6, reorder at 2
    assert r["low_stock"] is True and r["stock_left"] == 1


def test_update_stock_add_remove_and_create(ledger):
    assert ledger.update_stock("Maggi", 20)["stock"] == 60
    assert ledger.update_stock("Maggi", -5)["stock"] == 55
    r = ledger.update_stock("Haldiram Bhujia", 12, price=55)
    assert r["created"] and r["stock"] == 12
    assert ledger.record_sale("haldiram bhujia", 2)["amount"] == 110


def test_query_unknown_customer(ledger):
    r = ledger.query_balance("Zebediah")
    assert r["known"] is False and r["balance"] == 0


def test_daily_summary_totals(ledger):
    ledger.add_credit("Ramesh", 240)
    ledger.record_sale("Aashirvaad Atta 5kg", 2)       # 570 cash
    ledger.record_sale("Parle-G", 3, customer="Fatima")  # 30 on credit
    ledger.record_payment("Ramesh", 100)
    s = ledger.daily_summary()
    assert s["sales_count"] == 2 and s["sales_total"] == 600 and s["cash_sales"] == 570
    assert s["credit_given"] == 270 and s["payments_received"] == 100
    assert s["outstanding_total"] == 170
    assert s["top_debtors"][0]["customer"] == "Ramesh"
    assert "₹600" in s["whatsapp_text"] and "Test Kirana" in s["whatsapp_text"]


def test_daily_summary_other_day_is_empty(ledger):
    ledger.record_sale("Maggi", 1)
    y = (datetime.now(IST) - timedelta(days=1)).date().isoformat()
    assert ledger.daily_summary(y)["sales_count"] == 0


def test_reminders_have_whatsapp_links(ledger):
    ledger.add_credit("Ramesh", 240)
    ledger.add_credit("Lakshmi", 1200)
    rem = ledger.reminders("hi")
    assert [r["customer"] for r in rem] == ["Lakshmi", "Ramesh"]
    assert "₹1,200" in rem[0]["text"] and rem[0]["whatsapp_url"].startswith("https://wa.me/?text=")
    assert "ಬಾಕಿ" in ledger.reminders("kn")[0]["text"]


def test_tool_schemas_match_ledger_methods():
    for t in TOOLS:
        assert callable(getattr(Ledger, t["function"]["name"]))


def test_run_tool_accepts_json_string_and_ignores_extra_args(ledger):
    r = run_tool(ledger, "add_credit", '{"customer": "Ramesh", "amount": 99, "bogus": 1}')
    assert r["ok"] and r["balance"] == 99
    assert run_tool(ledger, "drop_tables", {})["ok"] is False


def test_persistence_on_disk(tmp_path):
    p = tmp_path / "k.db"
    L = Ledger(str(p)); L.seed_demo(); L.add_credit("Ramesh", 10)
    L2 = Ledger(str(p))
    assert L2.query_balance("Ramesh")["balance"] == 10


def test_opening_balances_are_dated_yesterday(ledger):
    L = Ledger(":memory:"); L.seed_demo(opening_balances=True)
    assert L.query_balance("Lakshmi")["balance"] == 1200
    s = L.daily_summary()
    assert s["credit_given"] == 0 and s["outstanding_total"] == 1550


def test_advance_payment_confirmation(ledger):
    from server import messages
    r = ledger.add_credit("Suresh", 50) and ledger.record_payment("Suresh", 80)
    assert "एडवांस" in messages.confirm(r, "hi") and "30" in messages.confirm(r, "hi")
