"""Independent acceptance for server-managed judge collaboration defaults.

No provider calls: native transports are replaced, but the real cost ledger
and the real Arena apply/Runner path are retained where relevant.
"""
from __future__ import annotations

import difflib
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_postgres_judging_profile_requires_remote_runner(monkeypatch):
    from evoforge import collaboration
    with monkeypatch.context() as configured_env:
        configured_env.setenv("EVO_MODEL_PROFILE", "collaborative")
        configured_env.setenv("EVO_STATE_BACKEND", "postgres")
        configured_env.delenv("EVO_RUNNER_URL", raising=False)
        assert collaboration.public_defaults()["ready"] is False
        with pytest.raises(collaboration.ConfigurationError):
            collaboration.require_ready()


def test_cloud_judging_cannot_fall_back_to_local_execution(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "evoforge-api")
    assert collaboration.public_defaults()["ready"] is False


def test_default_meta_key_cannot_route_to_another_endpoint(monkeypatch):
    monkeypatch.setenv("MODEL_API_BASE", "https://unrelated.invalid/v1")
    assert collaboration.public_defaults()["ready"] is False

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge import arena, arena_prompt, broker_meta, ledger, platform_models, sealed_eval
from evoforge import collaboration


KEYS = {
    "MODEL_API_KEY": "test-meta-private-credential-do-not-publish",
    "OPENAI_API_KEY": "test-openai-private-credential-do-not-publish",
    "GEMINI_API_KEY": "test-google-private-credential-do-not-publish",
    "ANTHROPIC_API_KEY": "test-anthropic-private-credential-do-not-publish",
}
PEERS = {"gpt-6.1-sol", "gemini-4-argon"}


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("EVO_STATE_BACKEND", "memory")
    monkeypatch.setenv("EVO_MODEL_PROFILE", "collaborative")
    monkeypatch.setenv("MODEL_BUILDER", "muse-spark-1.3")
    monkeypatch.setenv("MODEL_CRITIC", "claude-opus-5-5")
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.delenv("CRITIC_API_BASE", raising=False)
    monkeypatch.delenv("CRITIC_API_KEY", raising=False)
    for key, value in KEYS.items():
        monkeypatch.setenv(key, value)
    ledger.reset()
    ledger.configure({"default": 5000})
    original_records = collaboration._records
    collaboration.configure({})
    yield
    collaboration.configure(original_records)
    ledger.reset()
    ledger.configure({"default": 50000})


def response(model, text="Use the public contract; verify boundary cases.", usage=True):
    return platform_models.CompatibleResponse(
        model=model, requested_model=model,
        provider=platform_models.MODELS[model].provider,
        text=text, finish_reason="stop",
        usage={"prompt_tokens": 1000, "completion_tokens": 200,
               "completion_includes_reasoning": True} if usage else None,
        response_id=f"response-{model}", request_id=f"request-{model}")


def clients(monkeypatch, calls, fail_model=None, failure=None, missing_usage=False):
    def factory(model):
        def create(**kwargs):
            calls.append({"model": model, **kwargs})
            if model == fail_model:
                raise failure
            return response(model, text=json.dumps({"advice": f"Unverified advice from {model}: add one."}),
                            usage=not missing_usage)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(platform_models, "client_for", factory)


def test_default_profile_lists_actual_models_without_credentials():
    out = collaboration.public_defaults()
    assert out["profile"] == "collaborative"
    assert out["ready"] is True
    assert out["requires_api_key"] is False
    assert out["default_builder"] == "muse-spark-1.3"
    assert out["default_critic"] == "claude-opus-5-5"
    assert {p["model"] for p in out["participants"]} == {
        "muse-spark-1.3", "claude-opus-5-5", *PEERS}
    assert all(p["configured"] for p in out["participants"])
    serialized = json.dumps(out)
    for value in KEYS.values():
        assert value not in serialized
    assert "api.meta.ai" not in serialized
    assert "https://" not in serialized


def test_missing_required_key_is_visible_and_blocks_before_dispatch(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    out = collaboration.public_defaults()
    assert out["ready"] is False
    assert out["blocked_reason"]
    assert next(p for p in out["participants"] if p["model"] == "gemini-4-argon")["configured"] is False
    monkeypatch.setattr(platform_models, "client_for", lambda *a: pytest.fail("must refuse before native dispatch"))
    with pytest.raises(Exception):
        collaboration.prepare_advice("Implement inc", [{"path": "app.py", "content": "pass\n"}])
    assert ledger.snapshot()["spent_cents"] == 0
    assert ledger.snapshot()["reserved_cents"] == 0


def test_both_planners_have_individual_reservations_and_usage_cost(monkeypatch):
    calls = []
    clients(monkeypatch, calls)
    out = collaboration.prepare_advice("Implement inc", [{"path": "app.py", "content": "pass\n"}])
    assert {c["model"] for c in calls} == PEERS
    assert len(calls) == 2
    assert len(set(out["reservation_ids"])) == 2
    assert {c["model"] for c in out["provider_calls"]} == PEERS
    assert out["cost_cents"] == 2
    assert out["usage_missing"] is False
    assert ledger.snapshot()["spent_cents"] == 2
    assert ledger.snapshot()["reserved_cents"] == 0
    assert all(ledger.reservation(r)["state"] == "SETTLED" for r in out["reservation_ids"])
    for call in calls:
        wire = json.dumps(call)
        assert "Implement inc" in wire and "app.py" in wire
        assert "reference_fix" not in wire and "heldout" not in wire
        for value in KEYS.values():
            assert value not in wire


def test_provider_evidence_retains_receipts_without_advice_or_keys(monkeypatch):
    calls = []
    clients(monkeypatch, calls)
    records = {}
    collaboration.configure(records)
    out = collaboration.prepare_advice("Implement inc", [{"path": "app.py", "content": "pass\n"}])
    assert len(records) == 2
    assert set(out["evidence_ids"]) == set(records)
    for doc in records.values():
        assert doc["kind"] == "provider_call"
        assert doc["reservation"]["state"] == "SETTLED"
        assert doc["metadata"]["provider_response_id"]
        assert len(doc["response_sha256"]) == 64
        public = json.dumps(doc)
        assert "Unverified advice" not in public
        for value in KEYS.values():
            assert value not in public


def test_missing_usage_remains_unknown_and_stops_planning(monkeypatch):
    calls = []
    clients(monkeypatch, calls, missing_usage=True)
    with pytest.raises(collaboration.CollaborationFailure) as raised:
        collaboration.prepare_advice("Implement inc", [{"path": "app.py", "content": "pass\n"}])
    assert len(calls) == 1
    assert raised.value.usage_missing is True
    assert ledger.snapshot()["spent_cents"] == 0
    assert ledger.snapshot()["reserved_cents"] == 120
    assert len(ledger.snapshot()["unknown_reservations"]) == 1


def test_bad_advice_is_billed_but_never_triggers_fallback(monkeypatch):
    calls = []
    def factory(model):
        def create(**kwargs):
            calls.append(model)
            return response(model, text='{"advice": ""}')
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(platform_models, "client_for", factory)
    with pytest.raises(collaboration.CollaborationFailure) as raised:
        collaboration.prepare_advice("Implement inc", [{"path": "app.py", "content": "pass\n"}])
    assert calls == ["gpt-6.1-sol"]
    assert raised.value.cost_cents == 1
    assert ledger.snapshot()["spent_cents"] == 1
    assert ledger.snapshot()["reserved_cents"] == 0


def test_critic_second_phase_rejection_does_not_refund_phase_a(monkeypatch):
    sends = []
    def critic(goal, diff, ci, dispatch):
        budget = 32000
        messages = [{"role": "user", "content": goal}]
        def send():
            assert budget == 32000 and messages
            sends.append(len(sends) + 1)
            if len(sends) == 2:
                raise broker_meta.ProviderNotAccepted("phase B rejected")
            return response("claude-opus-5-5", text='{"sealed_tests": []}')
        dispatch(send)
        dispatch(send)
        pytest.fail("required phase B rejection must abort")
    monkeypatch.setattr(broker_meta, "call_critic", critic)
    with pytest.raises(collaboration.CollaborationFailure) as raised:
        collaboration.call_critic_accounted("Implement inc")
    assert sends == [1, 2]
    assert raised.value.cost_cents == 1
    assert ledger.snapshot()["spent_cents"] == 1
    assert ledger.snapshot()["reserved_cents"] == 0
    reservations = raised.value.public_result["reservation_ids"]
    assert [ledger.reservation(r)["state"] for r in reservations] == ["SETTLED", "REFUNDED"]


def test_default_native_critic_routes_both_phases_to_claude(monkeypatch):
    import openai
    calls = []
    suite = [{"kind": kind, "code": f"def test_{kind}():\n    import app\n    assert app.inc(1) == 2\n"}
             for kind in ["compositional", "negative", "boundary"]]
    def factory(model):
        assert model == "claude-opus-5-5"
        def create(**kwargs):
            calls.append(kwargs)
            text = json.dumps({"sealed_tests": suite, "review": {"result": "PASS", "findings": []}})
            return response(model, text=text)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(platform_models, "client_for", factory)
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: pytest.fail("native Critic must not call Meta's compatible client"))
    rid, output, cost, missing = sealed_eval._call_critic_suite("In app.py implement inc(x) as x plus one.")
    assert len(calls) == 2
    assert output["model"] == "claude-opus-5-5"
    assert output["stub"] is False
    assert all(call["model"] == "claude-opus-5-5" for call in calls)
    assert {p["provider"] for p in output["provider_calls"]} == {"anthropic"}
    assert {p["phase"] for p in output["provider_calls"]} == {"critic_spec", "critic_review"}
    assert cost == ledger.snapshot()["spent_cents"] == 2
    assert ledger.reservation(rid)["state"] == "SETTLED"
    assert ledger.snapshot()["reserved_cents"] == 0
    assert missing is False


def test_failed_prompt_judge_preserves_completed_phase_cost(monkeypatch):
    def failed_judge(goal):
        result = collaboration.new_result()
        rid = ledger.reserve(120)
        ledger.settle(rid, 1)
        result["reservation_ids"].append(rid)
        result["cost_cents"] = 1
        raise collaboration.CollaborationFailure(result)
    monkeypatch.setattr(sealed_eval, "_call_critic_suite", failed_judge)
    result = arena_prompt.run_prompt_arena(
        "judge-failure-" + uuid.uuid4().hex, "Build an increment counter", feedback="critic")
    assert result["status"] == "failed"
    assert result["judge_cost_cents"] == ledger.snapshot()["spent_cents"] == 1
    assert ledger.snapshot()["reserved_cents"] == 0


def test_evidence_store_failure_keeps_billed_cost_in_failure_result(monkeypatch):
    class Unavailable(dict):
        def __setitem__(self, key, value):
            raise RuntimeError("test evidence store unavailable")
    collaboration.configure(Unavailable())
    calls = []
    clients(monkeypatch, calls)
    with pytest.raises(collaboration.CollaborationFailure) as raised:
        collaboration.prepare_advice("Implement inc", [{"path": "app.py", "content": "pass\n"}])
    assert len(calls) == 1
    assert raised.value.cost_cents == 1
    assert ledger.snapshot()["spent_cents"] == 1
    assert ledger.snapshot()["reserved_cents"] == 0


@pytest.mark.parametrize("rejected", [False, True])
def test_partial_failure_keeps_successful_peer_charge_and_never_falls_back(monkeypatch, rejected):
    calls = []
    error = (broker_meta.ProviderNotAccepted("rejected") if rejected
             else broker_meta.ProviderOutcomeUnknown("timeout"))
    clients(monkeypatch, calls, fail_model="gemini-4-argon", failure=error)
    with pytest.raises(collaboration.CollaborationFailure) as raised:
        collaboration.prepare_advice("Implement inc", [{"path": "app.py", "content": "pass\n"}])
    assert {c["model"] for c in calls} == PEERS
    assert len(calls) == 2, "A failed required planner must not trigger another model as fallback"
    snap = ledger.snapshot()
    assert snap["spent_cents"] == 1, "Earlier successful work must never be refunded"
    assert (snap["reserved_cents"] == 0) if rejected else (snap["reserved_cents"] > 0)
    assert raised.value.cost_cents == 1
    assert "muse-spark" not in json.dumps(calls)
    for value in KEYS.values():
        assert value not in str(raised.value)


def test_budget_exhaustion_blocks_native_dispatch(monkeypatch):
    ledger.configure({"default": 0})
    def factory(*args):
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kwargs: pytest.fail("zero budget must not dispatch"))))
    monkeypatch.setattr(platform_models, "client_for", factory)
    with pytest.raises(Exception):
        collaboration.prepare_advice("Implement inc", [{"path": "app.py", "content": "pass\n"}])
    assert ledger.snapshot()["spent_cents"] == 0
    assert ledger.snapshot()["reserved_cents"] == 0


def test_public_budget_guards_include_both_new_planning_calls(monkeypatch):
    monkeypatch.setenv("EVO_MODEL_PROFILE", "legacy")
    old_arena = arena.budget_worst_cents("critic")
    old_prompt = arena_prompt.budget_worst_cents("critic")
    monkeypatch.setenv("EVO_MODEL_PROFILE", "collaborative")
    assert arena.budget_worst_cents("critic") >= old_arena + 240
    assert arena_prompt.budget_worst_cents("critic") >= old_prompt + 240


def test_defaults_endpoint_never_requires_a_visitor_key(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    c = TestClient(main.app, raise_server_exceptions=False)
    r = c.get("/v1/models/defaults")
    assert r.status_code == 200, r.text
    assert r.json()["requires_api_key"] is False
    assert r.json()["ready"] is True
    for value in KEYS.values():
        assert value not in r.text


@pytest.mark.parametrize("invalid", ["missing_key", "unknown_profile"])
def test_unavailable_profile_is_rejected_before_public_job_queue(monkeypatch, invalid):
    from fastapi.testclient import TestClient
    import main
    if invalid == "missing_key":
        monkeypatch.delenv("GEMINI_API_KEY")
    else:
        monkeypatch.setenv("EVO_MODEL_PROFILE", "collaborative-typo")
    monkeypatch.setattr(main, "_check_public_daily_or_429", lambda *a: None)
    monkeypatch.setattr(main.eval_jobs_mod, "create_job", lambda **kwargs: pytest.fail("unavailable profile must not enqueue provider work"))
    c = TestClient(main.app, raise_server_exceptions=False)
    out = c.post("/v1/arena/prompt", json={"prompt": "Implement inc", "feedback": "critic", "single_apply": "tolerant"})
    assert out.status_code in (422, 503), out.text
    assert ledger.snapshot()["spent_cents"] == 0
    assert ledger.snapshot()["reserved_cents"] == 0
    for value in KEYS.values():
        assert value not in out.text


def test_arena_uses_plans_once_across_retry_but_critic_never_sees_them(monkeypatch):
    calls, goals, critic_goals = [], [], []
    clients(monkeypatch, calls)
    original = "def inc(x):\n    return x\n"
    fixed = "def inc(x):\n    return x + 1\n"
    diff = "".join(difflib.unified_diff(original.splitlines(True), fixed.splitlines(True), "a/app.py", "b/app.py"))
    task = {
        "id": "JUDGE-COLLAB-ROUTING", "goal": "Implement inc(x), returning x plus one.",
        "files": {"app.py": original}, "reference_fix": diff,
        "heldout": [{"kind": k, "code": f"def test_private_{k}_NEVER_LEAK():\n    import app\n    assert app.inc(1) == 2\n"}
                    for k in ["compositional", "negative", "boundary"]],
    }
    suite = [{"kind": k, "code": f"def test_critic_{k}():\n    import app\n    assert app.inc(1) == 2\n"}
             for k in ["compositional", "negative", "boundary"]]
    def critic(goal):
        critic_goals.append(goal)
        rid = ledger.reserve(120)
        ledger.settle(rid, 1)
        out = {"sealed_tests": suite, "stub": False, "model": "claude-opus-5-5",
               "usage": {"prompt_tokens": 100, "completion_tokens": 100}}
        return rid, out, 1, False
    def builder(goal, base, file_context=None, **kwargs):
        goals.append(goal)
        return {"diff": "" if len(goals) == 1 else diff, "tests": [], "stub": False,
                "model": "muse-spark-1.3", "usage": {"prompt_tokens": 100, "completion_tokens": 100}}
    monkeypatch.setattr(sealed_eval, "_call_critic_suite", critic)
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    result = arena._run_evoforge_lane_critic(task, "muse-spark-1.3", 30, max_attempts=2)
    assert result["status"] == "succeeded", result
    assert result["outcome"] == "passed", result
    assert len(goals) == 2
    assert len(calls) == 2, "Planning is per run, not billed again for every Builder retry"
    for goal in goals:
        assert "gpt-6.1-sol" in goal and "gemini-4-argon" in goal
        assert "NEVER_LEAK" not in goal
    for goal in critic_goals:
        assert "Unverified advice" not in goal
        assert "NEVER_LEAK" not in goal
    assert all("NEVER_LEAK" not in json.dumps(call) for call in calls)
    assert result["cost_cents"] == ledger.snapshot()["spent_cents"]


def test_single_lane_stays_one_model_call_without_planners(monkeypatch):
    calls = []
    clients(monkeypatch, calls)
    task = {"id": "JUDGE-SINGLE", "goal": "Implement inc", "files": {"app.py": "pass\n"},
            "heldout": [{"kind": k, "code": f"def test_{k}():\n    assert 1 == 1\n"}
                        for k in ["compositional", "negative", "boundary"]]}
    builder_calls = []
    def builder(*args, **kwargs):
        builder_calls.append(args)
        return {"diff": "", "tests": [], "stub": False, "model": "muse-spark-1.3",
                "usage": {"prompt_tokens": 100, "completion_tokens": 100}}
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    arena._run_single_lane(task, "muse-spark-1.3", 30, recount=True)
    assert len(builder_calls) == 1
    assert calls == []


def test_mission_generate_core_uses_both_plans_and_preserves_execution_gate(monkeypatch):
    import main
    planner_calls, builder_goals = [], []
    clients(monkeypatch, planner_calls)
    collaboration.configure(main._evidence)
    original = "def inc(x):\n    return x\n"
    fixed = "def inc(x):\n    return x + 1\n"
    diff = "".join(difflib.unified_diff(original.splitlines(True), fixed.splitlines(True),
                                       "a/app.py", "b/app.py"))
    tests = [{"code": "def test_inc():\n    import app\n    assert app.inc(1) == 2\n"}]
    def builder(goal, base, file_context=None):
        builder_goals.append(goal)
        assert base == "a" * 40
        assert file_context == [{"path": "app.py", "content": original}]
        return {"diff": diff, "tests": tests, "rationale": "unverified proposal", "stub": False,
                "model": "muse-spark-1.3", "usage": {"prompt_tokens": 100, "completion_tokens": 100}}
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    monkeypatch.setattr(main, "_run_core", lambda **kwargs: pytest.fail("generation cannot fabricate a Runner run"))
    eid, candidate, gates = main._generate_core(
        goal="Implement inc(x) as x plus one.", base_sha="a" * 40,
        file_context=[{"path": "app.py", "content": original}], store_extra={"kind": "judge-generation-test"})
    assert {c["model"] for c in planner_calls} == PEERS
    assert len(planner_calls) == 2 and len(builder_goals) == 1
    assert all(model in builder_goals[0] for model in PEERS)
    peers = candidate["collaboration"]
    assert "advice" not in peers
    assert "Unverified advice" not in json.dumps(peers)
    assert {c["model"] for c in peers["provider_calls"]} == PEERS
    stored = main._evidence[eid]
    reservations = peers["reservation_ids"] + [stored["reservation_id"]]
    assert len(set(reservations)) == 3
    assert all(ledger.reservation(r)["state"] == "SETTLED" for r in reservations)
    assert ledger.snapshot()["spent_cents"] == 3
    assert ledger.snapshot()["reserved_cents"] == 0
    assert peers["cost_cents"] == 2
    assert set(peers["evidence_ids"]).issubset(set(main._evidence))
    integrity = next(g for g in gates if g.gate == "GH_INTEGRITY")
    assert integrity.result != "PASS", "Planning and generation cannot replace sealed execution evidence"
    chain = {item["stage"]: item["event_id"] for item in main.evidence_chain.chain(eid)}
    assert all(chain[stage] for stage in ["Task", "Candidate", "Gate"])
    assert not chain["PR"] and not chain["Outcome"]
    for value in KEYS.values():
        assert value not in json.dumps(main._redact_value(stored))


def test_mission_review_core_stores_two_native_claude_receipts_at_usage_cost(monkeypatch):
    import main
    import openai
    calls = []
    suite = [{"kind": kind, "code": f"def test_{kind}():\n    import app\n    assert app.inc(1) == 2\n"}
             for kind in ["compositional", "negative", "boundary"]]
    diff = "--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n def inc(x):\n-    return x\n+    return x + 1\n"
    def factory(model):
        assert model == "claude-opus-5-5"
        def create(**kwargs):
            calls.append(kwargs)
            text = json.dumps({"sealed_tests": suite, "review": {"result": "PASS", "findings": []}})
            return response(model, text=text)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(platform_models, "client_for", factory)
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: pytest.fail("native review cannot route to Meta"))
    monkeypatch.setattr(main, "_run_core", lambda **kwargs: pytest.fail("review cannot fabricate a Runner run"))
    eid, output, phases = main._review_core(
        goal_contract="In app.py implement inc(x) as x plus one.", diff=diff, ci="not executed",
        store_extra={"kind": "judge-review-test"})
    assert len(calls) == len(phases) == len(set(phases)) == 2
    assert diff not in calls[0]["messages"][1]["content"]
    assert diff in calls[1]["messages"][1]["content"]
    assert output["model"] == "claude-opus-5-5" and output["stub"] is False
    assert output["execution_verified"] is False
    records = [main._evidence[p] for p in phases]
    assert {r["phase"] for r in records} == {"critic_spec", "critic_review"}
    assert {r["metadata"]["provider"] for r in records} == {"anthropic"}
    reservations = [r["reservation"] for r in records]
    assert len({r["id"] for r in reservations}) == 2
    assert all(r["state"] == "SETTLED" for r in reservations)
    assert ledger.snapshot()["spent_cents"] == 2, "Native usage must not be billed as two fixed 120-cent calls"
    assert ledger.snapshot()["reserved_cents"] == 0
    assert main._evidence[eid]["provider_evidence_ids"] == phases
    chain = {item["stage"]: item["event_id"] for item in main.evidence_chain.chain(eid)}
    assert chain["Review"] and not chain["PR"] and not chain["Outcome"]
    public = json.dumps(main._redact_value(main._evidence[eid]))
    for value in KEYS.values():
        assert value not in public
