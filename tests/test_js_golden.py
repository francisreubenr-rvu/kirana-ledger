"""Keeps the in-browser demo honest: tests/fixtures/js_golden.json must match what the Python code does today,
and (when node is installed) docs/js/kirana-core.js must reproduce it exactly."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _fresh_golden(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("mkgolden", ROOT / "scripts" / "make_js_golden.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_golden_fixture_is_current(tmp_path, monkeypatch):
    mod = _fresh_golden(tmp_path, monkeypatch)
    saved = (ROOT / "tests" / "fixtures" / "js_golden.json").read_text(encoding="utf-8")
    mod.main()  # rewrites the fixture from the current Python code
    now = (ROOT / "tests" / "fixtures" / "js_golden.json").read_text(encoding="utf-8")
    assert json.loads(now) == json.loads(saved), "python behaviour changed: commit the regenerated js_golden.json and re-check the JS port"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_port_matches_python():
    r = subprocess.run(["node", str(ROOT / "tests" / "js_parity.mjs")], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def test_cors_allows_pages_origin():
    from fastapi.testclient import TestClient

    from server.config import Settings
    from server.ledger import Ledger
    from server.main import create_app

    c = TestClient(create_app(Settings(force_mock=True, db_path=":memory:"), Ledger(":memory:")))
    r = c.options("/text", headers={"Origin": "https://francisreubenr-rvu.github.io", "Access-Control-Request-Method": "POST",
                                     "Access-Control-Request-Headers": "content-type",
                                     "Access-Control-Request-Private-Network": "true"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://francisreubenr-rvu.github.io"
    assert r.headers.get("access-control-allow-private-network") == "true"
    r = c.options("/text", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") is None
