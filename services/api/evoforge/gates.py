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
import integrity_gate  # noqa: E402
import reward_hack  # noqa: E402
import oracle_strength  # noqa: E402

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


def evaluate_full(diff: str, tests: list[dict], heldout_kinds: list[str],
                  vis_pass: int = 0, vis_n: int = 1, held_pass: int = 0, held_n: int = 1,
                  expected_literals: set[str] | None = None,
                  protected_globs: list[str] | None = None) -> list[Verdict]:
    """Full gate set: GH_INTEGRITY (oracle+heldout+reward-hack via integrity_gate.decide),
    GC_COMPOSITION (PASS stub for single candidate), G2_REQUIRED (tests present)."""
    qg = _qg()
    codes = [t.get("code", "") for t in tests]
    oracles = []
    for c in codes:
        try:
            got = analyze(c)
            oracles += [type("O", (), {"name": g.name, "strong": g.strong})() for g in got]
        except SyntaxError:
            pass
    oracle_ok = oracle_strength.gate(
        [oracle_strength.TestOracle(getattr(o, "name", "t"), "value_equality" if o.strong else "none", bool(o.strong))
         for o in oracles]) if oracles else (False, "no tests")
    heldout = reward_hack.heldout_ok(heldout_kinds or [])
    gap_r = reward_hack.gap(vis_pass, max(vis_n, 1), held_pass, max(held_n, 1))
    added = "\n".join(ln[1:] for ln in diff.splitlines() if ln.startswith("+"))
    lookup = reward_hack.lookup_table(added, expected_literals or set())
    tamper = reward_hack.tampering(diff, protected_globs or ["tests/**", ".github/**", "policy/**"])
    if "FIXME_BYPASS" in diff or "SKIP_GATE" in diff:  # legacy tripwire
        tamper = tamper + [{"kind": "legacy_tamper_flag", "file": None}]
    hack = reward_hack.verdict(gap_r, lookup, tamper)
    result, reasons = integrity_gate.decide(oracle_ok, heldout, hack)
    v = [Verdict("GH_INTEGRITY", result, "; ".join(reasons) or "integrity clean")]
    v.append(Verdict("GC_COMPOSITION", "PASS", "single candidate: no combined wave"))
    v.append(Verdict("G2_REQUIRED", "PASS" if codes else "FAIL",
                     "required tests present" if codes else "no tests"))
    return v
