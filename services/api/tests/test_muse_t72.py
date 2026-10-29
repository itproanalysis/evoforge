"""Builder acceptance — T72 second Critic provider on another Meta open model.

No network: openai.OpenAI is substituted; costs are usage-derived.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import openai
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from evoforge import arena, arena_prompt, broker_meta, critic, ledger, performance, sealed_eval  # noqa: E402

VALID = [{"code": "def test_c():\n    assert f(f(1)) == 4\n", "kind": "compositional"},
         {"code": "def test_n():\n    assert f(-1) == 0\n", "kind": "negative"},
         {"code": "def test_b():\n    assert f(0) == 1\n", "kind": "boundary"}]


class _Resp:
    def __init__(self, n, content, finish="stop"):
        self.id = f"completion-{n}"
        self._request_id = f"request-{n}"
        self.usage = None
        self.choices = [type("C", (), {"finish_reason": finish,
                                       "message": type("M", (), {"content": content})()})()]


@pytest.fixture
def fake_openai(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "MODEL-SECRET-abc")
    ctor, calls, plans = [], [], []

    class _Completions:
        def create(self, **kw):
            calls.append(kw)
            content, finish = plans.pop(0)
            return _Resp(len(calls), content if isinstance(content, str) else json.dumps(content), finish)

    class _Client:
        def __init__(self, **kw):
            ctor.append(kw)
            self.chat = type("Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(openai, "OpenAI", _Client)
    return {"ctor": ctor, "calls": calls, "plans": plans}


@pytest.fixture
def _ledger():
    ledger.reset()
    ledger.configure({"default": 500000})
    yield
    ledger.reset()
    ledger.configure({"default": 50000})


def _clear_critic_env(monkeypatch):
    for name in ("CRITIC_API_BASE", "CRITIC_API_KEY",
                 "CRITIC_PRICE_INPUT_PER_MTOK", "CRITIC_PRICE_OUTPUT_PER_MTOK",
                 "MODEL_API_BASE", "MODEL_CRITIC"):
        monkeypatch.delenv(name, raising=False)


def test_endpoint_defaults_to_builder_meta_endpoint(monkeypatch):
    _clear_critic_env(monkeypatch)
    ep = critic.critic_endpoint()
    assert ep == {"base_url": "https://api.meta.ai/v1", "model": "muse-spark-1.3",
                  "provider": "api.meta.ai", "second": False}
    assert "CRITIC" not in json.dumps(ep) and "KEY" not in json.dumps(ep)


def test_endpoint_second_provider(monkeypatch):
    _clear_critic_env(monkeypatch)
    monkeypatch.setenv("CRITIC_API_BASE", "https://api.fireworks.ai/v1")
    monkeypatch.setenv("CRITIC_API_KEY", "CRITIC-SECRET-xyz")
    monkeypatch.setenv("MODEL_CRITIC", "critic-2")
    ep = critic.critic_endpoint()
    assert ep == {"base_url": "https://api.fireworks.ai/v1", "model": "critic-2",
                  "provider": "api.fireworks.ai", "second": True}
    blob = json.dumps(ep)
    assert "CRITIC-SECRET-xyz" not in blob


def test_endpoint_needs_both_base_and_key(monkeypatch):
    _clear_critic_env(monkeypatch)
    monkeypatch.setenv("CRITIC_API_BASE", "https://api.fireworks.ai/v1")
    assert critic.critic_endpoint()["second"] is False


def test_call_critic_default_uses_meta_key_and_reports_provider(monkeypatch, fake_openai):
    _clear_critic_env(monkeypatch)
    fake_openai["plans"].extend([({"sealed_tests": VALID}, "stop"),
                                 ({"review": {"result": "PASS", "findings": []}}, "stop")])
    out = critic.call_critic("spec", "diff")
    assert fake_openai["ctor"][0]["base_url"] == "https://api.meta.ai/v1"
    assert fake_openai["ctor"][0]["api_key"] == "MODEL-SECRET-abc"
    assert fake_openai["ctor"][0]["max_retries"] == 0
    assert out["provider"] == "api.meta.ai"
    assert all(call["provider"] == "api.meta.ai" for call in out["provider_calls"])
    blob = json.dumps(out)
    assert "MODEL-SECRET-abc" not in blob


def test_call_critic_second_provider_uses_critic_key(monkeypatch, fake_openai):
    _clear_critic_env(monkeypatch)
    monkeypatch.setenv("CRITIC_API_BASE", "https://api.fireworks.ai/v1")
    monkeypatch.setenv("CRITIC_API_KEY", "CRITIC-SECRET-xyz")
    monkeypatch.setenv("CRITIC_PRICE_INPUT_PER_MTOK", "2.0")
    monkeypatch.setenv("CRITIC_PRICE_OUTPUT_PER_MTOK", "8.0")
    monkeypatch.setenv("MODEL_CRITIC", "critic-2")
    fake_openai["plans"].extend([({"sealed_tests": VALID}, "stop"),
                                 ({"review": {"result": "PASS", "findings": []}}, "stop")])
    out = critic.call_critic("spec", "diff")
    assert fake_openai["ctor"][0]["base_url"] == "https://api.fireworks.ai/v1"
    assert fake_openai["ctor"][0]["api_key"] == "CRITIC-SECRET-xyz"
    assert out["model"] == "critic-2" and out["provider"] == "api.fireworks.ai"
    assert all(call["provider"] == "api.fireworks.ai" for call in out["provider_calls"])
    blob = json.dumps(out)
    assert "CRITIC-SECRET-xyz" not in blob and "MODEL-SECRET-abc" not in blob


def test_call_critic_second_without_prices_refuses_before_client(monkeypatch, fake_openai):
    _clear_critic_env(monkeypatch)
    monkeypatch.setenv("CRITIC_API_BASE", "https://api.fireworks.ai/v1")
    monkeypatch.setenv("CRITIC_API_KEY", "CRITIC-SECRET-xyz")
    with pytest.raises(broker_meta.ProviderNotAccepted):
        critic.call_critic("spec", "diff")
    assert fake_openai["ctor"] == [] and fake_openai["calls"] == []


def test_stub_path_unchanged_without_key(monkeypatch, fake_openai):
    _clear_critic_env(monkeypatch)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    out = critic.call_critic("spec", "diff")
    assert out["stub"] is True
    assert fake_openai["ctor"] == []


def test_critic_pricing_and_cache_at_input_price(monkeypatch):
    _clear_critic_env(monkeypatch)
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    assert performance.usage_cost_cents(usage) == 550  # today's EVO prices
    monkeypatch.setenv("CRITIC_API_BASE", "https://api.fireworks.ai/v1")
    monkeypatch.setenv("CRITIC_API_KEY", "k")
    monkeypatch.setenv("CRITIC_PRICE_INPUT_PER_MTOK", "2.0")
    monkeypatch.setenv("CRITIC_PRICE_OUTPUT_PER_MTOK", "8.0")
    monkeypatch.setenv("MODEL_CRITIC", "critic-2")
    assert performance.usage_cost_cents(usage) == 550  # no model -> Builder prices
    assert performance.usage_cost_cents(usage, model="muse-spark-1.3") == 550
    assert performance.usage_cost_cents(usage, model="critic-2") == 1000
    cached = {"prompt_tokens": 1_000_000, "completion_tokens": 0, "cached_tokens": 1_000_000}
    assert performance.usage_cost_cents(cached) == 15
    assert performance.usage_cost_cents(cached, model="critic-2") == 200
    out = {"model": "critic-2", "usage": dict(usage)}
    assert performance.output_cost_cents(out) == 1000
    assert performance.output_cost_cents({"model": "muse-spark-1.3", "usage": dict(usage)}) == 550
    assert performance.output_cost_cents({"model": "critic-2"}) is None
    assert performance.output_cost_cents(None) is None


def test_critic_suite_settles_at_critic_prices(monkeypatch, _ledger):
    _clear_critic_env(monkeypatch)
    monkeypatch.setenv("CRITIC_API_BASE", "https://api.fireworks.ai/v1")
    monkeypatch.setenv("CRITIC_API_KEY", "k")
    monkeypatch.setenv("CRITIC_PRICE_INPUT_PER_MTOK", "2.0")
    monkeypatch.setenv("CRITIC_PRICE_OUTPUT_PER_MTOK", "8.0")
    monkeypatch.setenv("MODEL_CRITIC", "critic-2")
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}

    def fake_critic(goal, diff, ci="", **k):
        return {"sealed_tests": VALID, "review": {"result": "PASS", "findings": []},
                "stub": False, "model": "critic-2", "usage": dict(usage)}

    monkeypatch.setattr(broker_meta, "call_critic", fake_critic)
    _rsv, _out, actual, missing = sealed_eval._call_critic_suite("goal")
    assert actual == 1000 and missing is False


def test_prompt_manifest_discloses_judge_and_critic(monkeypatch):
    _clear_critic_env(monkeypatch)
    m = arena_prompt.build_manifest("do it", "critic", "tolerant")
    assert m["judge_model"] == "muse-spark-1.3"
    assert m["lanes"]["evoforge"]["critic_model"] == "muse-spark-1.3"
    assert m["lanes"]["evoforge"]["critic_provider"] == "api.meta.ai"
    assert m["lanes"]["single"]["model"] == m["lanes"]["evoforge"]["model"] == "muse-spark-1.3"
    monkeypatch.setenv("CRITIC_API_BASE", "https://api.baseten.co/v1")
    monkeypatch.setenv("CRITIC_API_KEY", "k")
    monkeypatch.setenv("MODEL_CRITIC", "critic-2")
    m = arena_prompt.build_manifest("do it", "critic", "tolerant")
    assert m["judge_model"] == "critic-2"
    assert m["lanes"]["evoforge"]["critic_model"] == "critic-2"
    assert m["lanes"]["evoforge"]["critic_provider"] == "api.baseten.co"
    assert m["lanes"]["single"]["model"] == m["lanes"]["evoforge"]["model"]


def test_arena_manifest_discloses_critic(monkeypatch):
    _clear_critic_env(monkeypatch)
    task = {"id": "t", "goal": "g", "files": {"a.py": "x = 1\n"}, "heldout": []}
    m = arena.build_manifest("v2", "t", "muse-spark-1.3", task, feedback="critic")
    assert m["lanes"]["evoforge"]["critic_model"] == "muse-spark-1.3"
    assert m["lanes"]["evoforge"]["critic_provider"] == "api.meta.ai"
    assert m["lanes"]["single"]["model"] == m["lanes"]["evoforge"]["model"] == "muse-spark-1.3"
