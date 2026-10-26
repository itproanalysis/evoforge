"""Calibrated model cascade (EvoForge v4.1, executable spec).

Adopted (TRIAL): arXiv:2605.18796 (UCCI) — route to a cheap model first and escalate only when a
calibrated confidence says the cheap answer is likely wrong; isotonic calibration made cascades
reliably cheaper at equal quality in the paper. EvoForge restricts it: never for critic/security
roles and never for HIGH/CRITICAL risk (contracts/quality_gates.json `cascade`), and the chosen
threshold must keep the Wilson UPPER bound of the accepted-error rate under the cap.
"""
from __future__ import annotations

import bisect
import json
import os

from quality_gate import wilson

_GATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts", "quality_gates.json")


def _cfg() -> dict:
    with open(_GATES, encoding="utf-8") as fh:
        return json.load(fh)["cascade"]


def isotonic_fit(scores: list[float], labels: list[int]) -> tuple[list[float], list[float]]:
    """Pool-adjacent-violators. Returns (block upper score bounds, calibrated probabilities)."""
    pts = sorted(zip(scores, labels))
    blocks: list[list[float]] = []  # [sum_y, count, max_score]
    for s, y in pts:
        blocks.append([float(y), 1.0, s])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            y2, c2, s2 = blocks.pop()
            blocks[-1][0] += y2
            blocks[-1][1] += c2
            blocks[-1][2] = s2
    return [b[2] for b in blocks], [b[0] / b[1] for b in blocks]


def calibrate(model: tuple[list[float], list[float]], score: float) -> float:
    xs, ps = model
    i = bisect.bisect_left(xs, score)
    return ps[min(i, len(ps) - 1)]


def choose_threshold(scores: list[float], correct: list[int], cost_cheap: float, cost_strong: float,
                     cfg: dict | None = None) -> dict:
    """Minimize expected cost per task subject to Wilson-UB(error among accepted) <= cap.
    Cost model: every task pays cheap; escalated tasks additionally pay strong."""
    cfg = cfg or _cfg()
    if len(scores) < cfg["min_calibration_samples"]:
        return {"enabled": False, "reason": f"needs >= {cfg['min_calibration_samples']} calibration samples"}
    model = isotonic_fit(scores, correct)
    cal = [calibrate(model, s) for s in scores]
    n = len(scores)
    best = {"enabled": False, "reason": "no threshold meets the error cap", "tau": None,
            "expected_cost": cost_strong}  # baseline: always strong
    for tau in sorted(set(cal)):
        acc = [c for p, c in zip(cal, correct) if p >= tau]
        if not acc:
            continue
        err_ub = wilson(len(acc) - sum(acc), len(acc))[1]
        if err_ub > cfg["max_accepted_error_wilson_ub"]:
            continue
        cost = cost_cheap + (n - len(acc)) / n * cost_strong
        if cost < best["expected_cost"]:
            best = {"enabled": True, "tau": tau, "accept_rate": len(acc) / n, "accepted_error_ub": err_ub,
                    "expected_cost": cost, "model": model, "reason": "calibrated threshold"}
    return best


def route(score: float, plan: dict, role: str, risk: str, cfg: dict | None = None) -> str:
    cfg = cfg or _cfg()
    if role in cfg["never_for_roles"] or risk in cfg["never_for_risk"] or not plan.get("enabled"):
        return "strong"
    return "cheap" if calibrate(plan["model"], score) >= plan["tau"] else "strong"
