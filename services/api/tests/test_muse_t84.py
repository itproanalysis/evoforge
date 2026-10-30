"""T84 round plans with a daily public limit (API only)."""
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
from evoforge import arena as arena_mod  # noqa: E402
from evoforge import arena_prompt, broker_meta  # noqa: E402
from evoforge import eval_jobs as eval_jobs_mod  # noqa: E402
from evoforge import ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
WEB = Path(__file__).resolve().parents[3] / "apps" / "web"

USAGE = {"prompt_tokens": 1000, "completion_tokens": 200}

KEEP_A = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t84_keep_a_has_text():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert (root.text or '').strip() != ''\n")
KEEP_B = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t84_keep_b_hello():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert 'hello' in (root.text or '')\n")
KEEP_C = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t84_keep_c_world():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert 'world' in (root.text or '')\n")


def _settle(limit=300):
    end = time.time() + limit
    while time.time() < end and any(
            j["status"] in ("queued", "running")
            for j in c.get("/v1/eval/jobs").json()["jobs"]):
        time.sleep(0.3)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    _settle()
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.delenv("EVO_PUBLIC_DAILY_RUNS", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset()
    ledger.configure({"default": 500000})
    eval_jobs_mod.clear()
    arena_mod.clear()
    yield
    _settle()
    eval_jobs_mod.clear()
    arena_mod.clear()
    ledger.reset()
    ledger.configure({"default": 500000})


def _diff(old: str, new: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(True), new.splitlines(True),
        "a/app.py", "b/app.py"))


HELLO = arena_prompt.TEMPLATE.replace("'<main></main>'",
                                       "'<main>hello world</main>'")
HELLO_GOODBYE = arena_prompt.TEMPLATE.replace(
    "'<main></main>'", "'<main>hello world goodbye</main>'")


class _Stubs:
    def __init__(self, monkeypatch, fail_marker=None):
        self.judge_calls: list[str] = []
        self.builder_goals: list[str] = []
        self.builder_contexts: list[list[dict]] = []
        self.fail_marker = fail_marker
        self.lock = threading.Lock()
        monkeypatch.setattr(broker_meta, "call_builder", self.builder)
        monkeypatch.setattr(broker_meta, "call_critic", self.critic)

    def builder(self, goal, sha, file_context=None, **k):
        if self.fail_marker and self.fail_marker in (goal or ""):
            raise RuntimeError("t84 planned lane failure")
        with self.lock:
            self.builder_goals.append(goal)
            self.builder_contexts.append(
                [dict(f) for f in (file_context or [])])
            cur = next((f["content"] for f in (file_context or [])
                        if f["path"] == "app.py"), arena_prompt.TEMPLATE)
        if arena_prompt.REFERENCE_MARKER in (goal or ""):
            target = HELLO_GOODBYE
        elif "goodbye" in cur:
            target = HELLO_GOODBYE
        elif "goodbye" in (goal or "").lower():
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
            self.judge_calls.append(goal)
        return {"sealed_tests": [{"code": t}
                                 for t in (KEEP_A, KEEP_B, KEEP_C)],
                "stub": False, "usage": dict(USAGE)}


def _wait(aid, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        a = c.get(f"/v1/arena/{aid}").json()
        if a["status"] in ("succeeded", "failed"):
            return a
        time.sleep(0.3)
    pytest.fail("arena did not finish")


def test_rounds_validation_starts_nothing(monkeypatch):
    _Stubs(monkeypatch)
    assert c.post("/v1/arena/prompt",
                  json={"prompt": "hi", "rounds": ["a", "b", "c",
                                                  "d", "e"]}).status_code == 422
    assert c.post("/v1/arena/prompt",
                  json={"prompt": "hi",
                        "rounds": ["   "]}).status_code == 422
    assert c.post("/v1/arena/prompt",
                  json={"prompt": "hi",
                        "rounds": ["x" * 2001]}).status_code == 422
    assert c.post("/v1/arena/prompt",
                  json={"prompt": "hi",
                        "rounds": [123]}).status_code == 422
    assert c.post("/v1/arena/prompt",
                  json={"prompt": "hi",
                        "rounds": "nope"}).status_code == 422
    assert c.get("/v1/eval/jobs").json()["jobs"] == []
    assert c.get("/v1/arena").json()["arenas"] == []


def test_round_plan_chain_continues_from_own_code(monkeypatch):
    stubs = _Stubs(monkeypatch)
    r = c.post("/v1/arena/prompt",
               json={"prompt": "say hello world please",
                     "rounds": ["also say goodbye"]})
    assert r.status_code == 202, r.text
    root_id = r.json()["arena_id"]
    root = _wait(root_id)
    assert root["status"] == "succeeded", root.get("error")
    assert root["plan"] == ["say hello world please",
                            "also say goodbye"]
    assert root["round_index"] == 1
    _settle()
    chain = c.get(f"/v1/arena/{root_id}/chain").json()["rounds"]
    assert [x["round_index"] for x in chain] == [1, 2]
    assert [x["prompt"] for x in chain] == ["say hello world please",
                                            "also say goodbye"]
    assert chain[1]["parent_id"] == root_id
    assert chain[1]["root_id"] == root_id
    assert chain[0]["lanes"]["single"]["heldout"]["n"] >= 3
    assert chain[1]["lanes"]["single"]["heldout"]["n"] >= 3
    # Round 2 lanes kept building on round 1 code, not the template.
    assert any("hello world" in (f.get("content", ""))
               for ctx in stubs.builder_contexts for f in ctx)
    assert any("also say goodbye" in g for g in stubs.builder_goals)
    blob = repr(chain)
    assert "test_t84_keep_a_has_text" not in blob


def test_plan_stops_after_failed_round(monkeypatch):
    _Stubs(monkeypatch, fail_marker="T84BOOM")
    r = c.post("/v1/arena/prompt",
               json={"prompt": "say hello world please",
                     "rounds": ["T84BOOM mission", "third mission"]})
    assert r.status_code == 202, r.text
    root_id = r.json()["arena_id"]
    _settle()
    chain = c.get(f"/v1/arena/{root_id}/chain").json()["rounds"]
    assert len(chain) == 2
    assert chain[1]["status"] == "failed"
    assert chain[1]["prompt"] == "T84BOOM mission"


def test_daily_limit_and_limits_endpoint(monkeypatch):
    _Stubs(monkeypatch)
    monkeypatch.setenv("EVO_PUBLIC_DAILY_RUNS", "2")
    r = c.post("/v1/arena/prompt",
               json={"prompt": "say hello world please",
                     "rounds": ["also say goodbye", "third round"]})
    assert r.status_code == 429, r.text
    assert "daily run limit reached" in r.text
    assert c.get("/v1/eval/jobs").json()["jobs"] == []
    assert c.get("/v1/arena").json()["arenas"] == []
    monkeypatch.setenv("EVO_PUBLIC_DAILY_RUNS", "20")
    r = c.post("/v1/arena/prompt",
               json={"prompt": "say hello world please"})
    assert r.status_code == 202, r.text
    root = _wait(r.json()["arena_id"])
    assert root["status"] == "succeeded", root.get("error")
    _settle()
    monkeypatch.setenv("EVO_PUBLIC_DAILY_RUNS", "1")
    over = c.post("/v1/arena/prompt",
                  json={"prompt": "another try"})
    assert over.status_code == 429, over.text
    assert "daily run limit reached" in over.text
    over_fw = c.post(f"/v1/arena/{root['arena_id']}/followup",
                     json={"prompt": "one more"})
    assert over_fw.status_code == 429, over_fw.text
    lim = c.get("/v1/arena/limits").json()
    assert lim["daily_limit"] == 1
    assert lim["used_today"] == 1
    assert lim["remaining"] == 0
    assert lim["remaining"] == max(0, lim["daily_limit"] - lim["used_today"])


def test_limits_proxy_allow():
    src = (WEB / "lib" / "proxyPolicy.ts").read_text(encoding="utf-8")
    assert "/v1/arena/limits" in src
    cases = json.loads((WEB / "lib" / "proxyPolicy.cases.json").read_text(
        encoding="utf-8"))
    by_path = {tuple(e["path_segments"]): e["expected"] for e in cases}
    assert by_path[("v1", "arena", "limits")] == "/v1/arena/limits"
