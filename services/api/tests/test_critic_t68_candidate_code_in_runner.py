"""Sealed (Critic) — T68 / SEC-02: candidate code leaves the API container. With a Runner configured, every score of
Builder output (pipeline, Arena, evolution rounds) and every preview() render runs in the secret-free Runner service;
the API never executes candidate code itself, and a Runner failure fails closed (no local fallback)."""
from __future__ import annotations

import difflib
import importlib.util
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
from evoforge import broker_meta, ledger, runner, runner_client, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
ROOT = Path(__file__).resolve().parents[3]
RUNNER_PY = ROOT / "services" / "runner" / "app.py"
APP = json.loads((ROOT / "evals" / "rounds_v1" / "mission_board.json").read_text(encoding="utf-8"))
USAGE = {"prompt_tokens": 1000, "completion_tokens": 200}


def _load_runner():
    spec = importlib.util.spec_from_file_location("evoforge_runner_service_t68", RUNNER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUNNER = _load_runner()
RC = TestClient(RUNNER.app, raise_server_exceptions=False)


class _Resp:
    def __init__(self, r):
        self.status_code, self.text, self._r = r.status_code, r.text, r

    def json(self):
        return self._r.json()


def _settle(limit=300):
    end = time.time() + limit
    while time.time() < end and any(j["status"] in ("queued", "running") for j in c.get("/v1/eval/jobs").json()["jobs"]):
        time.sleep(0.3)


@pytest.fixture(autouse=True)
def wired(monkeypatch):
    _settle()
    sealed_eval.load_suites("v2")  # suite validation (trusted Critic data) may run locally, before the guard below
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("EVO_RUNNER_URL", "http://runner.test")
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset(); ledger.configure({"default": 500000})
    calls = {"n": 0, "preview": 0, "fail": False}

    def post(url, json=None, headers=None, timeout=None, **k):
        assert url.endswith("/run"), url
        calls["n"] += 1
        if json.get("preview_module"):
            calls["preview"] += 1
        if calls["fail"]:
            class R:
                status_code, text = 500, "runner down"

                def json(self):
                    return {}
            return R()
        return _Resp(RC.post("/run", json=json))
    import httpx
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(runner_client, "_auth_headers", lambda: {})

    def no_local(*a, **k):
        raise AssertionError("candidate code executed inside the API process")
    monkeypatch.setattr(runner, "_run_suite", no_local)  # the API-side local executor must stay unused
    yield calls
    _settle()


def _round_of(goal):
    m = re.search(r"Round (\d) ", goal or "")
    return int(m.group(1)) if m else 1


def _stub_rounds(monkeypatch):
    def builder(goal, sha, file_context=None, **k):
        n = _round_of(goal)
        current = next(f["content"] for f in (file_context or []) if f["path"] == "board.py")
        d = "".join(difflib.unified_diff(current.splitlines(True), APP["rounds"][n - 1]["reference"].splitlines(True),
                                         "a/board.py", "b/board.py"))
        return {"diff": d, "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": USAGE}

    def critic(goal, diff, ci="", **k):
        n = _round_of(goal)
        return {"sealed_tests": [{"code": h["code"].replace("def test_", "def test_critic_")}
                                 for h in APP["rounds"][n - 1]["heldout"]], "stub": False, "usage": USAGE}
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    monkeypatch.setattr(broker_meta, "call_critic", critic)


def _wait(path):
    end = time.time() + 900
    while time.time() < end:
        d = c.get(path).json()
        if d["status"] in ("succeeded", "failed"):
            return d
        time.sleep(0.5)
    pytest.fail(f"{path} did not finish")


def test_run_files_returns_counts_failure_names_and_a_preview(wired):
    files = {"m.py": "def f():\n    return 1\n\n\ndef preview():\n    return '<p>' + str(f()) + '</p>'\n"}
    tests = [{"code": "import m\n\n\ndef test_ok():\n    assert m.f() == 1\n"},
             {"code": "import m\n\n\ndef test_wrong():\n    assert m.f() == 2\n"}]
    out = runner_client.run_files(files, tests, timeout_s=60, preview_module="m")
    h = out["heldout"]
    assert (h["pass"], h["n"]) == (1, 2) and h["report_integrity"] is True
    assert any("test_wrong" in f["test"] for f in h["failures"]) and not any("test_ok" in f["test"] for f in h["failures"])
    assert out["preview"] == {"html": "<p>1</p>", "error": None}
    assert wired["n"] == 1


def test_evolution_rounds_score_and_render_in_the_runner(monkeypatch, wired):
    _stub_rounds(monkeypatch)
    r = c.post("/v1/evolution/runs", json={"app_id": "mission_board", "rounds": 2})
    assert r.status_code == 202, r.text
    d = _wait(f"/v1/evolution/runs/{r.json()['run_id']}")
    for rnd in d["rounds"]:
        for side in ("single", "evoforge"):
            s = rnd["sides"][side]
            assert s["status"] == "READY", (rnd["index"], side, s.get("events"))
            assert "Mission Board" in s["preview_html"]
    assert wired["n"] >= 8 and wired["preview"] >= 4  # scoring + Critic + previews all went to the Runner


def test_arena_scores_in_the_runner(monkeypatch, wired):
    t = next(x for s in sealed_eval.load_suites("v2") for x in s["tasks"] if x["id"] == "SV2-SS-01")
    monkeypatch.setattr(broker_meta, "call_builder", lambda goal, sha, file_context=None, **k: {
        "diff": t["reference_fix"], "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
        "provider_calls": [], "usage": USAGE})
    r = c.post("/v1/arena", json={"suite_version": "v2", "task_id": "SV2-SS-01"})
    assert r.status_code == 202, r.text
    a = _wait(f"/v1/arena/{r.json()['arena_id']}")
    assert a["lanes"]["single"]["heldout"]["passed"] == a["lanes"]["single"]["heldout"]["n"] > 0
    assert a["verdict"]["winner"] == "tie" and wired["n"] >= 2


def test_runner_failure_fails_closed(monkeypatch, wired):
    _stub_rounds(monkeypatch)
    wired["fail"] = True
    r = c.post("/v1/evolution/runs", json={"app_id": "mission_board", "rounds": 1})
    assert r.status_code == 202, r.text
    d = _wait(f"/v1/evolution/runs/{r.json()['run_id']}")
    s = d["rounds"][0]["sides"]["single"]
    assert s["status"] in ("FAILED", "UNVERIFIED") and s["verified"] is False  # never READY without a Runner verdict
