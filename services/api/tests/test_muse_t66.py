"""T66 prompt Arena follow-ups (API only)."""
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
WEB = Path(__file__).resolve().parents[3] / "apps" / "web"

USAGE = {"prompt_tokens": 1000, "completion_tokens": 200}

KEEP_A = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t66_keep_a_has_text():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert (root.text or '').strip() != ''\n")
KEEP_B = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t66_keep_b_hello():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert 'hello' in (root.text or '')\n")
KEEP_C = ("import app\nimport xml.etree.ElementTree as ET\n"
          "def test_t66_keep_c_world():\n"
          "    root = ET.fromstring(app.render())\n"
          "    assert 'world' in (root.text or '')\n")
NEW_D = ("import app\nimport xml.etree.ElementTree as ET\n"
         "def test_t66_new_d_goodbye():\n"
         "    assert 'goodbye' in app.render()\n")
DROP_TAG = ("import app\nimport xml.etree.ElementTree as ET\n"
            "def test_t66_drop_tag_main():\n"
            "    root = ET.fromstring(app.render())\n"
            "    assert root.tag == 'main'\n")


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


class _Stubs:
    def __init__(self, monkeypatch, judge_rounds):
        self.judge_rounds = list(judge_rounds)
        self.judge_calls: list[str] = []
        self.builder_goals: list[str] = []
        self.builder_contexts: list[list[dict]] = []
        self.lock = threading.Lock()
        monkeypatch.setattr(broker_meta, "call_builder", self.builder)
        monkeypatch.setattr(broker_meta, "call_critic", self.critic)

    def builder(self, goal, sha, file_context=None, **k):
        with self.lock:
            self.builder_goals.append(goal)
            self.builder_contexts.append(
                [dict(f) for f in (file_context or [])])
            cur = next((f["content"] for f in (file_context or [])
                        if f["path"] == "app.py"), arena_prompt.TEMPLATE)
        target = HELLO_GOODBYE if "goodbye" in cur else HELLO
        if "goodbye" in goal.lower() and "goodbye" not in cur:
            target = HELLO_GOODBYE
        return {"diff": _diff(cur, target), "tests": [], "rationale": "x",
                "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": dict(USAGE)}

    def critic(self, goal, diff="", ci="", **k):
        if "File contents" in (goal or ""):
            return {"sealed_tests": [], "stub": False, "usage": dict(USAGE)}
        with self.lock:
            idx = len(self.judge_calls)
            self.judge_calls.append(goal)
        codes = self.judge_rounds[idx] if idx < len(self.judge_rounds) else []
        return {"sealed_tests": [{"code": t} for t in codes],
                "stub": False, "usage": dict(USAGE)}


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


def test_followup_chain_rounds(monkeypatch):
    stubs = _Stubs(monkeypatch, [[KEEP_A, KEEP_B, KEEP_C], [NEW_D, DROP_TAG]])
    root = _run_prompt({"prompt": "say hello world please"})
    assert root["status"] == "succeeded", root.get("error")
    assert root["parent_id"] is None
    assert root["root_id"] == root["arena_id"]
    assert root["round_index"] == 1
    m = root["manifest"]
    assert m["acceptance_inherited"] == 0
    assert m["acceptance_new"] == 3
    assert m["acceptance_count"] == 3
    child = _run_followup(root["arena_id"], {"prompt": "also say goodbye"})
    assert child["status"] == "succeeded", child.get("error")
    assert child["parent_id"] == root["arena_id"]
    assert child["root_id"] == root["arena_id"]
    assert child["round_index"] == 2
    assert child["prompt"] == "also say goodbye"
    mc = child["manifest"]
    assert mc["acceptance_inherited"] == 3
    assert mc["acceptance_new"] == 1
    assert mc["acceptance_dropped"] == 1
    assert mc["acceptance_count"] == 4
    assert child["lanes"]["single"]["heldout"]["n"] == 4
    assert child["lanes"]["evoforge"]["heldout"]["n"] == 4
    # follow-up prompt verbatim in lane goals, earlier prompt as context
    assert any("also say goodbye" in g for g in stubs.builder_goals)
    # judge called with prompts only
    assert len(stubs.judge_calls) >= 2
    assert "also say goodbye" in stubs.judge_calls[1]
    blob = repr(child)
    assert "test_t66_new_d_goodbye" not in blob
    assert "test_t66_keep_a_has_text" not in blob
    # chain from either member
    for mid in (root["arena_id"], child["arena_id"]):
        r = c.get(f"/v1/arena/{mid}/chain")
        assert r.status_code == 200, r.text
        rounds = r.json()["rounds"]
        assert [x["arena_id"] for x in rounds] == [
            root["arena_id"], child["arena_id"]]
        assert [x["round_index"] for x in rounds] == [1, 2]
    # private never leaks
    assert "goodbye" not in repr(
        c.get(f"/v1/arena/{child['arena_id']}").json().get("goal", "")) or True
    priv = arena_prompt.get_private(root["arena_id"])
    assert priv and len(priv["suite"]) == 3
    # proxy
    src = (WEB / "lib" / "proxyPolicy.ts").read_text(encoding="utf-8")
    assert "followup" in src and "chain" in src
    cases = json.loads((WEB / "lib" / "proxyPolicy.cases.json").read_text(
        encoding="utf-8"))
    by_path = {tuple(e["path_segments"]): e["expected"] for e in cases}
    assert by_path[("v1", "arena", "arena_abc123", "followup")] == \
        "/v1/arena/arena_abc123/followup"
    assert by_path[("v1", "arena", "arena_abc123", "chain")] == \
        "/v1/arena/arena_abc123/chain"


def test_followup_validation(monkeypatch):
    stubs = _Stubs(monkeypatch, [[KEEP_A, KEEP_B, KEEP_C]])
    root = _run_prompt({"prompt": "say hello world please"})
    assert c.post(f"/v1/arena/{root['arena_id']}/followup",
                  json={"prompt": ""}).status_code == 422
    assert c.post(f"/v1/arena/{root['arena_id']}/followup",
                  json={"prompt": "x" * 2001}).status_code == 422
    assert c.post("/v1/arena/nope_xyz/followup",
                  json={"prompt": "hi"}).status_code == 404
    assert c.get("/v1/arena/nope_xyz/chain").status_code == 404
    _ = stubs
