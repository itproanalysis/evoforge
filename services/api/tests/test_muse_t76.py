"""T76 prompt Arena: check the judge's hidden tests against a reference build.

After the template filter, ONE Builder call (goal starting with
``arena_prompt.REFERENCE_MARKER``) implements the lanes' goal from the
template; only tests that pass on that reference build stay scored. Fewer
than 3 left -> unscorable mentioning the judge reference, never a tie or
a win. Reference code/diff and dropped tests never reach a lane goal, the
response, or the proof certificate.
"""
from __future__ import annotations

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

GOOD_A = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t76_good_a_has_text():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert (root.text or '').strip() != ''\n")
GOOD_B = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t76_good_b_hello():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert 'hello' in (root.text or '')\n")
GOOD_C = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t76_good_c_world():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert 'world' in (root.text or '')\n")
DROP_TAG = ("import app\nimport xml.etree.ElementTree as ET\n"
            "def test_t76_drop_tag_main():\n"
            "    root = ET.fromstring(app.render())\n"
            "    assert root.tag == 'main'\n")
BAD_X = ("import app\n"
         "def test_t76_bad_x_goodbye():\n"
         "    assert 'goodbye' in app.render()\n")
BAD_Y = ("import app\n"
         "def test_t76_bad_y_meter():\n"
         "    assert 'meter' in app.render()\n")
BAD_Z = ("import app\n"
         "def test_t76_bad_z_strong():\n"
         "    assert 'strong' in app.render()\n")


def _settle(limit=300):
    """Wait until no eval job (from this or an earlier test file) is active."""
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


def _page_diff(page: str):
    import difflib

    old = arena_prompt.TEMPLATE
    new = old.replace("'<main></main>'", f"'{page}'")
    assert new != old
    return "".join(difflib.unified_diff(
        old.splitlines(True), new.splitlines(True),
        "a/app.py", "b/app.py"))


class _Stubs:
    """Judge codes from the first Critic call; reference + lanes via Builder."""

    def __init__(self, monkeypatch, judge_codes):
        self.judge_codes = list(judge_codes)
        self.judged = False
        self.builder_goals = []
        self.builder_contexts = []
        # Reference-only marker string: must never leak to lanes/responses.
        self.reference_diff = _page_diff("<main>hello world t76refok</main>")
        self.lane_diff = _page_diff("<main>hello world</main>")
        self.lock = threading.Lock()
        monkeypatch.setattr(broker_meta, "call_builder", self.builder)
        monkeypatch.setattr(broker_meta, "call_critic", self.critic)

    def builder(self, goal, sha, file_context=None, **k):
        with self.lock:
            self.builder_goals.append(goal)
            self.builder_contexts.append(file_context)
        if arena_prompt.REFERENCE_MARKER in (goal or ""):
            diff = self.reference_diff
        else:
            diff = self.lane_diff
        return {"diff": diff, "tests": [], "rationale": "x",
                "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": dict(USAGE)}

    def critic(self, goal, diff="", ci="", **k):
        with self.lock:
            if not self.judged:
                self.judged = True
                return {"sealed_tests": [{"code": code} for code in self.judge_codes],
                        "stub": False, "usage": dict(USAGE)}
        return {"sealed_tests": [], "stub": False, "usage": dict(USAGE)}

    def reference_goals(self):
        return [g for g in self.builder_goals
                if arena_prompt.REFERENCE_MARKER in (g or "")]

    def lane_goals(self):
        return [g for g in self.builder_goals
                if arena_prompt.REFERENCE_MARKER not in (g or "")]


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


def test_reference_marker_goal_shape():
    assert arena_prompt.REFERENCE_MARKER == "Judge reference build"
    assert arena_prompt.build_reference_goal("goal-text") == (
        "Judge reference build\n\ngoal-text")


def test_wrong_judge_suite_is_unscorable_not_a_tie(monkeypatch):
    stubs = _Stubs(monkeypatch, [BAD_X, BAD_Y, BAD_Z, GOOD_A])
    a = _run({"prompt": "say hello world please"})
    assert a["status"] == "succeeded", a.get("error")
    # Exactly ONE reference build, on the lanes' goal with file context.
    assert len(stubs.reference_goals()) == 1
    ref_goal = stubs.reference_goals()[0]
    assert ref_goal.startswith(arena_prompt.REFERENCE_MARKER + "\n\n")
    assert stubs.lane_goals(), "lanes never ran"
    assert ref_goal[len(arena_prompt.REFERENCE_MARKER) + 2:] in stubs.lane_goals()
    assert stubs.builder_contexts
    ref_idx = stubs.builder_goals.index(ref_goal)
    assert stubs.builder_contexts[ref_idx] == [
        {"path": "app.py", "content": arena_prompt.TEMPLATE}]
    # The wrong tests died on the reference; only GOOD_A scores.
    m = a["manifest"]
    assert m["reference_checked"] is True
    assert m["acceptance_reference_dropped"] == 3
    assert m["acceptance_dropped"] == 0
    assert m["acceptance_count"] == 1
    assert m["acceptance_hash"] == "sha256:" + hashlib.sha256(
        json.dumps([GOOD_A]).encode("utf-8")).hexdigest()
    assert m["acceptance_interface"] == arena_prompt.acceptance_interface(
        [{"code": GOOD_A}])
    # Never a tie or a win, even though both lanes pass the scored test.
    assert a["lanes"]["single"]["heldout"] == {"passed": 1, "n": 1}
    assert a["lanes"]["evoforge"]["heldout"] == {"passed": 1, "n": 1}
    assert a["verdict"]["winner"] == "unscorable"
    assert "judge reference" in a["verdict"]["reason"].lower()
    # Reference cost is part of the judge cost.
    assert a["judge_cost_cents"] > 0
    # Nothing of the reference or the dropped tests leaks.
    for goal in stubs.lane_goals():
        assert "t76refok" not in goal
        assert "test_t76_bad_" not in goal
    blob = repr(a)
    assert "t76refok" not in blob
    assert "test_t76_bad_x_goodbye" not in blob
    assert "test_t76_bad_y_meter" not in blob
    assert "test_t76_bad_z_strong" not in blob
    assert "goodbye" not in blob.replace("say hello world please", "")
    cert = c.get(f"/v1/arena/{a['arena_id']}/proof").json()
    assert "t76refok" not in repr(cert)
    assert "test_t76_bad_" not in repr(cert)


def test_healthy_judge_suite_scores_normally(monkeypatch):
    stubs = _Stubs(monkeypatch, [DROP_TAG, GOOD_A, GOOD_B, GOOD_C])
    a = _run({"prompt": "say hello world please"})
    assert a["status"] == "succeeded", a.get("error")
    assert len(stubs.reference_goals()) == 1
    m = a["manifest"]
    assert m["reference_checked"] is True
    assert m["acceptance_reference_dropped"] == 0
    assert m["acceptance_count"] == 3
    assert m["acceptance_hash"] == "sha256:" + hashlib.sha256(
        json.dumps([GOOD_A, GOOD_B, GOOD_C]).encode("utf-8")).hexdigest()
    assert a["lanes"]["single"]["heldout"] == {"passed": 3, "n": 3}
    assert a["lanes"]["evoforge"]["heldout"] == {"passed": 3, "n": 3}
    assert a["verdict"]["winner"] == "tie"
    blob = repr(a)
    assert "t76refok" not in blob
    assert "test_t76_drop_tag_main" not in blob
