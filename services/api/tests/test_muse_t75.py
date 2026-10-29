"""T75 live Arena progress (API only).

While an Arena runs, GET /v1/arena/{id} and GET /v1/arena show each lane's
events as they are emitted (seq strictly increasing, a prefix of the final
document's messages). Hidden acceptance names stay scrubbed live, and prompt
arenas carry a top-level judge event, visible live and kept in the final
document. Live state is an in-process overlay; the store is only written for
the seeded running document and the terminal document.
"""
from __future__ import annotations

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
from evoforge import arena as arena_mod  # noqa: E402
from evoforge import arena_prompt, broker_meta, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)

USAGE = {"prompt_tokens": 1000, "completion_tokens": 200}

KEEP_A = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t75_keep_a_has_text():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert (root.text or '').strip() != ''\n")
KEEP_B = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t75_keep_b_hello():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert 'hello' in (root.text or '')\n")
KEEP_C = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t75_keep_c_world():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert 'world' in (root.text or '')\n")


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


class _Stubs:
    """Mock providers with a slow Builder so live polling observes the run."""

    def __init__(self, monkeypatch, judge_codes, delay=3.0):
        self.builder_goals = []
        self.delay = delay
        self.diff = _hello_world_diff()
        self.reference_diff = _hello_world_diff()
        self.judge_codes = list(judge_codes)
        self.judged = False
        monkeypatch.setattr(broker_meta, "call_builder", self.builder)
        monkeypatch.setattr(broker_meta, "call_critic", self.critic)

    def builder(self, goal, sha, file_context=None, **k):
        self.builder_goals.append(goal)
        if arena_prompt.REFERENCE_MARKER in (goal or ""):
            time.sleep(0)
            return {"diff": self.reference_diff, "tests": [], "rationale": "x",
                    "stub": False, "model": "muse-spark-1.3",
                    "provider_calls": [], "usage": dict(USAGE)}
        time.sleep(self.delay)
        return {"diff": self.diff, "tests": [], "rationale": "x",
                "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": dict(USAGE)}

    def critic(self, goal, diff="", ci="", **k):
        if not self.judged:
            self.judged = True
            return {"sealed_tests": [{"code": code} for code in self.judge_codes],
                    "stub": False, "usage": dict(USAGE)}
        return {"sealed_tests": [], "stub": False, "usage": dict(USAGE)}


def _lane_prefix_ok(live_evs, final_evs):
    assert [e["seq"] for e in live_evs] == list(range(1, len(live_evs) + 1))
    assert [e["message"] for e in live_evs] == [
        e["message"] for e in final_evs[:len(live_evs)]]
    assert [e["role"] for e in live_evs] == [
        e["role"] for e in final_evs[:len(live_evs)]]


def test_prompt_arena_live_events_are_prefix_of_final(monkeypatch):
    _Stubs(monkeypatch, [KEEP_A, KEEP_B, KEEP_C])
    r = c.post("/v1/arena/prompt", json={"prompt": "say hello world please"})
    assert r.status_code == 202, r.text
    aid = r.json()["arena_id"]
    assert r.json()["status"] == "running"

    observations = []
    judge_seen_live = False
    end = time.time() + 300
    final = None
    while time.time() < end:
        a = c.get(f"/v1/arena/{aid}").json()
        listed = [x for x in c.get("/v1/arena").json()["arenas"]
                  if x["arena_id"] == aid]
        assert listed, "running arena missing from GET /v1/arena"
        # Both reads show the same live lane events; the list is read a moment later, so it may have more.
        for lane in ("single", "evoforge"):
            first, later = a["lanes"][lane]["events"], listed[0]["lanes"][lane]["events"]
            assert later[:len(first)] == first
        if a["status"] in ("succeeded", "failed"):
            final = a
            break
        # Live: strictly increasing seq, scrubbed names, judge step present
        # once the lanes have started emitting.
        for lane in ("single", "evoforge"):
            evs = a["lanes"][lane]["events"]
            seqs = [e["seq"] for e in evs]
            assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
            assert seqs == list(range(1, len(seqs) + 1))
            assert "test_t75_keep" not in repr(evs)
        if isinstance(a.get("events"), list) and a["events"]:
            assert a["events"][0]["role"] == "judge"
            assert "hidden" in a["events"][0]["message"].lower()
            judge_seen_live = True
        if a["lanes"]["single"]["events"] or a["lanes"]["evoforge"]["events"]:
            observations.append({lane: [dict(e) for e in a["lanes"][lane]["events"]]
                                 for lane in ("single", "evoforge")})
            assert judge_seen_live, "lanes emit live but the judge step is missing"
        time.sleep(0.3)
    assert final is not None, "prompt arena did not finish"
    assert final["status"] == "succeeded", final.get("error")
    assert observations, "never observed live lane events during the run"
    # Every live observation is a prefix of the final document.
    for obs in observations:
        for lane in ("single", "evoforge"):
            _lane_prefix_ok(obs[lane], final["lanes"][lane]["events"])
    # Final lane events keep strictly increasing seq and scrubbed names.
    for lane in ("single", "evoforge"):
        evs = final["lanes"][lane]["events"]
        assert [e["seq"] for e in evs] == list(range(1, len(evs) + 1))
    assert "test_t75_keep" not in repr(final)
    # Judge step kept in the final document.
    assert isinstance(final.get("events"), list) and final["events"]
    assert final["events"][0]["role"] == "judge"
    assert "3" in final["events"][0]["message"]
    assert "hidden" in final["events"][0]["message"].lower()
    # Live overlay cleared once the terminal document was saved.
    assert aid not in arena_mod._LIVE


def test_live_scrub_matches_final_scrub():
    lane = {"status": "succeeded", "attempts": 1,
            "heldout": {"passed": 1, "n": 3}, "outcome": "heldout_failed",
            "cost_cents": 1, "diff": "diff",
            "events": [
                {"seq": 1, "ts": 0.0, "role": "runner",
                 "message": "single: held-out 1/3 passed (failing: test_t75_keep_b_hello)"},
            ],
            "failing_tests": ["test_t75_keep_b_hello"]}
    arena_prompt._scrub_lane(lane, ["test_t75_keep_b_hello"])
    assert lane["events"][0]["message"] == arena_mod._scrub_text(
        "single: held-out 1/3 passed (failing: test_t75_keep_b_hello)",
        ["test_t75_keep_b_hello"])
    assert "test_t75_keep" not in repr(lane)
