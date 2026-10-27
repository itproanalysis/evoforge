"""Acceptance tests for Supply-Chain / BSL-1.1 / SBOM Scanner (CR-23, CR-35),
Tenant Weighted Fair Queue (CR-49), and Platform Key KMS Envelope Isolation (CR-50).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from evoforge.runtime_guards import (
    CodecRelease,
    CodecReleaseManager,
    PlatformKeyVault,
    scan_supply_chain,
    simulate_fair_queue_flood,
)


def test_repo_supply_chain_sbom_clean_and_bsl_caveman_litellm_blocked_cr23_cr35(tmp_path: Path):
    """CR-23 (codec supply-chain scan failure blocks deploy and keeps active version),
    CR-35 (BSL-1.1 / Caveman / LiteLLM / unpinned git dependency fails build scan).
    """
    # 1. Actual repository manifests and source code must pass clean with deterministic SBOM
    live_report = scan_supply_chain()
    assert live_report.passed is True, f"unexpected repo violations: {live_report.violations}"
    assert len(live_report.sbom_components) > 0
    assert len(live_report.sbom_sha256) == 64

    # 2. Injecting Caveman, LiteLLM, unpinned git URL, or BSL-1.1 package fails scan (CR-35)
    bad_req = tmp_path / "requirements-bad.txt"
    bad_req.write_text(
        "fastapi>=0.115.0\n"
        "caveman-engine==3.1.0\n"
        "litellm>=1.0.0\n"
        "git+https://github.com/example/unpinned-tool.git@main\n",
        encoding="utf-8",
    )
    bad_lock = tmp_path / "package-lock-bad.json"
    bad_lock.write_text(
        json.dumps({
            "packages": {
                "node_modules/caveman-shrink": {
                    "version": "3.0.1",
                    "license": "BSL-1.1",
                }
            }
        }),
        encoding="utf-8",
    )
    bad_src_dir = tmp_path / "src"
    bad_src_dir.mkdir()
    (bad_src_dir / "bad_adapter.py").write_text(
        "# SPDX-License-Identifier: BSL-1.1\nimport caveman_proxy\n",
        encoding="utf-8",
    )

    bad_report = scan_supply_chain(
        extra_requirements=[bad_req],
        extra_npm_locks=[bad_lock],
        extra_source_dirs=[bad_src_dir],
    )
    assert bad_report.passed is False
    assert len(bad_report.violations) >= 5
    joined = "\n".join(bad_report.violations)
    assert "caveman-engine" in joined
    assert "litellm" in joined
    assert "unpinned git dependency" in joined
    assert "BSL-1.1" in joined
    assert "caveman_proxy" in joined

    # 3. CR-23: CodecReleaseManager keeps existing version v1.0.0 when candidate scan/digest/determinism fails
    v1_bytes = b"codec-v1-clean-binary"
    v1_rel = CodecRelease(
        name="log.structural",
        version="1.0.0",
        bundle_sha256=hashlib.sha256(v1_bytes).hexdigest(),
        encode_fn=lambda b: b.decode("utf-8", errors="replace"),
    )
    mgr = CodecReleaseManager(v1_rel)

    # Attempt deploy with failed supply-chain report -> rejected, 1.0.0 stays active
    v2_bytes = b"codec-v2-contaminated"
    v2_rel = CodecRelease(
        name="log.structural",
        version="2.0.0",
        bundle_sha256=hashlib.sha256(v2_bytes).hexdigest(),
        encode_fn=lambda b: b.decode("utf-8", errors="replace"),
    )
    ok_sc, reason_sc = mgr.deploy_codec(v2_rel, bundle_bytes=v2_bytes, supply_chain_report=bad_report)
    assert ok_sc is False
    assert mgr.active_release("log.structural").version == "1.0.0"

    # Attempt deploy with BSL-1.1 license -> rejected, 1.0.0 stays active
    ok_bsl, _ = mgr.deploy_codec(v2_rel, bundle_bytes=v2_bytes, license_id="BSL-1.1", supply_chain_report=live_report)
    assert ok_bsl is False
    assert mgr.active_release("log.structural").version == "1.0.0"

    # Attempt deploy with non-deterministic codec -> rejected, 1.0.0 stays active
    rng = random.Random(42)
    v2_nondet = CodecRelease(
        name="log.structural",
        version="2.0.1",
        bundle_sha256=hashlib.sha256(v2_bytes).hexdigest(),
        encode_fn=lambda b: f"{rng.random()}:{b.decode('utf-8', errors='replace')}",
    )
    ok_nd, reason_nd = mgr.deploy_codec(v2_nondet, bundle_bytes=v2_bytes, supply_chain_report=live_report)
    assert ok_nd is False
    assert "determinism" in reason_nd
    assert mgr.active_release("log.structural").version == "1.0.0"

    # Clean, deterministic v1.1.0 deploy -> succeeds and updates active release
    v11_bytes = b"codec-v1.1.0-verified"
    v11_rel = CodecRelease(
        name="log.structural",
        version="1.1.0",
        bundle_sha256=hashlib.sha256(v11_bytes).hexdigest(),
        encode_fn=lambda b: b.decode("utf-8", errors="replace").strip(),
    )
    ok_good, _ = mgr.deploy_codec(v11_rel, bundle_bytes=v11_bytes, supply_chain_report=live_report)
    assert ok_good is True
    assert mgr.active_release("log.structural").version == "1.1.0"


def test_tenant_fair_queue_bounds_p95_wait_increase_under_flood_cr49():
    """CR-49: Under a single-tenant burst flood on shared provider rate limits,
    other tenants' p95 wait time increase stays <= 20%.
    """
    res = simulate_fair_queue_flood(service_interval_ms=10.0, normal_requests=40, flood_multiplier=25)
    assert res["passed"] is True
    assert res["p95_increase_ratio"] <= 0.20


def test_platform_key_kms_envelope_broker_only_decryption_cr50():
    """CR-50: Platform provider API keys can ONLY be decrypted by `provider_broker`;
    all other identities (`codec_worker`, `runner`, `critic`, `web_bff`, etc.) have
    0 successful decryptions.
    """
    vault = PlatformKeyVault()
    env = vault.store_platform_key("meta_prod_key_v1", "meta", "meta-secret-platform-key-998877")
    assert b"meta-secret-platform-key" not in env.ciphertext

    broker_token = vault.issue_identity_token("provider_broker")
    assert (
        vault.decrypt_platform_key(
            "meta_prod_key_v1",
            caller_identity="provider_broker",
            identity_token=broker_token,
        )
        == "meta-secret-platform-key-998877"
    )
    assert vault.decrypt_counts_by_identity == {"provider_broker": 1}

    # Every non-broker service identity must fail with PermissionError and 0 decryptions (CR-50)
    forbidden_identities = [
        "codec_worker",
        "runner",
        "critic",
        "builder",
        "web_bff",
        "retrieval_gateway",
        "anonymous",
    ]
    for ident in forbidden_identities:
        tok = vault.issue_identity_token(ident)
        with pytest.raises(PermissionError):
            vault.decrypt_platform_key("meta_prod_key_v1", caller_identity=ident, identity_token=tok)
        assert vault.decrypt_counts_by_identity.get(ident, 0) == 0

    # Even claiming provider_broker with a forged or mismatched token is denied
    worker_token = vault.issue_identity_token("codec_worker")
    with pytest.raises(PermissionError):
        vault.decrypt_platform_key(
            "meta_prod_key_v1",
            caller_identity="provider_broker",
            identity_token=worker_token,
        )

    assert len(vault.security_events) == len(forbidden_identities) + 1
    assert sum(v for k, v in vault.decrypt_counts_by_identity.items() if k != "provider_broker") == 0


def test_fair_scheduler_weights_and_codec_digest_mismatch_rollback():
    """Verify custom tenant weights in TenantFairScheduler and digest mismatch rollback in CodecReleaseManager."""
    from evoforge.runtime_guards import TenantFairScheduler

    sched = TenantFairScheduler({"tenant_high": 2.0, "tenant_low": 1.0})
    with pytest.raises(ValueError):
        sched.set_weight("tenant_low", 0.0)

    sched.enqueue("r_low_1", "tenant_low", submit_ms=0.0, cost_units=2.0)
    sched.enqueue("r_high_1", "tenant_high", submit_ms=0.0, cost_units=2.0)
    sched.enqueue("r_low_2", "tenant_low", submit_ms=1.0, cost_units=2.0)
    sched.enqueue("r_high_2", "tenant_high", submit_ms=1.0, cost_units=2.0)

    order = [sched.pop_next().request_id for _ in range(4)]
    # tenant_high has weight 2.0 so its second call has virtual_start=1.0 vs tenant_low's virtual_start=2.0
    assert order.index("r_high_2") < order.index("r_low_2")

    v1 = CodecRelease(
        name="json.structural",
        version="1.1.0",
        bundle_sha256=hashlib.sha256(b"v1").hexdigest(),
        encode_fn=lambda b: "{}",
    )
    mgr = CodecReleaseManager(v1)
    v2_bad_sha = CodecRelease(
        name="json.structural",
        version="1.2.0",
        bundle_sha256="f" * 64,
        encode_fn=lambda b: "{}",
    )
    ok, reason = mgr.deploy_codec(v2_bad_sha, bundle_bytes=b"tampered-bytes")
    assert ok is False
    assert "SHA-256 mismatch" in reason
    assert mgr.active_release("json.structural").version == "1.1.0"

