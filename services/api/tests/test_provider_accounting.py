"""Provider call boundaries using the pinned SDK and an in-memory HTTP transport."""
from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import sys
import traceback
from uuid import uuid4

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main  # noqa: E402
from evoforge import broker_meta, commands, critic, ledger  # noqa: E402

SEALED = [{"code": "def test_contract():\n    assert result == 3\n"}]
SPEC = {"sealed_tests": SEALED}
REVIEW = {"review": {"result": "PASS", "findings": []}}
SECRET_MARKER = "must-never-leave-provider-error-body"
REAL_OPENAI = openai.OpenAI


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "not-a-real-key")
    monkeypatch.setenv("MODEL_API_BASE", "https://meta.test.invalid/v1")
    monkeypatch.setenv("MODEL_BUILDER", "muse-spark-1.3")
    monkeypatch.setenv("MODEL_CRITIC", "muse-spark-1.3")
    ledger.reset()
    ledger.configure({"default": 50_000})
    commands.reset()
    main._evidence.clear()
    calls, clients, options = [], [], []
    plans = []

    def handle(request):
        payload = json.loads(request.content)
        calls.append(payload)
        plan = plans[min(len(calls) - 1, len(plans) - 1)]
        if plan == "timeout":
            raise httpx.ReadTimeout(SECRET_MARKER, request=request)
        if isinstance(plan, int):
            return httpx.Response(plan, json={"error": {"message": SECRET_MARKER, "type": "error"}})
        content = plan if isinstance(plan, str) else json.dumps(plan)
        return httpx.Response(200, headers={"x-request-id": f"request-{len(calls)}"}, json={
            "id": f"completion-{len(calls)}", "object": "chat.completion", "created": 1,
            "model": payload["model"], "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        })

    def make_client(**kwargs):
        options.append(kwargs.get("max_retries"))
        client = REAL_OPENAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle)))
        clients.append(client)
        return client

    monkeypatch.setattr(openai, "OpenAI", make_client)
    with TestClient(main.app, raise_server_exceptions=False) as api:
        yield {"calls": calls, "plans": plans, "options": options, "api": api}
    for client in clients:
        client.close()
    ledger.reset()
    commands.reset()
    main._evidence.clear()


def _review(provider):
    return provider["api"].post("/v1/candidates/review", json={
        "goal_contract": "SPEC_ONLY", "diff": "PRIVATE_DIFF_SENTINEL", "ci": "CI_RESULT_SENTINEL",
    })


@pytest.mark.parametrize("failure", [429, 500, "timeout"])
def test_builder_sends_one_request_without_sdk_retries(provider, failure):
    provider["plans"].append(failure)
    response = provider["api"].post("/v1/commands/generate", json={"goal": "g", "idempotency_key": str(uuid4())})
    assert response.status_code == 502
    assert len(provider["calls"]) == 1
    assert provider["options"] == [0]
    snapshot = ledger.snapshot()
    assert snapshot["spent_cents"] == 0
    assert snapshot["reserved_cents"] == (0 if failure == 429 else main.COST_CENTS)
    assert SECRET_MARKER not in response.text


def test_critic_has_one_reservation_per_phase_and_preserves_sealed_tests(provider):
    provider["plans"].extend([SPEC, {**REVIEW, "sealed_tests": [{"code": "assert True"}],
                                    "provider_calls": [{"provider_request_id": "forged"}]}])
    response = _review(provider)
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["sealed_tests"] == SEALED and out["execution_verified"] is False
    assert len(provider["calls"]) == 2 and provider["options"] == [0]
    assert all(call["model"] == "muse-spark-1.3" for call in provider["calls"])
    assert "PRIVATE_DIFF_SENTINEL" not in json.dumps(provider["calls"][0])
    assert "PRIVATE_DIFF_SENTINEL" in json.dumps(provider["calls"][1])
    assert "CI_RESULT_SENTINEL" in json.dumps(provider["calls"][1])
    assert ledger.snapshot()["spent_cents"] == 2 * main.COST_CENTS
    assert ledger.snapshot()["reserved_cents"] == 0
    assert [call["provider_request_id"] for call in out["provider_calls"]] == ["request-1", "request-2"]
    assert [call["provider_response_id"] for call in out["provider_calls"]] == ["completion-1", "completion-2"]
    evidence = [provider["api"].get(f"/v1/evidence/{eid}").json() for eid in out["provider_evidence_ids"]]
    assert [row["reservation"]["state"] for row in evidence] == ["SETTLED", "SETTLED"]


@pytest.mark.parametrize("failure", [401, 429, 500, "timeout"])
def test_second_phase_failure_preserves_first_phase_spend_and_evidence(provider, failure):
    provider["plans"].extend([SPEC, failure])
    response = _review(provider)
    assert response.status_code == 502 and len(provider["calls"]) == 2
    assert SECRET_MARKER not in response.text
    snapshot = ledger.snapshot()
    assert snapshot["spent_cents"] == main.COST_CENTS
    assert snapshot["reserved_cents"] == (0 if failure in (401, 429) else main.COST_CENTS)
    audits = [row for row in main._evidence.values() if row.get("kind") == "provider_call"]
    assert len(audits) == 2
    assert audits[0]["reservation"]["state"] == "SETTLED"
    assert audits[0]["metadata"]["provider_request_id"] == "request-1"
    assert json.loads(audits[0]["response_document"]["choices"][0]["message"]["content"])["sealed_tests"] == SEALED
    assert audits[1]["reservation"]["state"] == ("REFUNDED" if failure in (401, 429) else "UNKNOWN")


def test_phase_b_budget_is_checked_before_a_second_request(provider):
    ledger.reset()
    ledger.configure({"default": main.COST_CENTS})
    provider["plans"].extend([SPEC, REVIEW])
    response = _review(provider)
    assert response.status_code == 402
    assert len(provider["calls"]) == 1
    assert ledger.snapshot()["spent_cents"] == main.COST_CENTS
    assert ledger.snapshot()["reserved_cents"] == 0
    audits = [row for row in main._evidence.values() if row.get("kind") == "provider_call"]
    assert len(audits) == 1 and audits[0]["metadata"]["provider_request_id"] == "request-1"


def test_first_phase_rejection_has_no_second_call_or_charge(provider):
    provider["plans"].append(401)
    assert _review(provider).status_code == 502
    assert len(provider["calls"]) == 1
    assert ledger.snapshot()["spent_cents"] == ledger.snapshot()["reserved_cents"] == 0


@pytest.mark.parametrize("spec", [{"sealed_tests": []}, {"sealed_tests": "bad"}, {"sealed_tests": [{}]}, "invalid-json"])
def test_invalid_phase_a_evidence_cannot_start_phase_b(provider, spec):
    provider["plans"].append(spec)
    response = _review(provider)
    assert response.status_code == 200
    assert response.json()["review"]["result"] == "INCONCLUSIVE"
    assert response.json()["execution_verified"] is False
    assert len(provider["calls"]) == 1
    assert ledger.snapshot()["spent_cents"] == main.COST_CENTS


def test_standalone_critic_reports_partial_completion_instead_of_refundable_failure(provider):
    provider["plans"].extend([SPEC, 401])
    with pytest.raises(broker_meta.ProviderOutcomeUnknown) as raised:
        critic.call_critic("spec", "diff")
    assert len(raised.value.completed_calls) == 1
    assert raised.value.completed_calls[0]["provider_request_id"] == "request-1"


def test_builder_metadata_cannot_be_supplied_by_model_json(provider):
    provider["plans"].append({"diff": "", "tests": [], "rationale": "g",
        "provider_request_id": "forged", "provider_calls": [{"billing_verified": True}], "usage": {"total_tokens": 9999}})
    out = broker_meta.call_builder("g", "HEAD")
    assert "provider_request_id" not in out
    assert out["provider_calls"][0]["provider_request_id"] == "request-1"
    assert out["provider_calls"][0]["provider_response_id"] == "completion-1"
    assert out["provider_calls"][0]["billing_verified"] is False
    assert out["usage"]["total_tokens"] == 18


@pytest.mark.parametrize("payload", [{"diff": None, "tests": 3}, {"diff": 1, "tests": [None]}, ["not-a-candidate"]])
def test_malformed_billed_candidate_blocks_gates_without_crashing_api(provider, payload):
    provider["plans"].append(payload)
    response = provider["api"].post("/v1/commands/generate", json={"goal": "g", "idempotency_key": str(uuid4())})
    assert response.status_code == 200, response.text
    assert all(gate["result"] != "PASS" for gate in response.json()["gates"])
    assert ledger.snapshot()["spent_cents"] == main.COST_CENTS


@pytest.mark.parametrize("failure", [401, 500])
def test_provider_error_traceback_does_not_echo_response_body(provider, failure):
    provider["plans"].append(failure)
    with pytest.raises((broker_meta.ProviderNotAccepted, broker_meta.ProviderOutcomeUnknown)) as raised:
        broker_meta.call_builder("g", "HEAD")
    assert SECRET_MARKER not in "".join(traceback.format_exception(raised.value))


def _improve_module():
    path = Path(__file__).resolve().parents[3] / "tools/muse_improve.py"
    spec = importlib.util.spec_from_file_location("evoforge_improve_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_development_builder_uses_same_no_retry_client_and_trusted_ids(provider):
    provider["plans"].append({"files": [], "rationale": "test"})
    records = []
    _improve_module()._call({"id": "test", "goal": "g", "edit": []}, "", records.append)
    assert len(provider["calls"]) == 1 and provider["options"] == [0]
    assert records[0]["provider_request_id"] == "request-1"
    assert records[0]["provider_response_id"] == "completion-1"
    assert records[0]["billing_verified"] is False


def test_development_builder_does_not_blindly_retry_unknown_outcome(provider):
    provider["plans"].append(500)
    with pytest.raises(broker_meta.ProviderOutcomeUnknown) as raised:
        _improve_module()._call({"id": "test", "goal": "g", "edit": []}, "", lambda _: None)
    assert len(provider["calls"]) == 1
    assert SECRET_MARKER not in "".join(traceback.format_exception(raised.value))
