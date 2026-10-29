"""Sealed (Critic) — T80 follow-up rounds check the judge's NEW tests against a judge reference build too (T76 covered
only the first round). The follow-up reference is one Builder call marked arena_prompt.REFERENCE_MARKER with the
follow-up goal (earlier requests as context), from the template; a new test it cannot pass is not scored; inherited
tests were already checked in their own round. Lanes still resume from their own code."""
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
from evoforge import arena_prompt, broker_meta, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
MARK = arena_prompt.REFERENCE_MARKER
USAGE = {"prompt_tokens": 1000, "completion_tokens": 200}
PROMPT = "A landing page for a coffee shop called Coffee Corner with a menu of at least three drinks and their prices."
FOLLOW = "Add a footer that shows the opening hours 7:00-19:00."
PARTIAL = "def render(state=None):\n    return '<main><h1>Coffee Corner</h1></main>'\n\n\ndef preview():\n    return render()\n"
FULL = ('def render(state=None):\n    items = "".join(f"<li>{n} {p}</li>" for n, p in (("Latte", "4.5"), ("Mocha", "5.0"), '
        '("Americano", "3.5")))\n    return f\'<main><h1>Coffee Corner</h1><ul class="menu">{items}</ul></main>\'\n\n\n'
        'def preview():\n    return render()\n')
FOOTER = FULL.replace("</ul></main>", "</ul><footer>Open 7:00-19:00</footer></main>")
H = "import re\nimport xml.etree.ElementTree as ET\n\nimport app\n\n\n"
ACCEPT = [
    H + "def test_accept_title():\n    assert 'Coffee' in ''.join(ET.fromstring(app.render()).find('.//h1').itertext())\n",
    H + "def test_accept_menu():\n    assert len(ET.fromstring(app.render()).findall(\".//ul[@class='menu']/li\")) >= 3\n",
    H + "def test_accept_prices():\n    items = ET.fromstring(app.render()).findall('.//li')\n"
        "    assert len(items) >= 3 and all(re.search(r'\\d+\\.\\d', ''.join(li.itertext())) for li in items)\n",
]
FOLLOW_ACCEPT = [
    H + "def test_accept_footer_hours():\n    assert '7:00-19:00' in ''.join(ET.fromstring(app.render()).find('.//footer').itertext())\n",
    H + "def test_accept_follow_impossible():\n    assert app.render().count('<footer>') == 7\n",  # no correct page passes
]


def _settle(limit=300):
    end = time.time() + limit
    while time.time() < end and any(j["status"] in ("queued", "running") for j in c.get("/v1/eval/jobs").json()["jobs"]):
        time.sleep(0.3)


@pytest.fixture
def stubs(monkeypatch):
    _settle()
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset(); ledger.configure({"default": 500000})
    rec = {"refs": [], "lanes": []}
    lock = threading.Lock()

    def builder(goal, sha, file_context=None, **k):
        current = next(f["content"] for f in (file_context or []) if f["path"] == "app.py")
        if MARK in goal:
            target = FOOTER if FOLLOW in goal else FULL
            with lock:
                rec["refs"].append((FOLLOW in goal, current))
        else:
            target = FOOTER if FOLLOW in goal else (FULL if "Previous attempt" in goal else PARTIAL)
            with lock:
                rec["lanes"].append((FOLLOW in goal, current, goal))
        d = "".join(difflib.unified_diff(current.splitlines(True), target.splitlines(True), "a/app.py", "b/app.py"))
        return {"diff": d, "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": USAGE}

    def critic(goal, diff, ci="", **k):
        if "File contents" in (goal or ""):  # a lane's own Critic
            tests = [t.replace("def test_accept_", "def test_lane_") for t in ACCEPT]
        else:
            tests = FOLLOW_ACCEPT if FOLLOW in (goal or "") else ACCEPT
        return {"sealed_tests": [{"code": t} for t in tests], "stub": False, "usage": USAGE}
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    monkeypatch.setattr(broker_meta, "call_critic", critic)
    yield rec
    _settle()


def _wait(aid):
    end = time.time() + 600
    while time.time() < end:
        a = c.get(f"/v1/arena/{aid}").json()
        if a["status"] in ("succeeded", "failed"):
            return a
        time.sleep(0.3)
    pytest.fail("arena did not finish")


def test_follow_up_new_tests_are_checked_against_a_reference(stubs):
    r = c.post("/v1/arena/prompt", json={"prompt": PROMPT})
    root = _wait(r.json()["arena_id"])
    assert root["manifest"]["acceptance_count"] == 3
    r = c.post(f"/v1/arena/{root['arena_id']}/followup", json={"prompt": FOLLOW})
    assert r.status_code == 202, r.text
    f = _wait(r.json()["arena_id"])
    assert f["status"] == "succeeded", f.get("error")
    m = f["manifest"]
    assert m["reference_checked"] is True and m["acceptance_reference_dropped"] == 1
    assert (m["acceptance_inherited"], m["acceptance_new"], m["acceptance_count"]) == (3, 1, 4)
    assert [is_follow for is_follow, _cur in stubs["refs"]] == [False, True]  # one reference per round
    assert all(MARK not in g for _f, _c, g in stubs["lanes"])
    starts = {cur for is_follow, cur, _g in stubs["lanes"] if is_follow}
    assert starts == {PARTIAL, FULL}  # lanes still resume from their own code (single partial, EvoForge full)
    assert f["lanes"]["single"]["heldout"]["n"] == 4 and f["lanes"]["evoforge"]["heldout"]["n"] == 4
    from evoforge import performance
    assert f["judge_cost_cents"] >= 2 * performance.usage_cost_cents(USAGE)  # judge call + reference call
    assert "test_accept_follow_impossible" not in json.dumps(f)
