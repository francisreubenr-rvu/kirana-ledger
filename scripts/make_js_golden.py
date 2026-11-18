"""Write tests/fixtures/js_golden.json: what the Python offline path does for every sample utterance plus
extra variants. tests/js_parity.mjs replays the same inputs through docs/js/kirana-core.js and must match.

    python scripts/make_js_golden.py && node tests/js_parity.mjs
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["KIRANA_NO_AUTOAPP"] = "1"
os.environ.pop("SARVAM_API_KEY", None)

from server import rule_parser  # noqa: E402
from server.agent import Agent  # noqa: E402
from server.config import Settings  # noqa: E402
from server.ledger import Ledger  # noqa: E402

EXTRA = [
    "Laxmi ne 100 jama kiye", "Ramesh ka kitna baaki", "Sures 50 kottru", "5 Haldiram bhujia aaye",
    "2 Haldiram bhujia bik gaye", "Sold 3 maggi", "Fatima ko 2 doodh udhaar", "Vikram ne 20 diye",
    "Nobody 50 jama", "aaj ka hisaab", "Murugan kku 75 kadan", "Muruganukku 30 kadan", "3 sugar becha ₹150",
    "Rs 60 Ramesh ne wapas kiye", "4 Surf Excel bik gaye", "1 Surf Excel bik gaya", "teen Parle-G becha",
    "Suresh ne 400 jama kiye", "Suresh ka kitna baaki hai", "Ramesh ಅವರಿಗೆ 20 ಸಾಲ", "Lakshmi ने 50 दिए",
    "Murugan எவ்வளவு பாக்கி", "hello there", "summary", "10 Toor dal kharab, stock se hatao",
    "Rameshge 10 saala mattu 1 sakkare maaratu", "Lakshmi 1,200 kottru", "2.5 sugar bik gaye",
    "Ravi ka 99.50 udhaar", "Ravi ka kitna baaki", "indina lekka", "inniki kanakku",
    # Kannada/Tamil/Hindi payment forms, Indian digit grouping, fuzzy + ambiguous names
    "Sures ka kitna baaki", "Sures eshtu baaki", "Rameshge 40 kottru", "Fatima ko 2 Maggi diye", "Laksmi 10 kottru",
    "Lakshmi 12,34,567 kottru", "Suresh 25 ವಾಪಸ್ ಕೊಟ್ಟ", "Murugan 30 kuduthaanga", "Fatima ने 15 लौटाए",
    "Rajesh ka 40 udhaar", "Raesh 10 kottru", "Sur 5 jama", "ಸುರೇಶ್ 50 ಕೊಟ್ಟರು",
    # stock never below zero
    "8 Surf Excel bik gaye", "Surf Excel ಮಾರಾಟ", "5 Fortune oil kharab, stock se hatao", "20 Fortune oil kharab",
    "3 Surf Excel aaye", "Suresh ka kitna baaki",
]


def main():
    samples = json.loads((ROOT / "samples" / "utterances.json").read_text(encoding="utf-8"))
    texts = [s["text"] for s in samples] + EXTRA
    led = Ledger(":memory:", shop_name="Sri Lakshmi Kirana")
    led.seed_demo(opening_balances=True)
    lookup = lambda q: (r["name"] if (r := led._find_item(q)) else None)  # noqa: E731
    customers = [c["name"] for c in led.snapshot()["customers"]]
    parses = []
    for t in texts:
        r = rule_parser.parse(t, customers, lookup)
        parses.append({"text": t, "lang": r.lang, "calls": r.calls})
    ag = Agent(Settings(force_mock=True, owner_lang="auto", shop_name="Sri Lakshmi Kirana"), led)
    run = []
    for t in texts:
        out = ag.handle_text(t, speak=False)
        run.append({"text": t, "lang": out["lang"], "reply": out["reply"],
                    "actions": [{"tool": a["tool"], "args": a["args"], "ok": a["result"]["ok"]} for a in out["actions"]]})
    snap = led.snapshot(limit=200)
    final = {
        "customers": {c["name"]: c["balance"] for c in snap["customers"]},
        "items": {i["name"]: i["stock"] for i in snap["items"]},
        "sales": len(snap["sales"]),
    }
    out = {"seed_customers": customers, "parses": parses, "run": run, "final": final}
    path = ROOT / "tests" / "fixtures" / "js_golden.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}: {len(parses)} parses, {len(run)} agent turns")


if __name__ == "__main__":
    main()
