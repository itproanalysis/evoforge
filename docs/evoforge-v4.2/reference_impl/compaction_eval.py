"""Boundary-local evaluation of context compaction (EvoForge v4.2, executable spec for CR-75).

Source idea (ADOPT as method): arXiv:2608.06503 — repeated compression weakens recent context and
raises blocked actions, repeated exploration and run-to-run instability; evaluate each compaction
EVENT with paired continuations from the same state instead of only the end-of-session score.

Unit: one compaction boundary b in session s. From the same snapshot, run a continuation of N
turns with the uncompacted context (baseline) and with the compacted/folded context (candidate).
Record per continuation: success within N turns (0/1), repeated-exploration count, blocked-action
count. Cluster = session (boundaries of one session are correlated).

Decision (all must hold):
  * success: paired non-inferiority with quality_gate.paired_noninferiority at the tier's delta
  * repeated exploration: cluster-bootstrap ratio upper bound <= max_repeat_ratio_ub
  * blocked actions:      cluster-bootstrap ratio upper bound <= max_blocked_ratio_ub
  * instability: share of boundaries where candidate repeats DISAGREE (seeds differ) does not exceed
    the baseline's share by more than max_instability_increase
"""
from __future__ import annotations

from dataclasses import dataclass

import quality_gate as qg


@dataclass(frozen=True)
class Boundary:
    session_id: str
    boundary_id: str
    base_success: list[int]          # one entry per seed
    cand_success: list[int]
    base_repeats: float
    cand_repeats: float
    base_blocked: float
    cand_blocked: float


def _unstable(xs: list[int]) -> bool:
    return len(set(xs)) > 1


def decide(boundaries: list[Boundary], tier: str, g: dict | None = None) -> dict:
    g = g or qg.load_gates()
    ce = g["compaction_eval"]
    delta = g["tiers"][tier]["delta_verified_fix_rate"]
    pairs = []
    for b in boundaries:
        if len(b.base_success) != len(b.cand_success):
            raise ValueError("paired seeds required")
        pairs += [(b.session_id, x, y) for x, y in zip(b.base_success, b.cand_success)]
    ni = qg.paired_noninferiority(pairs, delta)
    _, _, rep_hi = qg.ratio_ci([(b.session_id, b.base_repeats + 1, b.cand_repeats + 1) for b in boundaries])
    _, _, blk_hi = qg.ratio_ci([(b.session_id, b.base_blocked + 1, b.cand_blocked + 1) for b in boundaries])
    multi = [b for b in boundaries if len(b.base_success) > 1]
    inst_base = sum(_unstable(b.base_success) for b in multi) / len(multi) if multi else 0.0
    inst_cand = sum(_unstable(b.cand_success) for b in multi) / len(multi) if multi else 0.0
    reasons = []
    if not ni.passed:
        reasons.append(f"success: {ni.reason}")
    if rep_hi > ce["max_repeat_ratio_ub"]:
        reasons.append(f"repeated exploration ratio UB {rep_hi:.3f} > {ce['max_repeat_ratio_ub']}")
    if blk_hi > ce["max_blocked_ratio_ub"]:
        reasons.append(f"blocked actions ratio UB {blk_hi:.3f} > {ce['max_blocked_ratio_ub']}")
    if inst_cand - inst_base > ce["max_instability_increase"]:
        reasons.append(f"instability +{inst_cand - inst_base:.3f} > {ce['max_instability_increase']}")
    if len({b.session_id for b in boundaries}) < ce["min_sessions"]:
        reasons.append(f"UNDERPOWERED: < {ce['min_sessions']} sessions")
    return {"passed": not reasons, "reasons": reasons, "noninferiority": ni, "repeat_ratio_ub": rep_hi,
            "blocked_ratio_ub": blk_hi, "instability_base": inst_base, "instability_cand": inst_cand}
