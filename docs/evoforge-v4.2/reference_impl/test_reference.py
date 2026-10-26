"""Executable acceptance tests for the reference codecs/gate/cost model.

Run:  python3 -I -m unittest -v test_reference   (from this directory)
Maps to contracts/Context_Quality_Test_Matrix_v3.6.md IDs in each docstring.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cost_model  # noqa: E402
import fidelity_gate as fg  # noqa: E402
import json_codec  # noqa: E402
import junit_codec  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load(name: str) -> bytes:
    with open(os.path.join(FIX, name), "rb") as fh:
        return fh.read()


def receipt(b: bytes, ok: bool = True) -> fg.VaultReceipt:
    return fg.VaultReceipt(hashlib.sha256(b).hexdigest(), len(b), ok)


class JUnit(unittest.TestCase):
    def setUp(self):
        self.orig = load("junit_report.xml")
        self.view = junit_codec.encode(self.orig)

    def test_pass_and_gain(self):
        """CR-01/CR-03 happy path: all invariants pass, view keeps every failure."""
        ok, checks = fg.gate("test.junit", self.orig, self.view, receipt(self.orig))
        self.assertTrue(ok, [c for c in checks if not c.passed])
        self.assertIn("failures=2 errors=1", self.view)
        self.assertLess(fg.est_tokens(self.view), 0.2 * fg.est_tokens(self.orig))

    def test_deterministic(self):
        """CR-27: byte-identical re-encode (cache-stable prefix)."""
        self.assertEqual(self.view, junit_codec.encode(self.orig))

    def test_dropped_failure_rejected(self):
        """CR-09: a failing case removed from the view fails T1/T2/T5."""
        lines = self.view.splitlines(keepends=True)
        i = next(k for k, ln in enumerate(lines) if ln.startswith("#case "))
        j = next(k for k in range(i + 1, len(lines)) if lines[k].startswith(("#case ", "#omitted ")))
        tampered = "".join(lines[:i] + lines[j:])
        ok, checks = fg.gate("test.junit", self.orig, tampered, receipt(self.orig), encode=lambda _b: tampered)
        failed = {c.invariant_id for c in checks if not c.passed}
        self.assertFalse(ok)
        self.assertIn("T2", failed)

    def test_zeroed_counts_rejected(self):
        """CR-09: 'looks green' summary (failures=0) is rejected."""
        tampered = self.view.replace("failures=2", "failures=0")
        ok, checks = fg.gate("test.junit", self.orig, tampered, receipt(self.orig), encode=lambda _b: tampered)
        self.assertFalse(ok)
        self.assertIn("T1", {c.invariant_id for c in checks if not c.passed})

    def test_paraphrased_message_rejected(self):
        """CR-03: assertion text must be verbatim, not paraphrased."""
        tampered = self.view.replace("expected 200 but was 500", "expected success but failed")
        ok, checks = fg.gate("test.junit", self.orig, tampered, receipt(self.orig), encode=lambda _b: tampered)
        self.assertFalse(ok)
        self.assertIn("T3", {c.invariant_id for c in checks if not c.passed})

    def test_vault_not_verified_blocks(self):
        """CR-02: original not stored/read-back-verified => U1 fails => no lossy emit."""
        ok, checks = fg.gate("test.junit", self.orig, self.view, receipt(self.orig, ok=False))
        self.assertFalse(ok)
        ok2, _ = fg.gate("test.junit", self.orig, self.view, None)
        self.assertFalse(ok2)

    def test_nondeterministic_codec_rejected(self):
        """CR-27: a codec that varies between calls fails U3."""
        rnd = random.Random(7)

        def flaky(b: bytes) -> str:
            return junit_codec.encode(b) + ("" if rnd.random() < 0.5 else " ")

        v = flaky(self.orig)
        ok, checks = fg.gate("test.junit", self.orig, v, receipt(self.orig), encode=flaky)
        # either the view differs from a re-encode, or two re-encodes differ
        self.assertFalse(ok and all(flaky(self.orig) == v for _ in range(8)))

    def test_entity_expansion_rejected(self):
        """CR-04/CR-11: DOCTYPE/ENTITY input is not parsed -> RAW(PARSE_FAILED)."""
        bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><testsuite><testcase name="&a;"/></testsuite>'
        with self.assertRaises(junit_codec.CodecError):
            junit_codec.encode(bomb)

    def test_no_gain_rejected(self):
        """CR-05: tiny report where the view is not smaller => U2 fails."""
        tiny = b'<testsuite name="s"><testcase name="t"/></testsuite>'
        ok, checks = fg.gate("test.junit", tiny, junit_codec.encode(tiny), receipt(tiny))
        self.assertFalse(ok)
        self.assertIn("U2", {c.invariant_id for c in checks if not c.passed})

    def test_secret_in_view_rejected(self):
        """CR-19: secret-like material in a view fails U4 (ingest guard should have blocked earlier)."""
        tampered = self.view + "#frame AKIAABCDEFGHIJKLMNOP\n"
        ok, checks = fg.gate("test.junit", self.orig, tampered, receipt(self.orig), encode=lambda _b: tampered)
        self.assertFalse(ok)
        self.assertIn("U4", {c.invariant_id for c in checks if not c.passed})


class Json(unittest.TestCase):
    RULE = json_codec.KeepRule("/state", ("FAILED",))

    def setUp(self):
        self.orig = load("api_result.json")
        self.enc = lambda b: json_codec.encode(b, self.RULE)
        self.view = self.enc(self.orig)

    def test_pass(self):
        ok, checks = fg.gate("json.api", self.orig, self.view, receipt(self.orig), encode=self.enc,
                             required_pointers=["/status", "/items/0/id", "/meta/request_id", "/items/13/id"],
                             keep_rule=self.RULE)
        self.assertTrue(ok, [c for c in checks if not c.passed])

    def test_failed_records_beyond_head_kept(self):
        """J5: rule-matching elements beyond the head (FAILED orders 13/26/39) survive truncation."""
        v = json.loads(self.view)
        self.assertEqual(sorted(v["items"][-1]["$kept"], key=int), ["13", "26", "39"])

    def test_truncation_without_rule_rejected_in_safe(self):
        """J5/CR-03: SAFE forbids array truncation without a registered keep rule (would silently drop FAILED rows)."""
        plain = json_codec.encode(self.orig)
        ok, checks = fg.gate("json.api", self.orig, plain, receipt(self.orig), encode=json_codec.encode)
        self.assertFalse(ok)
        self.assertIn("J5", {c.invariant_id for c in checks if not c.passed})

    def test_rule_violation_rejected(self):
        """J5: a view that drops a rule-matching element is rejected even if counts are adjusted."""
        v = json.loads(self.view)
        m = v["items"][-1]
        del m["$kept"]["26"]
        m["$omitted"] += 1
        tampered = json.dumps(v)
        ok, checks = fg.gate("json.api", self.orig, tampered, receipt(self.orig), encode=lambda _b: tampered, keep_rule=self.RULE)
        self.assertIn("J5", {c.invariant_id for c in checks if not c.passed})

    def test_value_change_rejected(self):
        """J2: a leaf changed in the view is rejected."""
        v = json.loads(self.view)
        v["status"] = "ok"
        tampered = json.dumps(v)
        ok, checks = fg.gate("json.api", self.orig, tampered, receipt(self.orig), encode=lambda _b: tampered, min_gain=0.0, keep_rule=self.RULE)
        self.assertIn("J2", {c.invariant_id for c in checks if not c.passed})

    def test_required_pointer_in_omitted_tail_rejected(self):
        """J3: a required pointer that the codec dropped fails the gate."""
        ok, checks = fg.gate("json.api", self.orig, self.view, receipt(self.orig), encode=self.enc,
                             required_pointers=["/items/40/id"], keep_rule=self.RULE)
        self.assertFalse(ok)
        self.assertIn("J3", {c.invariant_id for c in checks if not c.passed})

    def test_wrong_omission_count_rejected(self):
        """J4: omission marker count must equal the real number of omitted elements."""
        tampered = self.view.replace('"$omitted":42', '"$omitted":4')
        self.assertNotEqual(tampered, self.view)
        ok, checks = fg.gate("json.api", self.orig, tampered, receipt(self.orig), encode=lambda _b: tampered, keep_rule=self.RULE)
        self.assertIn("J4", {c.invariant_id for c in checks if not c.passed})

    def test_unknown_kind_is_raw(self):
        """CR-04: no gate for kind => RAW(UNSUPPORTED_TYPE)."""
        ok, checks = fg.gate("html", b"<p>x</p>", "x", receipt(b"<p>x</p>"))
        self.assertFalse(ok)
        self.assertEqual(checks[0].invariant_id, "U0")


class Cost(unittest.TestCase):
    def test_correct_baseline_is_cached_raw(self):
        """CR-12/CR-29: savings are measured vs A_RAW (provider cache), not vs uncached."""
        p = cost_model.Params()
        a0 = cost_model.session_cost(p, False, False)
        a = cost_model.session_cost(p, False, True)
        c = cost_model.session_cost(p, True, True)
        self.assertLess(a, a0)
        self.assertGreater(c / a, c / a0)  # vs-uncached overstates the saving

    def test_compression_without_cache_can_lose_to_cache_only(self):
        """CR-12: CACHE before COMPRESS — compressed-uncached costs more than raw-cached here."""
        p = cost_model.Params()
        self.assertGreater(cost_model.session_cost(p, True, False), cost_model.session_cost(p, False, True))

    def test_retrieval_break_even_exists(self):
        """CR-28: enough retrieval turns make RECOVERABLE more expensive than RAW."""
        be = cost_model.break_even_retrievals(cost_model.Params())
        self.assertIsNotNone(be)
        self.assertGreater(be, 0)

    def test_rewrite_in_place_costs_more(self):
        """CR-27: rewriting already-sent history breaks the cached prefix."""
        p = cost_model.Params()
        self.assertGreater(cost_model.session_cost(p, False, True, rewrite_at=6), cost_model.session_cost(p, False, True))


if __name__ == "__main__":
    unittest.main()
