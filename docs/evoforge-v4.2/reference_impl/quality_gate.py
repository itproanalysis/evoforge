"""Reference Quality Gate statistics (EvoForge v4.1, executable spec).

Implements the decision rules of contracts/quality_gates.json. Stdlib only and
deterministic (seeded bootstrap) so the same evidence always yields the same
decision.

Units
  pair    = one task-seed executed under BOTH baseline and candidate arm
  cluster = task id (repeats of the same task are correlated -> resample tasks)
"""
from __future__ import annotations

import json
import math
import os
import random
from dataclasses import dataclass
from statistics import NormalDist

_N = NormalDist()
GATES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts", "quality_gates.json")


def load_gates(path: str = GATES_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- basic intervals
def wilson(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (two-sided conf)."""
    if n == 0:
        return 0.0, 1.0
    z = _N.inv_cdf(1 - (1 - conf) / 2)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def required_pairs(p_discordant: float, delta: float, alpha: float = 0.05, power: float = 0.80,
                   design_effect: float = 1.0) -> int:
    """Pairs needed for a paired-binary non-inferiority test at true difference 0.

    n = (z_{1-a} + z_{power})^2 * p_d / delta^2 * DE   (one-sided alpha)
    """
    z = _N.inv_cdf(1 - alpha) + _N.inv_cdf(power)
    return math.ceil(z * z * p_discordant / (delta * delta) * design_effect)


# ---------------------------------------------------------------- cluster bootstrap
def _cluster_bootstrap(clusters: dict[str, list[float]], stat, b: int, seed: int) -> list[float]:
    keys = sorted(clusters)
    rng = random.Random(seed)
    out = []
    for _ in range(b):
        sample = [clusters[keys[rng.randrange(len(keys))]] for _ in keys]
        out.append(stat(sample))
    out.sort()
    return out


def _pct(sorted_vals: list[float], q: float) -> float:
    i = min(len(sorted_vals) - 1, max(0, int(math.floor(q * len(sorted_vals)))))
    return sorted_vals[i]


@dataclass(frozen=True)
class NonInferiority:
    n_pairs: int
    n_clusters: int
    mean_diff: float
    lower_bound: float
    delta: float
    p_discordant: float
    n_required: int
    powered: bool
    passed: bool
    reason: str


def paired_noninferiority(pairs: list[tuple[str, int, int]], delta: float, alpha: float = 0.05,
                          power: float = 0.80, b: int = 4000, seed: int = 20261025) -> NonInferiority:
    """pairs: (cluster_id, baseline_success 0/1, candidate_success 0/1).

    Decision: one-sided (1-alpha) cluster-bootstrap lower bound of mean(cand - base) > -delta,
    AND the sample is powered for the OBSERVED discordance rate.
    """
    clusters: dict[str, list[float]] = {}
    disc = 0
    for cid, base, cand in pairs:
        clusters.setdefault(cid, []).append(float(cand - base))
        disc += base != cand
    n = len(pairs)
    flat_mean = lambda groups: sum(sum(g) for g in groups) / sum(len(g) for g in groups)  # noqa: E731
    boot = _cluster_bootstrap(clusters, flat_mean, b, seed)
    lb = _pct(boot, alpha)
    md = flat_mean(list(clusters.values()))
    p_d = disc / n if n else 1.0
    need = required_pairs(max(p_d, 1e-9), delta, alpha, power)
    powered = n >= need
    ok = powered and lb > -delta
    reason = ("PASS" if ok else
              f"UNDERPOWERED: {n} pairs < {need} required at observed discordance {p_d:.3f}" if not powered else
              f"FAIL: lower bound {lb:+.4f} <= -delta {-delta:+.4f}")
    return NonInferiority(n, len(clusters), md, lb, delta, p_d, need, powered, ok, reason)


def ratio_ci(rows: list[tuple[str, float, float]], conf: float = 0.95, b: int = 4000,
             seed: int = 20261025) -> tuple[float, float, float]:
    """rows: (cluster_id, baseline_value, candidate_value). Returns (ratio, lo, hi) of
    sum(candidate)/sum(baseline) with a two-sided cluster-bootstrap CI.
    Used for speedup (higher is better) and cost ratio (lower is better)."""
    clusters: dict[str, list[float]] = {}
    for cid, base, cand in rows:
        clusters.setdefault(cid, []).append((base, cand))  # type: ignore[arg-type]

    def stat(groups):
        sb = sum(x[0] for g in groups for x in g)
        sc = sum(x[1] for g in groups for x in g)
        return sc / sb if sb else float("inf")

    boot = _cluster_bootstrap(clusters, stat, b, seed)
    a = (1 - conf) / 2
    return stat(list(clusters.values())), _pct(boot, a), _pct(boot, 1 - a)


# ---------------------------------------------------------------- composite decisions
def safety_gate(critical_pairs: list[tuple[str, int, int]], escaped_regressions: int,
                policy_violations: int, g: dict) -> tuple[bool, list[str]]:
    """Zero-tolerance safety class. critical_pairs: (task, baseline_caught, candidate_caught) for
    CRITICAL seeded defects."""
    s = g["safety"]
    reasons = []
    arm_only_miss = sum(1 for _, b, c in critical_pairs if b == 1 and c == 0)
    caught = sum(c for _, _, c in critical_pairs)
    lo, _ = wilson(caught, len(critical_pairs))
    if arm_only_miss > s["max_arm_only_critical_misses"]:
        reasons.append(f"{arm_only_miss} critical defects caught by baseline but missed by candidate")
    if len(critical_pairs) < s["min_critical_seeded"]:
        reasons.append(f"only {len(critical_pairs)} critical seeded defects (< {s['min_critical_seeded']})")
    elif lo < s["critical_recall_wilson_lb_min"]:
        reasons.append(f"critical recall Wilson LB {lo:.3f} < {s['critical_recall_wilson_lb_min']}")
    if escaped_regressions > s["max_escaped_regressions"]:
        reasons.append(f"{escaped_regressions} escaped regressions in sealed regrade")
    if policy_violations > s["max_policy_violations"]:
        reasons.append(f"{policy_violations} policy/tenant/approval violations")
    return not reasons, reasons


def promotion_decision(tier: str, vfr_pairs, recall_pairs, critical_pairs, escaped_regressions: int,
                       policy_violations: int, cost_rows=None, g: dict | None = None) -> dict:
    """Full decision for promoting a strategy/topology/context arm/harness against its baseline."""
    g = g or load_gates()
    t = g["tiers"][tier]
    a = g["alpha_one_sided"]
    vfr = paired_noninferiority(vfr_pairs, t["delta_verified_fix_rate"], a, g["power"])
    rec = paired_noninferiority(recall_pairs, t["delta_seeded_recall"], a, g["power"])
    safe_ok, safe_reasons = safety_gate(critical_pairs, escaped_regressions, policy_violations, g)
    out = {"tier": tier, "verified_fix_rate": vfr.__dict__, "seeded_recall": rec.__dict__,
           "safety": {"passed": safe_ok, "reasons": safe_reasons}}
    cost_ok = True
    if cost_rows is not None:
        r, lo, hi = ratio_ci(cost_rows, g["ci_two_sided"])
        cost_ok = hi < t["cost_ratio_ub_max"]
        out["cost_ratio"] = {"ratio": r, "lo": lo, "hi": hi, "passed": cost_ok}
    n_tasks = len({c for c, _, _ in vfr_pairs})
    enough_tasks = n_tasks >= t["min_tasks"]
    out["min_tasks"] = {"tasks": n_tasks, "required": t["min_tasks"], "passed": enough_tasks}
    out["passed"] = vfr.passed and rec.passed and safe_ok and cost_ok and enough_tasks
    return out


def codec_runtime_decision(audits: int, misses: int, critical_misses: int, lossy_events: int,
                           fallbacks: int, g: dict | None = None) -> tuple[str, str]:
    """Production monitoring of a (source_kind, codec@version, provider) profile.
    Separates SAFETY (missed defects found by RAW shadow audit) from EFFICIENCY (gate fallbacks)."""
    g = g or load_gates()
    r = g["codec_runtime"]
    if critical_misses > 0:
        return "DISABLE", "confirmed critical miss in RAW shadow audit"
    lo, hi = wilson(misses, audits)
    if audits and lo > r["target_miss_rate"]:
        return "DISABLE", f"miss rate Wilson LB {lo:.4f} > target {r['target_miss_rate']}"
    if audits < r["min_audits_per_window"]:
        return "ALERT_INSUFFICIENT_AUDIT", f"{audits} audits < {r['min_audits_per_window']} in window"
    if lossy_events + fallbacks >= r["fallback_min_events"] and fallbacks / (lossy_events + fallbacks) >= r["fallback_review_ratio"]:
        return "REVIEW_EFFICIENCY", f"fallback ratio {fallbacks / (lossy_events + fallbacks):.2f} >= {r['fallback_review_ratio']}"
    return "KEEP", f"miss rate {misses}/{audits} (Wilson UB {hi:.4f})"


def reviewer_qualification(critical_caught: int, critical_seeded: int, false_blocks: int,
                           clean_candidates: int, findings_valid: int | None = None,
                           findings_total: int | None = None, g: dict | None = None) -> tuple[bool, str]:
    """Approver qualification per (model, profile, harness) combo.

    v4.1 adds signal-to-noise: the share of the reviewer's findings that correspond to real defects
    (CR-Bench, arXiv:2603.11078). High recall bought with noisy findings does not qualify.
    """
    g = g or load_gates()
    q = g["reviewer_qualification"]
    lo, _ = wilson(critical_caught, critical_seeded)
    if critical_seeded < q["min_critical_seeded"]:
        return False, f"needs >= {q['min_critical_seeded']} critical seeded defects (has {critical_seeded})"
    if lo < q["critical_recall_wilson_lb_min"]:
        return False, f"critical recall Wilson LB {lo:.3f} < {q['critical_recall_wilson_lb_min']}"
    if clean_candidates < q["min_clean_candidates"]:
        return False, f"needs >= {q['min_clean_candidates']} clean candidates (has {clean_candidates})"
    if false_blocks / clean_candidates > q["max_false_block_rate"]:
        return False, f"false block rate {false_blocks / clean_candidates:.3f} > {q['max_false_block_rate']}"
    if findings_total is None or findings_valid is None or findings_total < q["min_findings_for_precision"]:
        return False, f"needs >= {q['min_findings_for_precision']} adjudicated findings for precision (SNR)"
    plo, _ = wilson(findings_valid, findings_total)
    if plo < q["finding_precision_wilson_lb_min"]:
        return False, f"finding precision Wilson LB {plo:.3f} < {q['finding_precision_wilson_lb_min']}"
    return True, "qualified"


def speedup_claim(rows, milestone: str, g: dict | None = None) -> dict:
    """10X ladder: claim value is the CI LOWER bound, never the point estimate."""
    g = g or load_gates()
    target = g["speedup_ladder"][milestone]
    r, lo, hi = ratio_ci(rows, g["ci_two_sided"])
    return {"ratio": r, "lo": lo, "hi": hi, "target_lb": target, "met": lo >= target,
            "claimable_text": f"검증 생산성 {lo:.2f}배 이상(95% CI {lo:.2f}–{hi:.2f}, 점추정 {r:.2f})"}
