"""Critic acceptance (sealed during build, promoted after) — T8 sealed held-out suite shape (Muse Spark round-3 plan)."""
from __future__ import annotations

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
from evoforge import commands, critic, ledger  # noqa: E402

KINDS = {"compositional", "negative", "boundary"}
DIFF_MARK = "T8_DIFF_SENTINEL_5521"
VALID = [{"code": "def test_c():\n    assert f(f(1)) == 4\n", "kind": "compositional"},
         {"code": "def test_n():\n    assert f(-1) == 0\n", "kind": "negative"},
         {"code": "def test_b():\n    assert f(0) == 1\n", "kind": "boundary"}]


def _valid_suite(tests):
    return (isinstance(tests, list) and len(tests) >= 3
            and all(isinstance(t, dict) and isinstance(t.get("code"), str) and "def test_" in t["code"]
                    and t.get("kind") in KINDS for t in tests)
            and KINDS <= {t["kind"] for t in tests})


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    ledger.reset()
    ledger.configure({"default": 50000})
    commands.reset()


# ---- stub (no key) ----

def test_stub_builds_three_kind_suite_from_goal_only():
    out = critic.call_critic("add two numbers correctly", f"--- a/x\n+++ b/x\n+{DIFF_MARK}\n")
    assert out["stub"] is True and out["review"]["result"] == "INCONCLUSIVE"
    assert _valid_suite(out["sealed_tests"]), out["sealed_tests"]
    assert DIFF_MARK not in json.dumps(out["sealed_tests"])
    for t in out["sealed_tests"]:
        compile(t["code"], "<sealed>", "exec")


def test_stub_is_deterministic():
    a = critic.call_critic("goal X", "d1")
    b = critic.call_critic("goal X", "d2")
    assert a["sealed_tests"] == b["sealed_tests"]


def test_stub_via_api_is_200_and_shaped():
    c = TestClient(main.app, raise_server_exceptions=False)
    r = c.post("/v1/candidates/review", json={"goal_contract": "spec", "diff": "d"})
    assert r.status_code == 200
    st = r.json()["sealed_tests"]  # T12: redacted over HTTP
    assert len(st) >= 3 and KINDS <= {t["kind"] for t in st} and all("code" not in t for t in st)


# ---- model path with a fake OpenAI client ----

class _Resp:
    def __init__(self, n, content):
        self.id = f"completion-{n}"
        self._request_id = f"request-{n}"
        self.usage = None
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "not-a-real-key")
    calls, plans = [], []

    class _Completions:
        def create(self, **kw):
            calls.append(kw)
            plan = plans.pop(0)
            return _Resp(len(calls), plan if isinstance(plan, str) else json.dumps(plan))

    class _Client:
        def __init__(self, **kw):
            self.chat = type("Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(openai, "OpenAI", _Client)
    return {"calls": calls, "plans": plans}


REVIEW_PASS = {"review": {"result": "PASS", "findings": []}}


def test_valid_model_suite_passes_through(model):
    model["plans"].extend([{"sealed_tests": VALID}, REVIEW_PASS])
    out = critic.call_critic("spec", f"diff {DIFF_MARK}")
    assert out["sealed_tests"] == VALID
    assert out["review"]["result"] == "PASS" and out["stub"] is False
    assert len(model["calls"]) == 2
    assert DIFF_MARK not in json.dumps(model["calls"][0]["messages"])  # Phase A = goal only


@pytest.mark.parametrize("bad", [
    VALID[:2],                                                          # < 3 tests
    [dict(t, kind="compositional") for t in VALID],                     # kinds missing
    [VALID[0], VALID[1], {"code": "assert f(0) == 1\n", "kind": "boundary"}],  # no def test_
    [VALID[0], VALID[1], {"code": "def test_b():\n    assert 1\n", "kind": "weird"}],  # unknown kind
    [VALID[0], VALID[1], {"kind": "boundary"}],                         # missing code
])
def test_bad_model_suite_is_inconclusive_without_phase_b(model, bad):
    model["plans"].extend([{"sealed_tests": bad}, REVIEW_PASS])
    out = critic.call_critic("spec", "diff")
    assert out["review"]["result"] == "INCONCLUSIVE" and out["review"].get("findings")
    assert out["stub"] is False and out["execution_verified"] is False
    assert len(model["calls"]) == 1
    st = out["sealed_tests"]
    assert st == [] or _valid_suite(st)


def test_bad_model_suite_via_api_is_200(model):
    model["plans"].extend([{"sealed_tests": VALID[:1]}, REVIEW_PASS])
    c = TestClient(main.app, raise_server_exceptions=False)
    r = c.post("/v1/candidates/review", json={"goal_contract": "spec", "diff": "d"})
    assert r.status_code == 200, r.text
    assert r.json()["review"]["result"] == "INCONCLUSIVE"


def test_ensure_sealed_suite_helper():
    ok, normalized, findings = critic.ensure_sealed_suite(VALID)
    assert ok is True and _valid_suite(normalized) and isinstance(findings, list)
    ok, normalized, findings = critic.ensure_sealed_suite(VALID[:2])
    assert ok is False and findings
    ok, _, _ = critic.ensure_sealed_suite("not a list")
    assert ok is False
