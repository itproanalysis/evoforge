"""Sealed (Critic) — T76 prompt Arena: the judge's hidden tests must be satisfiable. Production 2026-10-30 (password
meter): both lanes scored 0/5 and later 0/3 while a fresh judge suite for the same prompt passed 3/3 on BOTH
candidates — the production judge suite was wrong, and nothing checked it. Before the lanes run, the judge also builds
a reference app.py (one Builder call marked arena_prompt.REFERENCE_MARKER, from the prompt only); only acceptance tests
that PASS on that reference (and still fail on the empty template) are scored. Fewer than 3 left -> "unscorable",
never a tie or a win. The reference never reaches a lane or the response; its cost is part of the judge cost."""
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
USAGE = {"prompt_tokens": 1000, "completion_tokens": 200}
PROMPT = "A landing page for a tea shop called Leaf and Cup with a menu of at least three teas and their prices."


def _app(title, items, extra=""):
    lis = "".join(f"<li>{n} {p}</li>" for n, p in items)
    return (f"def render(state=None):\n    return '<main><h1>{title}</h1><ul class=\"menu\">{lis}</ul>{extra}</main>'\n\n\n"
            "def preview():\n    return render()\n")


THREE = (("Sencha", "4.5"), ("Earl Grey", "4.0"), ("Chai", "5.0"))
REFERENCE = _app("Leaf and Cup", THREE, "<p class=\"marker\">REFERENCE-ONLY-7f3a</p>")
EVO = _app("Leaf and Cup", THREE)
SINGLE = _app("Leaf and Cup", (("Sencha", "4.5"),))
T = "import re\nimport xml.etree.ElementTree as ET\n\nimport app\n\n\n"
VALID = [
    T + "def test_accept_title():\n    e = ET.fromstring(app.render())\n    assert 'Leaf' in ''.join(e.find('.//h1').itertext())\n",
    T + "def test_accept_menu():\n    e = ET.fromstring(app.render())\n    assert len(e.findall(\".//ul[@class='menu']/li\")) >= 3\n",
    T + "def test_accept_prices():\n    items = ET.fromstring(app.render()).findall('.//li')\n"
        "    assert len(items) >= 3 and all(re.search(r'\\d+\\.\\d', ''.join(li.itertext())) for li in items)\n",
]
WRONG = T + "def test_accept_impossible():\n    assert app.render().count('<li>') == 99\n"  # no correct page passes this


def _settle(limit=300):
    end = time.time() + limit
    while time.time() < end and any(j["status"] in ("queued", "running") for j in c.get("/v1/eval/jobs").json()["jobs"]):
        time.sleep(0.3)


def _stubs(monkeypatch, suite, reference=REFERENCE):
    _settle()
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset(); ledger.configure({"default": 500000})
    calls, lock = {"reference": 0, "lane_goals": []}, threading.Lock()

    def builder(goal, sha, file_context=None, **k):
        current = next(f["content"] for f in (file_context or []) if f["path"] == "app.py")
        if arena_prompt.REFERENCE_MARKER in goal:
            with lock:
                calls["reference"] += 1
            target = reference
        else:
            with lock:
                calls["lane_goals"].append(goal)
            target = EVO if "Previous attempt" in goal else SINGLE  # first tries miss the menu; a retry fixes it
        d = "".join(difflib.unified_diff(current.splitlines(True), target.splitlines(True), "a/app.py", "b/app.py"))
        return {"diff": d, "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": USAGE}

    def critic(goal, diff, ci="", **k):
        tests = list(suite)
        if "File contents" in (goal or ""):  # the EvoForge lane's own Critic
            tests = [t.replace("def test_accept_", "def test_lane_") for t in VALID]
        return {"sealed_tests": [{"code": t} for t in tests], "stub": False, "usage": USAGE}
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    monkeypatch.setattr(broker_meta, "call_critic", critic)
    return calls


def _run():
    r = c.post("/v1/arena/prompt", json={"prompt": PROMPT})
    assert r.status_code == 202, r.text
    aid = r.json()["arena_id"]
    end = time.time() + 600
    while time.time() < end:
        a = c.get(f"/v1/arena/{aid}").json()
        if a["status"] in ("succeeded", "failed"):
            return a
        time.sleep(0.3)
    pytest.fail("prompt arena did not finish")


def test_tests_the_reference_cannot_pass_are_not_scored(monkeypatch):
    calls = _stubs(monkeypatch, VALID + [WRONG])
    a = _run()
    assert a["status"] == "succeeded", a.get("error")
    m = a["manifest"]
    assert calls["reference"] == 1
    assert m["acceptance_count"] == 3 and m["acceptance_reference_dropped"] == 1 and m["reference_checked"] is True
    assert a["lanes"]["single"]["heldout"]["n"] == 3 and a["lanes"]["evoforge"]["heldout"]["n"] == 3
    blob = json.dumps(a)
    assert "REFERENCE-ONLY-7f3a" not in blob and "test_accept_impossible" not in blob
    assert all(arena_prompt.REFERENCE_MARKER not in g and "REFERENCE-ONLY-7f3a" not in g for g in calls["lane_goals"])
    # the reference build is part of the judge's cost (judge Critic call + reference Builder call)
    from evoforge import performance
    assert a["judge_cost_cents"] >= 2 * performance.usage_cost_cents(USAGE)
    assert a["verdict"]["winner"] == "evoforge"  # 1/3 vs 3/3 on the reference-checked suite


def test_judge_suite_the_reference_fails_is_unscorable_not_a_tie(monkeypatch):
    broken = _app("Somewhere Else", ())  # a reference that passes none of the valid tests
    _stubs(monkeypatch, VALID + [WRONG], reference=broken)
    a = _run()
    assert a["verdict"]["winner"] == "unscorable"
    assert "reference" in a["verdict"]["reason"].lower()
    assert a["manifest"]["acceptance_count"] < 3 and a["manifest"]["reference_checked"] is True
