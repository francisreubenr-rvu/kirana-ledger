"""Run the 2-minute demo sequence against a running server and print what the box would say.

    python scripts/demo.py                 # http://127.0.0.1:8000
    python scripts/demo.py http://192.168.1.50:8000
"""
import sys

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
STEPS = [
    "Ramesh ka 240 udhaar, 2 Aashirvaad 5kg bik gaye",
    "Lakshmi 300 kottru",
    "Murugan ku 200 kadan",
    "Fatima ko 3 Parle-G udhaar pe diye",
    "20 Maggi aaye",
    "Suresh ka kitna baaki hai",
    "aaj ka hisaab batao",
]

with httpx.Client(timeout=60, trust_env=False) as c:  # talk to the LAN server directly, not via a proxy
    c.post(f"{BASE}/reset")
    print("modes:", c.get(f"{BASE}/health").json()["modes"], "\n")
    for text in STEPS:
        j = c.post(f"{BASE}/text", json={"text": text, "speak": False}).json()
        print(f"🗣  {text}")
        for a in j["actions"]:
            print(f"   → {a['tool']}({a['args']})")
        print(f"🔊 [{j['lang']}] {j['reply']}\n")
    print("— WhatsApp summary —\n" + c.get(f"{BASE}/summary").json()["whatsapp_text"])
    print("\n— Reminders —")
    for r in c.get(f"{BASE}/reminders").json():
        print(f"{r['customer']}: {r['whatsapp_url'][:80]}…")
