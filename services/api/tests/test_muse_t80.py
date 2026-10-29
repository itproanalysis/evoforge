"""T80 prompt-Arena follow-ups check NEW judge tests against a judge reference build."""
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

KEEP_A = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t80_keep_a_has_text():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert (root.text or '').strip() != ''\n")
KEEP_B = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t80_keep_b_hello():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert 'hello' in (root.text or '')\n")
KEEP_C = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t80_keep_c_world():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert 'world' in (root.text or '')\n")
NEW_GOOD = ("import app\n"
            "def test_t80_new_good_goodbye():\n"
            "    assert 'goodbye' in app.render()\n")
NEW_BAD_X = ("import app\n"
             "def test_t80_new_bad_x_meter():\n"
             "    assert 'meter' in app.render()\n")
NEW_BAD_Y = ("import app\n"
             "def test_t80_new_bad_y_strong():\n"
             "    assert 'strong' in app.render()\n")


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


def _diff(old: str, new: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(True), new.splitlines(True),
        "a/app.py", "b/app.py"))


HELLO = arena_prompt.TEMPLATE.replace("'<main></main>'",
                                       "'<main>hello world</main>'")
HELLO_GOODBYE = arena_prompt.TEMPLATE.replace(
    "'<main></main>'", "'<main>hello world goodbye</main>'")
REF_PAGE = arena_prompt.TEMPLATE.replace(
    "'<main></main>'", "'<main>hello world goodbye t80refok</main>'")


class _Stubs:
    """Judge codes per Critic round; reference vs lane Builder diffs."""

    def __init__(self, monkeypatch, judge_rounds):
        self.judge_rounds = list(judge_rounds)
        self.judge_calls: list[str] = []
        self.builder_goals: list[str] = []
        self.builder_contexts: list = []
        self.lock = threading.Lock()
        monkeypatch.setattr(broker_meta, "call_builder", self.builder)
        monkeypatch.setattr(broker_meta, "call_critic", self.critic)

    def builder(self, goal, sha, file_context=None, **k):
        with self.lock:
            self.builder_goals.append(goal)
            self.builder_contexts.append(file_context)
            cur = next((f["content"] for f in (file_context or [])
                        if f["path"] == "app.py"),
                       arena_prompt.TEMPLATE)
        if arena_prompt.REFERENCE_MARKER in (goal or ""):
            target = REF_PAGE
            return {"diff": _diff(cur, target), "tests": [],
                    "rationale": "x", "stub": False,
                    "model": "muse-spark-1.3", "provider_calls": [],
                    "usage": dict(USAGE)}
        if "goodbye" in (goal or "").lower() or "goodbye" in (cur or ""):
            target = HELLO_GOODBYE
        else:
            target = HELLO
        return {"diff": _diff(cur, target), "tests": [],
                "rationale": "x", "stub": False,
                "model": "muse-spark-1.3", "provider_calls": [],
                "usage": dict(USAGE)}

    def critic(self, goal, diff="", ci="", **k):
        if "File contents" in (goal or ""):
            return {"sealed_tests": [], "stub": False,
                    "usage": dict(USAGE)}
        with self.lock:
            idx = len(self.judge_calls)
            self.judge_calls.append(goal)
        codes = self.judge_rounds[idx] if idx < len(self.judge_rounds) else []
        return {"sealed_tests": [{"code": t} for t in codes],
                "stub": False, "usage": dict(USAGE)}

    def reference_goals(self):
        return [g for g in self.builder_goals
                if arena_prompt.REFERENCE_MARKER in (g or "")]

    def lane_goals(self):
        return [g for g in self.builder_goals
                if arena_prompt.REFERENCE_MARKER not in (g or "")]


def _run_prompt(body):
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


def _run_followup(pid, body):
    r = c.post(f"/v1/arena/{pid}/followup", json=body)
    assert r.status_code == 202, r.text
    aid = r.json()["arena_id"]
    end = time.time() + 300
    while time.time() < end:
        a = c.get(f"/v1/arena/{aid}").json()
        if a["status"] in ("succeeded", "failed"):
            return a
        time.sleep(0.3)
    pytest.fail("followup did not finish")


def test_followup_wrong_new_tests_dropped_by_reference(monkeypatch):
    stubs = _Stubs(monkeypatch,
                   [[KEEP_A, KEEP_B, KEEP_C],
                    [NEW_GOOD, NEW_BAD_X, NEW_BAD_Y]])
    root = _run_prompt({"prompt": "say hello world please"})
    assert root["status"] == "succeeded", root.get("error")
    assert root["manifest"]["acceptance_count"] == 3
    child = _run_followup(root["arena_id"], {"prompt": "also say goodbye"})
    assert child["status"] == "succeeded", child.get("error")
    # ONE follow-up reference on top of the first-round one.
    assert len(stubs.reference_goals()) == 2
    follow_ref = stubs.reference_goals()[1]
    assert follow_ref.startswith(arena_prompt.REFERENCE_MARKER + "\n\n")
    lane_goals = stubs.lane_goals()
    assert lane_goals, "lanes never ran"
    assert follow_ref[len(arena_prompt.REFERENCE_MARKER) + 2:] in lane_goals
    ref_idx = stubs.builder_goals.index(follow_ref)
    assert stubs.builder_contexts[ref_idx] == [
        {"path": "app.py", "content": arena_prompt.TEMPLATE}]
    m = child["manifest"]
    assert m["reference_checked"] is True
    assert m["acceptance_reference_dropped"] == 2
    assert m["acceptance_inherited"] == 3
    assert m["acceptance_new"] == 1
    assert m["acceptance_count"] == 4
    assert m["acceptance_dropped"] == 0
    assert m["acceptance_hash"] == "sha256:" + hashlib.sha256(
        json.dumps([KEEP_A, KEEP_B, KEEP_C, NEW_GOOD]).encode(
            "utf-8")).hexdigest()
    assert m["acceptance_interface"] == arena_prompt.acceptance_interface(
        [{"code": KEEP_A}, {"code": KEEP_B}, {"code": KEEP_C},
         {"code": NEW_GOOD}])
    assert child["lanes"]["single"]["heldout"]["n"] == 4
    assert child["lanes"]["evoforge"]["heldout"]["n"] == 4
    assert child["judge_cost_cents"] > 0
    for goal in lane_goals:
        assert "t80refok" not in goal
        assert "test_t80_new_bad_" not in goal
    blob = repr(child)
    assert "t80refok" not in blob
    assert "test_t80_new_bad_x_meter" not in blob
    assert "test_t80_new_bad_y_strong" not in blob
    cert = c.get(f"/v1/arena/{child['arena_id']}/proof").json()
    assert "t80refok" not in repr(cert)
    assert "test_t80_new_bad_" not in repr(cert)


def test_followup_healthy_new_tests_score(monkeypatch):
    stubs = _Stubs(monkeypatch,
                   [[KEEP_A, KEEP_B, KEEP_C], [NEW_GOOD]])
    root = _run_prompt({"prompt": "say hello world please"})
    assert root["status"] == "succeeded", root.get("error")
    child = _run_followup(root["arena_id"], {"prompt": "also say goodbye"})
    assert child["status"] == "succeeded", child.get("error")
    assert len(stubs.reference_goals()) == 2
    m = child["manifest"]
    assert m["reference_checked"] is True
    assert m["acceptance_reference_dropped"] == 0
    assert m["acceptance_inherited"] == 3
    assert m["acceptance_new"] == 1
    assert m["acceptance_count"] == 4
    assert child["lanes"]["single"]["heldout"]["n"] == 4
    assert child["lanes"]["evoforge"]["heldout"]["n"] == 4
    blob = repr(child)
    assert "t80refok" not in blob
