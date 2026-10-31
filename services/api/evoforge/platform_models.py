"""Server-managed, first-party model transports for the judging profile.

Transport only: callers must reserve before dispatch and settle/refund/hold
from the returned usage or broker exception. No retries, fallback, user URL,
credential serialization, or model-provided cost fields are accepted here.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
import json
import os
import re
import time
from types import MappingProxyType, SimpleNamespace
from typing import Any

import httpx


@dataclass(frozen=True)
class ModelSpec:
    id: str
    provider: str
    key_env: str
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    cache_per_mtok: Decimal


MODELS = MappingProxyType({
    "muse-spark-1.3": ModelSpec("muse-spark-1.3", "meta", "MODEL_API_KEY", Decimal("1.25"), Decimal("4.25"), Decimal("0.15")),
    "gpt-6.1-sol": ModelSpec("gpt-6.1-sol", "openai", "OPENAI_API_KEY", Decimal("2"), Decimal("10"), Decimal("0.10")),
    "gemini-4-argon": ModelSpec("gemini-4-argon", "google", "GEMINI_API_KEY", Decimal("2"), Decimal("10"), Decimal("0.10")),
    "claude-opus-5-5": ModelSpec("claude-opus-5-5", "anthropic", "ANTHROPIC_API_KEY", Decimal("4"), Decimal("20"), Decimal("0.20")),
})
# October 31, 2026 standard rates. Gemini's promotional rates expire Nov 30.
PRICE_TABLE_VERSION = "first-party-standard-2026-10-31"
_ENDPOINTS = MappingProxyType({
    "openai": "https://api.openai.com/v1/responses",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "google": "https://generativelanguage.googleapis.com/v1beta/models/gemini-4-argon:generateContent",
})


def model_spec(model: str) -> ModelSpec:
    try:
        return MODELS[model]
    except (KeyError, TypeError):
        from evoforge.broker_meta import ProviderNotAccepted
        raise ProviderNotAccepted("unsupported platform model") from None


def is_platform_model(model: str) -> bool:
    return isinstance(model, str) and model in MODELS


def has_key(model: str) -> bool:
    spec = model_spec(model)
    return bool(os.getenv(spec.key_env, "").strip())


def public_models() -> list[dict]:
    """Capability inventory only; credentials and endpoints are not public."""
    return [{"model": spec.id, "provider": spec.provider,
             "configured": has_key(spec.id)} for spec in MODELS.values()]


def _integer(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid provider token count")
    return value


def canonical_usage(provider: str, raw: Any) -> dict | None:
    """Normalize complete provider usage without counting thinking twice.

    Canonical prompt includes cache reads/writes. Canonical completion already
    includes reasoning. Missing/invalid usage remains unknown, never free.
    """
    if not isinstance(raw, dict) or not raw:
        return None
    try:
        writes_5m = writes_1h = 0
        if provider == "openai":
            prompt = _integer(raw["input_tokens"])
            completion = _integer(raw["output_tokens"])
            cached = _integer((raw.get("input_tokens_details") or {}).get("cached_tokens", 0))
            reasoning = _integer((raw.get("output_tokens_details") or {}).get("reasoning_tokens", 0))
        elif provider == "google":
            prompt = _integer(raw["promptTokenCount"])
            if "candidatesTokenCount" not in raw and "thoughtsTokenCount" not in raw:
                return None
            reasoning = _integer(raw.get("thoughtsTokenCount", 0))
            completion = _integer(raw.get("candidatesTokenCount", 0)) + reasoning
            cached = _integer(raw.get("cachedContentTokenCount", 0))
        elif provider == "anthropic":
            ordinary = _integer(raw["input_tokens"])
            completion = _integer(raw["output_tokens"])
            cached = _integer(raw.get("cache_read_input_tokens", 0))
            write_total = _integer(raw.get("cache_creation_input_tokens", 0))
            details = raw.get("cache_creation") or {}
            writes_1h = _integer(details.get("ephemeral_1h_input_tokens", 0))
            writes_5m = _integer(details.get("ephemeral_5m_input_tokens", write_total - writes_1h))
            if writes_5m + writes_1h != write_total:
                return None
            prompt = ordinary + cached + write_total
            reasoning = _integer((raw.get("output_tokens_details") or {}).get("thinking_tokens", 0))
        elif provider == "meta":
            prompt = _integer(raw["prompt_tokens"])
            completion = _integer(raw["completion_tokens"])
            cached = _integer((raw.get("prompt_tokens_details") or {}).get("cached_tokens", raw.get("cached_tokens", 0)))
            reasoning = _integer((raw.get("completion_tokens_details") or {}).get("reasoning_tokens", 0))
        else:
            return None
        if cached + writes_5m + writes_1h > prompt or reasoning > completion:
            return None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return {"prompt_tokens": prompt, "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "prompt_tokens_details": {"cached_tokens": cached},
            "completion_tokens_details": {"reasoning_tokens": reasoning},
            "completion_includes_reasoning": True,
            "cache_creation_5m_tokens": writes_5m,
            "cache_creation_1h_tokens": writes_1h}


def model_cost_cents(usage: Any, model: str) -> int | None:
    """Price canonical usage once, rounded UP to integer cents per call."""
    spec = model_spec(model)
    if not isinstance(usage, dict) or not usage:
        return None
    try:
        prompt = _integer(usage["prompt_tokens"])
        completion = _integer(usage["completion_tokens"])
        cached = _integer((usage.get("prompt_tokens_details") or {}).get("cached_tokens", usage.get("cached_tokens", 0)))
        writes_5m = _integer(usage.get("cache_creation_5m_tokens", 0))
        writes_1h = _integer(usage.get("cache_creation_1h_tokens", 0))
        ordinary = prompt - cached - writes_5m - writes_1h
        if ordinary < 0:
            return None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    cents = (ordinary * spec.input_per_mtok + cached * spec.cache_per_mtok
             + writes_5m * spec.input_per_mtok * Decimal("1.25")
             + writes_1h * spec.input_per_mtok * Decimal("2")
             + completion * spec.output_per_mtok) / Decimal("10000")
    return int(cents.to_integral_value(rounding=ROUND_CEILING))


def normalize_json_content(text: str) -> str:
    """Remove one valid JSON fence only; never repair generated code/JSON."""
    if not isinstance(text, str):
        return ""
    try:
        if isinstance(json.loads(text), dict):
            return text
    except (ValueError, TypeError):
        pass
    fences = re.findall(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", text, re.DOTALL)
    if len(fences) != 1 or text.count("```") != 2:
        return text
    try:
        if isinstance(json.loads(fences[0]), dict):
            return fences[0]
    except (ValueError, TypeError):
        pass
    return text


def _model_matches(requested: str, actual: Any) -> bool:
    if not isinstance(actual, str):
        return False
    if actual == requested:
        return True
    # Providers may resolve a stable alias to a dated or numbered snapshot.
    # Do not accidentally accept another capability variant such as "-lite".
    return re.fullmatch(re.escape(requested) + r"-(?:\d{4}-\d{2}-\d{2}|\d{8}|\d{3})", actual) is not None


class _Usage:
    def __init__(self, data: dict):
        self._data = dict(data)

    def model_dump(self, **_kwargs) -> dict:
        return dict(self._data)


class CompatibleResponse:
    """Small OpenAI ChatCompletion-shaped adapter for existing broker code."""
    def __init__(self, *, model: str, requested_model: str, provider: str,
                 text: str, finish_reason: str, usage: dict | None,
                 response_id: str | None, request_id: str | None):
        self.model = model
        self.requested_model = requested_model
        self.provider = provider
        self.id = response_id
        self._request_id = request_id
        self.created = int(time.time())
        self.usage = _Usage(usage) if usage is not None else None
        self.choices = [SimpleNamespace(index=0, finish_reason=finish_reason,
                                       message=SimpleNamespace(role="assistant", content=text))]

    def model_dump(self, **_kwargs) -> dict:
        return {"id": self.id, "object": "chat.completion", "created": self.created,
                "model": self.model,
                "choices": [{"index": 0, "finish_reason": self.choices[0].finish_reason,
                             "message": {"role": "assistant", "content": self.choices[0].message.content}}],
                "usage": self.usage.model_dump() if self.usage is not None else None}


def response_metadata(response: Any, model: str, phase: str) -> dict:
    spec = model_spec(model)
    usage = getattr(response, "usage", None)
    canonical = usage.model_dump() if usage is not None else None
    # Meta comes from the official compatible SDK; native adapters are already normalized.
    if spec.provider == "meta" and canonical is not None:
        canonical = canonical_usage("meta", canonical)
    actual = getattr(response, "model", None)
    choices = getattr(response, "choices", None)
    finish_reason = getattr(choices[0], "finish_reason", None) if choices else None
    return {"provider": spec.provider, "model": model, "requested_model": model,
            "response_model": actual,
            "response_model_matches": _model_matches(model, actual),
            "phase": phase,
            "finish_reason": finish_reason,
            "provider_request_id": getattr(response, "_request_id", None),
            "provider_response_id": getattr(response, "id", None),
            "usage": canonical or {}, "billing_verified": False,
            "price_table_version": PRICE_TABLE_VERSION}


def _response_parts(provider: str, data: dict) -> tuple[str, str, str | None, str | None, dict | None]:
    if provider == "openai":
        text = "".join(part.get("text", "") for output in data.get("output", [])
                       if output.get("type") == "message"
                       for part in output.get("content", []) if part.get("type") == "output_text")
        status = data.get("status")
        reason = (data.get("incomplete_details") or {}).get("reason")
        finish = "length" if reason == "max_output_tokens" else "content_filter" if reason == "content_filter" else "stop"
        if status not in ("completed", "incomplete"):
            raise ValueError("provider response not completed")
        if status == "incomplete" and finish == "stop":
            finish = "length"  # incomplete output must never look complete to existing guards
        return text, finish, data.get("model"), data.get("id"), canonical_usage(provider, data.get("usage"))
    if provider == "anthropic":
        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
        stop = data.get("stop_reason")
        finish = "length" if stop == "max_tokens" else "content_filter" if stop == "refusal" else "stop"
        return text, finish, data.get("model"), data.get("id"), canonical_usage(provider, data.get("usage"))
    candidates = data.get("candidates") or [{}]
    candidate = candidates[0]
    text = "".join(part.get("text", "") for part in (candidate.get("content") or {}).get("parts", []) if not part.get("thought"))
    stop = candidate.get("finishReason")
    finish = "length" if stop == "MAX_TOKENS" else "content_filter" if stop in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII") else "stop"
    return text, finish, data.get("modelVersion"), data.get("responseId"), canonical_usage(provider, data.get("usageMetadata"))


class NativeClient:
    def __init__(self, model: str):
        self._spec = model_spec(model)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, *, model: str, messages: list[dict], max_tokens: int = 8000,
               response_format: dict | None = None, **kwargs) -> CompatibleResponse:
        from evoforge.broker_meta import ProviderNotAccepted, ProviderOutcomeUnknown
        spec = self._spec
        if model != spec.id:
            raise ProviderNotAccepted("platform client model mismatch")
        key = os.getenv(spec.key_env, "").strip()
        if not key:
            raise ProviderNotAccepted("platform provider key not configured")
        if not key.isascii() or "\r" in key or "\n" in key:
            raise ProviderNotAccepted("platform provider key format invalid")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 128000:
            raise ProviderNotAccepted("invalid output token budget")
        if not isinstance(messages, list) or any(not isinstance(m, dict) or m.get("role") not in ("system", "user", "assistant") or not isinstance(m.get("content"), str) for m in messages):
            raise ProviderNotAccepted("invalid platform messages")
        # Explicit tools, URL overrides, tiers, and hidden auto-retries are not supported.
        if kwargs.keys() - {"temperature", "reasoning_effort"}:
            raise ProviderNotAccepted("unsupported platform request options")
        requested_effort = kwargs.get("reasoning_effort", "medium")
        if requested_effort != "medium":
            raise ProviderNotAccepted("platform profile requires medium effort")
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        conversation = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
        json_output = (response_format or {}).get("type") == "json_object"
        if json_output:
            system += "\nReturn exactly one valid JSON object. Do not add commentary or Markdown."
        provider = spec.provider
        if provider == "openai":
            headers = {"Authorization": "Bearer " + key}
            body = {"model": model, "input": ([{"role": "system", "content": system}] if system else []) + conversation,
                    "max_output_tokens": max_tokens, "reasoning": {"effort": "medium"}, "store": False,
                    "service_tier": "default"}
            if json_output:
                body["text"] = {"format": {"type": "json_object"}}
        elif provider == "anthropic":
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
            body = {"model": model, "max_tokens": max_tokens, "system": system,
                    "messages": conversation, "output_config": {"effort": "medium"}, "service_tier": "standard_only"}
        else:
            headers = {"x-goog-api-key": key}
            generation = {"maxOutputTokens": max_tokens, "thinkingConfig": {"thinkingLevel": "MEDIUM"}}
            if json_output:
                generation["responseMimeType"] = "application/json"
            body = {"systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in conversation],
                    "generationConfig": generation}
        try:
            # A single first-party request. All credentials are headers, not URLs.
            with httpx.Client(timeout=240.0, follow_redirects=False) as client:
                response = client.post(_ENDPOINTS[provider], headers=headers, json=body)
        except httpx.HTTPError:
            raise ProviderOutcomeUnknown("platform provider transport outcome unknown") from None
        if 400 <= response.status_code < 500 and response.status_code not in (408, 409):
            raise ProviderNotAccepted(f"platform provider HTTP {response.status_code}")
        if not 200 <= response.status_code < 300:
            raise ProviderOutcomeUnknown(f"platform provider HTTP {response.status_code}")
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("invalid provider response")
            text, finish, actual_model, response_id, usage = _response_parts(provider, data)
            if not isinstance(text, str):
                raise ValueError("invalid provider text")
            if actual_model is not None and not _model_matches(model, actual_model):
                raise ValueError("unexpected provider model")
        except (ValueError, KeyError, TypeError, AttributeError, IndexError):
            raise ProviderOutcomeUnknown("platform provider response unusable") from None
        if finish != "length" and json_output:
            text = normalize_json_content(text)
        return CompatibleResponse(model=actual_model, requested_model=model, provider=provider,
            text=text, finish_reason=finish, usage=usage, response_id=response_id,
            request_id=response.headers.get("x-request-id") or response.headers.get("request-id"))


def client_for(model: str):
    spec = model_spec(model)
    if not has_key(model):
        from evoforge.broker_meta import ProviderNotAccepted
        raise ProviderNotAccepted("platform provider key not configured")
    if spec.provider == "meta":
        from openai import OpenAI
        # Meta keeps its existing official-SDK transport and account endpoint.
        return OpenAI(base_url=os.getenv("MODEL_API_BASE", "https://api.meta.ai/v1"),
                      api_key=os.environ[spec.key_env], max_retries=0, timeout=240.0)
    return NativeClient(model)
