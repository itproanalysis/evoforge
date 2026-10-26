"""Prediction-powered inference for expensive human labels (EvoForge v4.1, executable spec).

Source: Angelopoulos et al. 2023 (arXiv:2301.09633) and the power-tuned PPI++ variant; FAQ-style
active sampling (arXiv:2601.20251) is TRIAL and not implemented here.

Use: human acceptance of merged changes (WVI's "accepted" component) is slow to label. An
autorater f scores every task; humans label a random subset. PPI combines both and stays unbiased
whatever the autorater's quality — a bad autorater only widens the interval (λ→0 recovers the
human-only estimate). Never used for safety metrics (contracts/quality_gates.json `ppi`).

Estimator (mean of Y):
    θ̂_λ = λ·mean(f_unlabeled) + mean(Y_labeled − λ·f_labeled)
    Var  = λ²·var(f_u)/N + var(Y − λ·f)_l/n
    λ*   = cov(Y, f)_l / ((1 + n/N)·var(f)_l), clipped to [0, 1]
"""
from __future__ import annotations

import json
import math
import os
from statistics import NormalDist, fmean

_GATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts", "quality_gates.json")
_N = NormalDist()


def _cfg() -> dict:
    with open(_GATES, encoding="utf-8") as fh:
        return json.load(fh)["ppi"]


def _var(x: list[float]) -> float:
    m = fmean(x)
    return sum((v - m) ** 2 for v in x) / (len(x) - 1)


def _cov(x: list[float], y: list[float]) -> float:
    mx, my = fmean(x), fmean(y)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (len(x) - 1)


def ppi_mean(y_l: list[float], f_l: list[float], f_u: list[float], conf: float = 0.95,
             lam: float | None = None) -> dict:
    n, N = len(y_l), len(f_u)
    if n < 2 or N < 2 or len(f_l) != n:
        raise ValueError("need >= 2 labeled and unlabeled points, aligned f_l")
    vf = _var(f_l)
    if lam is None:
        lam = 0.0 if vf == 0 else max(0.0, min(1.0, _cov(y_l, f_l) / ((1 + n / N) * vf)))
    resid = [y - lam * f for y, f in zip(y_l, f_l)]
    theta = lam * fmean(f_u) + fmean(resid)
    se = math.sqrt(lam * lam * _var(f_u) / N + _var(resid) / n)
    z = _N.inv_cdf(1 - (1 - conf) / 2)
    return {"theta": theta, "lo": theta - z * se, "hi": theta + z * se, "se": se, "lambda": lam}


def classical_mean(y_l: list[float], conf: float = 0.95) -> dict:
    n = len(y_l)
    se = math.sqrt(_var(y_l) / n)
    z = _N.inv_cdf(1 - (1 - conf) / 2)
    m = fmean(y_l)
    return {"theta": m, "lo": m - z * se, "hi": m + z * se, "se": se}


def noninferiority(d_l: list[float], fd_l: list[float], fd_u: list[float], delta: float, metric: str,
                   tier: str, alpha: float = 0.05, cfg: dict | None = None) -> dict:
    """d = candidate − baseline acceptance per task (paired). PASS iff one-sided LB > −delta."""
    cfg = cfg or _cfg()
    if metric in cfg["forbidden_metrics"] or metric not in cfg["allowed_metrics"]:
        return {"decision": "NOT_ALLOWED", "reason": f"PPI not allowed for metric '{metric}'"}
    if len(d_l) < cfg["min_labeled"][tier]:
        return {"decision": "UNDERPOWERED", "reason": f"needs >= {cfg['min_labeled'][tier]} human labels for {tier}"}
    r = ppi_mean(d_l, fd_l, fd_u, conf=1 - 2 * alpha)
    return {"decision": "PASS" if r["lo"] > -delta else "FAIL", **r}
