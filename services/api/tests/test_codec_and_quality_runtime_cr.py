"""Acceptance tests for Multi-Codec Pipeline, Codec Shadow Audit Monitor,
Rewrite Cost Accountant, and Quality/Promotion/Integrity/Review Signal Runtime.

Covers:
- CR-03, CR-04, CR-05, CR-09, CR-27, CR-36, CR-57: `junit.structural` (T1-T5),
  `json.structural` (J1-J5), DOCTYPE/ENTITY & binary rejection, no-gain &
  non-deterministic fallback, shadow audit auto-disable, and in-place rewrite
  surcharge accounting.
- CR-51..CR-58, CR-62..CR-64, CR-67, CR-77, CR-79: Sample-size formula parity,
  Tier A/B promotion & cluster bootstrap, zero-tolerance safety gate, speedup
  lower-bound claim, AST oracle corpus accuracy, GH_INTEGRITY decision mapping,
  and executable-evidence review signal triage.
"""
from __future__ import annotations

import json
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evoforge.codec_and_quality_runtime import (  # noqa: E402
    CodecShadowAuditMonitor,
    MultiCodecPipeline,
    QualityAndIntegrityRuntime,
    RewriteCostAccountant,
    VaultUnavailableError,
    json_codec,
    junit_codec,
)
from evoforge.context_mesh import EvidenceVault  # noqa: E402

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_FIX_DIR = os.path.join(_ROOT, "docs", "evoforge-v4.2", "reference_impl", "fixtures")
TENANT_ID = "6f1d2c3b-0a00-4b1e-9c2d-0000000000a1"
PROJECT_ID = "6f1d2c3b-0a00-4b1e-9c2d-0000000000b1"


def _load_fixture_bytes(name: str) -> bytes:
    with open(os.path.join(_FIX_DIR, name), "rb") as fh:
        return fh.read()


class FailingVault(EvidenceVault):
    """Vault stub that simulates backend storage outage (CR-16)."""

    def put_blob(self, *args, **kwargs):
        raise VaultUnavailableError("simulated KMS / disk storage outage")


def test_codec_shadow_audit_auto_disable_cr09_cr57() -> None:
    """CR-09, CR-57: Shadow audit monitor tracks defect misses and auto-disables faulty codecs."""
    monitor = CodecShadowAuditMonitor()
    pkey = ("test.junit", f"{junit_codec.CODEC_NAME}@{junit_codec.CODEC_VERSION}", "meta")

    assert not monitor.is_disabled(pkey)

    # Under min_audits_per_window (200), clean audits return ALERT_INSUFFICIENT_AUDIT; once >= 200, KEEP
    action_early, _ = monitor.record_shadow_audit(pkey, missed_defect=False)
    assert action_early == "ALERT_INSUFFICIENT_AUDIT"
    for _ in range(199):
        action, _ = monitor.record_shadow_audit(pkey, missed_defect=False)
    assert action == "KEEP"
    assert not monitor.is_disabled(pkey)

    # Critical miss immediately triggers DISABLE
    action, reason = monitor.record_shadow_audit(pkey, critical_miss=True)
    assert action == "DISABLE"
    assert "critical" in reason or "miss" in reason
    assert monitor.is_disabled(pkey)

    vault = EvidenceVault()
    pipeline = MultiCodecPipeline(vault=vault, monitor=monitor)
    junit_xml = _load_fixture_bytes("junit_report.xml")
    res = pipeline.encode_and_gate(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        source_kind="test.junit",
        original=junit_xml,
    )
    assert res.fidelity == "RAW"
    assert res.raw_reason == "PROFILE_DISABLED"
    assert res.profile_action == "DISABLE"


def test_multi_codec_pipeline_junit_and_binary_rejection_cr04_cr05_cr09_cr27() -> None:
    """CR-04, CR-05, CR-09, CR-27: JUnit XML compression, DOCTYPE/binary rejection, U2/U3/T1-T5 checks."""
    vault = EvidenceVault()
    monitor = CodecShadowAuditMonitor()
    pipeline = MultiCodecPipeline(vault=vault, monitor=monitor)

    junit_bytes = _load_fixture_bytes("junit_report.xml")
    ok_res = pipeline.encode_and_gate(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        source_kind="test.junit",
        original=junit_bytes,
    )
    assert ok_res.fidelity == "STRUCTURAL"
    assert ok_res.raw_reason is None
    assert "failures=2 errors=1" in ok_res.content

    # CR-04: DOCTYPE / ENTITY expansion bomb rejected before XML parse -> RAW(PARSE_FAILED)
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>'
        b'<testsuite><testcase name="&a;"/></testsuite>'
    )
    bomb_res = pipeline.encode_and_gate(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        source_kind="test.junit",
        original=bomb,
    )
    assert bomb_res.fidelity == "RAW"
    assert bomb_res.raw_reason == "PARSE_FAILED"

    # CR-04: Binary payload containing NUL byte -> RAW(UNSUPPORTED_TYPE)
    bin_res = pipeline.encode_and_gate(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        source_kind="test.junit",
        original=b"ELF\x00\x01\x02binary-executable-payload",
    )
    assert bin_res.fidelity == "RAW"
    assert bin_res.raw_reason == "UNSUPPORTED_TYPE"

    # CR-04: Unknown source kind without a gate -> RAW(UNSUPPORTED_TYPE)
    html_res = pipeline.encode_and_gate(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        source_kind="html",
        original=b"<p>hello</p>",
    )
    assert html_res.fidelity == "RAW"
    assert html_res.raw_reason == "UNSUPPORTED_TYPE"

    # CR-05: Tiny JUnit XML with no token gain -> U2 fails -> RAW(NO_TOKEN_GAIN)
    tiny = b'<testsuite name="s"><testcase name="t"/></testsuite>'
    tiny_res = pipeline.encode_and_gate(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        source_kind="test.junit",
        original=tiny,
    )
    assert tiny_res.fidelity == "RAW"
    assert tiny_res.raw_reason == "NO_TOKEN_GAIN"

    # CR-27: Non-deterministic codec fails U3 -> RAW(FIDELITY_FAILED)
    counter = {"n": 0}

    def _flaky_encode(b: bytes) -> str:
        counter["n"] += 1
        return junit_codec.encode(b) + (" " * counter["n"])

    flaky_res = pipeline.encode_and_gate(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        source_kind="test.junit",
        original=junit_bytes,
        custom_encode=_flaky_encode,
    )
    assert flaky_res.fidelity == "RAW"
    assert flaky_res.raw_reason == "FIDELITY_FAILED"

    # CR-09: Zeroed failure count in JUnit view fails T1 -> RAW(FIDELITY_FAILED)
    zeroed_view = ok_res.content.replace("failures=2", "failures=0")
    zeroed_res = pipeline.encode_and_gate(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        source_kind="test.junit",
        original=junit_bytes,
        override_view=zeroed_view,
    )
    assert zeroed_res.fidelity == "RAW"
    assert zeroed_res.raw_reason == "FIDELITY_FAILED"

    # CR-16: Vault failure falls back to RAW(VAULT_UNAVAILABLE)
    failing_pipe = MultiCodecPipeline(vault=FailingVault())
    fail_res = failing_pipe.encode_and_gate(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        source_kind="test.junit",
        original=junit_bytes,
    )
    assert fail_res.fidelity == "RAW"
    assert fail_res.raw_reason == "VAULT_UNAVAILABLE"


def test_multi_codec_pipeline_json_api_structural_and_keep_rule_cr36() -> None:
    """CR-36: JSON structural codec preserves required pointers and enforces J5 KeepRule in SAFE profile."""
    vault = EvidenceVault()
    pipeline = MultiCodecPipeline(vault=vault)

    api_bytes = _load_fixture_bytes("api_result.json")
    rule = json_codec.KeepRule("/state", ("FAILED",))

    # Happy path with KeepRule: FAILED elements at indices 13, 26, 39 survive truncation
    ok_json = pipeline.encode_and_gate(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        source_kind="json.api",
        original=api_bytes,
        required_pointers=["/status", "/items/0/id", "/meta/request_id", "/items/13/id"],
        keep_rule=rule,
        profile="SAFE",
    )
    assert ok_json.fidelity == "STRUCTURAL"
    parsed_view = json.loads(ok_json.content)
    assert sorted(parsed_view["items"][-1]["$kept"], key=int) == ["13", "26", "39"]

    # CR-36 / J5: SAFE profile rejects array truncation without a KeepRule
    no_rule_res = pipeline.encode_and_gate(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        source_kind="json.api",
        original=api_bytes,
        keep_rule=None,
        profile="SAFE",
    )
    assert no_rule_res.fidelity == "RAW"
    assert no_rule_res.raw_reason == "FIDELITY_FAILED"

    # CR-36 / J5: Dropping a rule-matching element (index "26") from $kept fails J5
    tampered_doc = json.loads(ok_json.content)
    del tampered_doc["items"][-1]["$kept"]["26"]
    tampered_doc["items"][-1]["$omitted"] += 1
    tampered_res = pipeline.encode_and_gate(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        source_kind="json.api",
        original=api_bytes,
        keep_rule=rule,
        override_view=json.dumps(tampered_doc),
    )
    assert tampered_res.fidelity == "RAW"
    assert tampered_res.raw_reason == "FIDELITY_FAILED"


def test_rewrite_cost_accountant_in_place_surcharge_cr27() -> None:
    """CR-27: In-place history rewrites invalidate cached prefix and record surcharge in receipt annotation."""
    accountant = RewriteCostAccountant()

    with pytest.raises(ValueError, match="rewrite_turn must be in 2.."):
        accountant.record_in_place_rewrite(session_id="s_001", rewrite_turn=1)

    rec = accountant.record_in_place_rewrite(
        session_id="s_002",
        rewrite_turn=6,
        compressed=False,
    )
    assert rec.session_id == "s_002"
    assert rec.rewrite_turn == 6
    assert rec.rewritten_ite > rec.append_only_ite
    assert rec.surcharge_ite > 0
    assert rec.cache_write_surcharge_tokens > 0
    assert rec.receipt_annotation["rewrite_in_place"] is True


def test_quality_and_integrity_runtime_cr51_cr58_cr67_cr77_cr79() -> None:
    """CR-51..58, CR-62..64, CR-67, CR-77, CR-79: Sample size formula, Tier A/B promotion, AST oracle corpus, and review triage."""
    rt = QualityAndIntegrityRuntime()

    # 1. CR-51: Sample size formula matches quality_gates.json
    sz = rt.verify_sample_size_contract()
    assert sz["passed"] is True

    # 2. CR-52..CR-56: Tier A canary passes with 100 tasks, Tier B requires >= 250 tasks
    rng = random.Random(5)
    vfr_pairs = []
    for t in range(100):
        for _ in range(3):
            b = int(rng.random() < 0.7)
            c = b if rng.random() > 0.04 else (1 - b)
            vfr_pairs.append((f"task_{t:03d}", b, c))
    crit_pairs = [(f"crit_{i}", 1, 1) for i in range(120)]
    cheaper_cost = [(cid, 1.0, 0.70) for cid, _, _ in vfr_pairs]

    tier_a = rt.evaluate_promotion(
        tier="A_canary",
        vfr_pairs=vfr_pairs,
        recall_pairs=vfr_pairs,
        critical_pairs=crit_pairs,
        cost_rows=cheaper_cost,
    )
    tier_b = rt.evaluate_promotion(
        tier="B_default",
        vfr_pairs=vfr_pairs,
        recall_pairs=vfr_pairs,
        critical_pairs=crit_pairs,
        cost_rows=cheaper_cost,
    )
    assert tier_a["passed"] is True
    assert tier_b["passed"] is False
    assert tier_b["min_tasks"]["passed"] is False

    # 3. CR-58: 10X speedup claim uses lower bound
    sp_rows = [(f"w_{i}", 10.0, 35.0) for i in range(40)]
    sp = rt.evaluate_speedup_claim(sp_rows, "M5_ga")
    assert sp["met"] is True
    assert f"{sp['lo']:.2f}배 이상" in sp["claimable_text"]

    # 4. CR-77: AST oracle classifier corpus accuracy
    acc = rt.verify_oracle_classifier_accuracy()
    assert acc["passed"] is True
    assert acc["dev"]["exact"] == 1.0
    assert acc["holdout"]["binary_agreement"] >= 0.85
    assert acc["holdout"]["false_strong_rate"] <= 0.05

    # 5. CR-62..CR-64, CR-79: GH_INTEGRITY decision mapping
    weak_src = [("def test_weak():\n    assert True\n", "py")]
    complete_kinds = ["compositional", "negative", "boundary"]
    prov = rt.evaluate_candidate_integrity(
        diff="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n",
        new_test_sources=weak_src,
        heldout_kinds=complete_kinds,
        vis_pass=3,
        vis_n=3,
        held_pass=3,
        held_n=3,
        holdout_cases=100,
    )
    assert prov["result"] == "INCONCLUSIVE"

    hard_fail = rt.evaluate_candidate_integrity(
        diff="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n",
        new_test_sources=weak_src,
        heldout_kinds=complete_kinds,
        vis_pass=3,
        vis_n=3,
        held_pass=3,
        held_n=3,
        holdout_cases=250,
    )
    assert hard_fail["result"] == "FAIL"

    # 6. CR-67: Blocking findings without executable evidence downgraded to advisory and capped at 5
    noisy_findings = [
        {"id": f"f_{i}", "severity": "high", "blocking": True, "evidence": None}
        for i in range(8)
    ] + [
        {
            "id": "f_real",
            "severity": "critical",
            "blocking": True,
            "evidence": {"kind": "failing_test", "ref": "evr_real_01"},
        }
    ]
    triaged = rt.triage_review_findings(noisy_findings)
    assert len(triaged["blocking"]) == 1
    assert triaged["blocking"][0]["id"] == "f_real"
    assert len(triaged["advisory"]) == 5
    assert triaged["suppressed"] == 3
    assert all(a["downgraded"] is True and a["blocking"] is False for a in triaged["advisory"])
