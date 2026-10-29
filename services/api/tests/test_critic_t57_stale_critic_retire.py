"""Sealed (Critic) — T57 retire stale Critic tests (production run job_b9fbd6da2e3f: an R1 Critic test that the R2
redesign legitimately breaks burnt every retry in R2-R5 and quadrupled cost). When the same earlier-round Critic tests
fail on two consecutive attempts while all of this round's Critic tests pass, those tests are retired, retrying stops,
and the attempt is judged; a real regression (fixed on retry) is still caught."""
from __future__ import annotations

import difflib
import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
ROOT = Path(__file__).resolve().parents[3]
APP = json.loads((ROOT / "evals" / "rounds_v1" / "mission_board.json").read_text(encoding="utf-8"))
USAGE = {"prompt_tokens": 1000, "completion_tokens": 200}
STALE = ("import xml.etree.ElementTree as ET\n\nimport board\n\n\ndef test_critic_r1_single_list():\n"
         "    e = ET.fromstring(board.render([{'id': 1, 'title': 'A', 'status': 'todo'}]))\n"
         "    assert e.find('ul') is not None and len(e.findall('ul')) == 1\n")


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
    ledger.reset(); ledger.configure({"default": 500000})
    yield
    _settle()


def _round_of(goal):
    m = re.search(r"Round (\d) ", goal or "")
    return int(m.group(1)) if m else 1


def _diff(old, new):
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "a/board.py", "b/board.py"))


def _stubs(monkeypatch):
    def builder(goal, sha, file_context=None, **k):
        n = _round_of(goal)
        current = next(f["content"] for f in (file_context or []) if f["path"] == "board.py")
        return {"diff": _diff(current, APP["rounds"][n - 1]["reference"]), "tests": [], "rationale": "x",
                "stub": False, "model": "muse-spark-1.3", "provider_calls": [], "usage": USAGE}

    def critic(goal, diff, ci="", **k):
        n = _round_of(goal)
        tests = [{"code": h["code"].replace("def test_", "def test_critic_")} for h in APP["rounds"][n - 1]["heldout"]]
        if n == 1:
            tests.append({"code": STALE})  # true for R1, legitimately false after the R2 redesign
        return {"sealed_tests": tests, "stub": False, "usage": USAGE}
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    monkeypatch.setattr(broker_meta, "call_critic", critic)


def _run(rounds=3):
    r = c.post("/v1/evolution/runs", json={"app_id": "mission_board", "feedback": "critic", "rounds": rounds})
    assert r.status_code == 202, r.text
    rid = r.json()["run_id"]
    end = time.time() + 900
    while time.time() < end:
        d = c.get(f"/v1/evolution/runs/{rid}").json()
        if d["status"] in ("succeeded", "failed"):
            return d
        time.sleep(0.5)
    pytest.fail("evolution run did not finish")


def test_stale_earlier_round_critic_test_is_retired_not_retried_forever(monkeypatch):
    _stubs(monkeypatch)
    d = _run()
    r1, r2, r3 = (d["rounds"][i]["sides"]["evoforge"] for i in range(3))
    assert r1["status"] == "READY" and r1["attempts"] == 1 and r1["critic_tests"] == 4
    assert r2["status"] == "READY" and r2["attempts"] == 2, r2.get("attempts")  # stopped after the repeat, not 3
    assert r2["critic_retired"] == 1
    assert any(e["role"] == "critic" and "retired" in e["message"].lower() for e in r2["events"])
    assert r3["attempts"] == 1 and r3["critic_tests"] == 9  # 4 + 3 + 3 minus the retired one
    assert r3.get("critic_retired", 0) == 0


def test_cost_drops_when_nothing_is_stale(monkeypatch):
    _stubs(monkeypatch)
    d = _run()
    assert sum(d["rounds"][i]["sides"]["evoforge"]["attempts"] for i in range(3)) == 4  # 1 + 2 + 1, not 1 + 3 + 3
