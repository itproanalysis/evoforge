"""Critic acceptance (sealed during build, promoted after) — T12 sealed test code never appears in an HTTP body (finding F3)."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import openai
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from critic_helpers import sealed_suite, server_review  # noqa: E402
from evoforge import commands, critic, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
MARK = "T12_SEALED_MARK_3377"
REAL = sealed_suite(f"from v import result\n\ndef test_h():\n    assert result == 3  # {MARK}\n")
STRONG = [{"code": "def test_value():\n    assert result == 3\n"}]
SEEN: list = []


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    ledger.reset()
    ledger.configure({"default": 50000})
    commands.reset()
    SEEN.clear()
    from evoforge import runner

    def fake(source_repo, base_sha, diff, visible_tests, heldout_tests, timeout_s=120, future_shas=None):
        SEEN.append([t["code"] for t in heldout_tests])
        return {"base": "b" * 40, "hygiene": [], "heldout_kinds": [t["kind"] for t in heldout_tests],
                "visible": {"pass": 1, "n": 1, "timed_out": False, "exit_code": 0},
                "heldout": {"pass": 3, "n": 3, "timed_out": False, "exit_code": 0}}

    monkeypatch.setattr(runner, "run_candidate", fake)


def _all_evidence_text():
    return "".join(c.get(f"/v1/evidence/{eid}").text for eid in list(main._evidence))


def _check_metadata(entries, suite):
    assert len(entries) == len(suite)
    for got, want in zip(entries, suite):
        assert "code" not in got
        assert got["kind"] == want["kind"]
        assert got["code_sha256"] == hashlib.sha256(want["code"].encode("utf-8")).hexdigest()
        assert got["code_len"] == len(want["code"])


def test_review_http_redacts_but_run_executes_full_code(monkeypatch):
    from evoforge import broker_meta
    out = {"sealed_tests": REAL, "review": {"result": "PASS", "findings": []}, "stub": False,
           "execution_verified": False, "model": "muse-spark-1.3"}
    monkeypatch.setattr(broker_meta, "call_critic", lambda *a, **k: json.loads(json.dumps(out)))
    r = c.post("/v1/candidates/review", json={"goal_contract": "spec", "diff": ""})
    assert r.status_code == 200 and MARK not in r.text
    _check_metadata(r.json()["sealed_tests"], REAL)
    rid = r.json()["evidence_id"]
    ev = c.get(f"/v1/evidence/{rid}")
    assert MARK not in ev.text
    run = c.post("/v1/runs", json={"source_repo": "C:/repos/p", "base_sha": "b" * 40, "diff": "",
                                   "tests": STRONG, "review_evidence_id": rid})
    assert run.status_code == 200, run.text
    assert SEEN and all(MARK in code for code in SEEN[0])  # server ran the unredacted suite
    assert MARK not in run.text and MARK not in _all_evidence_text()


def test_stub_review_http_redacted():
    r = c.post("/v1/candidates/review", json={"goal_contract": "add numbers", "diff": ""})
    assert r.status_code == 200
    assert "def test_" not in r.text
    assert all({"kind", "code_sha256", "code_len"} <= set(t) for t in r.json()["sealed_tests"])


def test_python_critic_shape_unchanged():
    out = critic.call_critic("add numbers", "")
    assert all("def test_" in t["code"] for t in out["sealed_tests"])


class _Resp:
    def __init__(self, n, content):
        self.id = f"completion-{n}"
        self._request_id = f"request-{n}"
        self.usage = None
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]


def test_model_path_audits_redacted(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "not-a-real-key")
    plans = [{"sealed_tests": REAL}, {"review": {"result": "PASS", "findings": []}}]
    calls = []

    class _Completions:
        def create(self, **kw):
            calls.append(kw)
            return _Resp(len(calls), json.dumps(plans.pop(0)))

    class _Client:
        def __init__(self, **kw):
            self.chat = type("Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(openai, "OpenAI", _Client)
    r = c.post("/v1/candidates/review", json={"goal_contract": "spec", "diff": "d"})
    assert r.status_code == 200, r.text
    assert MARK not in r.text
    assert MARK not in _all_evidence_text()  # includes provider_call audit records
