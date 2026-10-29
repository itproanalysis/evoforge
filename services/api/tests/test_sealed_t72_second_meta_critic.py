"""Sealed (Critic) — T72: the Critic (and the prompt-Arena judge, which uses the Critic) can run on a second Meta
open-weight model behind any OpenAI-compatible endpoint (e.g. Llama on Fireworks/Baseten), configured only by env.
Unset -> exactly today's Meta Model API path. The key never appears in any output; cost uses the owner-set prices of
that provider (no guessed prices: unset prices -> refuse before any call); the fairness manifest names the Critic."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge import arena_prompt, broker_meta, critic, performance  # noqa: E402

KEY = "sk-test-SECRET-t72-0123456789"
MODEL = "accounts/fireworks/models/llama-v3p3-70b-instruct"
BASE = "https://api.fireworks.ai/inference/v1"


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)
        self.finish_reason = "stop"


class _Usage:
    def model_dump(self):
        return {"prompt_tokens": 1000, "completion_tokens": 100}


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]
        self.usage = _Usage()
        self.id = "resp_t72"
        self.model = MODEL


SUITE = {"sealed_tests": [
    {"code": "def test_a():\n    import m\n    assert m.f(1) == 2", "kind": "compositional"},
    {"code": "def test_b():\n    import m, pytest\n    with pytest.raises(ValueError):\n        m.f(-1)", "kind": "negative"},
    {"code": "def test_c():\n    import m\n    assert m.f(0) == 1", "kind": "boundary"}]}


class _FakeOpenAI:
    instances: list = []

    def __init__(self, **kw):
        self.kw = kw
        self.calls = 0
        _FakeOpenAI.instances.append(self)
        outer = self

        class _Completions:
            def create(self, **req):
                outer.last_model = req.get("model")
                outer.calls += 1
                return _Resp(json.dumps(SUITE if outer.calls == 1 else {"review": {"result": "PASS", "findings": []}}))

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


@pytest.fixture
def fake_openai(monkeypatch):
    import openai
    _FakeOpenAI.instances = []
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    monkeypatch.setenv("MODEL_API_KEY", "meta-platform-key-t72")
    for k in ("CRITIC_API_BASE", "CRITIC_API_KEY", "CRITIC_PRICE_INPUT_PER_MTOK", "CRITIC_PRICE_OUTPUT_PER_MTOK"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("MODEL_CRITIC", raising=False)
    return _FakeOpenAI


def _second(monkeypatch, prices=True):
    monkeypatch.setenv("CRITIC_API_BASE", BASE)
    monkeypatch.setenv("CRITIC_API_KEY", KEY)
    monkeypatch.setenv("MODEL_CRITIC", MODEL)
    if prices:
        monkeypatch.setenv("CRITIC_PRICE_INPUT_PER_MTOK", "0.90")
        monkeypatch.setenv("CRITIC_PRICE_OUTPUT_PER_MTOK", "0.90")


def test_unset_keeps_todays_meta_path(fake_openai):
    ep = critic.critic_endpoint()
    assert ep["provider"] == "api.meta.ai" and ep["model"] == "muse-spark-1.3"
    out = critic.call_critic("f(x) returns x+1; negative raises ValueError")
    assert fake_openai.instances[0].kw["base_url"] == os.getenv("MODEL_API_BASE", "https://api.meta.ai/v1")
    assert fake_openai.instances[0].kw["api_key"] == "meta-platform-key-t72"
    assert out["model"] == "muse-spark-1.3" and out.get("provider") == "api.meta.ai"


def test_second_meta_model_endpoint_and_no_key_leak(fake_openai, monkeypatch):
    _second(monkeypatch)
    ep = critic.critic_endpoint()
    assert ep["provider"] == "api.fireworks.ai" and ep["model"] == MODEL and "key" not in json.dumps(ep).lower()
    out = critic.call_critic("f(x) returns x+1; negative raises ValueError", "diff", "ci")
    kw = fake_openai.instances[0].kw
    assert kw["base_url"] == BASE and kw["api_key"] == KEY and kw.get("max_retries") == 0
    assert fake_openai.instances[0].last_model == MODEL
    assert out["model"] == MODEL and out["provider"] == "api.fireworks.ai"
    assert len(out["sealed_tests"]) == 3 and out["review"]["result"] == "PASS"
    assert all(c.get("provider") == "api.fireworks.ai" for c in out["provider_calls"])
    assert KEY not in json.dumps(out, default=str)


def test_cost_uses_the_providers_prices(monkeypatch):
    _second(monkeypatch)
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 0}
    assert performance.usage_cost_cents(usage, model=MODEL) == 90
    out = {"model": MODEL, "usage": {"prompt_tokens": 500_000, "completion_tokens": 500_000}}
    assert performance.output_cost_cents(out) == 90
    default = performance.usage_cost_cents(usage)  # Builder / Meta API prices unchanged
    assert default == performance.usage_cost_cents(usage, model="muse-spark-1.3")
    assert default != 90 or performance.prices()[0] == 0.90


def test_missing_prices_refuse_before_any_call(fake_openai, monkeypatch):
    _second(monkeypatch, prices=False)
    with pytest.raises(broker_meta.ProviderNotAccepted):
        critic.call_critic("spec")
    assert fake_openai.instances == []  # nothing sent, nothing billed


def test_manifest_names_the_critic(fake_openai, monkeypatch):
    m = arena_prompt.build_manifest("a page", "critic", "strict")
    assert m["lanes"]["evoforge"]["critic_model"] == "muse-spark-1.3"
    assert m["lanes"]["evoforge"]["critic_provider"] == "api.meta.ai"
    _second(monkeypatch)
    m = arena_prompt.build_manifest("a page", "critic", "strict")
    assert m["lanes"]["evoforge"]["critic_model"] == MODEL
    assert m["lanes"]["evoforge"]["critic_provider"] == "api.fireworks.ai"
    assert m["judge_model"] == MODEL  # the acceptance tests come from the Critic model
    assert m["lanes"]["single"]["model"] == m["lanes"]["evoforge"]["model"]  # Builders stay equal
    assert KEY not in json.dumps(m)


def test_critic_key_never_goes_to_the_meta_endpoint(fake_openai, monkeypatch):
    """Critic review: CRITIC_API_KEY without CRITIC_API_BASE must not be sent to api.meta.ai."""
    monkeypatch.setenv("CRITIC_API_KEY", KEY)
    critic.call_critic("f(x) returns x+1; negative raises ValueError")
    kw = fake_openai.instances[0].kw
    assert kw["api_key"] == "meta-platform-key-t72" and kw["base_url"] != BASE
