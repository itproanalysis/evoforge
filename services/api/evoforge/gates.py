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


def apply_run(verdicts: list[Verdict], run: dict) -> list[Verdict]:
    """G2_REQUIRED = the full required suite actually executed and passed (p.36).

    Only a server run can turn "definitions present" into PASS; any failure, skip,
    timeout or empty suite is FAIL. Static FAILs (invalid test definitions) stay FAIL.
    """
    vis, held = run["visible"], run["heldout"]
    for v in verdicts:
        if v.gate != "G2_REQUIRED" or v.result == "FAIL":
            continue
        counts = f"visible {vis['pass']}/{vis['n']}, held-out {held['pass']}/{held['n']}"
        if vis.get("timed_out") or held.get("timed_out"):
            v.result, v.reason = "FAIL", f"required tests timed out ({counts})"
        elif vis["n"] == 0 or held["n"] == 0:
            v.result, v.reason = "FAIL", f"required suite missing or not collected ({counts})"
        elif vis["pass"] < vis["n"] or held["pass"] < held["n"]:
            v.result, v.reason = "FAIL", f"required tests failing ({counts})"
        else:
            v.result, v.reason = "PASS", f"required tests executed and passed ({counts})"
    return verdicts


def _check_counts(vis_pass: int, vis_n: int, held_pass: int, held_n: int) -> None:
    for name, val in (("vis_pass", vis_pass), ("vis_n", vis_n), ("held_pass", held_pass), ("held_n", held_n)):
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            raise ValueError(f"{name} must be a non-negative int, got {val!r}")
    if vis_pass > vis_n or held_pass > held_n:
        raise ValueError(f"pass count exceeds run count (visible {vis_pass}/{vis_n}, held-out {held_pass}/{held_n})")


def evaluate_full(diff: str, tests: list[dict], heldout_kinds: list[str],
                  vis_pass: int = 0, vis_n: int = 0, held_pass: int = 0, held_n: int = 0,
                  expected_literals: set[str] | None = None,
                  protected_globs: list[str] | None = None) -> list[Verdict]:
    """Static evidence checks; these verdicts do not attest to test execution."""
    _check_counts(vis_pass, vis_n, held_pass, held_n)
    ran = vis_n > 0 and held_n > 0
    qg = _qg()
    oracles, invalid = _test_oracles(tests, set(qg["oracle_strength"]["strong"]))
    oracle_ok = oracle_strength.gate(oracles, cfg=qg["oracle_strength"])
    heldout = reward_hack.heldout_ok(heldout_kinds or [], cfg=qg["reward_hack"])
    if invalid:
        reasons = ([heldout[1]] if not heldout[0] else []) + invalid
        heldout = (False, "; ".join(reasons))
    gap_r = (reward_hack.gap(vis_pass, vis_n, held_pass, held_n, cfg=qg["reward_hack"]) if ran
             else {"gap": 0.0, "lo": 0.0, "hi": 0.0, "flagged": False})
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
    if not ran and result != "FAIL":  # 0 runs is missing evidence, never a clean pass
        result = "INCONCLUSIVE"
        reasons = [*reasons, f"no execution evidence (visible n={vis_n}, held-out n={held_n})"]
    from evoforge.runner_diff_screen import report_tampering_risks
    report_risks = report_tampering_risks(diff, tests)
    if report_risks and result != "FAIL":
        result = "INCONCLUSIVE"
        reasons = [*reasons, "Runner report integrity requires review: " + ", ".join(report_risks)]
    v = [Verdict("GH_INTEGRITY", result, "; ".join(reasons) or "integrity clean")]
    v.append(Verdict("GC_COMPOSITION", "PASS", "single candidate: no combined wave"))
    definitions_present = bool(tests) and not invalid
    v.append(Verdict("G2_REQUIRED", "PASS" if definitions_present else "FAIL",
                     "test definitions present; execution unverified" if definitions_present
                     else "; ".join(invalid) or "no tests"))
    return v
