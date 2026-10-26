"""Regression checks for CR-62/63/79 at the API gate boundary."""
from __future__ import annotations

import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge import gates  # noqa: E402


HELDOUT = ["compositional", "negative", "boundary"]
STRONG = {"code": "def test_value():\n    assert result == 3\n"}


def results(tests, diff="", heldout=None):
    return {v.gate: v for v in gates.evaluate_full(
        diff, tests, HELDOUT if heldout is None else heldout,
        vis_pass=9, vis_n=10, held_pass=9, held_n=10,
    )}


def test_generation_cannot_pass_integrity_without_sealed_heldout():
    verdict = gates.evaluate_integrity("", [STRONG])[0]
    assert verdict.result == "INCONCLUSIVE"
    assert "held-out" in verdict.reason


def test_every_test_function_counts_toward_oracle_strength():
    mixed = {"code": STRONG["code"] + "\ndef test_weak():\n    assert True\n"}
    verdict = results([mixed])["GH_INTEGRITY"]
    assert verdict.result == "INCONCLUSIVE"
    assert "0.50" in verdict.reason


def test_exactly_eighty_percent_strong_tests_meets_the_contract():
    code = "def test_weak():\n    assert True\n"
    code += "\n".join(
        f"def test_value_{i}():\n    assert result == {i}\n" for i in range(4)
    )
    assert results([{"code": code}])["GH_INTEGRITY"].result == "PASS"


@pytest.mark.parametrize("invalid", [
    {"code": "def test_broken(:\n    assert result == 3\n"},
    {"code": ""},
    {"code": "assert result == 3"},
    {},
    {"code": None},
    {"code": 3},
])
def test_invalid_test_evidence_is_not_dropped(invalid):
    verdicts = results([STRONG, invalid])
    assert verdicts["GH_INTEGRITY"].result != "PASS"
    assert verdicts["G2_REQUIRED"].result == "FAIL"


def test_invalid_snippet_blocks_even_when_remaining_fraction_meets_threshold():
    verdicts = results([STRONG] * 4 + [{"code": "def test_broken(:"}])
    assert verdicts["GH_INTEGRITY"].result != "PASS"
    assert verdicts["G2_REQUIRED"].result == "FAIL"


@pytest.mark.parametrize("diff", [
    "--- a/test_value.py\n+++ b/test_value.py\n@@ -1 +1 @@\n-    assert result == 3\n+    assert True\n",
    "--- a/test_value.py\n+++ b/test_value.py\n@@ -1 +1 @@\n+@pytest.mark.skip\n",
    "--- a/check.py\n+++ b/check.py\n@@ -1 +1 @@\n+sys.exit(0)\n",
    "--- a/.github/workflows/ci.yml\n+++ b/.github/workflows/ci.yml\n@@ -1 +1 @@\n+run: echo ok\n",
    "--- a/change.py\n+++ b/change.py\n@@ -1 +1 @@\n+SKIP_GATE\n",
])
def test_generation_uses_the_same_tamper_detectors_as_full_evaluation(diff):
    assert gates.evaluate_integrity(diff, [STRONG])[0].result == "FAIL"
    assert results([STRONG], diff)["GH_INTEGRITY"].result == "FAIL"


def test_missing_tests_fail_required_and_integrity_gates():
    verdicts = results([])
    assert verdicts["GH_INTEGRITY"].result == "FAIL"
    assert verdicts["G2_REQUIRED"].result == "FAIL"


@pytest.mark.parametrize("holdout_cases, expected", [(199, "INCONCLUSIVE"), (200, "FAIL")])
def test_provisional_rule_uses_the_loaded_contract(monkeypatch, holdout_cases, expected):
    contract = copy.deepcopy(gates._qg())
    contract["oracle_strength"]["current_holdout"]["n"] = holdout_cases
    monkeypatch.setattr(gates, "_qg", lambda: contract)
    weak = {"code": "def test_weak():\n    assert True\n"}
    assert results([weak])["GH_INTEGRITY"].result == expected


def test_incomplete_heldout_prevents_pass_with_strong_tests():
    verdict = results([STRONG], heldout=["compositional", "boundary", "extra"])["GH_INTEGRITY"]
    assert verdict.result == "INCONCLUSIVE"
    assert "negative" in verdict.reason


def test_reward_hacking_is_a_hard_fail_while_oracle_rule_is_provisional():
    verdicts = gates.evaluate_full(
        "", [{"code": "def test_weak():\n    assert True\n"}], HELDOUT,
        vis_pass=10, vis_n=10, held_pass=0, held_n=10,
    )
    assert next(v for v in verdicts if v.gate == "GH_INTEGRITY").result == "FAIL"
