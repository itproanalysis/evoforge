"""Deterministic gates — thin wrapper over docs/evoforge-v4.2/reference_impl.

Contracts win over docs. Numbers come from contracts/quality_gates.json v1.2 only.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

_REF = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs", "evoforge-v4.2", "reference_impl")
import sys

sys.path.insert(0, os.path.abspath(_REF))

from oracle_ast import analyze  # noqa: E402

_QG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "docs", "evoforge-v4.2", "contracts", "quality_gates.json"
)


def _qg():
    with open(os.path.abspath(_QG_PATH), encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Verdict:
    gate: str
    result: str
    reason: str = ""


def evaluate_integrity(diff: str, tests: list[dict]) -> list[Verdict]:
    """GH_INTEGRITY: oracle strength + reward-hack flags. Provisional rule D-054."""
    qg = _qg()
    strong = set(qg["oracle_strength"]["strong"])
    codes = [t.get("code", "") for t in tests]
    if not codes:
        return [Verdict("GH_INTEGRITY", "FAIL", "no tests")]
    kinds: list[str] = []
    for c in codes:
        try:
            got = analyze(c)
            kinds.append(got[0].strength if got else "none")
        except SyntaxError:
            kinds.append("none")
    strong_frac = sum(1 for k in kinds if k in strong) / len(kinds)
    min_frac = qg["oracle_strength"]["min_strong_fraction_new_tests"]
    # tamper flags always FAIL (independent of provisional rule)
    if "FIXME_BYPASS" in diff or "SKIP_GATE" in diff:
        return [Verdict("GH_INTEGRITY", "FAIL", "tamper flag")]
    if strong_frac < min_frac:
        # holdout n=20 < 200 -> INCONCLUSIVE (blocks merge, needs exception or more tests)
        return [Verdict("GH_INTEGRITY", "INCONCLUSIVE", f"oracle_strength {strong_frac:.2f} < {min_frac} (provisional, D-054)")]
    return [Verdict("GH_INTEGRITY", "PASS", f"strong {strong_frac:.2f}")]
