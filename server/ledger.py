"""SQLite ledger for a kirana shop: credit (udhaar), payments, stock and sales.

All money is stored as integer paise to avoid float drift; the public API takes
and returns rupees. Every public method here is also exposed to the LLM as a
tool (see tools.py), so each returns a small JSON-serialisable dict.
"""
from __future__ import annotations

import difflib
import re
import sqlite3
import threading
from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    phone TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS credit_txns (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    kind TEXT NOT NULL CHECK (kind IN ('credit', 'payment')),
    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
    note TEXT,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    aliases TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT 'pc',
    price_paise INTEGER,
    stock_qty REAL NOT NULL DEFAULT 0,
    reorder_level REAL NOT NULL DEFAULT 3
);
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY,
    item_id INTEGER REFERENCES items(id),
    item_name TEXT NOT NULL,
    qty REAL NOT NULL,
    amount_paise INTEGER,
    customer_id INTEGER REFERENCES customers(id),
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_moves (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id),
    delta REAL NOT NULL,
    reason TEXT NOT NULL,
    ts TEXT NOT NULL
);
"""

# Demo catalogue. Prices are illustrative sample values, not live MRPs.
DEMO_ITEMS = [
    ("Aashirvaad Atta 5kg", "aashirvaad|ashirvad|aashirvad|atta|आशीर्वाद|ಆಶೀರ್ವಾದ|ஆசீர்வாத்", "pack", 285, 12, 3),
    ("Maggi Noodles", "maggi|मैगी|ಮ್ಯಾಗಿ|மேகி", "pack", 14, 40, 10),
    ("Parle-G", "parle|parle g|parleg|biscuit|पारले|ಪಾರ್ಲೆ|பார்லே", "pack", 10, 50, 10),
    ("Amul Milk 500ml", "milk|doodh|amul|दूध|ಹಾಲು|haalu|பால்|paal", "packet", 27, 20, 5),
    ("Tata Salt 1kg", "salt|namak|tata salt|नमक|ಉಪ್ಪು|uppu|உப்பு", "pack", 28, 15, 4),
    ("Fortune Sunflower Oil 1L", "oil|tel|fortune|तेल|ಎಣ್ಣೆ|enne|எண்ணெய்|ennai", "pouch", 155, 10, 3),
    ("Toor Dal 1kg", "dal|daal|toor|tur|दाल|ಬೇಳೆ|bele|பருப்பு|paruppu", "kg", 160, 8, 3),
    ("Sugar 1kg", "sugar|cheeni|chini|shakkar|चीनी|ಸಕ್ಕರೆ|sakkare|சர்க்கரை|sakkarai", "kg", 46, 10, 3),
    ("Surf Excel 1kg", "surf|surf excel|detergent|सर्फ", "pack", 140, 6, 2),
]
DEMO_CUSTOMERS = [("Ramesh", None), ("Lakshmi", None), ("Suresh", None), ("Fatima", None), ("Murugan", None)]
# Opening udhaar carried over from the paper khata (dated yesterday so it doesn't count as today's credit).
DEMO_OPENING = [("Lakshmi", 1200), ("Suresh", 350)]


def _now() -> datetime:
    return datetime.now(IST)


def _rs(paise: int | None) -> float | None:
    return None if paise is None else round(paise / 100, 2)


def _paise(rupees: float | int | str) -> int:
    return int(round(float(rupees) * 100))


def _fmt_rs(paise: int) -> str:
    r = paise / 100
    return f"₹{r:,.0f}" if r == int(r) else f"₹{r:,.2f}"


def _phon(s: str) -> str:
    """Crude phonetic key so STT spelling drift still matches: Lakshmi/Laxmi, Suresh/Sures, Murugan/Muruhan."""
    s = s.lower().strip()
    for a, b in (("ksh", "x"), ("ks", "x"), ("sh", "s"), ("th", "t"), ("dh", "d"), ("bh", "b"), ("kh", "k"),
                 ("gh", "g"), ("ph", "f"), ("w", "v"), ("ee", "i"), ("oo", "u"), ("aa", "a"), ("z", "j")):
        s = s.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", s)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()


class LedgerError(ValueError):
    pass


class Ledger:
    def __init__(self, path: str = ":memory:", shop_name: str = "Kirana Store", low_stock_default: float = 3):
        self.path = path
        self.shop_name = shop_name
        self._lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self.low_stock_default = low_stock_default

    # ------------------------------------------------------------------ setup
    def seed_demo(self, opening_balances: bool = False) -> None:
        with self._lock, self.db:
            for name, aliases, unit, price, stock, reorder in DEMO_ITEMS:
                self.db.execute(
                    "INSERT OR IGNORE INTO items(name, aliases, unit, price_paise, stock_qty, reorder_level) VALUES (?,?,?,?,?,?)",
                    (name, aliases, unit, price * 100, stock, reorder),
                )
            for name, phone in DEMO_CUSTOMERS:
                self.db.execute(
                    "INSERT OR IGNORE INTO customers(name, phone, created_at) VALUES (?,?,?)",
                    (name, phone, _now().isoformat()),
                )
            if opening_balances and not self.db.execute("SELECT 1 FROM credit_txns LIMIT 1").fetchone():
                y = (_now() - timedelta(days=1)).isoformat()
                for name, amt in DEMO_OPENING:
                    cid = self.db.execute("SELECT id FROM customers WHERE name = ?", (name,)).fetchone()[0]
                    self.db.execute(
                        "INSERT INTO credit_txns(customer_id, kind, amount_paise, note, ts) VALUES (?,?,?,?,?)",
                        (cid, "credit", amt * 100, "opening balance (paper khata)", y),
                    )

    def reset(self, seed: bool = True, opening_balances: bool = True) -> None:
        with self._lock, self.db:
            for t in ("sales", "stock_moves", "credit_txns", "items", "customers"):
                self.db.execute(f"DELETE FROM {t}")
        if seed:
            self.seed_demo(opening_balances)

    # -------------------------------------------------------------- matching
    def _find_customer(self, name: str, create: bool) -> sqlite3.Row | None:
        name = name.strip()
        if not name:
            raise LedgerError("customer name is empty")
        row = self.db.execute("SELECT * FROM customers WHERE name = ?", (name,)).fetchone()
        if row:
            return row
        rows = self.db.execute("SELECT * FROM customers").fetchall()
        names = {r["name"].lower(): r for r in rows}
        close = difflib.get_close_matches(name.lower(), list(names), n=1, cutoff=0.8)
        if close:
            return names[close[0]]
        key = _phon(name)
        for n, r in names.items():
            if _phon(n) == key or (len(key) >= 5 and difflib.SequenceMatcher(None, _phon(n), key).ratio() >= 0.88):
                return r
        if not create:
            return None
        clean = name[:1].upper() + name[1:]
        self.db.execute("INSERT INTO customers(name, created_at) VALUES (?,?)", (clean, _now().isoformat()))
        return self.db.execute("SELECT * FROM customers WHERE name = ?", (clean,)).fetchone()

    def _find_item(self, name: str) -> sqlite3.Row | None:
        q = _norm(name)
        if not q:
            return None
        rows = self.db.execute("SELECT * FROM items").fetchall()
        best, best_score = None, 0.0
        for r in rows:
            cands = [_norm(r["name"])] + [_norm(a) for a in r["aliases"].split("|") if a]
            for c in cands:
                if not c:
                    continue
                if q == c:
                    score = 1.0
                elif c in q.split() or (len(c) > 3 and c in q) or (len(q) > 3 and q in c):
                    score = 0.9
                else:
                    score = difflib.SequenceMatcher(None, q, c).ratio()
                if score > best_score:
                    best, best_score = r, score
        return best if best_score >= 0.75 else None

    def _balance_paise(self, customer_id: int) -> int:
        row = self.db.execute(
            "SELECT COALESCE(SUM(CASE kind WHEN 'credit' THEN amount_paise ELSE -amount_paise END), 0) AS b "
            "FROM credit_txns WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
        return int(row["b"])

    @staticmethod
    def _positive(amount: Any, what: str = "amount") -> int:
        try:
            p = _paise(amount)
        except (TypeError, ValueError):
            raise LedgerError(f"{what} must be a number, got {amount!r}")
        if p <= 0:
            raise LedgerError(f"{what} must be positive")
        return p

    # ----------------------------------------------------------------- tools
    def add_credit(self, customer: str, amount: float, note: str | None = None) -> dict:
        """Customer took goods on credit (udhaar). Increases what they owe."""
        p = self._positive(amount)
        with self._lock, self.db:
            c = self._find_customer(customer, create=True)
            self.db.execute(
                "INSERT INTO credit_txns(customer_id, kind, amount_paise, note, ts) VALUES (?,?,?,?,?)",
                (c["id"], "credit", p, note, _now().isoformat()),
            )
            bal = self._balance_paise(c["id"])
        return {"ok": True, "action": "add_credit", "customer": c["name"], "amount": _rs(p), "balance": _rs(bal)}

    def record_payment(self, customer: str, amount: float) -> dict:
        """Customer paid back (jama). Reduces what they owe; may go negative (advance)."""
        p = self._positive(amount)
        with self._lock, self.db:
            c = self._find_customer(customer, create=False)
            if c is None:
                raise LedgerError(f"no customer named {customer!r} in the ledger")
            self.db.execute(
                "INSERT INTO credit_txns(customer_id, kind, amount_paise, ts) VALUES (?,?,?,?)",
                (c["id"], "payment", p, _now().isoformat()),
            )
            bal = self._balance_paise(c["id"])
        return {"ok": True, "action": "record_payment", "customer": c["name"], "amount": _rs(p), "balance": _rs(bal)}

    def record_sale(self, item: str, qty: float = 1, amount: float | None = None, customer: str | None = None) -> dict:
        """Record a sale. Decrements stock for known items. If `customer` is given the sale is on credit."""
        try:
            q = float(qty)
        except (TypeError, ValueError):
            raise LedgerError(f"qty must be a number, got {qty!r}")
        if q <= 0:
            raise LedgerError("qty must be positive")
        with self._lock, self.db:
            it = self._find_item(item)
            if amount is not None:
                amt = self._positive(amount)
            elif it is not None and it["price_paise"] is not None:
                amt = int(round(it["price_paise"] * q))
            else:
                amt = None
            ts = _now().isoformat()
            cust = self._find_customer(customer, create=True) if customer else None
            name = it["name"] if it else item.strip()
            self.db.execute(
                "INSERT INTO sales(item_id, item_name, qty, amount_paise, customer_id, ts) VALUES (?,?,?,?,?,?)",
                (it["id"] if it else None, name, q, amt, cust["id"] if cust else None, ts),
            )
            stock = low = None
            if it is not None:
                self.db.execute("UPDATE items SET stock_qty = stock_qty - ? WHERE id = ?", (q, it["id"]))
                self.db.execute(
                    "INSERT INTO stock_moves(item_id, delta, reason, ts) VALUES (?,?,?,?)", (it["id"], -q, "sale", ts)
                )
                stock = self.db.execute("SELECT stock_qty FROM items WHERE id = ?", (it["id"],)).fetchone()[0]
                low = stock <= it["reorder_level"]
            bal = None
            if cust is not None and amt:
                self.db.execute(
                    "INSERT INTO credit_txns(customer_id, kind, amount_paise, note, ts) VALUES (?,?,?,?,?)",
                    (cust["id"], "credit", amt, f"{_fmt_qty(q)} x {name}", ts),
                )
                bal = self._balance_paise(cust["id"])
        out = {
            "ok": True, "action": "record_sale", "item": name, "known_item": it is not None, "qty": q,
            "amount": _rs(amt), "stock_left": stock, "low_stock": bool(low),
        }
        if cust is not None:
            out.update(customer=cust["name"], balance=_rs(bal))
        return out

    def update_stock(self, item: str, qty: float, price: float | None = None, unit: str | None = None) -> dict:
        """Add (positive qty) or remove (negative qty) stock. Creates the item if it is new."""
        try:
            q = float(qty)
        except (TypeError, ValueError):
            raise LedgerError(f"qty must be a number, got {qty!r}")
        with self._lock, self.db:
            it = self._find_item(item)
            created = False
            if it is None:
                if q < 0:
                    raise LedgerError(f"unknown item {item!r}")
                clean = item.strip()
                self.db.execute(
                    "INSERT INTO items(name, unit, price_paise, stock_qty, reorder_level) VALUES (?,?,?,?,?)",
                    (clean, unit or "pc", _paise(price) if price else None, 0, self.low_stock_default),
                )
                it = self.db.execute("SELECT * FROM items WHERE name = ?", (clean,)).fetchone()
                created = True
            elif price:
                self.db.execute("UPDATE items SET price_paise = ? WHERE id = ?", (_paise(price), it["id"]))
            self.db.execute("UPDATE items SET stock_qty = stock_qty + ? WHERE id = ?", (q, it["id"]))
            self.db.execute(
                "INSERT INTO stock_moves(item_id, delta, reason, ts) VALUES (?,?,?,?)",
                (it["id"], q, "restock" if q >= 0 else "adjust", _now().isoformat()),
            )
            row = self.db.execute("SELECT * FROM items WHERE id = ?", (it["id"],)).fetchone()
        return {
            "ok": True, "action": "update_stock", "item": row["name"], "delta": q, "stock": row["stock_qty"],
            "created": created, "low_stock": row["stock_qty"] <= row["reorder_level"],
        }

    def query_balance(self, customer: str) -> dict:
        """How much a customer owes right now."""
        with self._lock:
            c = self._find_customer(customer, create=False)
            if c is None:
                return {"ok": True, "action": "query_balance", "customer": customer.strip(), "known": False, "balance": 0.0}
            bal = self._balance_paise(c["id"])
            last = self.db.execute(
                "SELECT ts FROM credit_txns WHERE customer_id = ? ORDER BY id DESC LIMIT 1", (c["id"],)
            ).fetchone()
        return {
            "ok": True, "action": "query_balance", "customer": c["name"], "known": True, "balance": _rs(bal),
            "last_txn": last["ts"] if last else None,
        }

    def daily_summary(self, day: str | None = None) -> dict:
        """Totals for one IST calendar day (YYYY-MM-DD, default today) plus WhatsApp-ready text."""
        d = date.fromisoformat(day) if day else _now().date()
        start = datetime.combine(d, time.min, IST).isoformat()
        end = datetime.combine(d + timedelta(days=1), time.min, IST).isoformat()
        with self._lock:
            s = self.db.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(amount_paise),0) amt, "
                "COALESCE(SUM(CASE WHEN customer_id IS NULL THEN amount_paise ELSE 0 END),0) cash "
                "FROM sales WHERE ts >= ? AND ts < ?",
                (start, end),
            ).fetchone()
            top = self.db.execute(
                "SELECT item_name, SUM(qty) q, COALESCE(SUM(amount_paise),0) a FROM sales WHERE ts >= ? AND ts < ? "
                "GROUP BY item_name ORDER BY a DESC LIMIT 3",
                (start, end),
            ).fetchall()
            cr = self.db.execute(
                "SELECT kind, COALESCE(SUM(amount_paise),0) a FROM credit_txns WHERE ts >= ? AND ts < ? GROUP BY kind",
                (start, end),
            ).fetchall()
            low = self.db.execute(
                "SELECT name, stock_qty FROM items WHERE stock_qty <= reorder_level ORDER BY stock_qty"
            ).fetchall()
        kinds = {r["kind"]: r["a"] for r in cr}
        debtors = self.outstanding()
        outstanding = sum(_paise(x["balance"]) for x in debtors)
        summary = {
            "ok": True, "action": "daily_summary", "date": d.isoformat(),
            "sales_count": s["n"], "sales_total": _rs(s["amt"]), "cash_sales": _rs(s["cash"]),
            "credit_given": _rs(kinds.get("credit", 0)), "payments_received": _rs(kinds.get("payment", 0)),
            "outstanding_total": _rs(outstanding),
            "top_items": [{"item": r["item_name"], "qty": r["q"], "amount": _rs(r["a"])} for r in top],
            "low_stock": [{"item": r["name"], "stock": r["stock_qty"]} for r in low],
            "top_debtors": debtors[:5],
        }
        summary["whatsapp_text"] = self._summary_text(summary)
        return summary

    # ------------------------------------------------------------- read-only
    def outstanding(self) -> list[dict]:
        with self._lock:
            rows = self.db.execute(
                "SELECT c.id, c.name, c.phone, "
                "COALESCE(SUM(CASE t.kind WHEN 'credit' THEN t.amount_paise ELSE -t.amount_paise END),0) bal, "
                "MAX(t.ts) last_ts FROM customers c JOIN credit_txns t ON t.customer_id = c.id "
                "GROUP BY c.id HAVING bal > 0 ORDER BY bal DESC"
            ).fetchall()
        return [{"customer": r["name"], "phone": r["phone"], "balance": _rs(r["bal"]), "last_txn": r["last_ts"]} for r in rows]

    def reminders(self, lang: str = "hi") -> list[dict]:
        out = []
        for d in self.outstanding():
            text = REMINDER_TEMPLATES.get(lang, REMINDER_TEMPLATES["hi"]).format(
                name=d["customer"], amt=_fmt_rs(_paise(d["balance"])), shop=self.shop_name
            )
            phone = re.sub(r"\D", "", d["phone"] or "")
            url = f"https://wa.me/{phone}?text={quote(text)}" if phone else f"https://wa.me/?text={quote(text)}"
            out.append({**d, "text": text, "whatsapp_url": url})
        return out

    def snapshot(self, limit: int = 20) -> dict:
        with self._lock:
            customers = self.db.execute(
                "SELECT c.name, c.phone, COALESCE(SUM(CASE t.kind WHEN 'credit' THEN t.amount_paise "
                "WHEN 'payment' THEN -t.amount_paise END),0) bal FROM customers c "
                "LEFT JOIN credit_txns t ON t.customer_id = c.id GROUP BY c.id ORDER BY bal DESC, c.name"
            ).fetchall()
            items = self.db.execute("SELECT * FROM items ORDER BY name").fetchall()
            sales = self.db.execute(
                "SELECT s.*, c.name cname FROM sales s LEFT JOIN customers c ON c.id = s.customer_id "
                "ORDER BY s.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            txns = self.db.execute(
                "SELECT t.*, c.name cname FROM credit_txns t JOIN customers c ON c.id = t.customer_id "
                "ORDER BY t.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return {
            "customers": [{"name": r["name"], "phone": r["phone"], "balance": _rs(r["bal"])} for r in customers],
            "items": [
                {"name": r["name"], "unit": r["unit"], "price": _rs(r["price_paise"]), "stock": r["stock_qty"],
                 "low": r["stock_qty"] <= r["reorder_level"]}
                for r in items
            ],
            "sales": [
                {"item": r["item_name"], "qty": r["qty"], "amount": _rs(r["amount_paise"]), "customer": r["cname"], "ts": r["ts"]}
                for r in sales
            ],
            "credit_txns": [
                {"customer": r["cname"], "kind": r["kind"], "amount": _rs(r["amount_paise"]), "note": r["note"], "ts": r["ts"]}
                for r in txns
            ],
        }

    def known_names(self) -> list[str]:
        """Customer and item names, used as STT keyterms (Saaras v4 supports up to 50)."""
        with self._lock:
            c = [r[0] for r in self.db.execute("SELECT name FROM customers ORDER BY id DESC LIMIT 30")]
            i = [r[0] for r in self.db.execute("SELECT name FROM items ORDER BY id LIMIT 20")]
        return (c + i)[:50]

    def _summary_text(self, s: dict) -> str:
        lines = [
            f"*{self.shop_name} — {s['date']}*",
            f"Sales: {s['sales_count']} bill{'' if s['sales_count'] == 1 else 's'}, {_fmt_rs(_paise(s['sales_total']))} (cash {_fmt_rs(_paise(s['cash_sales']))})",
            f"Udhaar given: {_fmt_rs(_paise(s['credit_given']))} | Collected: {_fmt_rs(_paise(s['payments_received']))}",
            f"Total outstanding: {_fmt_rs(_paise(s['outstanding_total']))}",
        ]
        if s["top_items"]:
            lines.append("Top items: " + ", ".join(f"{t['item']} x{_fmt_qty(t['qty'])}" for t in s["top_items"]))
        if s["low_stock"]:
            lines.append("Reorder: " + ", ".join(f"{t['item']} ({_fmt_qty(t['stock'])} left)" for t in s["low_stock"]))
        if s["top_debtors"]:
            lines.append("Biggest dues: " + ", ".join(f"{d['customer']} {_fmt_rs(_paise(d['balance']))}" for d in s["top_debtors"][:3]))
        return "\n".join(lines)


def _fmt_qty(q: float) -> str:
    return str(int(q)) if float(q) == int(q) else f"{q:g}"


REMINDER_TEMPLATES = {
    "hi": "Namaste {name} ji 🙏 {shop} mein aapka {amt} udhaar baaki hai. Suvidha ho to jama kar dijiye. Dhanyavaad!",
    "kn": "ನಮಸ್ಕಾರ {name} ಅವರೇ 🙏 {shop} ಅಂಗಡಿಯಲ್ಲಿ ನಿಮ್ಮ {amt} ಬಾಕಿ ಇದೆ. ಅನುಕೂಲವಾದಾಗ ಪಾವತಿಸಿ. ಧನ್ಯವಾದಗಳು!",
    "ta": "வணக்கம் {name} 🙏 {shop} கடையில் உங்கள் {amt} பாக்கி உள்ளது. வசதிப்படும்போது செலுத்தவும். நன்றி!",
    "en": "Hello {name} 🙏 You have {amt} pending at {shop}. Please clear it when convenient. Thank you!",
}
