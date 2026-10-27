"""Multi-Codec Pipeline (`junit.structural`, `json.structural`, `log.text`),
Codec Runtime Shadow Audit Monitor, In-Place Rewrite Cost Accountant, and
Quality/Promotion/Integrity/Review Signal Runtime.

Implements and integrates:
- CR-03, CR-04, CR-05, CR-09, CR-27, CR-36: Production multi-codec wrapper over
  `junit_codec`, `json_codec`, `fidelity_gate`, `cost_model`, and `EvidenceVault`.
- CR-51..CR-58, CR-62..CR-64, CR-67, CR-68, CR-77, CR-79: Statistical promotion
  gates (Tier A/B), cluster bootstrap, zero-tolerance safety gate, codec shadow
  audit auto-disable, AST oracle corpus accuracy verification, reward-hack &
  GH_INTEGRITY decision mapping, and executable-evidence review signal triage.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_V42_ROOT = os.path.join(_ROOT, "docs", "evoforge-v4.2")
_REF_DIR = os.path.join(_V42_ROOT, "reference_impl")

if _REF_DIR not in sys.path:
    sys.path.insert(0, _REF_DIR)

import cost_model  # noqa: E402
import fidelity_gate as fg  # noqa: E402
import integrity_gate as ig  # noqa: E402
import json_codec  # noqa: E402
import junit_codec  # noqa: E402
import oracle_ast as oa  # noqa: E402
import oracle_strength as osx  # noqa: E402
import quality_gate as qg  # noqa: E402
import review_policy as rp  # noqa: E402
import reward_hack as rh  # noqa: E402

from evoforge.context_mesh import (  # noqa: E402
    EvidenceVault,
    VaultCapacityExceeded,
    encode_log,
    evaluate_fidelity_gate,
)


class VaultUnavailableError(RuntimeError):
    """Raised when EvidenceVault storage or KMS is unavailable (CR-16)."""


@dataclass
class ProfileAuditState:
    audits: int = 0
    misses: int = 0
    critical_misses: int = 0
    lossy_events: int = 0
    fallbacks: int = 0
    disabled: bool = False
    last_action: str = "KEEP"
    last_reason: str = "initial"


class CodecShadowAuditMonitor:
    """Monitors `(source_kind, codec@version, provider)` profiles and auto-disables on safety misses (CR-09, CR-57)."""

    def __init__(self, gates_cfg: dict[str, Any] | None = None):
        self.gates_cfg = gates_cfg or qg.load_gates()
        self.profiles: dict[tuple[str, str, str], ProfileAuditState] = {}

    def _state(self, profile_key: tuple[str, str, str]) -> ProfileAuditState:
        if profile_key not in self.profiles:
            self.profiles[profile_key] = ProfileAuditState()
        return self.profiles[profile_key]

    def is_disabled(self, profile_key: tuple[str, str, str]) -> bool:
        return self._state(profile_key).disabled

    def record_gate_outcome(
        self,
        profile_key: tuple[str, str, str],
        *,
        lossy_emitted: bool,
        tamper_or_drop_detected: bool = False,
    ) -> tuple[str, str]:
        st = self._state(profile_key)
        if lossy_emitted:
            st.lossy_events += 1
        else:
            st.fallbacks += 1
        action, reason = qg.codec_runtime_decision(
            st.audits,
            st.misses,
            st.critical_misses,
            st.lossy_events,
            st.fallbacks,
            self.gates_cfg,
        )
        st.last_action, st.last_reason = action, reason
        if action == "DISABLE":
            st.disabled = True
        return action, reason

    def record_shadow_audit(
        self,
        profile_key: tuple[str, str, str],
        *,
        missed_defect: bool = False,
        critical_miss: bool = False,
    ) -> tuple[str, str]:
        st = self._state(profile_key)
        st.audits += 1
        if missed_defect or critical_miss:
            st.misses += 1
        if critical_miss:
            st.critical_misses += 1
        action, reason = qg.codec_runtime_decision(
            st.audits,
            st.misses,
            st.critical_misses,
            st.lossy_events,
            st.fallbacks,
            self.gates_cfg,
        )
        st.last_action, st.last_reason = action, reason
        if action == "DISABLE":
            st.disabled = True
        return action, reason


@dataclass
class EncodedItemResult:
    source_kind: str
    fidelity: str
    raw_reason: str | None
    content: str
    ref: str | None
    checks: list[dict[str, Any]]
    profile_action: str = "KEEP"


class MultiCodecPipeline:
    """Unified runtime pipeline for `junit.structural`, `json.structural`, and `log.text` (CR-03/04/05/09/27/36)."""

    def __init__(
        self,
        vault: EvidenceVault,
        monitor: CodecShadowAuditMonitor | None = None,
    ):
        self.vault = vault
        self.monitor = monitor or CodecShadowAuditMonitor()

    @staticmethod
    def _codec_id_for(source_kind: str) -> str:
        if source_kind == "test.junit":
            return f"{junit_codec.CODEC_NAME}@{junit_codec.CODEC_VERSION}"
        if source_kind == "json.api":
            return f"{json_codec.CODEC_NAME}@{json_codec.CODEC_VERSION}"
        if source_kind == "log.text":
            return "log.text@1.0.0"
        return "unknown@0.0.0"

    def encode_and_gate(
        self,
        *,
        tenant_id: str,
        project_id: str,
        source_kind: str,
        original: bytes,
        profile: str = "SAFE",
        provider: str = "meta",
        min_gain: float = 0.2,
        required_pointers: list[str] | None = None,
        keep_rule: json_codec.KeepRule | None = None,
        critical_assertions: list[str] | None = None,
        custom_encode: Callable[[bytes], str] | None = None,
        override_view: str | None = None,
    ) -> EncodedItemResult:
        codec_id = self._codec_id_for(source_kind)
        pkey = (source_kind, codec_id, provider)
        raw_text = original.decode("utf-8", errors="replace")

        if self.monitor.is_disabled(pkey):
            return EncodedItemResult(
                source_kind=source_kind,
                fidelity="RAW",
                raw_reason="PROFILE_DISABLED",
                content=raw_text,
                ref=None,
                checks=[],
                profile_action="DISABLE",
            )

        # Store in EvidenceVault first (CR-01 / CR-02)
        try:
            blob_id, receipt = self.vault.put_blob(
                tenant_id=tenant_id,
                project_id=project_id,
                data=original,
            )
        except (VaultCapacityExceeded, VaultUnavailableError):
            return EncodedItemResult(
                source_kind=source_kind,
                fidelity="RAW",
                raw_reason="VAULT_UNAVAILABLE",
                content=raw_text,
                ref=None,
                checks=[{"invariant_id": "U1", "passed": False, "detail": "vault capacity exceeded or unavailable"}],
            )

        if not receipt.read_back_verified:
            return EncodedItemResult(
                source_kind=source_kind,
                fidelity="RAW",
                raw_reason="VAULT_UNAVAILABLE",
                content=raw_text,
                ref=blob_id or None,
                checks=[{"invariant_id": "U1", "passed": False, "detail": "read-back not verified"}],
            )

        # Binary input detection (NUL byte in non-supported binary payload) -> CR-04
        if b"\x00" in original:
            self.monitor.record_gate_outcome(pkey, lossy_emitted=False)
            return EncodedItemResult(
                source_kind=source_kind,
                fidelity="RAW",
                raw_reason="UNSUPPORTED_TYPE",
                content=raw_text,
                ref=blob_id,
                checks=[{"invariant_id": "U0", "passed": False, "detail": "binary payload rejected"}],
            )

        if source_kind == "log.text":
            enc_fn = custom_encode or (lambda b: encode_log(b, critical_tokens=critical_assertions or ()))
            view = override_view if override_view is not None else enc_fn(original)
            ok, checks = evaluate_fidelity_gate(
                source_kind="log.text",
                original=original,
                view=view,
                receipt=receipt,
                encode=(lambda _b: view) if override_view is not None and custom_encode is None else enc_fn,
                min_gain=min_gain,
                critical_tokens=critical_assertions or (),
            )
            failed_ids = {c.invariant_id for c in checks if not c.passed}
            action, _ = self.monitor.record_gate_outcome(pkey, lossy_emitted=ok)
            if not ok:
                raw_reason = "NO_TOKEN_GAIN" if failed_ids == {"U2"} else "FIDELITY_FAILED"
                return EncodedItemResult(
                    source_kind=source_kind,
                    fidelity="RAW",
                    raw_reason=raw_reason,
                    content=raw_text,
                    ref=blob_id,
                    checks=[c.__dict__ for c in checks],
                    profile_action=action,
                )
            return EncodedItemResult(
                source_kind=source_kind,
                fidelity="RECOVERABLE",
                raw_reason=None,
                content=view,
                ref=blob_id,
                checks=[c.__dict__ for c in checks],
                profile_action=action,
            )

        if source_kind == "test.junit":
            enc_fn = custom_encode or junit_codec.encode
            try:
                view = override_view if override_view is not None else enc_fn(original)
                ok, checks = fg.gate(
                    "test.junit",
                    original,
                    view,
                    receipt,
                    min_gain=min_gain,
                    encode=(lambda _b: view) if override_view is not None and custom_encode is None else enc_fn,
                )
            except junit_codec.CodecError as exc:
                action, _ = self.monitor.record_gate_outcome(pkey, lossy_emitted=False)
                return EncodedItemResult(
                    source_kind=source_kind,
                    fidelity="RAW",
                    raw_reason="PARSE_FAILED",
                    content=raw_text,
                    ref=blob_id,
                    checks=[{"invariant_id": "PARSE", "passed": False, "detail": str(exc)}],
                    profile_action=action,
                )

            failed_ids = {c.invariant_id for c in checks if not c.passed}
            t_failed = bool(failed_ids & {"T1", "T2", "T3", "T4", "T5"})
            action, _ = self.monitor.record_gate_outcome(
                pkey,
                lossy_emitted=ok,
                tamper_or_drop_detected=t_failed,
            )
            if not ok:
                raw_reason = "NO_TOKEN_GAIN" if failed_ids == {"U2"} else "FIDELITY_FAILED"
                return EncodedItemResult(
                    source_kind=source_kind,
                    fidelity="RAW",
                    raw_reason=raw_reason,
                    content=raw_text,
                    ref=blob_id,
                    checks=[c.__dict__ for c in checks],
                    profile_action=action,
                )
            return EncodedItemResult(
                source_kind=source_kind,
                fidelity="STRUCTURAL",
                raw_reason=None,
                content=view,
                ref=blob_id,
                checks=[c.__dict__ for c in checks],
                profile_action=action,
            )

        if source_kind == "json.api":
            enc_fn = custom_encode or (lambda b: json_codec.encode(b, keep_rule))
            try:
                view = override_view if override_view is not None else enc_fn(original)
                ok, checks = fg.gate(
                    "json.api",
                    original,
                    view,
                    receipt,
                    min_gain=min_gain,
                    encode=(lambda _b: view) if override_view is not None and custom_encode is None else enc_fn,
                    required_pointers=required_pointers or [],
                    keep_rule=keep_rule,
                    profile=profile,
                )
            except (ValueError, KeyError, TypeError) as exc:
                action, _ = self.monitor.record_gate_outcome(pkey, lossy_emitted=False)
                return EncodedItemResult(
                    source_kind=source_kind,
                    fidelity="RAW",
                    raw_reason="PARSE_FAILED",
                    content=raw_text,
                    ref=blob_id,
                    checks=[{"invariant_id": "J1", "passed": False, "detail": str(exc)}],
                    profile_action=action,
                )

            failed_ids = {c.invariant_id for c in checks if not c.passed}
            j_failed = bool(failed_ids & {"J1", "J2", "J3", "J4", "J5"})
            action, _ = self.monitor.record_gate_outcome(
                pkey,
                lossy_emitted=ok,
                tamper_or_drop_detected=j_failed,
            )
            if not ok:
                raw_reason = "NO_TOKEN_GAIN" if failed_ids == {"U2"} else "FIDELITY_FAILED"
                return EncodedItemResult(
                    source_kind=source_kind,
                    fidelity="RAW",
                    raw_reason=raw_reason,
                    content=raw_text,
                    ref=blob_id,
                    checks=[c.__dict__ for c in checks],
                    profile_action=action,
                )
            return EncodedItemResult(
                source_kind=source_kind,
                fidelity="STRUCTURAL",
                raw_reason=None,
                content=view,
                ref=blob_id,
                checks=[c.__dict__ for c in checks],
                profile_action=action,
            )

        # Any other source_kind without a registered gate -> U0 fails -> RAW(UNSUPPORTED_TYPE) (CR-04)
        ok, checks = fg.gate(source_kind, original, raw_text, receipt, min_gain=min_gain)
        action, _ = self.monitor.record_gate_outcome(pkey, lossy_emitted=False)
        return EncodedItemResult(
            source_kind=source_kind,
            fidelity="RAW",
            raw_reason="UNSUPPORTED_TYPE",
            content=raw_text,
            ref=blob_id,
            checks=[c.__dict__ for c in checks],
            profile_action=action,
        )


@dataclass
class RewriteSurchargeRecord:
    session_id: str
    rewrite_turn: int
    append_only_ite: float
    rewritten_ite: float
    surcharge_ite: float
    cache_write_surcharge_tokens: int
    receipt_annotation: dict[str, Any]


class RewriteCostAccountant:
    """Computes and records cache invalidation costs caused by mid-session in-place history rewrites (CR-27)."""

    def __init__(self, params: cost_model.Params | None = None):
        self.params = params or cost_model.Params()
        self.records: list[RewriteSurchargeRecord] = []

    def record_in_place_rewrite(
        self,
        *,
        session_id: str,
        rewrite_turn: int,
        compressed: bool = False,
    ) -> RewriteSurchargeRecord:
        if rewrite_turn < 2 or rewrite_turn > self.params.K:
            raise ValueError(f"rewrite_turn must be in 2..{self.params.K}")
        base_ite = cost_model.session_cost(self.params, compressed=compressed, cache=True, rewrite_at=None)
        rewritten_ite = cost_model.session_cost(
            self.params, compressed=compressed, cache=True, rewrite_at=rewrite_turn
        )
        surcharge_ite = round(rewritten_ite - base_ite, 4)
        v_tokens = int(self.params.T * (self.params.c if compressed else 1.0))
        invalidated_history_tokens = (rewrite_turn - 1) * (v_tokens + self.params.o)
        rec = RewriteSurchargeRecord(
            session_id=session_id,
            rewrite_turn=rewrite_turn,
            append_only_ite=base_ite,
            rewritten_ite=rewritten_ite,
            surcharge_ite=surcharge_ite,
            cache_write_surcharge_tokens=invalidated_history_tokens,
            receipt_annotation={
                "rewrite_in_place": True,
                "rewrite_turn": rewrite_turn,
                "cache_write_tokens": invalidated_history_tokens,
                "surcharge_ite": surcharge_ite,
                "policy_note": "in-place rewrite invalidated cached prefix; recorded in usage receipt (CR-27)",
            },
        )
        self.records.append(rec)
        return rec


class QualityAndIntegrityRuntime:
    """Runtime facade for statistical quality gates, promotion decisions, AST oracle corpus checks, and review triage (CR-51..58, CR-62..64, CR-67, CR-77, CR-79)."""

    def __init__(self, gates_cfg: dict[str, Any] | None = None):
        self.gates_cfg = gates_cfg or qg.load_gates()

    def verify_sample_size_contract(self) -> dict[str, Any]:
        """CR-51: Verify `pairs_required_at_p_discordant_0.10` matches the formula in quality_gates.json."""
        results = {}
        for tier in ("A_canary", "B_default"):
            t = self.gates_cfg["tiers"][tier]
            computed = qg.required_pairs(
                0.10,
                t["delta_verified_fix_rate"],
                self.gates_cfg["alpha_one_sided"],
                self.gates_cfg["power"],
            )
            expected = t["pairs_required_at_p_discordant_0.10"]
            results[tier] = {
                "computed": computed,
                "expected": expected,
                "matches": computed == expected,
            }
        return {"passed": all(r["matches"] for r in results.values()), "tiers": results}

    def evaluate_noninferiority(
        self,
        pairs: list[tuple[str, int, int]],
        delta: float,
        *,
        seed: int = 20261025,
    ) -> qg.NonInferiority:
        """CR-52, CR-53, CR-54, CR-55: Paired cluster-bootstrap non-inferiority test."""
        return qg.paired_noninferiority(
            pairs,
            delta,
            alpha=self.gates_cfg["alpha_one_sided"],
            power=self.gates_cfg["power"],
            seed=seed,
        )

    def evaluate_promotion(
        self,
        *,
        tier: str,
        vfr_pairs: list[tuple[str, int, int]],
        recall_pairs: list[tuple[str, int, int]],
        critical_pairs: list[tuple[str, int, int]],
        escaped_regressions: int = 0,
        policy_violations: int = 0,
        cost_rows: list[tuple[str, float, float]] | None = None,
    ) -> dict[str, Any]:
        """CR-52..CR-56: Full Tier A / Tier B promotion decision."""
        return qg.promotion_decision(
            tier=tier,
            vfr_pairs=vfr_pairs,
            recall_pairs=recall_pairs,
            critical_pairs=critical_pairs,
            escaped_regressions=escaped_regressions,
            policy_violations=policy_violations,
            cost_rows=cost_rows,
            g=self.gates_cfg,
        )

    def evaluate_speedup_claim(
        self,
        rows: list[tuple[str, float, float]],
        milestone: str,
    ) -> dict[str, Any]:
        """CR-58: 10X speedup ladder claim using cluster-bootstrap CI lower bound."""
        return qg.speedup_claim(rows, milestone, g=self.gates_cfg)

    def verify_oracle_classifier_accuracy(self) -> dict[str, Any]:
        """CR-77: Measure AST oracle classifier accuracy on dev corpus and human-labeled holdout."""
        fix_dir = os.path.join(_REF_DIR, "fixtures")
        with open(os.path.join(fix_dir, "oracle_corpus.json"), encoding="utf-8") as fh:
            corpus = json.load(fh)["cases"]
        with open(os.path.join(fix_dir, "oracle_holdout.json"), encoding="utf-8") as fh:
            holdout = json.load(fh)["cases"]

        dev_m = oa.measure(corpus)
        hold_m = oa.measure(holdout)
        comb_m = oa.measure(corpus + holdout)
        cfg = self.gates_cfg["oracle_strength"]

        passed = (
            dev_m["exact"] >= cfg["dev_exact_min"]
            and hold_m["binary_agreement"] >= cfg["holdout_binary_agreement_min"]
            and hold_m["false_strong_rate"] <= cfg["max_false_strong_rate"]
            and comb_m["false_strong_rate"] <= cfg["max_false_strong_rate"]
        )
        return {
            "passed": passed,
            "dev": dev_m,
            "holdout": hold_m,
            "combined": comb_m,
        }

    def evaluate_candidate_integrity(
        self,
        *,
        diff: str,
        new_test_sources: list[tuple[str, str]],
        heldout_kinds: list[str],
        vis_pass: int,
        vis_n: int,
        held_pass: int,
        held_n: int,
        expected_literals: set[str] | None = None,
        protected_globs: list[str] | None = None,
        holdout_cases: int | None = None,
    ) -> dict[str, Any]:
        """CR-62, CR-63, CR-64, CR-79: Combine oracle strength, held-out completeness, and reward-hack checks into GH_INTEGRITY."""
        oracles: list[osx.TestOracle] = []
        for src, lang in new_test_sources:
            norm_lang = "py" if lang in ("py", "python") else ("js" if lang in ("js", "ts", "javascript", "typescript") else lang)
            oracles.extend(osx.analyze(src, norm_lang))
        oracle_ok = osx.gate(oracles, cfg=self.gates_cfg["oracle_strength"])
        heldout = rh.heldout_ok(heldout_kinds, cfg=self.gates_cfg["reward_hack"])
        gap_r = rh.gap(vis_pass, vis_n, held_pass, held_n, cfg=self.gates_cfg["reward_hack"])
        added = "\n".join(
            ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")
        )
        lookup = rh.lookup_table(added, expected_literals or set(), cfg=self.gates_cfg["reward_hack"])
        tamper = rh.tampering(diff, protected_globs or ["tests/**", ".github/**", "policy/**"])
        hack = rh.verdict(gap_r, lookup, tamper)
        verdict, reasons = ig.decide(
            oracle_ok=oracle_ok,
            heldout=heldout,
            hack=hack,
            holdout_cases=holdout_cases,
            g=self.gates_cfg,
        )
        return {
            "gate": "GH_INTEGRITY",
            "result": verdict,
            "reasons": reasons,
            "oracle_ok": oracle_ok,
            "heldout_ok": heldout,
            "gap": gap_r,
            "lookup": lookup,
            "tamper": tamper,
        }

    def triage_review_findings(self, findings: list[dict[str, Any]]) -> dict[str, Any]:
        """CR-67: Blocking findings without executable evidence are downgraded to advisory and capped at 5."""
        return rp.triage_findings(findings, cfg=self.gates_cfg)
