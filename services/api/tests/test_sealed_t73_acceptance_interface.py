"""Sealed (Critic) — T73 prompt Arena: a hidden acceptance suite is only fair if both lanes can build the interface it
calls. Production 2026-10-30 (password meter): EvoForge's own Critic 3/3, yet the judge's hidden tests 0/5 for BOTH
lanes — the tests called an interface neither lane was told about. The interface the judge's tests use (functions on
`app`, their argument counts, the keys of dict literals passed to them) is derived from the kept suite and given to
both Builders in the same words; expected values, test names and test code stay hidden."""
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
from evoforge import arena_prompt, broker_meta, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
USAGE = {"prompt_tokens": 1000, "completion_tokens": 200}
PROMPT = "A password strength meter: one password input and a label Weak, Fair or Strong."
SUITE = [
    "import xml.etree.ElementTree as ET\n\nimport app\n\n\ndef test_accept_weak_label():\n"
    "    e = ET.fromstring(app.render({'password': 'abc'}))\n    assert 'Weak' in ''.join(e.itertext())\n",
    "import xml.etree.ElementTree as ET\n\nimport app\n\n\ndef test_accept_strong_label():\n"
    "    e = ET.fromstring(app.render({'password': 'Abcdefgh12!x'}))\n    assert 'Strong' in ''.join(e.itertext())\n",
    "import app\n\n\ndef test_accept_score_function():\n    assert app.strength_label(3) == 'Fair'\n",
    "import xml.etree.ElementTree as ET\n\nimport app\n\n\ndef test_accept_has_input():\n"
    "    e = ET.fromstring(app.render())\n    assert e.find('.//input') is not None\n",
]
TARGET = '''def strength_label(score):
    return "Weak" if score <= 1 else "Fair" if score <= 3 else "Strong"


def _score(pw):
    return (len(pw) >= 8) + (len(pw) >= 12) + any(ch.isdigit() for ch in pw) + any(not ch.isalnum() for ch in pw)


def render(state=None):
    pw = (state or {}).get("password", "")
    label = strength_label(_score(pw)) if pw else ""
    return f'<main><input type="password" id="password" /><span id="label">{label}</span></main>'


def preview():
    return render()
'''


def test_interface_is_derived_from_the_suite_without_expected_values():
    iface = arena_prompt.acceptance_interface([{"code": t} for t in SUITE])
    assert iface == [{"name": "render", "arities": [0, 1], "keys": ["password"]},
                     {"name": "strength_label", "arities": [1], "keys": []}]
    text = arena_prompt.interface_text(iface)
    assert text == arena_prompt.interface_text(list(reversed(iface)))  # deterministic
    assert "render" in text and "password" in text and "strength_label" in text
    for hidden in ("Weak", "Strong", "Fair", "abc", "Abcdefgh12!x", "test_accept", "assert", "itertext"):
        assert hidden not in text, hidden
    assert arena_prompt.acceptance_interface([]) == [] and arena_prompt.interface_text([]) == ""


def test_template_and_judge_support_input_state():
    ns: dict = {}
    exec(arena_prompt.TEMPLATE, ns)
    assert ns["render"]() == ns["render"]({}) == ns["preview"]()
    assert "render(state)" in arena_prompt.JUDGE_INSTRUCTION
    assert "render(state" in arena_prompt.TASK_INSTRUCTION


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
    goals, lock = [], threading.Lock()

    def builder(goal, sha, file_context=None, **k):
        current = next(f["content"] for f in (file_context or []) if f["path"] == "app.py")
        with lock:
            goals.append(goal)
        d = "".join(difflib.unified_diff(current.splitlines(True), TARGET.splitlines(True), "a/app.py", "b/app.py"))
        return {"diff": d, "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": USAGE}

    def critic(goal, diff, ci="", **k):
        tests = list(SUITE)
        if "File contents" in (goal or ""):  # the EvoForge lane's own Critic
            tests = [t.replace("def test_accept_", "def test_lane_") for t in tests]
        return {"sealed_tests": [{"code": t} for t in tests], "stub": False, "usage": USAGE}
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    monkeypatch.setattr(broker_meta, "call_critic", critic)
    yield goals
    _settle()


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


def test_both_lanes_get_the_same_interface_and_can_pass(stubs):
    a = _run({"prompt": PROMPT})
    assert a["status"] == "succeeded", a.get("error")
    m = a["manifest"]
    assert m["acceptance_count"] == 4
    assert m["acceptance_interface"] == arena_prompt.acceptance_interface([{"code": t} for t in SUITE])
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", m["interface_hash"])
    text = arena_prompt.interface_text(m["acceptance_interface"])
    assert stubs and all(text in g for g in stubs)  # every Builder call of both lanes saw the same interface
    for g in stubs:
        assert "test_accept_" not in g and "'Weak'" not in g and "Abcdefgh12!x" not in g
    assert a["lanes"]["single"]["heldout"] == {"passed": 4, "n": 4}
    assert a["lanes"]["evoforge"]["heldout"] == {"passed": 4, "n": 4}
    blob = json.dumps(a)
    assert "test_accept_weak_label" not in blob and "Abcdefgh12!x" not in blob
