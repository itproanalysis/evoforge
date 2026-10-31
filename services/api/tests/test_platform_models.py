"""Native adapter contracts: mocked HTTP only; never uses a real key."""
import json
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evoforge import platform_models as models
from evoforge.broker_meta import ProviderNotAccepted, ProviderOutcomeUnknown


TARGETS = ["gpt-6.1-sol", "gemini-4-argon", "claude-opus-5-5"]
MESSAGES = [{"role": "system", "content": "Output JSON only."},
            {"role": "user", "content": "Plan the requested patch."}]
TEST_KEY = "unit-test-secret-must-never-appear"


def provider_response(model, text='{"plan":"done"}', truncated=False):
    provider = models.model_spec(model).provider
    if provider == "openai":
        return {"id": "resp_test", "model": model,
                "status": "incomplete" if truncated else "completed",
                "incomplete_details": {"reason": "max_output_tokens"} if truncated else None,
                "output": [{"type": "reasoning", "summary": [{"text": "private thought"}]},
                           {"type": "message", "content": [{"type": "output_text", "text": text}]}],
                "usage": {"input_tokens": 100, "output_tokens": 200,
                          "output_tokens_details": {"reasoning_tokens": 150}}}
    if provider == "google":
        return {"responseId": "google_test", "modelVersion": model,
                "candidates": [{"finishReason": "MAX_TOKENS" if truncated else "STOP",
                                "content": {"parts": [{"text": "private thought", "thought": True}, {"text": text}]}}],
                "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 50, "thoughtsTokenCount": 150}}
    return {"id": "msg_test", "model": model,
            "stop_reason": "max_tokens" if truncated else "end_turn",
            "content": [{"type": "thinking", "thinking": "private thought"}, {"type": "text", "text": text}],
            "usage": {"input_tokens": 100, "output_tokens": 200,
                      "output_tokens_details": {"thinking_tokens": 150}}}


def install_http(monkeypatch, model, *, data=None, status=200, error=None):
    monkeypatch.setenv(models.model_spec(model).key_env, TEST_KEY)
    original = httpx.Client
    calls = []
    clients = []
    def handle(request):
        calls.append(request)
        if error:
            raise error
        return httpx.Response(status, json=data if data is not None else provider_response(model),
                              headers={"x-request-id": "req_test"})
    def client(**kwargs):
        clients.append(kwargs)
        return original(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(models.httpx, "Client", client)
    return calls, clients


@pytest.mark.parametrize("model", TARGETS)
def test_native_payload_response_usage_and_no_cross_provider_key(monkeypatch, model):
    calls, clients = install_http(monkeypatch, model)
    response = models.client_for(model).chat.completions.create(
        model=model, messages=MESSAGES, max_tokens=32000, response_format={"type": "json_object"})
    assert len(calls) == 1
    body = json.loads(calls[0].content)
    provider = models.model_spec(model).provider
    assert TEST_KEY not in str(calls[0].url)
    assert clients == [{"timeout": 240.0, "follow_redirects": False}]
    assert response.choices[0].message.content == '{"plan":"done"}'
    assert response.choices[0].finish_reason == "stop"
    assert response.usage.model_dump()["completion_tokens"] == 200
    assert response.usage.model_dump()["completion_tokens_details"]["reasoning_tokens"] == 150
    assert "private thought" not in json.dumps(response.model_dump(mode="json"))
    assert TEST_KEY not in json.dumps(response.model_dump(mode="json"))
    metadata = models.response_metadata(response, model, "critic_spec")
    assert metadata["model"] == metadata["requested_model"] == metadata["response_model"] == model
    assert metadata["response_model_matches"] is True
    assert metadata["provider_request_id"] == "req_test"
    assert metadata["billing_verified"] is False
    if provider == "openai":
        assert str(calls[0].url) == "https://api.openai.com/v1/responses"
        assert calls[0].headers["authorization"] == "Bearer " + TEST_KEY
        assert body["max_output_tokens"] == 32000 and body["reasoning"] == {"effort": "medium"}
        assert body["text"] == {"format": {"type": "json_object"}}
        assert body["store"] is False and body["service_tier"] == "default"
        assert "x-api-key" not in calls[0].headers and "x-goog-api-key" not in calls[0].headers
    elif provider == "anthropic":
        assert str(calls[0].url) == "https://api.anthropic.com/v1/messages"
        assert calls[0].headers["x-api-key"] == TEST_KEY
        assert body["max_tokens"] == 32000 and body["output_config"] == {"effort": "medium"}
        assert body["service_tier"] == "standard_only"
        assert "thinking" not in body and "authorization" not in calls[0].headers
        assert body["messages"] == [MESSAGES[1]]
    else:
        assert str(calls[0].url) == "https://generativelanguage.googleapis.com/v1beta/models/gemini-4-argon:generateContent"
        assert calls[0].headers["x-goog-api-key"] == TEST_KEY
        assert body["generationConfig"] == {"maxOutputTokens": 32000, "thinkingConfig": {"thinkingLevel": "MEDIUM"}, "responseMimeType": "application/json"}
        assert "authorization" not in calls[0].headers and "x-api-key" not in calls[0].headers


@pytest.mark.parametrize("model", TARGETS)
def test_truncation_is_never_normalized_into_a_complete_response(monkeypatch, model):
    text='preface\n```json\n{"plan":"done"}\n```'
    install_http(monkeypatch, model, data=provider_response(model, text, truncated=True))
    response=models.client_for(model).chat.completions.create(model=model,messages=MESSAGES,max_tokens=2048,response_format={"type":"json_object"})
    assert response.choices[0].finish_reason == "length"
    assert response.choices[0].message.content == text


@pytest.mark.parametrize("model", TARGETS)
def test_uniform_format_only_extraction_does_not_edit_generated_code(monkeypatch, model):
    obj={"diff":"--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n"}
    text='Explanation.\n```json\n'+json.dumps(obj)+'\n```'
    install_http(monkeypatch,model,data=provider_response(model,text))
    response=models.client_for(model).chat.completions.create(model=model,messages=MESSAGES,response_format={"type":"json_object"})
    assert json.loads(response.choices[0].message.content)==obj


@pytest.mark.parametrize("text", ['Explanation {"diff":"x"}', '```json\n{broken}\n```',
    '```json\n{"diff":"a"}\n```\n```json\n{"diff":"b"}\n```'])
def test_no_arbitrary_json_repair_or_best_of_multiple_fences(text):
    assert models.normalize_json_content(text)==text


@pytest.mark.parametrize("status", [400,401,403,404,422,429])
def test_rejections_have_safe_errors_and_exactly_one_request(monkeypatch,status):
    calls,_=install_http(monkeypatch,TARGETS[0],status=status,data={"error":{"message":TEST_KEY}})
    with pytest.raises(ProviderNotAccepted) as exc:
        models.client_for(TARGETS[0]).chat.completions.create(model=TARGETS[0],messages=MESSAGES)
    assert TEST_KEY not in str(exc.value) and str(status) in str(exc.value)
    assert len(calls)==1


@pytest.mark.parametrize("status", [302,408,409,500,502,503])
def test_uncertain_acceptance_stays_unknown_no_retry_or_redirect(monkeypatch,status):
    calls,_=install_http(monkeypatch,TARGETS[0],status=status,data={"error":{"message":TEST_KEY}})
    with pytest.raises(ProviderOutcomeUnknown) as exc:
        models.client_for(TARGETS[0]).chat.completions.create(model=TARGETS[0],messages=MESSAGES)
    assert TEST_KEY not in str(exc.value)
    assert len(calls)==1


def test_timeout_does_not_expose_request_details_or_refund(monkeypatch):
    calls,_=install_http(monkeypatch,TARGETS[0],error=httpx.ReadTimeout(TEST_KEY))
    with pytest.raises(ProviderOutcomeUnknown) as exc:
        models.client_for(TARGETS[0]).chat.completions.create(model=TARGETS[0],messages=MESSAGES)
    assert TEST_KEY not in str(exc.value) and len(calls)==1


def test_no_key_or_unknown_model_refuses_before_http(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY",raising=False)
    monkeypatch.setattr(models.httpx,"Client",lambda **kwargs: pytest.fail("must not dispatch"))
    with pytest.raises(ProviderNotAccepted):models.client_for("gpt-6.1-sol")
    with pytest.raises(ProviderNotAccepted):models.client_for("gpt-4o")


@pytest.mark.parametrize('bad_key', ['secret\nheader', 'secret\rheader', 'secret-non-ascii-\u00e9'])
def test_illegal_auth_headers_refuse_without_revealing_key(monkeypatch,bad_key):
    monkeypatch.setenv('OPENAI_API_KEY',bad_key)
    monkeypatch.setattr(models.httpx,'Client',lambda **kwargs: pytest.fail('must not dispatch'))
    with pytest.raises(ProviderNotAccepted) as exc:
        models.client_for(TARGETS[0]).chat.completions.create(model=TARGETS[0],messages=MESSAGES)
    assert bad_key not in str(exc.value)


@pytest.mark.parametrize("kwargs", [{"model":"gemini-4-argon"},{"max_tokens":True},
    {"max_tokens":0},{"max_tokens":128001},{"tools":[{}]},{"reasoning_effort":"max"},
    {"base_url":"https://untrusted.invalid"}])
def test_invalid_options_never_dispatch(monkeypatch,kwargs):
    monkeypatch.setenv("OPENAI_API_KEY",TEST_KEY)
    monkeypatch.setattr(models.httpx,"Client",lambda **kwargs: pytest.fail("must not dispatch"))
    request=dict(model="gpt-6.1-sol",messages=MESSAGES)
    request.update(kwargs)
    with pytest.raises(ProviderNotAccepted):models.client_for("gpt-6.1-sol").chat.completions.create(**request)


def test_response_model_mismatch_is_unknown_not_silent_fallback(monkeypatch):
    data=provider_response(TARGETS[0]);data["model"]="gpt-4o"
    install_http(monkeypatch,TARGETS[0],data=data)
    with pytest.raises(ProviderOutcomeUnknown):
        models.client_for(TARGETS[0]).chat.completions.create(model=TARGETS[0],messages=MESSAGES)


@pytest.mark.parametrize("suffix", ["-2026-10-31", "-20261031", "-001"])
def test_provider_snapshots_are_preserved(monkeypatch, suffix):
    data=provider_response(TARGETS[1]);data['modelVersion']=TARGETS[1]+suffix
    install_http(monkeypatch,TARGETS[1],data=data)
    response=models.client_for(TARGETS[1]).chat.completions.create(model=TARGETS[1],messages=MESSAGES)
    assert response.model==TARGETS[1]+suffix
    assert models.response_metadata(response,TARGETS[1],'peer')['response_model_matches'] is True


def test_capability_variant_suffix_is_not_a_snapshot(monkeypatch):
    data=provider_response(TARGETS[1]);data['modelVersion']=TARGETS[1]+'-lite'
    install_http(monkeypatch,TARGETS[1],data=data)
    with pytest.raises(ProviderOutcomeUnknown):
        models.client_for(TARGETS[1]).chat.completions.create(model=TARGETS[1],messages=MESSAGES)


def test_invalid_usage_does_not_claim_zero_cost(monkeypatch):
    data=provider_response(TARGETS[0]);data["usage"]={"input_tokens":True,"output_tokens":1}
    install_http(monkeypatch,TARGETS[0],data=data)
    response=models.client_for(TARGETS[0]).chat.completions.create(model=TARGETS[0],messages=MESSAGES)
    assert response.usage is None
    assert models.model_cost_cents(None,TARGETS[0]) is None


def test_reasoning_not_double_priced_and_google_thoughts_added_once():
    gpt=models.canonical_usage("openai",{"input_tokens":1000,"output_tokens":10000,"output_tokens_details":{"reasoning_tokens":9000}})
    gemini=models.canonical_usage("google",{"promptTokenCount":1000,"candidatesTokenCount":1000,"thoughtsTokenCount":9000})
    assert models.model_cost_cents(gpt,"gpt-6.1-sol")==11
    assert models.model_cost_cents(gemini,"gemini-4-argon")==11


def test_anthropic_cached_tokens_not_omitted_or_double_charged():
    usage=models.canonical_usage("anthropic",{"input_tokens":100000,"cache_read_input_tokens":1000000,"output_tokens":100000})
    assert usage["prompt_tokens"]==1100000
    assert models.model_cost_cents(usage,"claude-opus-5-5")==260


def test_anthropic_cache_write_ttls_have_their_own_rates():
    usage=models.canonical_usage("anthropic",{"input_tokens":0,"output_tokens":0,
        "cache_creation_input_tokens":2000000,
        "cache_creation":{"ephemeral_5m_input_tokens":1000000,"ephemeral_1h_input_tokens":1000000}})
    assert models.model_cost_cents(usage,"claude-opus-5-5")==1300


def test_anthropic_cache_write_partial_ttl_details():
    usage=models.canonical_usage('anthropic',{'input_tokens':0,'output_tokens':0,
        'cache_creation_input_tokens':1000000,'cache_creation':{'ephemeral_1h_input_tokens':1000000}})
    assert models.model_cost_cents(usage,'claude-opus-5-5')==800


@pytest.mark.parametrize("provider,raw", [("openai",{}),("google",{"promptTokenCount":1}),
    ("anthropic",{"input_tokens":0,"output_tokens":-1}),
    ("meta",{"prompt_tokens":1,"completion_tokens":1,"prompt_tokens_details":{"cached_tokens":2}}),
    ("openai",{"input_tokens":1,"output_tokens":2,"output_tokens_details":{"reasoning_tokens":3}})])
def test_incomplete_or_impossible_usage_stays_unknown(provider,raw):
    assert models.canonical_usage(provider,raw) is None


def test_registry_is_immutable_and_inventory_has_no_secrets(monkeypatch):
    for spec in models.MODELS.values():monkeypatch.setenv(spec.key_env,TEST_KEY)
    public=models.public_models()
    assert {m["model"] for m in public}==set(models.MODELS)
    assert all(set(m)=={"model","provider","configured"} and m["configured"] for m in public)
    assert TEST_KEY not in json.dumps(public)
    with pytest.raises(TypeError):models.MODELS["fallback"]="bad"
