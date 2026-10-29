"""Critic — with EVO_RUNNER_URL set the pipeline never sends its ephemeral sealed-task repos down the repo-based remote
path (production RunnerBadRequest, release 5). Since T68 / SEC-02 it scores in the Runner by shipping exactly the files
(runner_client.run_files), never in the API process."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta, ledger, runner_client, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
RUNNER_PY = Path(__file__).resolve().parents[2] / "runner" / "app.py"


def _runner_client_in_process():
    spec = importlib.util.spec_from_file_location("evoforge_runner_for_pipeline_test", RUNNER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return TestClient(mod.app, raise_server_exceptions=False)


class _Resp:
    def __init__(self, r):
        self.status_code, self.text, self._r = r.status_code, r.text, r

    def json(self):
        return self._r.json()


def test_pipeline_with_runner_configured_never_sends_ephemeral_tasks_to_the_runner(monkeypatch):
    ledger.reset(); ledger.configure({"default": 500000})
    from evoforge import performance
    performance.clear()
    tasks = {t["goal"]: t for s in sealed_eval.load_suites("v1") for t in s["tasks"]}
    monkeypatch.setenv("EVO_RUNNER_URL", "https://runner.invalid")
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    monkeypatch.setattr(sealed_eval, "_run_heldout_remote",
                        lambda *a, **k: pytest.fail("pipeline must not use the repo-based remote path for sealed tasks"))
    rc = _runner_client_in_process()
    sent = []
    import httpx

    def post(url, json=None, headers=None, timeout=None, **k):
        sent.append(url)
        return _Resp(rc.post("/run", json=json))
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(runner_client, "_auth_headers", lambda: {})
    monkeypatch.setattr(broker_meta, "call_builder", lambda goal, sha, file_context=None, **k: {
        "diff": next((t["reference_fix"] for g, t in tasks.items() if g in goal), ""), "tests": [], "rationale": "x",
        "stub": False, "model": "m", "provider_calls": []})
    r = c.post("/v1/eval/pipeline", json={"suite_version": "v1", "family": "simple_sequential"})
    assert r.status_code == 201, r.text
    assert c.get("/v1/performance").json()["pipeline"]["passed"] == 2
    assert sent and all(u.endswith("/run") for u in sent)  # scored in the Runner (files shipped), not in the API
