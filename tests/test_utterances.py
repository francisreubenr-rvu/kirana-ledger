"""The sample utterance set doubles as a regression suite for the offline parser and the full agent."""
import json
from pathlib import Path

import pytest

from server import rule_parser
from server.agent import Agent
from server.config import Settings

SAMPLES = json.loads((Path(__file__).resolve().parent.parent / "samples" / "utterances.json").read_text(encoding="utf-8"))


def _lookup(ledger):
    return lambda q: (r["name"] if (r := ledger._find_item(q)) else None)


@pytest.mark.parametrize("s", SAMPLES, ids=[s["id"] for s in SAMPLES])
def test_rule_parser_matches_expected(ledger, s):
    customers = [c["name"] for c in ledger.snapshot()["customers"]]
    r = rule_parser.parse(s["text"], customers, _lookup(ledger))
    got = [(c["tool"], c["args"]) for c in r.calls]
    assert len(got) == len(s["expected"]), got
    for (tool, args), e in zip(got, s["expected"]):
        assert tool == e["tool"], got
        for k, v in e["args"].items():
            assert args.get(k) == v, (k, got)
    assert r.lang == s["lang"]


@pytest.mark.parametrize("s", SAMPLES, ids=[s["id"] for s in SAMPLES])
def test_agent_executes_every_sample(ledger, s):
    ag = Agent(Settings(force_mock=True, owner_lang="auto"), ledger)
    out = ag.handle_text(s["text"], speak=True)
    assert len(out["actions"]) == len(s["expected"])
    # payments/queries for customers with no history are still valid tool runs
    assert all(a["result"]["ok"] for a in out["actions"]), out["actions"]
    assert out["reply"] and out["_audio"][:4] == b"RIFF"
