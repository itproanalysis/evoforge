"""Sealed (Critic) — T66 prompt Arena follow-ups (owner: type at the bottom, watch the result evolve): a finished prompt
arena can take a follow-up instruction; each side continues from ITS OWN final code; the judge adds tests for the new
instruction (dropping ones both sides already pass), and the round is scored on the inherited + new suite, so a lost
earlier feature shows. The chain of rounds is readable."""
from __future__ import annotations

import difflib
import json
import os
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
FOLLOW = "Add a footer that shows the opening hours 7:00-19:00."
PARTIAL = "def render():\n    return '<main><h1>Coffee Corner</h1></main>'\n\n\ndef preview():\n    return render()\n"
FULL = ('def render():\n    items = "".join(f"<li>{n} {p}</li>" for n, p in (("Latte", "4.5"), ("Mocha", "5.0"), '
        '("Americano", "3.5")))\n    return f\'<main><h1>Coffee Corner</h1><ul class="menu">{items}</ul></main>\'\n\n\n'
        'def preview():\n    return render()\n')
FOOTER = FULL.replace("</ul></main>", "</ul><footer>Open 7:00-19:00</footer></main>")
ACCEPT = [
    "import xml.etree.ElementTree as ET\n\nimport app\n\n\ndef test_accept_title():\n"
    "    assert 'Coffee' in ''.join(ET.fromstring(app.render()).find('.//h1').itertext())\n",
    "import xml.etree.ElementTree as ET\n\nimport app\n\n\ndef test_accept_menu():\n"
    "    assert len(ET.fromstring(app.render()).findall(\".//ul[@class='menu']/li\")) >= 3\n",
    "import re\nimport xml.etree.ElementTree as ET\n\nimport app\n\n\ndef test_accept_prices():\n"
    "    items = ET.fromstring(app.render()).findall('.//li')\n"
    "    assert len(items) >= 3 and all(re.search(r'\\d+\\.\\d', ''.join(li.itertext())) for li in items)\n",
]
FOLLOW_ACCEPT = [
    "import xml.etree.ElementTree as ET\n\nimport app\n\n\ndef test_accept_footer_hours():\n"
    "    assert '7:00-19:00' in ''.join(ET.fromstring(app.render()).find('.//footer').itertext())\n",
    "import xml.etree.ElementTree as ET\n\nimport app\n\n\ndef test_accept_still_titled():\n"
    "    assert ET.fromstring(app.render()).find('.//h1') is not None\n",  # passes on both starts -> dropped
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


def _stubs(monkeypatch, seen):
    lock = threading.Lock()

    def builder(goal, sha, file_context=None, **k):
        current = next(f["content"] for f in (file_context or []) if f["path"] == "app.py")
        if REFERENCE_MARK in goal:  # T76/T80: the judge's reference build is never a lane call
            ref = FOOTER if FOLLOW in goal else FULL
            d = "".join(difflib.unified_diff(current.splitlines(True), ref.splitlines(True), "a/app.py", "b/app.py"))
            return {"diff": d, "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
                    "provider_calls": [], "usage": USAGE}
        if FOLLOW in goal:
            target = FOOTER
        else:
            target = FULL if "Previous attempt" in goal else PARTIAL
        with lock:
            seen.append((FOLLOW in goal, current, goal))
        d = "".join(difflib.unified_diff(current.splitlines(True), target.splitlines(True), "a/app.py", "b/app.py"))
        return {"diff": d, "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": USAGE}

    def critic(goal, diff, ci="", **k):
        tests = FOLLOW_ACCEPT if FOLLOW in (goal or "") and "File contents" not in goal else ACCEPT
        if "File contents" in (goal or ""):  # a lane's own Critic: its own names
            tests = [t.replace("def test_accept_", "def test_lane_") for t in (FOLLOW_ACCEPT + ACCEPT)]
        return {"sealed_tests": [{"code": t} for t in tests], "stub": False, "usage": USAGE}
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    monkeypatch.setattr(broker_meta, "call_critic", critic)


def _wait(aid):
    end = time.time() + 600
    while time.time() < end:
        a = c.get(f"/v1/arena/{aid}").json()
        if a["status"] in ("succeeded", "failed"):
            return a
        time.sleep(0.3)
    pytest.fail("arena did not finish")


def _root():
    r = c.post("/v1/arena/prompt", json={"prompt": PROMPT})
    assert r.status_code == 202, r.text
    return _wait(r.json()["arena_id"])


def test_follow_up_continues_each_side_from_its_own_code(monkeypatch):
    seen = []
    _stubs(monkeypatch, seen)
    root = _root()
    assert root["lanes"]["single"]["heldout"] == {"passed": 1, "n": 3}
    r = c.post(f"/v1/arena/{root['arena_id']}/followup", json={"prompt": FOLLOW})
    assert r.status_code == 202, r.text
    f = _wait(r.json()["arena_id"])
    assert f["mode"] == "prompt" and f["parent_id"] == root["arena_id"] and f["round_index"] == 2
    starts = {cur for is_follow, cur, _g in seen if is_follow}
    assert starts == {PARTIAL, FULL}  # single resumed from its partial page, EvoForge from its full one
    m = f["manifest"]
    assert (m["acceptance_inherited"], m["acceptance_new"], m["acceptance_dropped"], m["acceptance_count"]) == (3, 1, 1, 4)
    assert f["lanes"]["single"]["heldout"] == {"passed": 4, "n": 4} and f["lanes"]["evoforge"]["heldout"]["n"] == 4
    for lane in ("single", "evoforge"):
        assert "7:00-19:00" in f["lanes"][lane]["preview_html"]


def test_chain_lists_rounds_and_nothing_secret_leaks(monkeypatch):
    seen = []
    _stubs(monkeypatch, seen)
    root = _root()
    f = _wait(c.post(f"/v1/arena/{root['arena_id']}/followup", json={"prompt": FOLLOW}).json()["arena_id"])
    chain = c.get(f"/v1/arena/{root['arena_id']}/chain").json()["rounds"]
    assert [x["arena_id"] for x in chain] == [root["arena_id"], f["arena_id"]]
    assert [x["round_index"] for x in chain] == [1, 2] and chain[1]["prompt"] == FOLLOW
    assert c.get(f"/v1/arena/{f['arena_id']}/chain").json()["rounds"][0]["arena_id"] == root["arena_id"]
    blob = json.dumps(f) + json.dumps(chain)
    for name in ("test_accept_title", "test_accept_menu", "test_accept_prices", "test_accept_footer_hours"):
        assert name not in blob
        assert all(name not in g for _f, _c, g in seen)


def test_follow_up_validation(monkeypatch):
    _stubs(monkeypatch, [])
    assert c.post("/v1/arena/arena_missing/followup", json={"prompt": FOLLOW}).status_code == 404
    root = _root()
    assert c.post(f"/v1/arena/{root['arena_id']}/followup", json={"prompt": ""}).status_code == 422
    assert c.post(f"/v1/arena/{root['arena_id']}/followup", json={"prompt": "x" * 2001}).status_code == 422
