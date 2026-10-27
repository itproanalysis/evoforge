"""Review Coverage Ledger, Large Diff Splitting (CR-32), and Seeded-Defect Canary /
Reviewer Qualification Pool (CR-08, CR-10, CR-14, CR-32, CR-34, CR-58, CR-66, CR-68).

Delegates statistical thresholds and independence rules to docs/evoforge-v4.2/
contracts/quality_gates.json, reference_impl/quality_gate.py, and
reference_impl/review_policy.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys

_V42_ROOT = Path(__file__).resolve().parents[3] / "docs" / "evoforge-v4.2"
_REF_IMPL = str(_V42_ROOT / "reference_impl")
if _REF_IMPL not in sys.path:
    sys.path.insert(0, _REF_IMPL)

import quality_gate  # noqa: E402
import review_policy  # noqa: E402

_GATES_PATH = _V42_ROOT / "contracts" / "quality_gates.json"


def _load_gates() -> dict:
    return json.loads(_GATES_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Large Diff Splitting & Chunked Review Planner (CR-32, Spec §8.3)
# ---------------------------------------------------------------------------

_FILE_SPLIT_RE = re.compile(r"(?m)^(?=---\s)")
_HUNK_SPLIT_RE = re.compile(r"(?m)^(?=@@\s-\d+)")


@dataclass(frozen=True)
class DiffChunk:
    chunk_index: int
    call_purpose: str  # "review_chunk" | "review_cross_chunk"
    byte_start: int
    byte_end: int
    content: str
    hunk_refs: list[str]


@dataclass(frozen=True)
class DiffReviewPlan:
    status: str  # "SINGLE_PASS" | "CHUNKED_REVIEW" | "REQUIRES_SPLIT_OR_HUMAN"
    total_bytes: int
    max_safe_context_bytes: int
    max_reviewable_diff_bytes: int
    requires_pr_split: bool
    requires_human_reviewer: bool
    chunks: list[DiffChunk]
    cross_chunk_pass: DiffChunk | None
    proposed_pr_splits: list[list[str]]


def _extract_file_blocks(diff: str) -> list[tuple[str, bytes]]:
    """Split a unified diff into (path, raw_bytes) blocks preserving exact byte lengths."""
    raw = diff.encode("utf-8")
    if not raw:
        return []
    matches = list(_FILE_SPLIT_RE.finditer(diff))
    if not matches:
        return [("unknown", raw)]
    blocks: list[tuple[str, bytes]] = []
    for idx, m in enumerate(matches):
        start_char = m.start() if idx > 0 else 0
        end_char = matches[idx + 1].start() if idx + 1 < len(matches) else len(diff)
        segment = diff[start_char:end_char]
        path = "unknown"
        for ln in segment.splitlines():
            if ln.startswith("+++ "):
                p = ln[4:].split("\t", 1)[0].strip()
                path = p[2:] if p.startswith(("a/", "b/")) else p
                break
        blocks.append((path, segment.encode("utf-8")))
    return blocks


def plan_diff_review(
    diff: str,
    *,
    max_safe_context_bytes: int = 32_768,
    max_reviewable_diff_bytes: int | None = None,
) -> DiffReviewPlan:
    """Plan diff review according to Context_Mesh_Spec.md §8.3 and CR-32.

    - If total_bytes > max_reviewable_diff_bytes (default 409,600 from quality_gates.json),
      automated single-PR review is refused (`REQUIRES_SPLIT_OR_HUMAN`), and file-group
      PR split boundaries are proposed.
    - If total_bytes > max_safe_context_bytes, splits into contiguous hunk/byte chunks
      (`call_purpose='review_chunk'`) whose union is [0, total_bytes), plus 1
      `review_cross_chunk` pass over the full hunk index.
    """
    if max_safe_context_bytes <= 0:
        raise ValueError("max_safe_context_bytes must be positive")
    gates = _load_gates()
    limit = (
        max_reviewable_diff_bytes
        if max_reviewable_diff_bytes is not None
        else int(gates["change_gates"]["max_reviewable_diff_bytes"])
    )
    raw = diff.encode("utf-8")
    total_bytes = len(raw)

    if total_bytes > limit:
        file_blocks = _extract_file_blocks(diff)
        splits: list[list[str]] = []
        cur_group: list[str] = []
        cur_bytes = 0
        for path, b in file_blocks:
            if cur_group and cur_bytes + len(b) > limit:
                splits.append(cur_group)
                cur_group = [path]
                cur_bytes = len(b)
            else:
                cur_group.append(path)
                cur_bytes += len(b)
        if cur_group:
            splits.append(cur_group)
        return DiffReviewPlan(
            status="REQUIRES_SPLIT_OR_HUMAN",
            total_bytes=total_bytes,
            max_safe_context_bytes=max_safe_context_bytes,
            max_reviewable_diff_bytes=limit,
            requires_pr_split=True,
            requires_human_reviewer=True,
            chunks=[],
            cross_chunk_pass=None,
            proposed_pr_splits=splits,
        )

    if total_bytes <= max_safe_context_bytes:
        return DiffReviewPlan(
            status="SINGLE_PASS",
            total_bytes=total_bytes,
            max_safe_context_bytes=max_safe_context_bytes,
            max_reviewable_diff_bytes=limit,
            requires_pr_split=False,
            requires_human_reviewer=False,
            chunks=[
                DiffChunk(
                    chunk_index=0,
                    call_purpose="review_chunk",
                    byte_start=0,
                    byte_end=total_bytes,
                    content=diff,
                    hunk_refs=["all"],
                )
            ],
            cross_chunk_pass=None,
            proposed_pr_splits=[],
        )

    # Chunk along line/hunk boundaries so byte ranges [byte_start, byte_end) partition [0, total_bytes)
    lines = diff.splitlines(keepends=True)
    chunks: list[DiffChunk] = []
    cur_lines: list[str] = []
    cur_hunks: list[str] = []
    cur_start = 0
    cur_len = 0
    current_file = "patch"
    hunk_seq = 0

    def flush_chunk() -> None:
        nonlocal cur_lines, cur_hunks, cur_start, cur_len
        if not cur_lines and cur_len == 0:
            return
        text = "".join(cur_lines)
        b_len = len(text.encode("utf-8"))
        chunks.append(
            DiffChunk(
                chunk_index=len(chunks),
                call_purpose="review_chunk",
                byte_start=cur_start,
                byte_end=cur_start + b_len,
                content=text,
                hunk_refs=list(cur_hunks) or [f"bytes:{cur_start}-{cur_start + b_len}"],
            )
        )
        cur_start += b_len
        cur_lines = []
        cur_hunks = []
        cur_len = 0

    for ln in lines:
        if ln.startswith("+++ "):
            p = ln[4:].split("\t", 1)[0].strip()
            current_file = p[2:] if p.startswith(("a/", "b/")) else p
            hunk_seq = 0
        elif ln.startswith("@@ "):
            hunk_seq += 1
        ln_bytes = len(ln.encode("utf-8"))
        # Prefer splitting at hunk/file boundaries, or when adding this line would exceed max_safe_context_bytes
        if cur_lines and (
            cur_len + ln_bytes > max_safe_context_bytes
            or (ln.startswith(("diff --git ", "--- ", "@@ ")) and cur_len >= max_safe_context_bytes // 2)
        ):
            flush_chunk()
        cur_lines.append(ln)
        cur_len += ln_bytes
        if ln.startswith("@@ "):
            cur_hunks.append(f"hunk:{current_file}#{hunk_seq}")

    flush_chunk()

    index_lines = [
        f"chunk {c.chunk_index}: bytes:{c.byte_start}-{c.byte_end} hunks={','.join(c.hunk_refs)}"
        for c in chunks
    ]
    cross_pass = DiffChunk(
        chunk_index=len(chunks),
        call_purpose="review_cross_chunk",
        byte_start=0,
        byte_end=total_bytes,
        content="\n".join(index_lines),
        hunk_refs=[h for c in chunks for h in c.hunk_refs],
    )
    return DiffReviewPlan(
        status="CHUNKED_REVIEW",
        total_bytes=total_bytes,
        max_safe_context_bytes=max_safe_context_bytes,
        max_reviewable_diff_bytes=limit,
        requires_pr_split=False,
        requires_human_reviewer=False,
        chunks=chunks,
        cross_chunk_pass=cross_pass,
        proposed_pr_splits=[],
    )


# ---------------------------------------------------------------------------
# 2. Review Coverage Ledger & Approval Gate (CR-08, CR-10, CR-14, CR-32)
# ---------------------------------------------------------------------------

class ReviewCoverageLedger:
    """Computes per-reviewer byte-interval union (`range_agg`) and enforces
    ctx.assert_review_gate invariants (Spec §8.1-8.2, CR-08, CR-10, CR-14, CR-32).
    """

    def __init__(self) -> None:
        # (agent_id, packet_id, ref) -> list of half-open [start, end) byte intervals
        self._delivered: dict[tuple[str, str, str], list[tuple[int, int]]] = {}
        self.events: list[dict] = []

    def register_packet(self, packet: dict) -> None:
        """Inline RAW items in the packet count as 100% delivered to recipient.agent_id."""
        agent_id = packet["recipient"]["agent_id"]
        packet_id = packet["packet_id"]
        for item in packet["items"]:
            if item["fidelity"] == "RAW":
                self.record_delivery(
                    agent_id=agent_id,
                    packet_id=packet_id,
                    ref=item["ref"],
                    byte_start=0,
                    byte_end=item["size_bytes"],
                    total_bytes=item["size_bytes"],
                    decision="ALLOW",
                )

    def record_delivery(
        self,
        *,
        agent_id: str,
        packet_id: str,
        ref: str,
        byte_start: int,
        byte_end: int,
        total_bytes: int,
        decision: str = "ALLOW",
    ) -> dict:
        if decision != "ALLOW":
            return self.item_coverage(agent_id, packet_id, ref, total_bytes)
        s = max(0, min(total_bytes, int(byte_start)))
        e = max(s, min(total_bytes, int(byte_end)))
        key = (agent_id, packet_id, ref)
        self._delivered.setdefault(key, []).append((s, e))
        cov = self.item_coverage(agent_id, packet_id, ref, total_bytes)
        self.events.append({
            "event": "REVIEW_COVERAGE_COMPLETE" if cov["complete"] else "REVIEW_COVERAGE_UPDATED",
            "agent_id": agent_id,
            "packet_id": packet_id,
            "ref": ref,
            **cov,
        })
        return cov

    @staticmethod
    def _union_length(intervals: list[tuple[int, int]]) -> int:
        valid = sorted((s, e) for s, e in intervals if e > s)
        if not valid:
            return 0
        merged = [valid[0]]
        for s, e in valid[1:]:
            ps, pe = merged[-1]
            if s <= pe:
                merged[-1] = (ps, max(pe, e))
            else:
                merged.append((s, e))
        return sum(e - s for s, e in merged)

    def item_coverage(self, agent_id: str, packet_id: str, ref: str, total_bytes: int) -> dict:
        covered = self._union_length(self._delivered.get((agent_id, packet_id, ref), []))
        return {
            "covered_bytes": covered,
            "total_bytes": total_bytes,
            "complete": covered >= total_bytes,
        }

    def assert_review_gate(
        self,
        packet: dict,
        *,
        reviewer_agent_id: str,
        candidate_head_sha: str,
        packet_status: str = "ISSUED",
        now_iso: str | None = None,
    ) -> tuple[bool, list[str]]:
        """Enforce ctx.assert_review_gate (Spec §8.2, CR-08, CR-10, CR-14, CR-32)."""
        reasons: list[str] = []
        rec = packet["recipient"]
        if packet_status != "ISSUED":
            reasons.append(f"packet status is {packet_status}, must be ISSUED (CR-22)")
        if now_iso is not None and now_iso >= packet["expires_at"]:
            reasons.append("packet has expired")
        if rec["function_role"] not in ("critic", "verifier"):
            reasons.append(f"recipient role {rec['function_role']!r} cannot approve")
        if rec.get("is_author_of_candidate"):
            reasons.append("author of candidate cannot approve own candidate")
        if rec["agent_id"] != reviewer_agent_id:
            reasons.append("reviewer_agent_id does not match packet recipient.agent_id")
        if rec.get("channel") == "chat" or not packet.get("recovery", {}).get("channels"):
            reasons.append("chat channel without recovery tool cannot be assigned as approver (CR-14)")
        if packet["fencing"]["repo_sha"] != candidate_head_sha:
            reasons.append(
                f"candidate head SHA moved from {packet['fencing']['repo_sha']} to {candidate_head_sha}; new packet required (CR-10)"
            )

        for item in packet["items"]:
            if not item.get("requires_original"):
                continue
            cov = self.item_coverage(reviewer_agent_id, packet["packet_id"], item["ref"], item["size_bytes"])
            if not cov["complete"]:
                reasons.append(
                    f"incomplete review coverage for {item['item_id']} ({item['source_kind']}): "
                    f"{cov['covered_bytes']}/{cov['total_bytes']} bytes (CR-08)"
                )
        return not reasons, reasons


# ---------------------------------------------------------------------------
# 3. Seeded-Defect Canary & Reviewer Qualification Pool (CR-34, 58, 66, 68)
# ---------------------------------------------------------------------------

@dataclass
class QualificationRecord:
    reviewer_id: str
    model: str
    model_revision: str
    profile: str
    harness_version: str
    risk_levels: frozenset[str]
    critical_caught: int
    critical_seeded: int
    false_blocks: int
    clean_candidates: int
    findings_valid: int
    findings_total: int
    context_fidelity_probe_score: float
    finding_precision_wilson_lb: float
    qualified: bool
    reason: str


class ReviewerQualificationPool:
    """Manages reviewer qualification exams, seeded-defect canary scores (CR-34),
    SNR precision gates (CR-58, CR-68), automatic version-change requalification,
    and HIGH/CRITICAL approval eligibility (CR-66).
    """

    def __init__(self) -> None:
        self._records: dict[str, QualificationRecord] = {}
        self._gates = _load_gates()

    def evaluate_exam(
        self,
        *,
        reviewer_id: str,
        model: str,
        model_revision: str,
        profile: str,
        harness_version: str,
        risk_levels: set[str] | frozenset[str],
        critical_caught: int,
        critical_seeded: int,
        false_blocks: int,
        clean_candidates: int,
        findings_valid: int | None,
        findings_total: int | None,
    ) -> QualificationRecord:
        """Run reviewer qualification exam + seeded-defect canary evaluation (CR-34, CR-58, CR-68)."""
        ok, reason = quality_gate.reviewer_qualification(
            critical_caught=critical_caught,
            critical_seeded=critical_seeded,
            false_blocks=false_blocks,
            clean_candidates=clean_candidates,
            findings_valid=findings_valid,
            findings_total=findings_total,
            g=self._gates,
        )
        recall_lb, _ = quality_gate.wilson(critical_caught, critical_seeded) if critical_seeded > 0 else (0.0, 0.0)
        prec_lb, _ = (
            quality_gate.wilson(findings_valid, findings_total)
            if findings_valid is not None and findings_total
            else (0.0, 0.0)
        )
        rec = QualificationRecord(
            reviewer_id=reviewer_id,
            model=model,
            model_revision=model_revision,
            profile=profile,
            harness_version=harness_version,
            risk_levels=frozenset(risk_levels),
            critical_caught=critical_caught,
            critical_seeded=critical_seeded,
            false_blocks=false_blocks,
            clean_candidates=clean_candidates,
            findings_valid=findings_valid or 0,
            findings_total=findings_total or 0,
            context_fidelity_probe_score=recall_lb,
            finding_precision_wilson_lb=prec_lb,
            qualified=ok,
            reason=reason,
        )
        self._records[reviewer_id] = rec
        return rec

    def record_canary_probe(
        self,
        reviewer_id: str,
        *,
        canary_caught: int,
        canary_seeded: int,
    ) -> QualificationRecord:
        """Update seeded-defect canary probe score (CR-34). If below critical_recall_wilson_lb_min,
        immediately exclude the reviewer from the approver pool.
        """
        rec = self._records.get(reviewer_id)
        if rec is None:
            raise KeyError(f"unknown reviewer {reviewer_id}")
        probe_lb, _ = quality_gate.wilson(canary_caught, canary_seeded)
        min_lb = float(self._gates["reviewer_qualification"]["critical_recall_wilson_lb_min"])
        min_seeded = int(self._gates["reviewer_qualification"]["min_critical_seeded"])
        passed_canary = canary_seeded >= min_seeded and probe_lb >= min_lb
        updated = QualificationRecord(
            reviewer_id=rec.reviewer_id,
            model=rec.model,
            model_revision=rec.model_revision,
            profile=rec.profile,
            harness_version=rec.harness_version,
            risk_levels=rec.risk_levels,
            critical_caught=canary_caught,
            critical_seeded=canary_seeded,
            false_blocks=rec.false_blocks,
            clean_candidates=rec.clean_candidates,
            findings_valid=rec.findings_valid,
            findings_total=rec.findings_total,
            context_fidelity_probe_score=probe_lb,
            finding_precision_wilson_lb=rec.finding_precision_wilson_lb,
            qualified=rec.qualified and passed_canary,
            reason=rec.reason if passed_canary else f"canary probe recall LB {probe_lb:.3f} < {min_lb} (excluded from pool)",
        )
        self._records[reviewer_id] = updated
        return updated

    def active_approver_pool(
        self,
        *,
        risk: str,
        model_revision: str | None = None,
        profile: str | None = None,
        harness_version: str | None = None,
    ) -> list[str]:
        """Return reviewer_ids currently qualified for the given risk and runtime versions (CR-34)."""
        out: list[str] = []
        for rid, rec in sorted(self._records.items()):
            if not rec.qualified or risk not in rec.risk_levels:
                continue
            if model_revision is not None and rec.model_revision != model_revision:
                continue
            if profile is not None and rec.profile != profile:
                continue
            if harness_version is not None and rec.harness_version != harness_version:
                continue
            out.append(rid)
        return out

    def check_reviewer_eligibility(
        self,
        reviewer_id: str,
        *,
        risk: str,
        model_revision: str,
        profile: str,
        harness_version: str,
    ) -> tuple[bool, str]:
        """Verify reviewer qualification and requalification triggers (model/harness/profile change)."""
        rec = self._records.get(reviewer_id)
        if rec is None:
            return False, "reviewer has no qualification record"
        if not rec.qualified:
            return False, f"reviewer disqualified: {rec.reason}"
        if risk not in rec.risk_levels:
            return False, f"reviewer not qualified for risk level {risk}"
        if rec.model_revision != model_revision:
            return False, f"requalification required: model revision changed ({rec.model_revision} -> {model_revision})"
        if rec.harness_version != harness_version:
            return False, f"requalification required: harness version changed ({rec.harness_version} -> {harness_version})"
        if rec.profile != profile:
            return False, f"requalification required: context profile changed ({rec.profile} -> {profile})"
        return True, "qualified"

    def authorize_high_risk_merge(
        self,
        *,
        risk: str,
        reviewer_id: str,
        model_revision: str,
        profile: str,
        harness_version: str,
        verifier_trace: dict,
        human_approved: bool,
    ) -> tuple[bool, list[str]]:
        """Enforce full HIGH/CRITICAL merge verification (CR-66):
        qualified for current (risk, model_revision, profile, harness_version)
        + context-independent + spec-first sealed tests + counterexample-only feedback
        + human approval.
        """
        elig_ok, elig_reason = self.check_reviewer_eligibility(
            reviewer_id,
            risk=risk,
            model_revision=model_revision,
            profile=profile,
            harness_version=harness_version,
        )
        trace_with_qual = dict(verifier_trace, qualified=elig_ok)
        ind_ok, ind_reasons = review_policy.check_independence(risk, trace_with_qual, cfg=self._gates)
        reasons: list[str] = []
        if not elig_ok:
            reasons.append(elig_reason)
        for r in ind_reasons:
            if r not in reasons:
                reasons.append(r)
        if risk in ("HIGH", "CRITICAL") and not human_approved:
            reasons.append("HIGH/CRITICAL candidate requires explicit human approval")
        return not reasons, reasons
