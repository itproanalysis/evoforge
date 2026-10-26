"""Tests for quality_gate.py against contracts/quality_gates.json.
Run: python3 -I reference_impl/test_quality_gate.py -v
"""
from __future__ import annotations

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quality_gate as q  # noqa: E402

G = q.load_gates()


def make_pairs(n_tasks: int, seeds: int, flip_down: float, flip_up: float, seed: int = 1):
    """Correlated paired outcomes: candidate equals baseline except for flips."""
    rng = random.Random(seed)
    out = []
    for t in range(n_tasks):
        p_task = rng.uniform(0.3, 0.9)
        for _ in range(seeds):
            base = int(rng.random() < p_task)
            cand = base
            if base == 1 and rng.random() < flip_down:
                cand = 0
            elif base == 0 and rng.random() < flip_up:
                cand = 1
            out.append((f"task{t:04d}", base, cand))
    return out


def critical(n: int, miss_arm_only: int = 0):
    rows = [(f"d{i}", 1, 1) for i in range(n - miss_arm_only)]
    rows += [(f"m{i}", 1, 0) for i in range(miss_arm_only)]
    return rows


class SampleSize(unittest.TestCase):
    def test_contract_numbers_match_formula(self):
        for tier in ("A_canary", "B_default"):
            t = G["tiers"][tier]
            self.assertEqual(q.required_pairs(0.10, t["delta_verified_fix_rate"], G["alpha_one_sided"], G["power"]),
                             t["pairs_required_at_p_discordant_0.10"], tier)


class NonInferiority(unittest.TestCase):
    def test_equivalent_arm_passes_tier_a(self):
        pairs = make_pairs(200, 3, 0.05, 0.08)
        r = q.paired_noninferiority(pairs, G["tiers"]["A_canary"]["delta_verified_fix_rate"])
        self.assertTrue(r.passed, r.reason)

    def test_degraded_arm_fails(self):
        pairs = make_pairs(300, 3, 0.20, 0.02)
        r = q.paired_noninferiority(pairs, 0.05)
        self.assertFalse(r.passed)
        self.assertTrue(r.reason.startswith("FAIL"), r.reason)

    def test_small_sample_is_underpowered_not_pass(self):
        pairs = make_pairs(15, 3, 0.05, 0.05)
        r = q.paired_noninferiority(pairs, 0.02)
        self.assertFalse(r.passed)
        self.assertTrue(r.reason.startswith("UNDERPOWERED"), r.reason)

    def test_deterministic(self):
        pairs = make_pairs(120, 3, 0.05, 0.05)
        self.assertEqual(q.paired_noninferiority(pairs, 0.05), q.paired_noninferiority(pairs, 0.05))

    def test_cluster_bootstrap_is_wider_than_naive(self):
        """Repeats of one task are correlated; resampling tasks must not understate uncertainty."""
        rng = random.Random(3)
        pairs = []
        for t in range(60):
            d = rng.choice([-1, 0, 0, 0, 1])
            for _ in range(5):  # perfectly correlated repeats
                pairs.append((f"t{t}", 1 if d <= 0 else 0, 1 if d >= 0 else 0))
        clustered = q.paired_noninferiority(pairs, 0.05)
        naive = q.paired_noninferiority([(f"p{i}", b, c) for i, (_, b, c) in enumerate(pairs)], 0.05)
        self.assertLess(clustered.lower_bound, naive.lower_bound)


class Safety(unittest.TestCase):
    def test_one_arm_only_critical_miss_fails(self):
        ok, why = q.safety_gate(critical(150, miss_arm_only=1), 0, 0, G)
        self.assertFalse(ok)
        self.assertIn("missed by candidate", why[0])

    def test_escaped_regression_fails(self):
        ok, _ = q.safety_gate(critical(150), 1, 0, G)
        self.assertFalse(ok)

    def test_too_few_seeded_defects_fails(self):
        ok, why = q.safety_gate(critical(40), 0, 0, G)
        self.assertFalse(ok)
        self.assertIn("seeded", why[0])

    def test_clean_passes(self):
        ok, why = q.safety_gate(critical(150), 0, 0, G)
        self.assertTrue(ok, why)


class Promotion(unittest.TestCase):
    def test_tier_a_pass_but_tier_b_needs_more(self):
        vfr = make_pairs(100, 3, 0.04, 0.05, seed=5)
        rec = make_pairs(100, 3, 0.04, 0.05, seed=6)
        a = q.promotion_decision("A_canary", vfr, rec, critical(120), 0, 0)
        b = q.promotion_decision("B_default", vfr, rec, critical(120), 0, 0)
        self.assertTrue(a["passed"], a)
        self.assertFalse(b["passed"])
        self.assertFalse(b["min_tasks"]["passed"])

    def test_cost_must_be_significantly_lower(self):
        vfr = make_pairs(100, 3, 0.03, 0.03, seed=7)
        flat = [(c, 1.0, 1.0) for c, _, _ in vfr]           # no saving -> UB >= 1
        cheaper = [(c, 1.0, 0.7) for c, _, _ in vfr]        # clear saving
        self.assertFalse(q.promotion_decision("A_canary", vfr, vfr, critical(120), 0, 0, flat)["passed"])
        self.assertTrue(q.promotion_decision("A_canary", vfr, vfr, critical(120), 0, 0, cheaper)["passed"])


class Runtime(unittest.TestCase):
    def test_critical_miss_disables(self):
        self.assertEqual(q.codec_runtime_decision(300, 0, 1, 10000, 100)[0], "DISABLE")

    def test_high_miss_rate_disables(self):
        self.assertEqual(q.codec_runtime_decision(400, 12, 0, 10000, 100)[0], "DISABLE")

    def test_low_miss_rate_keeps(self):
        self.assertEqual(q.codec_runtime_decision(400, 1, 0, 10000, 100)[0], "KEEP")

    def test_insufficient_audit_alerts(self):
        self.assertEqual(q.codec_runtime_decision(20, 0, 0, 1000, 10)[0], "ALERT_INSUFFICIENT_AUDIT")

    def test_fallbacks_are_efficiency_not_safety(self):
        self.assertEqual(q.codec_runtime_decision(200, 0, 0, 600, 400)[0], "REVIEW_EFFICIENCY")


class Reviewer(unittest.TestCase):
    def test_97_of_100_qualifies(self):
        self.assertTrue(q.reviewer_qualification(97, 100, 5, 100, 70, 120)[0])

    def test_95_of_100_does_not(self):
        self.assertFalse(q.reviewer_qualification(95, 100, 5, 100, 70, 120)[0])

    def test_false_blocks_limit(self):
        self.assertFalse(q.reviewer_qualification(99, 100, 15, 100, 70, 120)[0])

    def test_noisy_reviewer_does_not_qualify(self):
        # perfect recall but most findings are noise (CR-Bench SNR failure mode)
        ok, why = q.reviewer_qualification(100, 100, 5, 100, 30, 200)
        self.assertFalse(ok)
        self.assertIn("precision", why)

    def test_missing_precision_evidence_does_not_qualify(self):
        self.assertFalse(q.reviewer_qualification(99, 100, 5, 100)[0])


class Speedup(unittest.TestCase):
    def test_claim_uses_lower_bound(self):
        rng = random.Random(11)
        rows = [(f"w{i}", 10.0, 10.0 * rng.uniform(2.0, 4.5)) for i in range(40)]
        r = q.speedup_claim(rows, "M5_ga")
        self.assertLess(r["lo"], r["ratio"])
        self.assertIn(f"{r['lo']:.2f}배 이상", r["claimable_text"])
        self.assertEqual(r["met"], r["lo"] >= 3.0)


if __name__ == "__main__":
    unittest.main()
