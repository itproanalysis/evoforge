"""Candidate selection for RACE_2 / multi-candidate runs (EvoForge v4.1, executable spec).

Adopted (TRIAL):
  * arXiv:2607.00990 (SWE-Doctor): multi-faceted reproduction tests are the strongest cheap signal.
  * arXiv:2604.16529: structured candidate summaries + recursive tournament voting (RTV).
  * arXiv:2610.00972 (VeriHarness): resolve disagreement with execution, challenge consensus.

Rule: execution evidence decides; an LLM judge only breaks ties between candidates whose
evidence is indistinguishable (within `tie_epsilon`). Gates and reward-hack flags are hard
filters, never weights. Stdlib only, deterministic given a deterministic judge.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from quality_gate import wilson

_GATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts", "quality_gates.json")


def _cfg() -> dict:
    with open(_GATES, encoding="utf-8") as fh:
        return json.load(fh)["selection"]


@dataclass(frozen=True)
class Candidate:
    cid: str
    gates_pass: bool
    reward_hack_flag: bool
    repro_passed: int
    repro_total: int
    heldout_passed: int
    heldout_total: int
    diff_bytes: int
    behaviour_sig: str = ""     # hash of outputs on the shared probe set (for agreement)

    @property
    def full_pass(self) -> bool:
        return (self.gates_pass and not self.reward_hack_flag and self.repro_total > 0
                and self.repro_passed == self.repro_total and self.heldout_passed == self.heldout_total)

    def evidence(self) -> tuple[float, float]:
        return wilson(self.repro_passed, self.repro_total)[0], wilson(self.heldout_passed, self.heldout_total)[0]


def eligible(cands: list[Candidate]) -> list[Candidate]:
    return [c for c in cands if c.gates_pass and not c.reward_hack_flag]


def rank(cands: list[Candidate]) -> list[Candidate]:
    return sorted(eligible(cands), key=lambda c: (-c.evidence()[0], -c.evidence()[1], c.diff_bytes, c.cid))


def tournament(cands: list[Candidate], judge, votes: int = 3) -> Candidate:
    """Recursive pairwise tournament. judge(a, b, vote_index) -> winning cid. Majority of `votes`.
    Deterministic bracket: sorted by cid, odd one out gets a bye."""
    field = sorted(cands, key=lambda c: c.cid)
    while len(field) > 1:
        nxt = []
        for i in range(0, len(field) - 1, 2):
            a, b = field[i], field[i + 1]
            wins_a = sum(judge(a, b, v) == a.cid for v in range(votes))
            nxt.append(a if wins_a * 2 > votes else b)
        if len(field) % 2:
            nxt.append(field[-1])
        field = nxt
    return field[0]


def select(cands: list[Candidate], judge=None, cfg: dict | None = None) -> tuple[Candidate | None, str]:
    cfg = cfg or _cfg()
    ranked = rank(cands)
    if not ranked:
        return None, "no eligible candidate (gates failed or reward-hack flagged)"
    top = ranked[0]
    eps = cfg["tie_epsilon"]
    tied = [c for c in ranked
            if abs(c.evidence()[0] - top.evidence()[0]) <= eps and abs(c.evidence()[1] - top.evidence()[1]) <= eps]
    if len(tied) == 1 or judge is None:
        return top, "execution evidence" if len(tied) == 1 else "evidence tie, no judge: smallest diff"
    return tournament(tied, judge, cfg["tournament_votes"]), f"evidence tie among {len(tied)}: tournament"


def should_sample_more(cands: list[Candidate], risk: str, cfg: dict | None = None) -> tuple[bool, str]:
    """Adaptive k: stop early when evidence is already decisive, keep sampling while it is not."""
    a = (cfg or _cfg())["adaptive_k"]
    k = len(cands)
    if k < a["min_k"]:
        return True, "below min_k"
    if k >= a["max_k"]:
        return False, "max_k reached"
    full = [c for c in cands if c.full_pass]
    if full and risk in a["stop_on_first_full_pass_if_risk_in"]:
        return False, f"full pass at risk {risk}"
    sigs: dict[str, int] = {}
    for c in full:
        sigs[c.behaviour_sig] = sigs.get(c.behaviour_sig, 0) + 1
    if sigs and max(sigs.values()) >= a["stop_if_agreeing_full_pass_at_least"]:
        return False, "agreeing full passes"
    if len(sigs) >= 2:
        return True, "full passes disagree in behaviour: challenge consensus with another sample"
    return True, "no decisive evidence yet"
