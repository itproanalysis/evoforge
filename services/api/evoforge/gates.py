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
    """Generation has no sealed held-out evidence, so it cannot earn PASS yet."""
    return [v for v in evaluate_full(diff, tests, []) if v.gate == "GH_INTEGRITY"]


def _test_oracles(tests: list[dict], strong: set[str]) -> tuple[list[oracle_strength.TestOracle], list[str]]:
    """Count every test; retain malformed or empty snippets as missing evidence."""
    oracles = []
    invalid = []
    for index, test in enumerate(tests, 1):
        code = test.get("code") if isinstance(test, dict) else None
        found = []
        if isinstance(code, str) and code.strip():
            try:
                found = analyze(code)
            except SyntaxError:
                pass
        if found:
            oracles.extend(oracle_strength.TestOracle(t.name, t.strength, t.strength in strong) for t in found)
        else:
            invalid.append(f"test snippet {index}: missing or invalid Python test definitions")
            oracles.append(oracle_strength.TestOracle(f"snippet_{index}", "none", False))
    return oracles, invalid


def evaluate_full(diff: str, tests: list[dict], heldout_kinds: list[str],
                  vis_pass: int = 0, vis_n: int = 1, held_pass: int = 0, held_n: int = 1,
                  expected_literals: set[str] | None = None,
                  protected_globs: list[str] | None = None) -> list[Verdict]:
    """Static evidence checks; these verdicts do not attest to test execution."""
    qg = _qg()
    oracles, invalid = _test_oracles(tests, set(qg["oracle_strength"]["strong"]))
    oracle_ok = oracle_strength.gate(oracles, cfg=qg["oracle_strength"])
    heldout = reward_hack.heldout_ok(heldout_kinds or [], cfg=qg["reward_hack"])
    if invalid:
        reasons = ([heldout[1]] if not heldout[0] else []) + invalid
        heldout = (False, "; ".join(reasons))
    gap_r = reward_hack.gap(vis_pass, max(vis_n, 1), held_pass, max(held_n, 1), cfg=qg["reward_hack"])
    added = "\n".join(ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    lookup = reward_hack.lookup_table(added, expected_literals or set(), cfg=qg["reward_hack"])
    tamper = reward_hack.tampering(diff, protected_globs or ["tests/**", ".github/**", "policy/**"])
    if "FIXME_BYPASS" in diff or "SKIP_GATE" in diff:  # legacy tripwire
        tamper = tamper + [{"kind": "legacy_tamper_flag", "file": None}]
    hack = reward_hack.verdict(gap_r, lookup, tamper)
    result, reasons = integrity_gate.decide(oracle_ok, heldout, hack, g=qg)
    if not tests:
        result = "FAIL"
        reasons = ["no tests", *reasons]
    v = [Verdict("GH_INTEGRITY", result, "; ".join(reasons) or "integrity clean")]
    v.append(Verdict("GC_COMPOSITION", "PASS", "single candidate: no combined wave"))
    definitions_present = bool(tests) and not invalid
    v.append(Verdict("G2_REQUIRED", "PASS" if definitions_present else "FAIL",
                     "test definitions present; execution unverified" if definitions_present
                     else "; ".join(invalid) or "no tests"))
    return v
