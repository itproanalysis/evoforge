"""T64 prompt Arena: compare what the USER asks for (API only).

Both lanes implement one user prompt starting from the same template.
An independent judge Critic writes hidden acceptance tests from the prompt
before either lane runs; dropped-on-template tests never score, the suite
is never sent to any lane and never returned.
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
WEB = Path(__file__).resolve().parents[3] / "apps" / "web"

USAGE = {"prompt_tokens": 1000, "completion_tokens": 200}

KEEP_A = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t64_keep_a_has_text():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert (root.text or '').strip() != ''\n")
KEEP_B = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t64_keep_b_hello():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert 'hello' in (root.text or '')\n")
KEEP_C = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t64_keep_c_world():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert 'world' in (root.text or '')\n")
DROP_TAG = ("import app\nimport xml.etree.ElementTree as ET\n"
            "def test_t64_drop_tag_main():\n"
            "    root = ET.fromstring(app.render())\n"
            "    assert root.tag == 'main'\n")
SOLO = ("import app\nimport xml.etree.ElementTree as ET\n"
        "def test_t64_solo_hello():\n"
        "    root = ET.fromstring(app.render())\n"
        "    assert 'hello' in (root.text or '')\n")
NEEDS_GOODBYE = ("import app\nimport xml.etree.ElementTree as ET\n"
                 "def test_t64_need_goodbye():\n"
                 "    assert 'goodbye' in app.render()\n")


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


def _hello_world_diff():
    import difflib

    old = arena_prompt.TEMPLATE
    new = old.replace("'<main></main>'", "'<main>hello world</main>'")
    assert new != old
    return "".join(difflib.unified_diff(
        old.splitlines(True), new.splitlines(True),
        "a/app.py", "b/app.py"))


def _reference_diff():
    import difflib

    old = arena_prompt.TEMPLATE
    new = old.replace("'<main></main>'", "'<main>hello world goodbye</main>'")
    assert new != old
    return "".join(difflib.unified_diff(
        old.splitlines(True), new.splitlines(True),
        "a/app.py", "b/app.py"))


class _Stubs:
    """Mock providers: first Critic call is the judge, the rest internal."""

    def __init__(self, monkeypatch, judge_codes):
        self.judge_calls = []
        self.builder_goals = []
        self.internal_critic = 0
        self.judge_codes = list(judge_codes)
        self.diff = _hello_world_diff()
        self.reference_diff = _reference_diff()
        self.lock = threading.Lock()
        monkeypatch.setattr(broker_meta, "call_builder", self.builder)
        monkeypatch.setattr(broker_meta, "call_critic", self.critic)

    def builder(self, goal, sha, file_context=None, **k):
        with self.lock:
            self.builder_goals.append(goal)
        if arena_prompt.REFERENCE_MARKER in (goal or ""):
            diff = self.reference_diff
        else:
            diff = self.diff
        return {"diff": diff, "tests": [], "rationale": "x",
                "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": dict(USAGE)}

    def critic(self, goal, diff="", ci="", **k):
        with self.lock:
            if not self.judge_calls:
                self.judge_calls.append(goal)
                return {"sealed_tests": [{"code": code} for code in self.judge_codes],
                        "stub": False, "usage": dict(USAGE)}
            self.internal_critic += 1
        return {"sealed_tests": [], "stub": False, "usage": dict(USAGE)}


def _run(body):
    r = c.post("/v1/arena/prompt", json=body)
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "running"
    aid = r.json()["arena_id"]
    end = time.time() + 300
    while time.time() < end:
        a = c.get(f"/v1/arena/{aid}").json()
        if a["status"] in ("succeeded", "failed"):
            return a
        time.sleep(0.3)
    pytest.fail("prompt arena did not finish")


def test_prompt_validation(monkeypatch):
    _Stubs(monkeypatch, [SOLO])
    assert c.post("/v1/arena/prompt", json={"prompt": "   "}).status_code == 422
    assert c.post("/v1/arena/prompt", json={"prompt": ""}).status_code == 422
    assert c.post("/v1/arena/prompt", json={"prompt": "x" * 2001}).status_code == 422
    assert c.post("/v1/arena/prompt", json={"prompt": "x" * 2000}).status_code == 202
    _settle()
    assert c.post("/v1/arena/prompt",
                  json={"prompt": "ok", "feedback": "oracle"}).status_code == 422
    assert c.post("/v1/arena/prompt",
                  json={"prompt": "ok", "single_apply": "loose"}).status_code == 422


def test_prompt_arena_scorable_run(monkeypatch):
    stubs = _Stubs(monkeypatch, [DROP_TAG, KEEP_A, KEEP_B, KEEP_C])
    prompt = "say hello world please"
    a = _run({"prompt": prompt})
    assert a["status"] == "succeeded", a.get("error")
    assert a["mode"] == "prompt"
    assert a["prompt"] == prompt
    # Judge ran once, before any lane Builder call.
    assert len(stubs.judge_calls) == 1
    assert prompt in stubs.judge_calls[0]
    assert "ElementTree" in stubs.judge_calls[0]
    assert stubs.builder_goals, "lanes never ran"
    # Template-passing test dropped; the rest is the acceptance suite.
    m = a["manifest"]
    assert m["comparison_mode"] == "user_prompt_same_template"
    assert m["acceptance_count"] == 3
    assert m["acceptance_dropped"] == 1
    assert m["prompt_hash"] == "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert m["acceptance_hash"] == "sha256:" + hashlib.sha256(
        json.dumps([KEEP_A, KEEP_B, KEEP_C]).encode("utf-8")).hexdigest()
    assert m["judge"].count(".") == 1
    assert "hidden" in m["judge"].lower() and "critic" in m["judge"].lower()
    single_m, evo_m = m["lanes"]["single"], m["lanes"]["evoforge"]
    assert (single_m["harness"], single_m["apply"], single_m["max_attempts"],
            single_m["feedback"]) == ("api-sealed-eval/2", "tolerant", 1, "none")
    assert (evo_m["harness"], evo_m["apply"], evo_m["max_attempts"],
            evo_m["feedback"]) == ("api-sealed-eval/2", "tolerant", 3, "critic")
    assert m["cost_basis"] == "model_api_usage"
    assert m["runner_cost"] == "not_measured"
    assert m["disclosure"]
    # Acceptance suite never sent to any lane and never returned.
    for goal in stubs.builder_goals:
        assert "test_t64_keep_a_has_text" not in goal
        assert "test_t64_keep_b_hello" not in goal
        assert "test_t64_keep_c_world" not in goal
        assert "test_t64_drop_tag_main" not in goal
    blob = repr(a)
    assert "test_t64_keep_a_has_text" not in blob
    assert "test_t64_drop_tag_main" not in blob
    # Scored on the acceptance suite, with previews, judge cost separate.
    assert a["lanes"]["single"]["heldout"] == {"passed": 3, "n": 3}
    assert a["lanes"]["evoforge"]["heldout"] == {"passed": 3, "n": 3}
    assert a["verdict"]["winner"] == "tie"
    for name in ("single", "evoforge"):
        lane = a["lanes"][name]
        assert lane["preview_source"] == "candidate", lane.get("preview_error")
        assert "hello world" in lane["preview_html"]
    assert a["judge_cost_cents"] >= 0
    assert a["lanes"]["single"]["cost_cents"] + a["lanes"]["evoforge"]["cost_cents"] >= 0
    # Visible through both GETs.
    assert c.get(f"/v1/arena/{a['arena_id']}").json()["arena_id"] == a["arena_id"]
    assert any(x["arena_id"] == a["arena_id"]
               for x in c.get("/v1/arena").json()["arenas"])


def test_prompt_arena_unscorable_with_strict_single(monkeypatch):
    stubs = _Stubs(monkeypatch, [SOLO, NEEDS_GOODBYE])
    a = _run({"prompt": "say hello", "single_apply": "strict"})
    assert a["status"] == "succeeded", a.get("error")
    assert a["manifest"]["acceptance_count"] == 2
    assert a["verdict"]["winner"] == "unscorable"
    assert a["verdict"]["reason"]
    assert a["manifest"]["lanes"]["single"]["apply"] == "strict"
    assert a["manifest"]["lanes"]["single"]["harness"] == "api-sealed-eval/1"
    for name in ("single", "evoforge"):
        lane = a["lanes"][name]
        assert lane.get("preview_source") in ("candidate", "base")
        assert lane.get("preview_html")
    # Failing acceptance names stay hidden even though lanes missed one.
    blob = repr(a)
    assert "test_t64_solo_hello" not in blob
    assert "test_t64_need_goodbye" not in blob
    for lane in a["lanes"].values():
        assert "failing_tests" not in lane
    assert stubs.builder_goals


def test_prompt_arena_budget_refused_before_any_provider_call(monkeypatch):
    calls = []

    def _boom_builder(*a, **k):
        calls.append("builder")
        raise AssertionError("builder must not be called")

    def _boom_critic(*a, **k):
        calls.append("critic")
        raise AssertionError("critic must not be called")

    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "10")
    monkeypatch.setattr(broker_meta, "call_builder", _boom_builder)
    monkeypatch.setattr(broker_meta, "call_critic", _boom_critic)
    r = c.post("/v1/arena/prompt", json={"prompt": "say hello"})
    assert r.status_code == 402, r.text
    assert calls == []


def test_lane_scrub_removes_acceptance_names():
    lane = {"status": "succeeded", "attempts": 1,
            "heldout": {"passed": 1, "n": 3}, "outcome": "heldout_failed",
            "cost_cents": 1, "diff": "diff",
            "events": [
                {"seq": 1, "ts": 0.0, "role": "runner",
                 "message": "single: held-out 1/3 passed (failing: test_t64_keep_b_hello, test_t64_keep_c_world)"},
                {"seq": 2, "ts": 0.0, "role": "gate",
                 "message": "single: heldout_failed"},
            ],
            "failing_tests": ["test_t64_keep_b_hello", "test_t64_keep_c_world"]}
    arena_prompt._scrub_lane(lane, ["test_t64_keep_b_hello", "test_t64_keep_c_world"])
    blob = repr(lane)
    assert "test_t64_keep_b_hello" not in blob
    assert "test_t64_keep_c_world" not in blob
    assert "failing_tests" not in lane
    assert lane["heldout"] == {"passed": 1, "n": 3}
    assert lane["events"][0]["message"] == "single: held-out 1/3 passed"


def test_proxy_allows_prompt_arena():
    src = (WEB / "lib" / "proxyPolicy.ts").read_text(encoding="utf-8")
    assert "/v1/arena/prompt" in src
    cases = json.loads((WEB / "lib" / "proxyPolicy.cases.json").read_text(encoding="utf-8"))
    by_path = {tuple(e["path_segments"]): e["expected"] for e in cases}
    assert by_path[("v1", "arena", "prompt")] == "/v1/arena/prompt"
