"""GH_INTEGRITY gate decision (EvoForge v4.2, executable spec).

Combines the three integrity checks into the single gate result recorded in core.gate_results:
  * reward-hack / tamper flags (reward_hack.verdict)      -> FAIL (no provisional softening)
  * held-out set incomplete (reward_hack.heldout_ok)        -> INCONCLUSIVE (evaluation setup problem)
  * oracle strength below threshold (oracle_strength.gate)  -> FAIL once the classifier's human-labeled
    holdout reaches `holdout_min_cases_for_sole_block`; until then INCONCLUSIVE (blocks merge, but
    routes to exception approval / test strengthening instead of a hard fail)
"""
from __future__ import annotations

import json
import os

_GATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts", "quality_gates.json")


def decide(oracle_ok: tuple[bool, str], heldout: tuple[bool, str], hack: tuple[bool, list[str]],
           holdout_cases: int | None = None, g: dict | None = None) -> tuple[str, list[str]]:
    if g is None:
        with open(_GATES, encoding="utf-8") as fh:
            g = json.load(fh)
    o = g["oracle_strength"]
    n = o["current_holdout"]["n"] if holdout_cases is None else holdout_cases
    flagged, why = hack
    if flagged:
        return "FAIL", why
    reasons: list[str] = []
    result = "PASS"
    if not heldout[0]:
        result, reasons = "INCONCLUSIVE", reasons + [f"held-out: {heldout[1]}"]
    if not oracle_ok[0]:
        if n >= o["holdout_min_cases_for_sole_block"]:
            return "FAIL", reasons + [f"oracle_strength: {oracle_ok[1]}"]
        result, reasons = "INCONCLUSIVE", reasons + [f"oracle_strength (provisional, holdout n={n}): {oracle_ok[1]}"]
    return result, reasons
