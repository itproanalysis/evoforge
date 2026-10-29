"""T73 prompt Arena acceptance interface (API only).

Both lanes are told the interface the hidden acceptance tests call:
every ``app`` attribute the kept suite references (AST), its call
arities, and the string keys of dict literals passed to those calls.
"""
from __future__ import annotations

import difflib
import hashlib
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

JUDGE_STATE = ("import app\n"
               "def test_t73_judge_state():\n"
               "    html = app.render({'password': 'abc'})\n"
               "    assert 'abc' in html\n")
JUDGE_PLAIN = ("import app\n"
               "def test_t73_judge_plain():\n"
               "    assert '<main' in app.render()\n")


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
    ledger.reset()
    ledger.configure({"default": 500000})
    yield
    _settle()


def test_acceptance_interface_collects_attrs_arities_keys():
    suite = [{"code": "import app\ndef test_a():\n"
                      "    app.render()\n"},
             {"code": "import app\ndef test_b():\n"
                      "    app.render({'password': 'x', 'n': 1})\n"
                      "    app.preview()\n"}]
    assert arena_prompt.acceptance_interface(suite) == [
        {"name": "preview", "arities": [0], "keys": []},
        {"name": "render", "arities": [0, 1], "keys": ["n", "password"]},
    ]


def test_acceptance_interface_skips_unparsable_and_strings():
    suite = [{"code": "def broken(:\n"},
             {"code": "import app\ndef test_c():\n"
                      "    s = 'app.render({\"nope\": 1})'\n"
                      "    # app.preview()\n"
                      "    assert True\n"}]
    assert arena_prompt.acceptance_interface(suite) == []


def test_interface_text_empty_and_deterministic():
    assert arena_prompt.interface_text([]) == ""
    iface = [{"name": "render", "arities": [1], "keys": ["password"]}]
    text = arena_prompt.interface_text(iface)
    assert "render" in text and "1" in text and "password" in text
    assert arena_prompt.interface_text(iface) == text


def test_template_and_instructions_name_state_signature():
    assert "def render(state=None):" in arena_prompt.TEMPLATE
    assert "return render()" in arena_prompt.TEMPLATE
    assert "render(state" in arena_prompt.JUDGE_INSTRUCTION
    assert "dict" in arena_prompt.JUDGE_INSTRUCTION
    assert "render(state=None)" in arena_prompt.TASK_INSTRUCTION


def _candidate_diff():
    old = arena_prompt.TEMPLATE
    new = ("def render(state=None):\n"
           "    pw = ''\n"
           "    if isinstance(state, dict):\n"
           "        pw = str(state.get('password', ''))\n"
           "    return f'<main>{pw}</main>'\n"
           "\n"
           "\n"
           "def preview():\n"
           "    return render()\n")
    assert new != old
    return "".join(difflib.unified_diff(
        old.splitlines(True), new.splitlines(True),
        "a/app.py", "b/app.py"))


class _Stubs:
    def __init__(self, monkeypatch, judge_codes):
        self.judge_codes = list(judge_codes)
        self.builder_goals: list[str] = []
        self.critic_goals: list[str] = []
        self.diff = _candidate_diff()
        self.lock = threading.Lock()
        monkeypatch.setattr(broker_meta, "call_builder", self.builder)
        monkeypatch.setattr(broker_meta, "call_critic", self.critic)

    def builder(self, goal, sha, file_context=None, **k):
        with self.lock:
            self.builder_goals.append(goal)
        return {"diff": self.diff, "tests": [], "rationale": "x",
                "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": dict(USAGE)}

    def critic(self, goal, diff="", ci="", **k):
        with self.lock:
            if "File contents" in (goal or ""):
                self.critic_goals.append(goal)
                return {"sealed_tests": [], "stub": False,
                        "usage": dict(USAGE)}
        return {"sealed_tests": [{"code": t} for t in self.judge_codes],
                "stub": False, "usage": dict(USAGE)}


def _run(body):
    r = c.post("/v1/arena/prompt", json=body)
    assert r.status_code == 202, r.text
    aid = r.json()["arena_id"]
    end = time.time() + 300
    while time.time() < end:
        a = c.get(f"/v1/arena/{aid}").json()
        if a["status"] in ("succeeded", "failed"):
            return a
        time.sleep(0.3)
    pytest.fail("prompt arena did not finish")


def test_arena_goal_and_manifest_carry_the_kept_interface(monkeypatch):
    stubs = _Stubs(monkeypatch, [JUDGE_PLAIN, JUDGE_STATE])
    a = _run({"prompt": "a password strength meter"})
    assert a["status"] == "succeeded", a.get("error")
    kept = [{"code": JUDGE_STATE}]
    iface = arena_prompt.acceptance_interface(kept)
    assert iface == [{"name": "render", "arities": [1],
                      "keys": ["password"]}]
    text = arena_prompt.interface_text(iface)
    assert text
    m = a["manifest"]
    assert m["acceptance_interface"] == iface
    assert m["interface_hash"] == "sha256:" + hashlib.sha256(
        json.dumps(iface, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")).hexdigest()
    assert stubs.builder_goals
    for goal in stubs.builder_goals:
        assert text in goal
        assert "test_t73_judge_state" not in goal
        assert "test_t73_judge_plain" not in goal
    blob = repr(a)
    assert "test_t73_judge_state" not in blob
    assert "test_t73_judge_plain" not in blob
