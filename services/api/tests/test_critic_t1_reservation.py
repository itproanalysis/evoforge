"""Critic acceptance (sealed during build, promoted after) — T1 provider failure vs. cost reservation."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import openai
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta, critic, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
REQ = httpx.Request("POST", "https://api.meta.ai/v1/chat/completions")


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    ledger.reset()
    ledger.configure({"default": 50000})
    yield
    ledger.reset()


def _raiser(exc):
    def f(*a, **k):
        raise exc
    return f


def _status(cls, code):
    return cls("boom", response=httpx.Response(code, request=REQ), body=None)


def test_not_accepted_refunds_and_502(monkeypatch):
    monkeypatch.setattr(broker_meta, "call_builder", _raiser(broker_meta.ProviderNotAccepted("401")))
    r = c.post("/v1/commands/generate", json={"goal": "t1 a", "idempotency_key": "t1-a"})
    assert r.status_code == 502
    assert "not accepted" in r.json()["detail"]
    s = ledger.snapshot()
    assert s["reserved_cents"] == 0 and s["spent_cents"] == 0
    assert s["unknown_reservations"] == []


def test_unknown_outcome_keeps_reservation(monkeypatch):
    monkeypatch.setattr(broker_meta, "call_builder", _raiser(broker_meta.ProviderOutcomeUnknown("timeout")))
    r = c.post("/v1/commands/generate", json={"goal": "t1 b", "idempotency_key": "t1-b"})
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "outcome unknown" in detail
    s = ledger.snapshot()
    assert s["reserved_cents"] == main.COST_CENTS and s["spent_cents"] == 0
    assert len(s["unknown_reservations"]) == 1
    assert s["unknown_reservations"][0] in detail


def test_unexpected_error_is_treated_as_unknown(monkeypatch):
    monkeypatch.setattr(broker_meta, "call_builder", _raiser(KeyError("diff")))
    r = c.post("/v1/commands/generate", json={"goal": "t1 c", "idempotency_key": "t1-c"})
    assert r.status_code == 502 and "outcome unknown" in r.json()["detail"]
    assert ledger.snapshot()["reserved_cents"] == main.COST_CENTS


def test_failed_generate_is_not_cached(monkeypatch):
    calls = []

    def flaky(goal, sha):
        calls.append(goal)
        if len(calls) == 1:
            raise broker_meta.ProviderNotAccepted("429")
        return {"diff": "", "tests": [{"code": "def test_a():\n    assert f() == 1\n"}], "stub": True}

    monkeypatch.setattr(broker_meta, "call_builder", flaky)
    r1 = c.post("/v1/commands/generate", json={"goal": "t1 d", "idempotency_key": "t1-d"})
    r2 = c.post("/v1/commands/generate", json={"goal": "t1 d", "idempotency_key": "t1-d"})
    assert r1.status_code == 502 and r2.status_code == 200
    assert len(calls) == 2
    s = ledger.snapshot()
    assert s["spent_cents"] == main.COST_CENTS and s["reserved_cents"] == 0


def test_gate_crash_after_call_still_settles(monkeypatch):
    from evoforge import gates
    monkeypatch.setattr(gates, "evaluate_integrity", _raiser(RuntimeError("gate bug")))
    if hasattr(main, "evaluate_integrity"):
        monkeypatch.setattr(main, "evaluate_integrity", _raiser(RuntimeError("gate bug")))
    r = c.post("/v1/commands/generate", json={"goal": "t1 e", "idempotency_key": "t1-e"})
    assert r.status_code >= 500
    s = ledger.snapshot()
    assert s["spent_cents"] == main.COST_CENTS and s["reserved_cents"] == 0


def test_success_path_unchanged():
    r = c.post("/v1/commands/generate", json={"goal": "t1 f", "idempotency_key": "t1-f"})
    assert r.status_code == 200
    s = ledger.snapshot()
    assert s["spent_cents"] == main.COST_CENTS and s["reserved_cents"] == 0


@pytest.mark.parametrize("exc,kind", [
    (lambda: broker_meta.ProviderNotAccepted("x"), "not accepted"),
    (lambda: broker_meta.ProviderOutcomeUnknown("x"), "outcome unknown"),
])
def test_review_endpoint_same_policy(monkeypatch, exc, kind):
    monkeypatch.setattr(broker_meta, "call_critic", _raiser(exc()))
    r = c.post("/v1/candidates/review", json={"goal_contract": "g", "diff": "d"})
    assert r.status_code == 502 and kind in r.json()["detail"]
    reserved = ledger.snapshot()["reserved_cents"]
    assert reserved == (0 if kind == "not accepted" else main.COST_CENTS)


def test_ledger_mark_unknown_rules():
    rid = ledger.reserve(100)
    out = ledger.mark_unknown(rid, "timeout")
    assert isinstance(out, dict)
    assert ledger.snapshot()["reserved_cents"] == 100
    assert ledger.snapshot()["unknown_reservations"] == [rid]
    with pytest.raises(ValueError):
        ledger.mark_unknown(rid, "again")
    with pytest.raises(KeyError):
        ledger.mark_unknown("rsv_nope", "x")
    done = ledger.reserve(10)
    ledger.settle(done, 10)
    with pytest.raises(ValueError):
        ledger.mark_unknown(done, "late")


class _FakeCompletions:
    def __init__(self, exc):
        self.exc = exc

    def create(self, **kw):
        raise self.exc


class _FakeClient:
    def __init__(self, exc):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(exc)})()


NOT_ACCEPTED = [
    lambda: _status(openai.AuthenticationError, 401),
    lambda: _status(openai.PermissionDeniedError, 403),
    lambda: _status(openai.BadRequestError, 400),
    lambda: _status(openai.NotFoundError, 404),
    lambda: _status(openai.UnprocessableEntityError, 422),
    lambda: _status(openai.RateLimitError, 429),
]
UNKNOWN = [
    lambda: openai.APITimeoutError(request=REQ),
    lambda: openai.APIConnectionError(request=REQ),
    lambda: _status(openai.InternalServerError, 500),
    lambda: _status(openai.APIStatusError, 503),
]


@pytest.mark.parametrize("make", NOT_ACCEPTED)
def test_broker_maps_not_accepted(monkeypatch, make):
    monkeypatch.setenv("MODEL_API_KEY", "test-not-a-real-key")
    monkeypatch.setattr(broker_meta, "_client", lambda: _FakeClient(make()))
    with pytest.raises(broker_meta.ProviderNotAccepted):
        broker_meta.call_builder("g", "HEAD")


@pytest.mark.parametrize("make", UNKNOWN)
def test_broker_maps_unknown(monkeypatch, make):
    monkeypatch.setenv("MODEL_API_KEY", "test-not-a-real-key")
    monkeypatch.setattr(broker_meta, "_client", lambda: _FakeClient(make()))
    with pytest.raises(broker_meta.ProviderOutcomeUnknown):
        broker_meta.call_builder("g", "HEAD")


@pytest.mark.parametrize("make,cls", [(NOT_ACCEPTED[0], "ProviderNotAccepted"), (UNKNOWN[0], "ProviderOutcomeUnknown")])
def test_critic_maps_errors(monkeypatch, make, cls):
    monkeypatch.setenv("MODEL_API_KEY", "test-not-a-real-key")
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: _FakeClient(make()))
    with pytest.raises(getattr(broker_meta, cls)):
        critic.call_critic("spec", "diff")


def test_stub_without_key_unchanged():
    out = broker_meta.call_builder("goal x", "abc")
    assert out["stub"] is True and "goal: goal x" in out["diff"]
