"""Critic acceptance (sealed during build, promoted after) — T13 reasoning-model token budget and explicit truncation (live finding)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import openai
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from evoforge import broker_meta, critic  # noqa: E402

VALID = [{"code": "def test_c():\n    assert f(f(1)) == 4\n", "kind": "compositional"},
         {"code": "def test_n():\n    assert f(-1) == 0\n", "kind": "negative"},
         {"code": "def test_b():\n    assert f(0) == 1\n", "kind": "boundary"}]


class _Resp:
    def __init__(self, n, content, finish):
        self.id = f"completion-{n}"
        self._request_id = f"request-{n}"
        self.usage = None
        self.choices = [type("C", (), {"finish_reason": finish,
                                        "message": type("M", (), {"content": content})()})()]


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "not-a-real-key")
    calls, plans = [], []

    class _Completions:
        def create(self, **kw):
            calls.append(kw)
            content, finish = plans.pop(0)
            return _Resp(len(calls), content if isinstance(content, str) else json.dumps(content), finish)

    class _Client:
        def __init__(self, **kw):
            self.chat = type("Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(openai, "OpenAI", _Client)
    monkeypatch.setattr(broker_meta, "_client", lambda: _Client())
    return {"calls": calls, "plans": plans}


def test_default_budgets_critic_16000_builder_8000(fake, monkeypatch):
    monkeypatch.delenv("MODEL_MAX_TOKENS", raising=False)
    monkeypatch.delenv("MODEL_CRITIC_MAX_TOKENS", raising=False)
    fake["plans"].extend([({"sealed_tests": VALID}, "stop"), ({"review": {"result": "PASS", "findings": []}}, "stop")])
    critic.call_critic("spec", "diff")
    fake["plans"].append(({"diff": "", "tests": [], "rationale": "r"}, "stop"))
    broker_meta.call_builder("goal", "HEAD")
    assert [c["max_tokens"] for c in fake["calls"]] == [16000, 16000, 8000]


@pytest.mark.parametrize("env,want", [("12000", 12000), ("abc", 8000), ("0", 8000), ("-5", 8000)])
def test_env_budget(fake, monkeypatch, env, want):
    monkeypatch.setenv("MODEL_MAX_TOKENS", env)
    fake["plans"].append(({"diff": "", "tests": [], "rationale": "r"}, "stop"))
    broker_meta.call_builder("goal", "HEAD")
    assert fake["calls"][-1]["max_tokens"] == want


@pytest.mark.parametrize("env,want", [("20000", 20000), ("abc", 16000), ("0", 16000), ("-5", 16000)])
def test_critic_env_budget(fake, monkeypatch, env, want):
    monkeypatch.setenv("MODEL_CRITIC_MAX_TOKENS", env)
    fake["plans"].extend([({"sealed_tests": VALID}, "stop"), ({"review": {"result": "PASS", "findings": []}}, "stop")])
    critic.call_critic("spec", "diff")
    assert [c["max_tokens"] for c in fake["calls"]] == [want, want]


def test_critic_env_beats_shared_env(fake, monkeypatch):
    monkeypatch.setenv("MODEL_MAX_TOKENS", "12000")
    monkeypatch.setenv("MODEL_CRITIC_MAX_TOKENS", "20000")
    fake["plans"].extend([({"sealed_tests": VALID}, "stop"), ({"review": {"result": "PASS", "findings": []}}, "stop")])
    critic.call_critic("spec", "diff")
    assert [c["max_tokens"] for c in fake["calls"]] == [20000, 20000]


def test_phase_a_truncation_is_explicit(fake):
    fake["plans"].append(("", "length"))
    out = critic.call_critic("spec", "diff")
    assert len(fake["calls"]) == 1  # no Phase B
    assert out["sealed_tests"] == [] and out["review"]["result"] == "INCONCLUSIVE"
    notes = " ".join(f.get("note", "") for f in out["review"]["findings"])
    assert "truncated" in notes and "16000" in notes


def test_phase_a_truncated_even_if_partial_json_parses(fake):
    fake["plans"].append(({"sealed_tests": VALID}, "length"))  # never salvage a truncated reply
    out = critic.call_critic("spec", "diff")
    assert len(fake["calls"]) == 1 and out["sealed_tests"] == []
    assert "truncated" in json.dumps(out["review"]["findings"])


def test_phase_b_truncation_is_explicit(fake):
    fake["plans"].extend([({"sealed_tests": VALID}, "stop"), ("", "length")])
    out = critic.call_critic("spec", "diff")
    assert len(fake["calls"]) == 2
    assert out["sealed_tests"] == VALID
    assert out["review"]["result"] == "INCONCLUSIVE" and "truncated" in json.dumps(out["review"]["findings"])


def test_builder_truncation_is_explicit(fake):
    fake["plans"].append(("", "length"))
    out = broker_meta.call_builder("goal", "HEAD")
    assert out["diff"] == "" and out["tests"] == [] and "truncated" in out["rationale"]
    assert out["stub"] is False and out["provider_calls"]


def test_success_paths_unchanged(fake):
    fake["plans"].extend([({"sealed_tests": VALID}, "stop"), ({"review": {"result": "PASS", "findings": []}}, "stop")])
    out = critic.call_critic("spec", "diff")
    assert out["sealed_tests"] == VALID and out["review"]["result"] == "PASS"
