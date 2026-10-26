#!/usr/bin/env python3
"""Regenerate contracts/examples from the reference implementation.

Valid examples carry real hashes computed from reference_impl/fixtures, so
view_sha256 / sha256 / size_bytes are consistent with what the codecs emit.
Invalid examples are single-mutation variants of a valid one; their expected
failure is recorded in examples/invalid/EXPECTATIONS.json.

Usage: python3 -I tools/make_examples.py   (from the package root)
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "reference_impl"))
import fidelity_gate as fg  # noqa: E402
import json_codec  # noqa: E402
import junit_codec  # noqa: E402

EX = os.path.join(ROOT, "contracts", "examples")
H = lambda b: hashlib.sha256(b if isinstance(b, bytes) else b.encode()).hexdigest()  # noqa: E731

T, P = "6f1d2c3b-0a00-4b1e-9c2d-0000000000a1", "6f1d2c3b-0a00-4b1e-9c2d-0000000000b1"
RUN, TASK, ATT = "0b7e1f00-1111-4c22-8d33-000000000001", "0b7e1f00-1111-4c22-8d33-000000000002", "0b7e1f00-1111-4c22-8d33-000000000003"
CAND = "0b7e1f00-1111-4c22-8d33-0000000000c1"
HEAD = "3f9a" * 10
ISSUED, EXP = "2026-10-25T09:00:00Z", "2026-10-25T10:00:00Z"


def write(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def base_packet() -> dict:
    junit = open(os.path.join(ROOT, "reference_impl/fixtures/junit_report.xml"), "rb").read()
    jview = junit_codec.encode(junit)
    goal = "Goal v3: checkout API returns 200 for valid carts; no regression in tests/api; no new dependencies.\n".encode()
    policy = b"policy-7: merge requires non-author approval + required CI + no secrets.\n"
    diff = b"diff --git a/app/api/orders.py b/app/api/orders.py\n" + b"@@ -80,7 +80,9 @@\n-    return 500\n+    return 200\n" * 40
    seg = lambda i, layer, txt, bp, ttl=None: {k: v for k, v in {"index": i, "layer": layer, "sha256": H(txt), "tokens_est": fg.est_tokens(txt), "cache_breakpoint": bp, "ttl": ttl}.items() if v is not None}  # noqa: E731
    return {
        "schema_version": "context-packet/v2",
        "packet_id": "0b7e1f00-1111-4c22-8d33-0000000000e4",
        "tenant_id": T, "project_id": P, "run_id": RUN, "task_id": TASK, "task_attempt_id": ATT,
        "idempotency_key": "task-0002:attempt-0003:seat-4:ctx-v1",
        "issued_at": ISSUED, "expires_at": EXP, "supersedes_packet_id": None,
        "profile": "SAFE", "experiment_arm": None,
        "recipient": {"seat_id": 4, "seat_label": "Critic", "function_role": "critic",
                      "agent_id": "0b7e1f00-1111-4c22-8d33-0000000000a4", "candidate_id": CAND,
                      "is_author_of_candidate": False, "channel": "mcp"},
        "fencing": {"repo_sha": HEAD, "contract_version": 3, "policy_version": "policy-7",
                    "policy_hash": H(policy), "tool_schema_hash": H(b"tools-v12"),
                    "evidence_manifest_hash": H(b"manifest:" + H(diff).encode() + H(junit).encode()), "lease_epoch": 12},
        "items": [
            {"item_id": "it_goal", "source_kind": "contract.goal", "ref": "evr_0q3m8k2v7c4t1n6h9w5r2x8z3b", "sha256": H(goal),
             "size_bytes": len(goal), "trust": "trusted_contract", "classification": "internal", "requires_original": True,
             "fidelity": "RAW", "raw_reason": "POLICY_REQUIRED", "segment_index": 1, "view_sha256": H(goal), "view_tokens_est": fg.est_tokens(goal)},
            {"item_id": "it_policy", "source_kind": "contract.policy", "ref": "evr_1a2b3c4d5e6f7g8h9j0k1m2n3p", "sha256": H(policy),
             "size_bytes": len(policy), "trust": "trusted_contract", "classification": "internal", "requires_original": True,
             "fidelity": "RAW", "raw_reason": "POLICY_REQUIRED", "segment_index": 1, "view_sha256": H(policy), "view_tokens_est": fg.est_tokens(policy)},
            {"item_id": "it_diff", "source_kind": "git.diff", "ref": "evr_7y6x5w4v3t2s1r0q9p8n7m6k5j", "sha256": H(diff),
             "size_bytes": len(diff), "trust": "verified_tool_output", "classification": "restricted", "requires_original": True,
             "fidelity": "REF_ONLY", "segment_index": 3, "view_sha256": H(b""), "view_tokens_est": 0},
            {"item_id": "it_junit", "source_kind": "test.junit", "ref": "evr_9h8g7f6e5d4c3b2a1z0y9x8w7v", "sha256": H(junit),
             "size_bytes": len(junit), "trust": "verified_tool_output", "classification": "internal", "requires_original": True,
             "fidelity": "STRUCTURAL", "codec": {"name": junit_codec.CODEC_NAME, "version": junit_codec.CODEC_VERSION, "deterministic": True},
             "fidelity_checks": [{"invariant_id": i, "passed": True} for i in ("U1", "U2", "U3", "U4", "T1", "T2", "T3", "T4", "T5")],
             "omitted": [{"selector": "all", "count": 117, "unit": "testcases"}],
             "segment_index": 3, "view_sha256": H(jview), "view_tokens_est": fg.est_tokens(jview)},
        ],
        "critical_assertions": [
            {"assertion_id": "ca_t017", "kind": "failing_test", "item_id": "it_junit", "selector": "junit:api::app.api.test_orders_0.test_case_017", "origin": "parser", "label": "expected 200 but was 500"},
            {"assertion_id": "ca_t063", "kind": "failing_test", "item_id": "it_junit", "selector": "junit:api::app.api.test_orders_3.test_case_063", "origin": "parser"},
            {"assertion_id": "ca_t099", "kind": "failing_test", "item_id": "it_junit", "selector": "junit:api::app.api.test_orders_4.test_case_099", "origin": "parser"},
            {"assertion_id": "ca_goal", "kind": "goal_clause", "item_id": "it_goal", "selector": "all", "origin": "user"},
        ],
        "layout": {"prefix_layout": "STABLE_PREFIX", "serialization": "evoforge-canonical/v1",
                   "cache_namespace_id": "cns_01jb7m3k9q2w4e6r8t0y1v3j5p",
                   "segments": [seg(0, "L0_PLATFORM", "platform-system-v9 + tool schemas v12", True, "1h"),
                                seg(1, "L1_TENANT_CONTRACT", goal + policy, True, "1h"),
                                seg(2, "L2_ROLE_SCOPE", "critic role brief v4", True, "5m"),
                                seg(3, "L3_TASK_DELTA", jview, False)]},
        "cache_plan": {"provider": "anthropic", "model": "claude-opus-5-5", "cache_mode": "PROVIDER_EXPLICIT",
                       "registry_entry_id": "anthropic.claude-current", "registry_verified_at": "2026-10-25"},
        "recovery": {"channels": ["mcp", "rest"], "max_bytes_per_call": 262144, "max_calls": 40, "refs_expire_at": EXP},
    }


def builder_packet(critic: dict) -> dict:
    p = copy.deepcopy(critic)
    api = open(os.path.join(ROOT, "reference_impl/fixtures/api_result.json"), "rb").read()
    rule = json_codec.KeepRule("/state", ("FAILED",))
    view = json_codec.encode(api, rule)
    p.update({"packet_id": "0b7e1f00-1111-4c22-8d33-0000000000e2", "idempotency_key": "task-0002:attempt-0003:seat-2:ctx-v1"})
    p["recipient"] = {"seat_id": 2, "seat_label": "Builder Alpha", "function_role": "builder", "agent_id": "0b7e1f00-1111-4c22-8d33-0000000000a2",
                      "candidate_id": CAND, "is_author_of_candidate": True, "channel": "api"}
    p["items"] = [p["items"][0], p["items"][1], {
        "item_id": "it_apiresult", "source_kind": "json.api", "ref": "evr_2c3d4e5f6g7h8j9k0m1n2p3q4r", "sha256": H(api), "size_bytes": len(api),
        "trust": "untrusted_content", "classification": "internal", "requires_original": False, "fidelity": "STRUCTURAL",
        "codec": {"name": json_codec.CODEC_NAME, "version": json_codec.CODEC_VERSION, "deterministic": True},
        "fidelity_checks": [{"invariant_id": i, "passed": True} for i in ("U1", "U2", "U3", "U4", "J1", "J2", "J3", "J4", "J5")],
        "omitted": [{"selector": "json:/items", "count": 42, "unit": "elements"}],
        "segment_index": 3, "view_sha256": H(view), "view_tokens_est": fg.est_tokens(view)}]
    p["critical_assertions"] = [{"assertion_id": "ca_goal", "kind": "goal_clause", "item_id": "it_goal", "selector": "all", "origin": "user"},
                                {"assertion_id": "ca_reqid", "kind": "required_json_pointer", "item_id": "it_apiresult", "selector": "json:/meta/request_id", "origin": "policy"}]
    p["layout"]["segments"][2]["sha256"] = H("builder role brief v4")
    p["layout"]["segments"][3]["sha256"] = H(view)
    p["layout"]["segments"][3]["tokens_est"] = fg.est_tokens(view)
    p["cache_plan"] = {"provider": "openai", "model": "gpt-5.6", "cache_mode": "PROVIDER_IMPLICIT",
                       "registry_entry_id": "openai.gpt-5.6-plus", "registry_verified_at": "2026-10-25",
                       "provider_cache_key": "pck_" + H(T + P)[:24]}
    for s in p["layout"]["segments"]:
        s.pop("ttl", None)
        s["cache_breakpoint"] = False
    p["recovery"]["channels"] = ["rest"]
    return p


def main() -> None:
    critic = base_packet()
    builder = builder_packet(critic)
    write(os.path.join(EX, "valid/context-packet.critic.json"), critic)
    write(os.path.join(EX, "valid/context-packet.builder.json"), builder)
    req = {"kind": "retrieve_evidence.request", "request_id": "rq-0002-0003-seat4-000001", "ref": critic["items"][2]["ref"],
           "packet_id": critic["packet_id"], "task_attempt_id": ATT, "selector": "hunk:app/api/orders.py#1",
           "reason": "review_coverage", "expected_sha256": critic["items"][2]["sha256"], "max_bytes": 65536}
    write(os.path.join(EX, "valid/retrieve.request.json"), req)
    write(os.path.join(EX, "valid/retrieve.response.ok.json"), {
        "kind": "retrieve_evidence.response", "request_id": req["request_id"], "status": "ok", "trace_id": "tr_8c1e2f3a",
        "ref": req["ref"], "sha256": req["expected_sha256"], "total_size_bytes": critic["items"][2]["size_bytes"],
        "range": {"start": 0, "end": 120}, "encoding": "utf-8",
        "content": "diff --git a/app/api/orders.py b/app/api/orders.py\n@@ -80,7 +80,9 @@\n-    return 500\n+    return 200\n",
        "trust": "verified_tool_output", "next_selector": "hunk:app/api/orders.py#2",
        "coverage_after": {"covered_bytes": 120, "total_bytes": critic["items"][2]["size_bytes"], "complete": False}})
    write(os.path.join(EX, "valid/retrieve.response.not_found.json"), {
        "kind": "retrieve_evidence.response", "request_id": "rq-foreign-ref-probe-0001", "status": "not_found", "trace_id": "tr_77aa01"})
    receipt = {
        "schema_version": "provider-usage-receipt/v1", "receipt_id": "0b7e1f00-1111-4c22-8d33-0000000000f1", "tenant_id": T, "project_id": P,
        "packet_id": critic["packet_id"], "call_id": "0b7e1f00-1111-4c22-8d33-0000000000f2", "call_purpose": "retrieval_turn",
        "provider": "anthropic", "model": "claude-opus-5-5", "provider_request_id": "msg_example_0001", "source": "provider_billed",
        "billing_owner": "platform",
        "tokens": {"uncached_input": 180, "cache_write": 2400, "cache_write_ttl": "5m", "cache_read": 21500, "output": 140},
        "raw_usage_fields": {"input_tokens": 180, "cache_creation_input_tokens": 2400, "cache_read_input_tokens": 21500, "output_tokens": 140},
        "cost_micros": 0, "customer_price_micros": 0, "reservation_key": "rsv-0002-0003-seat4-000007",
        "ledger_entry_id": None, "currency": "USD", "price_table_version": "EXAMPLE-ONLY", "recorded_at": "2026-10-25T09:03:12Z"}
    write(os.path.join(EX, "valid/usage-receipt.retrieval_turn.json"), receipt)
    hpatch = {"schema_version": "harness-patch/v1", "patch_id": "hp_0c0ffee1", "run_id": "opt-2027-01-a", "generation": 3,
              "parent_versions": ["hv_00000007", "hv_0000000a"], "module": "C", "category": "prompt", "phase": "steering",
              "ops": [{"file": "prompts/builder.md", "op": "insert_after", "anchor": "## Rules\n",
                       "text": "- After a compaction, re-read the failing assertion before editing.\n"}],
              "rationale": "Repeated exploration rose after compaction boundaries in D_evo traces.",
              "minibatch": {"parent_score": 0.42, "child_score": 0.47, "batch_hash": H(b"minibatch-3")},
              "evaluated_on": ["minibatch", "dev"]}
    write(os.path.join(EX, "valid/harness-patch.steering.json"), hpatch)

    inv, expect = {}, {}

    def bad(name, why, mutate, src=critic):
        p = copy.deepcopy(src)
        mutate(p)
        inv[name] = p
        expect[name] = why

    bad("critic_is_author.json", "schema: reviewer must not be author", lambda p: p["recipient"].update(is_author_of_candidate=True))
    bad("critic_diff_not_requires_original.json", "schema: reviewer diff requires_original", lambda p: p["items"][2].update(requires_original=False))
    bad("critic_without_recovery_channel.json", "schema: reviewer needs a recovery channel (CR-14)", lambda p: p["recovery"].update(channels=[]))
    bad("lossy_without_codec.json", "schema: STRUCTURAL needs codec/fidelity_checks/omitted", lambda p: p["items"][3].pop("codec"))
    bad("lossy_failed_check.json", "schema: fidelity_checks must all pass", lambda p: p["items"][3]["fidelity_checks"].__setitem__(1, {"invariant_id": "T2", "passed": False}))
    bad("raw_without_reason.json", "schema: RAW needs raw_reason", lambda p: p["items"][0].pop("raw_reason"))
    bad("contract_summarized.json", "schema: contracts are RAW/POLICY_REQUIRED", lambda p: p["items"][0].update(
        fidelity="RECOVERABLE", codec={"name": "text.summary", "version": "1.0.0", "deterministic": True},
        fidelity_checks=[{"invariant_id": "U1", "passed": True}], omitted=[{"selector": "all", "count": 1}], **{"raw_reason": None}) or p["items"][0].pop("raw_reason"))
    bad("untrusted_claims_contract.json", "schema: only contracts may be trusted_contract", lambda p: p["items"][3].update(trust="trusted_contract"))
    bad("explicit_cache_no_breakpoint.json", "schema: PROVIDER_EXPLICIT needs a breakpoint", lambda p: [s.update(cache_breakpoint=False) for s in p["layout"]["segments"]])
    bad("sequential_ref.json", "schema: ref must be random evr_ id", lambda p: p["items"][2].update(ref="evref-000000000001"))
    bad("jsonpath_selector.json", "schema: no expression selectors", lambda p: p["critical_assertions"][0].update(selector="json:$..items[?(@.state=='FAILED')]"))
    bad("path_traversal_selector.json", "schema: no '..' in repo paths", lambda p: p["critical_assertions"][0].update(selector="file:../../etc/passwd"))
    bad("uuid_ids_as_slugs.json", "schema: ids are UUIDs (v3.5 example used slugs)", lambda p: p.update(tenant_id="tenant-demo"))
    bad("usage_inside_packet.json", "schema: usage belongs to receipts, not packets", lambda p: p.update(usage={"measured": True}))
    bad("untrusted_in_prefix.json", "semantic S2: untrusted content in L0/L1", lambda p: p["items"][2].update(segment_index=1, trust="untrusted_content"))
    bad("lossy_in_contract_layer.json", "semantic S9: lossy view outside L2/L3", lambda p: p["items"][3].update(segment_index=0, trust="verified_tool_output"))
    bad("assertion_on_ref_only.json", "semantic S4: parser assertion must be visible (not REF_ONLY)", lambda p: p["critical_assertions"].append(
        {"assertion_id": "ca_diff", "kind": "required_file", "item_id": "it_diff", "selector": "file:app/api/orders.py", "origin": "parser"}))
    bad("too_many_breakpoints.json", "semantic S6: > registry max_breakpoints (anthropic=4)", lambda p: p["layout"]["segments"].extend(
        [dict(p["layout"]["segments"][3], index=4 + k, cache_breakpoint=True) for k in range(2)]) or p["layout"]["segments"][3].update(cache_breakpoint=True))
    bad("nocache_on_undisableable_provider.json", "semantic S6: cache_mode NONE impossible on gemini (implicit, cannot disable)", lambda p: p["cache_plan"].update(
        provider="google", model="gemini-4-argon", cache_mode="NONE", registry_entry_id="google.gemini-4"))
    bad("stale_registry_entry.json", "semantic S6: registry entry older than max_age_days at issue time", lambda p: p["cache_plan"].update(registry_verified_at="2026-08-01"))
    bad("safe_profile_recoverable_test.json", "semantic S10: SAFE forbids RECOVERABLE on test reports", lambda p: p["items"][3].update(fidelity="RECOVERABLE"))
    bad("arm_mismatch.json", "semantic S8: arm A0_RAW_NOCACHE requires all-RAW + cache NONE", lambda p: p.update(experiment_arm="A0_RAW_NOCACHE"))
    bad("breakpoint_on_task_delta.json", "semantic S11: cache breakpoint on L3_TASK_DELTA (dynamic layer)", lambda p: p["layout"]["segments"][2].update(cache_breakpoint=False) or p["layout"]["segments"][3].update(cache_breakpoint=True))
    bad("tool_output_in_cached_prefix.json", "semantic S11: verified tool output inside the cached prefix", lambda p: p["items"][3].update(segment_index=2))
    bad("layer_order.json", "semantic S1: segments must be ordered L0<=L1<=L2<=L3", lambda p: p["layout"]["segments"].__setitem__(1, dict(p["layout"]["segments"][1], layer="L3_TASK_DELTA")))
    bad("refs_outlive_packet.json", "semantic S7: refs_expire_at must be <= expires_at", lambda p: p["recovery"].update(refs_expire_at="2026-10-26T10:00:00Z"))
    bad("legacy_v35_example.json", "schema: v3.5 packet is not v2", lambda p: p.clear() or p.update(json.load(open(os.path.join(ROOT, "legacy/v3.5_contracts/EvoForge_v3.5_Context_Packet_Example.json")))))
    bad("receipt_byok.json", "schema: BYOK out of scope (ADR-047)", lambda p: p.update(billing_owner="byok_customer"), src=receipt)
    bad("receipt_billed_without_request_id.json", "schema: provider_billed needs provider_request_id", lambda p: p.pop("provider_request_id"), src=receipt)
    bad("receipt_without_reservation.json", "schema: every call is reserved before it is sent", lambda p: p.pop("reservation_key"), src=receipt)
    bad("harness_patch_test_feedback.json", "schema: D_test results are not representable on a patch (D-057)", lambda p: p.update(evaluated_on=["dev", "test"]), src=hpatch)
    bad("harness_patch_freeform_rewrite.json", "schema: no free-form rewrite op", lambda p: p["ops"].__setitem__(0, {"file": "prompts/builder.md", "op": "rewrite_all", "text": "x"}), src=hpatch)
    bad("harness_patch_path_escape.json", "schema: no '..' in harness paths", lambda p: p["ops"][0].update(file="../policy/engine.py"), src=hpatch)
    for name, obj in inv.items():
        write(os.path.join(EX, "invalid", name), obj)
    write(os.path.join(EX, "invalid", "EXPECTATIONS.json"), expect)
    print(f"wrote 7 valid, {len(inv)} invalid examples")


if __name__ == "__main__":
    main()
