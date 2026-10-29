"""Sealed (Critic) — T64 prompt Arena (owner: the real service compares what the USER asks for, typed in the input at the
bottom of the Arena). Before either lane runs, an independent judge Critic writes acceptance tests from the prompt
only; tests that already pass on the starting template are dropped; the suite is fixed (hashed) and never shown to a
lane; both lanes build from the same template with the same patch tolerance; both are scored on that suite and their
rendered pages are returned. Too few meaningful tests -> "unscorable", never an invented winner."""
from __future__ import annotations

import difflib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
REFERENCE_MARK = getattr(__import__("evoforge.arena_prompt", fromlist=["x"]), "REFERENCE_MARKER", "<no reference build>")
USAGE = {"prompt_tokens": 1000, "completion_tokens": 200}
PROMPT = "A landing page for a coffee shop called Coffee Corner with a menu of at least three drinks and their prices."
PARTIAL = '''def render():
    return '<main><h1>Coffee Corner</h1></main>'


def preview():
    return render()
'''
FULL = '''def render():
    items = "".join(f"<li>{name} {price}</li>" for name, price in (("Latte", "4.5"), ("Mocha", "5.0"), ("Americano", "3.5")))
    return f'<main><h1>Coffee Corner</h1><ul class="menu">{items}</ul></main>'


def preview():
    return render()
'''
ACCEPT = [
    "import re\nimport xml.etree.ElementTree as ET\n\nimport app\n\n\ndef test_accept_title():\n"
    "    e = ET.fromstring(app.render())\n    assert 'Coffee' in ''.join(e.find('.//h1').itertext())\n",
    "import xml.etree.ElementTree as ET\n\nimport app\n\n\ndef test_accept_menu_items():\n"
    "    e = ET.fromstring(app.render())\n    assert len(e.findall(\".//ul[@class='menu']/li\")) >= 3\n",
    "import re\nimport xml.etree.ElementTree as ET\n\nimport app\n\n\ndef test_accept_prices():\n"
    "    items = ET.fromstring(app.render()).findall('.//li')\n"
    "    assert len(items) >= 3 and all(re.search(r'\\d+\\.\\d', ''.join(li.itertext())) for li in items)\n",
    "import app\n\n\ndef test_accept_trivially_true_on_template():\n    assert '<main' in app.render()\n",
]


def _settle(limit=300):
    end = time.time() + limit
    while time.time() < end and any(j["status"] in ("queued", "running") for j in c.get("/v1/eval/jobs").json()["jobs"]):
        time.sleep(0.3)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    _settle()
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset(); ledger.configure({"default": 500000})
    yield
    _settle()


def _stubs(monkeypatch, goals, accept=ACCEPT):
    lock = threading.Lock()

    def builder(goal, sha, file_context=None, **k):
        current = next(f["content"] for f in (file_context or []) if f["path"] == "app.py")
        # T76: the judge's reference build (marked) is a correct page; lanes' first tries miss the menu
        target = FULL if ("Previous attempt" in goal or REFERENCE_MARK in goal) else PARTIAL
        with lock:
            goals.append(goal)
        d = "".join(difflib.unified_diff(current.splitlines(True), target.splitlines(True), "a/app.py", "b/app.py"))
        return {"diff": d, "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": USAGE}

    def critic(goal, diff, ci="", **k):
        tests = list(accept)
        if "File contents" in (goal or ""):
            # The EvoForge lane's OWN Critic (sealed_eval._critic_goal_for_task adds the file contents): its tests have
            # their own names, so its retry feedback may name them; the judge's names must never reach a lane.
            tests = [t.replace("def test_accept_", "def test_lane_") for t in tests]
        return {"sealed_tests": [{"code": t} for t in tests], "stub": False, "usage": USAGE}
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    monkeypatch.setattr(broker_meta, "call_critic", critic)


def _run(body):
    r = c.post("/v1/arena/prompt", json=body)
    assert r.status_code == 202, r.text
    aid = r.json()["arena_id"]
    end = time.time() + 600
    while time.time() < end:
        a = c.get(f"/v1/arena/{aid}").json()
        if a["status"] in ("succeeded", "failed"):
            return a
        time.sleep(0.3)
    pytest.fail("prompt arena did not finish")


def test_user_prompt_is_compared_on_a_fixed_acceptance_suite(monkeypatch):
    goals = []
    _stubs(monkeypatch, goals)
    a = _run({"prompt": PROMPT})
    assert a["mode"] == "prompt" and a["status"] == "succeeded"
    m = a["manifest"]
    assert m["acceptance_count"] == 3 and m["acceptance_dropped"] == 1  # the template-passing test is dropped
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", m["acceptance_hash"]) and re.fullmatch(r"sha256:[0-9a-f]{64}", m["prompt_hash"])
    assert m["judge"] and m["lanes"]["single"]["apply"] == "tolerant"  # equal tools by default for user prompts
    single, evo = a["lanes"]["single"], a["lanes"]["evoforge"]
    assert single["heldout"] == {"passed": 1, "n": 3} and evo["heldout"] == {"passed": 3, "n": 3}
    assert a["verdict"]["winner"] == "evoforge"
    for lane in (single, evo):
        assert lane["preview_source"] == "candidate" and "Coffee Corner" in lane["preview_html"]


def test_acceptance_tests_never_reach_a_lane_or_the_response(monkeypatch):
    goals = []
    _stubs(monkeypatch, goals)
    blob = json.dumps(_run({"prompt": PROMPT}))
    for name in ("test_accept_title", "test_accept_menu_items", "test_accept_prices"):
        assert name not in blob
        assert all(name not in g for g in goals)  # neither Builder ever saw the judge's tests
    assert all(PROMPT in g for g in goals)


def test_too_few_meaningful_tests_is_unscorable_not_a_win(monkeypatch):
    _stubs(monkeypatch, [], accept=[ACCEPT[3]])  # only a test that passes on the empty template
    a = _run({"prompt": PROMPT})
    assert a["verdict"]["winner"] == "unscorable" and a["manifest"]["acceptance_count"] == 0
    assert "Coffee Corner" in a["lanes"]["single"]["preview_html"]  # the pages are still shown side by side


def test_validation_and_budget(monkeypatch):
    assert c.post("/v1/arena/prompt", json={"prompt": ""}).status_code == 422
    assert c.post("/v1/arena/prompt", json={"prompt": "x" * 2001}).status_code == 422
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "1")
    monkeypatch.setattr(broker_meta, "call_builder", lambda *a, **k: pytest.fail("provider called despite cap"))
    monkeypatch.setattr(broker_meta, "call_critic", lambda *a, **k: pytest.fail("provider called despite cap"))
    assert c.post("/v1/arena/prompt", json={"prompt": PROMPT}).status_code == 402
    web = Path(__file__).resolve().parents[3] / "apps" / "web" / "lib" / "proxyPolicy.ts"
    assert "/v1/arena/prompt" in web.read_text(encoding="utf-8")
