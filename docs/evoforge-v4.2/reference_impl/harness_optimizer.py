"""Harness optimizer discipline for M6 (EvoForge v4.2, executable spec for CR-76).

Adopted rules (D-051): GEPA is the baseline optimizer; mutations are structured patches
(harness-patch/v1); a patch is a candidate only if it raises the mini-batch score; final
selection uses D_val (dev) only; D_test is opened ONCE per optimization run after the candidate
is frozen and its result never feeds back into the harness (arXiv:2608.23041); the per-generation
edit budget anneals from 120 to 20 changed lines (arXiv:2609.24972); patches may not touch the
Trust Kernel (policy engine, verifiers, billing, evaluation data).

`OptimizationRun` is a small state machine that makes those rules impossible to break by accident:
  OPEN --propose/evaluate(dev)--> OPEN --freeze(candidate)--> FROZEN --evaluate(test, once)--> CLOSED
"""
from __future__ import annotations

import fnmatch
import json
import os

import quality_gate as qg

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GATES = os.path.join(_ROOT, "contracts", "quality_gates.json")


def _cfg() -> dict:
    with open(_GATES, encoding="utf-8") as fh:
        return json.load(fh)["optimizer"]


class OptimizerError(RuntimeError):
    pass


def edit_budget(generation: int, total_generations: int, cfg: dict | None = None) -> int:
    e = (cfg or _cfg())["edit_budget"]
    if total_generations <= 1:
        return e["end_lines"]
    t = min(max(generation, 0), total_generations - 1) / (total_generations - 1)
    return round(e["start_lines"] + (e["end_lines"] - e["start_lines"]) * t)


def patch_lines(patch: dict) -> int:
    n = 0
    for op in patch["ops"]:
        if op["op"] == "delete":
            n += op.get("lines", 1)
        else:
            n += max(1, op.get("text", "").count("\n") + (0 if op.get("text", "").endswith("\n") else 1))
            if op["op"] == "replace":
                n += op.get("lines", 1)
    return n


def check_patch(patch: dict, generation: int, total_generations: int, files: dict[str, str],
                cfg: dict | None = None) -> list[str]:
    """files: current harness file contents (path -> text). Returns violations."""
    cfg = cfg or _cfg()
    v = []
    for op in patch["ops"]:
        f = op["file"]
        if any(fnmatch.fnmatch(f, g) for g in cfg["protected_globs"]):
            v.append(f"touches Trust Kernel path {f}")
        elif op["op"] == "create":
            if f in files:
                v.append(f"create on existing file {f}")
        elif f not in files:
            v.append(f"unknown file {f}")
        elif files[f].count(op["anchor"]) == 0:
            v.append(f"anchor not found in {f}")
        elif files[f].count(op["anchor"]) > 1:
            v.append(f"ambiguous anchor in {f}")
    budget = edit_budget(generation, total_generations, cfg)
    n = patch_lines(patch)
    if n > budget:
        v.append(f"edit budget exceeded: {n} > {budget} lines at generation {generation}")
    return v


def superiority(pairs: list[tuple[str, int, int]], alpha: float = 0.05, b: int = 4000,
                seed: int = 20261025) -> tuple[bool, float]:
    """One-sided cluster-bootstrap lower bound of mean(candidate - baseline) > 0."""
    clusters: dict[str, list[float]] = {}
    for cid, base, cand in pairs:
        clusters.setdefault(cid, []).append(float(cand - base))
    mean = lambda groups: sum(sum(x) for x in groups) / sum(len(x) for x in groups)  # noqa: E731
    lb = qg._pct(qg._cluster_bootstrap(clusters, mean, b, seed), alpha)
    return lb > 0, lb


class OptimizationRun:
    def __init__(self, run_id: str, baseline: str = "GEPA", cfg: dict | None = None):
        self.cfg = cfg or _cfg()
        if baseline != self.cfg["baseline_name"]:
            raise OptimizerError(f"baseline must be {self.cfg['baseline_name']}")
        self.run_id, self.state = run_id, "OPEN"
        self.dev_scores: dict[str, float] = {}
        self.frozen: str | None = None
        self.test_result: float | None = None

    def propose(self, harness_id: str, patch: dict, parent_minibatch: float, child_minibatch: float,
                generation: int, total_generations: int, files: dict[str, str]) -> bool:
        if self.state != "OPEN":
            raise OptimizerError(f"run is {self.state}: no new patches after freeze (test feedback must not flow back)")
        v = check_patch(patch, generation, total_generations, files, self.cfg)
        if v:
            raise OptimizerError("; ".join(v))
        return child_minibatch > parent_minibatch      # only improving patches become candidates

    def record_dev(self, harness_id: str, score: float) -> None:
        if self.state != "OPEN":
            raise OptimizerError("dev evaluation after freeze")
        self.dev_scores[harness_id] = score

    def select(self) -> str:
        if not self.dev_scores:
            raise OptimizerError("no dev scores")
        return sorted(self.dev_scores.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    def freeze(self, harness_id: str, dev_pairs_vs_baseline: list[tuple[str, int, int]]) -> None:
        if harness_id != self.select():
            raise OptimizerError("frozen candidate must be the dev-selected one")
        ok, lb = superiority(dev_pairs_vs_baseline)
        if not ok:
            raise OptimizerError(f"does not beat {self.cfg['baseline_name']} on dev (LB {lb:+.4f})")
        self.frozen, self.state = harness_id, "FROZEN"

    def evaluate_test(self, harness_id: str, score: float) -> float:
        if self.state != "FROZEN" or harness_id != self.frozen:
            raise OptimizerError("D_test only for the frozen candidate, once")
        self.test_result, self.state = score, "CLOSED"
        return score
