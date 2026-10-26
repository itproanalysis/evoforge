"""Tests for the v4.1 performance modules (all thresholds read from contracts/quality_gates.json).
Run: python3 -I reference_impl/test_performance.py -v
"""
from __future__ import annotations

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cascade  # noqa: E402
import composition_gate as cg  # noqa: E402
import memory_policy as mp  # noqa: E402
import oracle_strength as osx  # noqa: E402
import partitioner  # noqa: E402
import ppi  # noqa: E402
import review_policy as rp  # noqa: E402
import reward_hack as rh  # noqa: E402
import selection as sel  # noqa: E402
import speculative as sp  # noqa: E402


# ------------------------------------------------------------------ partitioner (Co-Coder)
class Partitioner(unittest.TestCase):
    def _two_modules(self, cross=0.0):
        files = {f"billing/{x}.py": 2.0 for x in "abcd"} | {f"search/{x}.py": 2.0 for x in "abcd"} | {"core/types.py": 1.0}
        edges = []
        for mod in ("billing", "search"):
            names = [f"{mod}/{x}.py" for x in "abcd"]
            edges += [(a, b, 1.0) for i, a in enumerate(names) for b in names[i + 1:]]
        edges += [(f, "core/types.py", 1.0) for f in files if f != "core/types.py"]   # hub
        if cross:
            edges.append(("billing/a.py", "search/a.py", cross))
        return files, edges

    def test_hub_isolated_and_modules_parallel(self):
        p = partitioner.plan(*self._two_modules())
        self.assertEqual(p.topology, "DAG_PARALLEL")
        self.assertEqual(p.hubs, ["core/types.py"])
        self.assertEqual(sorted(len(x) for x in p.partitions), [4, 4])
        self.assertGreaterEqual(p.predicted_speedup, 1.3)

    def test_tightly_coupled_stays_single(self):
        files, edges = self._two_modules()
        edges += [(f"billing/{x}.py", f"search/{y}.py", 1.0) for x in "abcd" for y in "abcd"]
        p = partitioner.plan(files, edges)
        self.assertEqual(p.topology, "SINGLE")

    def test_small_task_stays_single(self):
        p = partitioner.plan({"a.py": 1.0, "b.py": 1.0}, [("a.py", "b.py", 1.0)])
        self.assertEqual(p.topology, "SINGLE")

    def test_deterministic(self):
        a = partitioner.plan(*self._two_modules(cross=0.5))
        b = partitioner.plan(*self._two_modules(cross=0.5))
        self.assertEqual((a.partitions, a.cohesion, a.predicted_speedup), (b.partitions, b.cohesion, b.predicted_speedup))

    def test_partitions_capped_by_seats(self):
        files = {f"m{i}/x.py": 1.0 for i in range(6)}
        p = partitioner.plan(files, [], seats_for_builders=3)
        self.assertLessEqual(len(p.partitions), 3)


# ------------------------------------------------------------------ composition gate
class Composition(unittest.TestCase):
    BASE = {"t_cart": True, "t_tax": True, "t_ship": True, "t_new": False}

    def test_interference_blocks_and_is_attributed(self):
        per = {"p1": dict(self.BASE, t_new=True), "p2": dict(self.BASE), "p3": dict(self.BASE)}
        combined = dict(self.BASE, t_new=True, t_tax=False)

        def run_subset(ids):
            return dict(self.BASE, t_tax=not ({"p1", "p2"} <= set(ids)))
        r = cg.gate(self.BASE, per, combined, run_subset)
        self.assertEqual(r.decision, "FAIL")
        self.assertEqual(r.interfering_tests, ["t_tax"])
        self.assertEqual(r.culprit_pairs, [("p1", "p2")])

    def test_test_already_broken_by_single_patch_is_not_interference(self):
        per = {"p1": dict(self.BASE, t_ship=False), "p2": dict(self.BASE)}
        combined = dict(self.BASE, t_ship=False)
        self.assertEqual(cg.gate(self.BASE, per, combined).decision, "PASS")

    def test_notice_goes_only_to_referencing_builder(self):
        diff = ("diff --git a/lib/price.py b/lib/price.py\n--- a/lib/price.py\n+++ b/lib/price.py\n"
                "@@ -1,3 +1,3 @@\n-def total(cart):\n+def total(cart, currency):\n-def legacy_round(x):\n+def helper(y):\n")
        n = cg.notices({"p1": diff, "p2": "", "p3": ""}, {"p1": {"total"}, "p2": {"total", "legacy_round"}, "p3": {"other"}})
        kinds = sorted((x["symbol"], x["kind"]) for x in n["p2"])
        self.assertEqual(kinds, [("legacy_round", "removed"), ("total", "signature_changed")])
        self.assertEqual(n["p1"], [])      # own change is not a notice
        self.assertEqual(n["p3"], [])      # does not reference the symbols
        self.assertFalse(any(x["symbol"] == "helper" for x in n["p2"]))   # additions are not breaking


# ------------------------------------------------------------------ oracle strength
PY_TESTS = '''
def test_runs():
    compute(3)

def test_not_none():
    assert compute(3) is not None

def test_value():
    assert compute(3) == 9

def test_raises():
    with pytest.raises(ValueError):
        compute(-1)

def test_mock():
    m = Mock(); use(m)
    m.send.assert_called_once()

def test_tautology():
    x = compute(3)
    assert x == x

@given(st.integers())
def test_property(n):
    check(n)
'''
JS_TESTS = '''
it('renders', () => { render(<App/>); expect(screen).toBeTruthy(); });
test('total', () => { expect(total([1, 2])).toEqual(3); });
it('snap', () => { expect(tree).toMatchSnapshot(); });
'''


class Oracle(unittest.TestCase):
    def test_python_taxonomy(self):
        got = {t.name: t.strength for t in osx.analyze(PY_TESTS, "py")}
        self.assertEqual(got, {"test_runs": "none", "test_not_none": "existence", "test_value": "value_equality",
                               "test_raises": "exception", "test_mock": "mock_only", "test_tautology": "tautology",
                               "test_property": "property"})

    def test_js_taxonomy(self):
        got = {t.name: t.strength for t in osx.analyze(JS_TESTS, "js")}
        self.assertEqual(got, {"renders": "boolean", "total": "value_equality", "snap": "snapshot"})

    def test_gate(self):
        tests = osx.analyze(PY_TESTS, "py")
        self.assertFalse(osx.gate(tests)[0])                    # 3/7 strong
        self.assertTrue(osx.gate([t for t in tests if t.strong])[0])
        self.assertFalse(osx.gate([])[0])


# ------------------------------------------------------------------ reward hacking
class RewardHack(unittest.TestCase):
    def test_gap(self):
        self.assertFalse(rh.gap(100, 100, 95, 100)["flagged"])
        self.assertTrue(rh.gap(100, 100, 80, 100)["flagged"])
        self.assertTrue(rh.gap(10, 10, 2, 3)["flagged"])       # per-candidate point gap
        self.assertFalse(rh.gap(9, 10, 3, 3)["flagged"])

    def test_heldout_must_be_compositional_and_negative(self):
        self.assertFalse(rh.heldout_ok(["unit", "unit", "unit"])[0])
        self.assertTrue(rh.heldout_ok(["unit", "compositional", "negative"])[0])

    def test_lookup_table(self):
        hack = ("+def solve(n):\n+    if n == 1: return 7\n+    if n == 2: return 11\n"
                "+    if n == 3: return 19\n+    if n == 4: return 23\n+    return 0\n")
        self.assertTrue(rh.lookup_table(hack, {"7", "11", "19"})["flagged"])
        honest = "+def solve(n):\n+    if n == 0:\n+        return 0\n+    return primes(n)[-1]\n"
        self.assertFalse(rh.lookup_table(honest, {"7", "11", "19"})["flagged"])

    def test_tampering(self):
        diff = ("--- a/tests/test_api.py\n+++ b/tests/test_api.py\n@@\n-    assert r.status == 200\n"
                "+@pytest.mark.skip(reason='flaky')\n--- a/app/x.py\n+++ b/app/x.py\n+    except Exception:\n")
        kinds = {f["kind"] for f in rh.tampering(diff, ["tests/*"])}
        self.assertEqual(kinds, {"protected_file_modified", "assertion_removed", "skip_added", "exception_swallowed"})
        self.assertEqual(rh.tampering("--- a/app/x.py\n+++ b/app/x.py\n+    return a + b\n", ["tests/*"]), [])

    def test_verdict(self):
        hit, why = rh.verdict(rh.gap(10, 10, 10, 10), {"flagged": False}, [])
        self.assertFalse(hit)
        hit, why = rh.verdict(rh.gap(10, 10, 10, 10), {"flagged": False}, [{"kind": "skip_added"}])
        self.assertTrue(hit)


# ------------------------------------------------------------------ selection
def C(cid, rp_=(3, 3), ho=(3, 3), diff=1000, gates=True, hack=False, sig="s"):
    return sel.Candidate(cid, gates, hack, rp_[0], rp_[1], ho[0], ho[1], diff, sig)


class Selection(unittest.TestCase):
    def test_evidence_beats_judge(self):
        best, why = sel.select([C("a", rp_=(1, 3)), C("b")], judge=lambda a, b, v: "a")
        self.assertEqual(best.cid, "b")
        self.assertEqual(why, "execution evidence")

    def test_hard_filters(self):
        best, _ = sel.select([C("a", hack=True), C("b", gates=False)])
        self.assertIsNone(best)

    def test_tie_goes_to_tournament(self):
        judge = lambda a, b, v: "c" if "c" in (a.cid, b.cid) else min(a.cid, b.cid)  # noqa: E731
        best, why = sel.select([C("a"), C("b"), C("c")], judge=judge)
        self.assertEqual(best.cid, "c")
        self.assertIn("tournament", why)

    def test_tie_without_judge_prefers_smaller_diff(self):
        best, _ = sel.select([C("a", diff=900), C("b", diff=300)])
        self.assertEqual(best.cid, "b")

    def test_adaptive_k(self):
        self.assertFalse(sel.should_sample_more([C("a")], "LOW")[0])
        self.assertTrue(sel.should_sample_more([C("a")], "HIGH")[0])
        self.assertFalse(sel.should_sample_more([C("a"), C("b")], "HIGH")[0])                # agreement
        more, why = sel.should_sample_more([C("a", sig="x"), C("b", sig="y")], "HIGH")
        self.assertTrue(more)
        self.assertIn("disagree", why)
        self.assertFalse(sel.should_sample_more([C(str(i), rp_=(0, 3)) for i in range(5)], "HIGH")[0])


# ------------------------------------------------------------------ speculation
class Speculation(unittest.TestCase):
    @staticmethod
    def execute(call, st):
        if call.kind == "fs.write":
            k = next(iter(call.writes))
            return f"w:{k}", {k: st.get(k, 0) + 1}
        return tuple(sorted((k, st.get(k, 0)) for k in call.reads)), {}

    def test_never_speculate_side_effects(self):
        self.assertFalse(sp.speculable(sp.Call("1", "provider.call")))
        self.assertFalse(sp.speculable(sp.Call("2", "github.create_pr")))
        self.assertFalse(sp.speculable(sp.Call("3", "fs.write", writes=frozenset({"a"}))))
        self.assertTrue(sp.speculable(sp.Call("4", "fs.read", reads=frozenset({"a"}))))
        self.assertFalse(sp.speculable(sp.Call("5", "fs.write")))          # kind alone forbids, even with no declared writes
        self.assertFalse(sp.speculable(sp.Call("6", "shell.exec")))

    def test_contract_lists_are_disjoint_and_cover_side_effects(self):
        c = sp._cfg()
        for k in c["speculable_kinds"]:
            self.assertFalse(any(k.startswith(p) for p in c["never_speculable_prefixes"]), k)
        for must in ("provider.call", "github.", "billing.", "fs.write", "shell.", "net.", "deploy."):
            self.assertIn(must, c["never_speculable_prefixes"])
        self.assertEqual(c["max_false_accepts"], 0)

    def test_zero_false_accepts_randomized(self):
        rng = random.Random(7)
        keys = list("abcdef")
        total_acc = 0
        for trial in range(300):
            calls = []
            for i in range(12):
                if rng.random() < 0.3:
                    calls.append(sp.Call(f"{i}", "fs.write", writes=frozenset({rng.choice(keys)})))
                else:
                    calls.append(sp.Call(f"{i}", rng.choice(["fs.read", "search.code"]), reads=frozenset(rng.sample(keys, 2))))
            seq = sp.sequential(calls, {}, self.execute)
            r = sp.run(calls, {}, self.execute)
            self.assertEqual(r["results"], seq, f"trial {trial}")
            total_acc += r["accepted"]
        self.assertGreater(total_acc, 0)

    def test_conflict_forces_reexecution(self):
        calls = [sp.Call("w", "fs.write", writes=frozenset({"a"})), sp.Call("r", "fs.read", reads=frozenset({"a"}))]
        r = sp.run(calls, {}, self.execute)
        self.assertEqual(r["reexecuted"], 1)
        self.assertEqual(r["results"][1], (("a", 1),))


# ------------------------------------------------------------------ PPI
class PPI(unittest.TestCase):
    def _data(self, noise, n=300, N=3000, seed=3):
        rng = random.Random(seed)
        def draw(k):  # noqa: E306
            out = []
            for _ in range(k):
                y = 1.0 if rng.random() < 0.7 else 0.0
                f = min(1.0, max(0.0, y + rng.gauss(0, noise)))
                out.append((y, f))
            return out
        lab = draw(n)
        unl = draw(N)
        return [y for y, _ in lab], [f for _, f in lab], [f for _, f in unl], [y for y, _ in unl]

    def test_good_autorater_narrows_interval(self):
        y, f, fu, _ = self._data(0.1)
        r, c = ppi.ppi_mean(y, f, fu), ppi.classical_mean(y)
        self.assertLess(r["se"], c["se"] * 0.6)
        self.assertLess(r["lo"], 0.7)
        self.assertGreater(r["hi"], 0.7)

    def test_useless_autorater_does_not_bias(self):
        rng = random.Random(5)
        y = [1.0 if rng.random() < 0.7 else 0.0 for _ in range(300)]
        f = [rng.random() for _ in y]
        fu = [rng.random() for _ in range(3000)]
        r, c = ppi.ppi_mean(y, f, fu), ppi.classical_mean(y)
        self.assertLess(r["lambda"], 0.2)
        self.assertAlmostEqual(r["theta"], c["theta"], delta=0.03)

    def test_not_for_safety_and_needs_labels(self):
        y, f, fu, _ = self._data(0.1)
        self.assertEqual(ppi.noninferiority(y, f, fu, 0.02, "critical_recall", "B_default")["decision"], "NOT_ALLOWED")
        self.assertEqual(ppi.noninferiority(y[:50], f[:50], fu, 0.05, "human_acceptance", "A_canary")["decision"], "UNDERPOWERED")


# ------------------------------------------------------------------ cascade
class Cascade(unittest.TestCase):
    def _cal(self, n=2000, seed=11):
        rng = random.Random(seed)
        s, y = [], []
        for _ in range(n):
            sc = rng.random()
            s.append(sc)
            y.append(1 if rng.random() < 0.5 + 0.5 * sc ** 0.5 * (sc > 0.6) else 0)
        return s, y

    def test_isotonic_is_monotone(self):
        xs, ps = cascade.isotonic_fit(*self._cal())
        self.assertEqual(ps, sorted(ps))
        self.assertEqual(xs, sorted(xs))

    def test_threshold_respects_error_cap_and_saves_cost(self):
        s, y = self._cal()
        plan = cascade.choose_threshold(s, y, cost_cheap=1.0, cost_strong=10.0)
        self.assertTrue(plan["enabled"])
        self.assertLessEqual(plan["accepted_error_ub"], 0.05)
        self.assertLess(plan["expected_cost"], 10.0)

    def test_never_for_reviewers_or_high_risk(self):
        s, y = self._cal()
        plan = cascade.choose_threshold(s, y, 1.0, 10.0)
        self.assertEqual(cascade.route(0.99, plan, "critic", "LOW"), "strong")
        self.assertEqual(cascade.route(0.99, plan, "builder", "HIGH"), "strong")
        self.assertEqual(cascade.route(0.99, plan, "builder", "LOW"), "cheap")

    def test_too_few_samples_disabled(self):
        self.assertFalse(cascade.choose_threshold([0.5] * 10, [1] * 10, 1, 10)["enabled"])


# ------------------------------------------------------------------ memory
class Memory(unittest.TestCase):
    def L(self, lid, phase="fix", tags=("django", "orm"), origin="verified_improvement", tenant="t1", run="r1"):
        return mp.Lesson(lid, tenant, phase, frozenset(tags), "...", run, origin)

    def test_admission(self):
        store = []
        self.assertTrue(mp.admit(store, self.L("a"))[0])
        self.assertFalse(mp.admit(store, self.L("b", origin="agent_self_report"))[0])
        self.assertFalse(mp.admit(store, self.L("a"))[0])

    def test_phase_gate_relevance_eviction_and_tenant(self):
        store = []
        for x in [self.L("a"), self.L("b", phase="localize"), self.L("c", tags=("react",)), self.L("d", tenant="t2")]:
            mp.admit(store, x)
        v = mp.TaskMemoryView("t1")
        self.assertEqual([x.lid for x in mp.recall(store, v, "fix", {"django", "orm", "migration"})], ["a"])
        self.assertEqual(mp.recall(store, v, "fix", {"django", "orm"}), [])     # evicted after one exposure

    def test_shred(self):
        store = []
        mp.admit(store, self.L("a", run="r9"))
        mp.admit(store, self.L("b"))
        self.assertEqual(mp.shred_run(store, "r9"), 1)
        self.assertEqual([x.lid for x in store], ["b"])


# ------------------------------------------------------------------ independence + review signal
class ReviewPolicy(unittest.TestCase):
    GOOD = {"qualified": True, "inputs": ["goal_contract", "spec", "diff", "ci_results", "verifier_own_tests"],
            "spec_tests_sealed_at": "2026-10-25T09:00:00Z", "diff_first_read_at": "2026-10-25T09:05:00Z",
            "feedback": [{"kind": "counterexample", "failing_input": "x", "expected": "1", "observed": "2", "test_ref": "t1"}]}

    def test_good_high_risk_verifier(self):
        self.assertEqual(rp.check_independence("HIGH", self.GOOD), (True, []))

    def test_same_provider_is_fine_but_transcript_leak_is_not(self):
        bad = dict(self.GOOD, inputs=self.GOOD["inputs"] + ["builder_transcript"])
        ok, why = rp.check_independence("CRITICAL", bad)
        self.assertFalse(ok)
        self.assertIn("independent", why[0])

    def test_spec_first_order_and_feedback_form(self):
        ok, why = rp.check_independence("HIGH", dict(self.GOOD, diff_first_read_at="2026-10-25T08:59:00Z"))
        self.assertFalse(ok)
        ok, why = rp.check_independence("HIGH", dict(self.GOOD, feedback=[{"kind": "rationale", "text": "I think..."}]))
        self.assertFalse(ok)
        self.assertTrue(rp.check_independence("LOW", {})[0])

    def test_blocking_needs_executable_evidence(self):
        fs = [{"id": "f1", "severity": "high", "blocking": True, "evidence": {"kind": "failing_test", "ref": "t9"}},
              {"id": "f2", "severity": "high", "blocking": True, "evidence": None}] + \
             [{"id": f"n{i}", "severity": "low", "blocking": False} for i in range(8)]
        r = rp.triage_findings(fs)
        self.assertEqual([f["id"] for f in r["blocking"]], ["f1"])
        self.assertTrue(r["merge_blocked"])
        self.assertEqual(r["advisory"][0]["id"], "f2")
        self.assertTrue(r["advisory"][0]["downgraded"])
        self.assertEqual(len(r["advisory"]), 5)
        self.assertEqual(r["suppressed"], 4)


if __name__ == "__main__":
    unittest.main()
