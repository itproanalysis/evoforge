"""Tests for v4.2 modules: AST oracle classifier + corpus accuracy gate, AST composition notices,
evaluation sandbox hygiene (real git), compaction boundary evaluation, harness optimizer discipline.
Run: python3 -I reference_impl/test_v42.py -v
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import compaction_eval as ce  # noqa: E402
import composition_gate as cg  # noqa: E402
import eval_hygiene as eh  # noqa: E402
import harness_optimizer as ho  # noqa: E402
import integrity_gate as ig  # noqa: E402
import oracle_ast as oa  # noqa: E402
import oracle_strength as osx  # noqa: E402
import quality_gate as qg  # noqa: E402

G = qg.load_gates()
CORPUS = json.load(open(os.path.join(HERE, "fixtures", "oracle_corpus.json"), encoding="utf-8"))["cases"]
HOLDOUT = json.load(open(os.path.join(HERE, "fixtures", "oracle_holdout.json"), encoding="utf-8"))["cases"]


# ------------------------------------------------------------------ oracle classifier accuracy
class OracleAccuracy(unittest.TestCase):
    def test_dev_corpus_is_exact(self):
        m = oa.measure(CORPUS)
        self.assertGreaterEqual(m["exact"], G["oracle_strength"]["dev_exact_min"], m["misses"])

    def test_holdout_meets_contract(self):
        m = oa.measure(HOLDOUT)
        self.assertGreaterEqual(m["binary_agreement"], G["oracle_strength"]["holdout_binary_agreement_min"], m["misses"])
        self.assertLessEqual(m["false_strong_rate"], G["oracle_strength"]["max_false_strong_rate"], m["misses"])

    def test_combined_false_strong_rate(self):
        m = oa.measure(CORPUS + HOLDOUT)
        self.assertLessEqual(m["false_strong_rate"], G["oracle_strength"]["max_false_strong_rate"])

    def test_ast_beats_regex_on_known_failure_modes(self):
        # string containing assert text, assertion message containing '==', multi-line assert: regex v4.1 misread these
        for cid in ("py004", "py019", "py037"):
            case = next(c for c in CORPUS if c["id"] == cid)
            self.assertEqual(oa.analyze(case["src"])[0].strength, case["label"], cid)

    def test_python_routes_to_ast_and_falls_back(self):
        self.assertEqual(osx.analyze("def test_a():\n    assert f() == 1\n", "py")[0].strength, "value_equality")
        broken = "def test_b():\n    assert f() == 1\n    if (:\n"
        self.assertTrue(osx.analyze(broken, "py"))     # regex fallback still returns something

    def test_nested_helper_not_followed(self):
        src = "def test_h():\n    def check(v):\n        assert v == 3\n    run()\n"
        self.assertEqual(oa.analyze(src)[0].strength, "none")


# ------------------------------------------------------------------ AST composition notices
class AstNotices(unittest.TestCase):
    OLD = "def total(cart):\n    return sum(cart)\n\nclass Cart:\n    def add(self, item):\n        pass\n\ndef keep(x):\n    return x\n\ndef _private(a):\n    pass\n"
    NEW = ("def total(cart, currency='KRW'):\n    return sum(cart)\n\nclass Cart:\n    def add(self, item, qty):\n        pass\n\n"
           "def keep(x):\n    return x + 1\n\ndef _private(a, b):\n    pass\n\ndef fresh():\n    pass\n")

    def test_signature_and_method_changes_only(self):
        n = cg.notices_from_sources({"p1": {"lib/a.py": (self.OLD, self.NEW)}}, {"p2": {"total", "Cart", "keep", "_private", "fresh"}, "p1": {"total"}})
        got = sorted((x["symbol"], x["kind"]) for x in n["p2"])
        self.assertEqual(got, [("Cart", "signature_changed"), ("total", "signature_changed")])   # body-only, private, added: no notice
        self.assertEqual(n["p1"], [])

    def test_removed_symbol(self):
        n = cg.notices_from_sources({"p1": {"lib/a.py": (self.OLD, "def total(cart):\n    pass\n")}}, {"p2": {"keep"}})
        self.assertEqual([(x["symbol"], x["kind"]) for x in n["p2"]], [("keep", "removed")])

    def test_non_python_falls_back_to_diff(self):
        n = cg.notices_from_sources({"p1": {"web/a.ts": ("export function f(a) {}\n", "export function f(a, b) {}\n")}}, {"p2": {"f"}})
        self.assertEqual([(x["symbol"], x["kind"]) for x in n["p2"]], [("f", "signature_changed")])


# ------------------------------------------------------------------ evaluation sandbox hygiene (real git)
def _git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main", *a],
                          cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@unittest.skipUnless(shutil.which("git"), "git CLI required")
class Hygiene(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="evoforge-t-")
        self.src = os.path.join(self.tmp, "src")
        os.makedirs(self.src)
        _git(self.src, "init", "-q")
        for i, body in enumerate(["v1", "v2 bug", "v3 FIXED_SECRET_ANSWER"]):
            with open(os.path.join(self.src, "app.py"), "w") as fh:
                fh.write(body + "\n")
            _git(self.src, "add", "-A")
            _git(self.src, "commit", "-q", "-m", f"c{i}")
        self.c = _git(self.src, "rev-list", "--reverse", "HEAD").split()
        _git(self.src, "tag", "v-fix", self.c[2])
        _git(self.src, "remote", "add", "upstream", "https://example.invalid/repo.git")
        _git(self.src, "branch", "fix-branch", self.c[2])
        self.base = self.c[1]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_naive_checkout_leaks_future(self):
        # control: a plain clone checked out at base still has the fix commit
        naive = os.path.join(self.tmp, "naive")
        _git(self.tmp, "clone", "-q", self.src, naive)
        _git(naive, "checkout", "-q", self.base)
        v = eh.audit(naive, self.base, [self.c[2]])
        self.assertTrue(any("future commit" in x for x in v), v)
        self.assertTrue(any("remote" in x for x in v), v)

    def test_sandbox_has_no_future(self):
        dest = os.path.join(self.tmp, "sandbox")
        base = eh.build_sandbox_repo(self.src, self.base, dest)
        self.assertEqual(base, self.base)
        self.assertEqual(eh.audit(dest, self.base, [self.c[2]]), [])
        objs = subprocess.run(["git", "rev-list", "--all", "--objects"], cwd=dest, capture_output=True, text=True).stdout
        blobs = [ln.split()[0] for ln in objs.splitlines()]
        contents = "".join(subprocess.run(["git", "cat-file", "-p", b], cwd=dest, capture_output=True, text=True).stdout for b in blobs)
        self.assertNotIn("FIXED_SECRET_ANSWER", contents)
        with open(os.path.join(dest, "app.py")) as fh:
            self.assertEqual(fh.read(), "v2 bug\n")

    def test_alternates_detected(self):
        dest = os.path.join(self.tmp, "sandbox2")
        eh.build_sandbox_repo(self.src, self.base, dest)
        with open(os.path.join(dest, ".git", "objects", "info", "alternates"), "w") as fh:
            fh.write(os.path.join(self.src, ".git", "objects") + "\n")
        self.assertTrue(any("alternates" in x for x in eh.audit(dest, self.base, [self.c[2]])))

    def test_unknown_base_and_existing_dest(self):
        with self.assertRaises(eh.HygieneError):
            eh.build_sandbox_repo(self.src, "0" * 40, os.path.join(self.tmp, "x"))
        os.makedirs(os.path.join(self.tmp, "exists"))
        with self.assertRaises(eh.HygieneError):
            eh.build_sandbox_repo(self.src, self.base, os.path.join(self.tmp, "exists"))

    def test_score_record_requires_scaffold_and_clean(self):
        sc = {"name": "evoforge-runner", "version": "0.1.0", "turn_cap": 250, "model": "m", "harness_version": "h-1"}
        self.assertEqual(eh.score_record("t1", 1.0, sc, [])["hygiene"], "clean")
        with self.assertRaises(eh.HygieneError):
            eh.score_record("t1", 1.0, {k: v for k, v in sc.items() if k != "turn_cap"}, [])
        with self.assertRaises(eh.HygieneError):
            eh.score_record("t1", 1.0, sc, ["remote present"])


# ------------------------------------------------------------------ compaction boundary evaluation
def boundaries(n_sessions=40, per=3, flip_down=0.0, extra_repeats=0.0, unstable=0.0, seed=4):
    rng = random.Random(seed)
    out = []
    for s in range(n_sessions):
        for b in range(per):
            base = [int(rng.random() < 0.8)] * 3
            cand = list(base)
            if base[0] == 1 and rng.random() < flip_down:
                cand = [0, 0, 0]
            if rng.random() < unstable:
                cand = [1, 0, 1]
            rb = rng.randint(0, 3)
            out.append(ce.Boundary(f"s{s:03d}", f"b{b}", base, cand, rb, rb + extra_repeats, 1, 1))
    return out


class CompactionEval(unittest.TestCase):
    def test_equivalent_compaction_passes_tier_a(self):
        r = ce.decide(boundaries(n_sessions=120, flip_down=0.0), "A_canary")
        # zero discordance -> required pairs tiny; must pass
        self.assertTrue(r["passed"], r["reasons"])

    def test_success_regression_fails(self):
        r = ce.decide(boundaries(n_sessions=120, flip_down=0.4), "A_canary")
        self.assertFalse(r["passed"])
        self.assertTrue(any(x.startswith("success") for x in r["reasons"]))

    def test_repeated_exploration_fails_even_if_success_holds(self):
        r = ce.decide(boundaries(n_sessions=120, extra_repeats=2.0), "A_canary")
        self.assertFalse(r["passed"])
        self.assertTrue(any("repeated exploration" in x for x in r["reasons"]))

    def test_instability_fails(self):
        r = ce.decide(boundaries(n_sessions=120, unstable=0.3), "A_canary")
        self.assertTrue(any("instability" in x for x in r["reasons"]))

    def test_too_few_sessions_underpowered(self):
        r = ce.decide(boundaries(n_sessions=10), "A_canary")
        self.assertTrue(any("UNDERPOWERED" in x for x in r["reasons"]))


# ------------------------------------------------------------------ harness optimizer discipline
FILES = {"prompts/builder.md": "## Rules\n- be careful\n", "tools/search.py": "def search(q):\n    return []\n",
         "policy/engine.py": "def allow():\n    return False\n"}


def patch(ops, gen=0):
    return {"schema_version": "harness-patch/v1", "patch_id": "hp_abcdef12", "run_id": "r1", "generation": gen,
            "parent_versions": ["hv_00000001"], "module": "C", "category": "prompt", "phase": "steering",
            "ops": ops, "rationale": "reduce repeated exploration after compaction"}


class Optimizer(unittest.TestCase):
    def test_budget_anneals(self):
        self.assertEqual(ho.edit_budget(0, 11), 120)
        self.assertEqual(ho.edit_budget(10, 11), 20)
        self.assertEqual(ho.edit_budget(5, 11), 70)

    def test_patch_checks(self):
        ok = patch([{"file": "prompts/builder.md", "op": "insert_after", "anchor": "## Rules\n", "text": "- verify first\n"}])
        self.assertEqual(ho.check_patch(ok, 0, 10, FILES), [])
        tk = patch([{"file": "policy/engine.py", "op": "replace", "anchor": "return False", "text": "return True", "lines": 1}])
        self.assertTrue(any("Trust Kernel" in v for v in ho.check_patch(tk, 0, 10, FILES)))
        miss = patch([{"file": "tools/search.py", "op": "replace", "anchor": "return None", "text": "x", "lines": 1}])
        self.assertTrue(any("anchor" in v for v in ho.check_patch(miss, 0, 10, FILES)))
        big = patch([{"file": "prompts/builder.md", "op": "insert_after", "anchor": "## Rules\n", "text": "- x\n" * 30}], gen=9)
        self.assertTrue(any("budget" in v for v in ho.check_patch(big, 9, 10, FILES)))

    def test_schema_examples(self):
        import jsonschema  # validator dependency; skip-free because the package validator already requires it
        with open(os.path.join(os.path.dirname(HERE), "contracts", "schemas", "harness-patch.v1.schema.json"), encoding="utf-8") as fh:
            schema = json.load(fh)
        v = jsonschema.Draft202012Validator(schema)
        good = patch([{"file": "prompts/builder.md", "op": "insert_after", "anchor": "## Rules\n", "text": "- verify\n"}])
        self.assertEqual(list(v.iter_errors(good)), [])
        bad = dict(good, evaluated_on=["test"])
        self.assertTrue(list(v.iter_errors(bad)))      # D_test results are not representable on a patch
        bad2 = patch([{"file": "../etc/passwd", "op": "create", "text": "x"}])
        self.assertTrue(list(v.iter_errors(bad2)))

    def _pairs(self, gain, n=200, seed=9):
        rng = random.Random(seed)
        out = []
        for t in range(n):
            base = int(rng.random() < 0.5)
            cand = 1 if (base == 1 or rng.random() < gain) else 0
            out.append((f"t{t:03d}", base, cand))
        return out

    def test_state_machine(self):
        run = ho.OptimizationRun("r1")
        with self.assertRaises(ho.OptimizerError):
            ho.OptimizationRun("r2", baseline="random-search")
        p = patch([{"file": "prompts/builder.md", "op": "insert_after", "anchor": "## Rules\n", "text": "- verify\n"}])
        self.assertFalse(run.propose("h1", p, 0.5, 0.5, 0, 10, FILES))     # not improving -> not a candidate
        self.assertTrue(run.propose("h1", p, 0.5, 0.6, 0, 10, FILES))
        run.record_dev("h1", 0.61)
        run.record_dev("h2", 0.58)
        with self.assertRaises(ho.OptimizerError):
            run.freeze("h2", self._pairs(0.3))                                  # not the dev-selected one
        with self.assertRaises(ho.OptimizerError):
            run.freeze("h1", self._pairs(0.0))                                  # does not beat GEPA
        with self.assertRaises(ho.OptimizerError):
            run.evaluate_test("h1", 0.5)                                         # test before freeze
        run.freeze("h1", self._pairs(0.3))
        with self.assertRaises(ho.OptimizerError):
            run.propose("h3", p, 0.5, 0.7, 1, 10, FILES)                         # no patches after freeze
        run.evaluate_test("h1", 0.55)
        with self.assertRaises(ho.OptimizerError):
            run.evaluate_test("h1", 0.56)                                        # test used once


# ------------------------------------------------------------------ GH_INTEGRITY decision
class Integrity(unittest.TestCase):
    OK = (True, "ok")

    def test_pass(self):
        self.assertEqual(ig.decide(self.OK, self.OK, (False, []))[0], "PASS")

    def test_hack_is_hard_fail(self):
        self.assertEqual(ig.decide(self.OK, self.OK, (True, ["skip_added"]))[0], "FAIL")

    def test_weak_oracle_is_inconclusive_while_provisional(self):
        r, why = ig.decide((False, "fraction 0.4"), self.OK, (False, []))
        self.assertEqual(r, "INCONCLUSIVE")
        self.assertIn("provisional", why[0])

    def test_weak_oracle_fails_once_holdout_is_large(self):
        self.assertEqual(ig.decide((False, "fraction 0.4"), self.OK, (False, []), holdout_cases=250)[0], "FAIL")

    def test_incomplete_heldout_inconclusive(self):
        self.assertEqual(ig.decide(self.OK, (False, "lacks ['negative']"), (False, []))[0], "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
