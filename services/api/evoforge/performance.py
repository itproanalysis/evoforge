"""Performance measurements (T22a): measured-only store, server side.

A number appears only when a server measurement backs it. Missing
measurement is an explicit ``not_measured`` status with a reason, never a
default and never a placeholder. Measurements persist for the process;
the HTTP layer reports ``storage: 'memory'`` until a PostgreSQL store
lands (honest).
"""
from __future__ import annotations

import math
import os
import time
import uuid

EVAL_MAX_DEFAULT = 500
PER_ATTEMPT_MAX_CENTS = 120

PRICE_INPUT_PER_MTOK_DEFAULT = 1.25
PRICE_OUTPUT_PER_MTOK_DEFAULT = 4.25
PRICE_CACHE_PER_MTOK_DEFAULT = 0.15


class BudgetExceeded(ValueError):
    """Eval would exceed the measurement budget cap or the ledger."""


def prices() -> tuple[float, float, float]:
    def _f(name: str, default: float) -> float:
        try:
            raw = os.getenv(name)
            return float(raw) if raw is not None else default
        except (TypeError, ValueError):
            return default

    return (
        _f("EVO_PRICE_INPUT_PER_MTOK", PRICE_INPUT_PER_MTOK_DEFAULT),
        _f("EVO_PRICE_OUTPUT_PER_MTOK", PRICE_OUTPUT_PER_MTOK_DEFAULT),
        _f("EVO_PRICE_CACHE_READ_PER_MTOK", PRICE_CACHE_PER_MTOK_DEFAULT),
    )


def _int_or_zero(value) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else 0
    return 0


def tokens_from_usage(usage) -> tuple[int, int, int, int] | None:
    """(prompt, completion, reasoning, cached) or None when usage is missing."""
    if not isinstance(usage, dict) or not usage:
        return None
    prompt = _int_or_zero(usage.get("prompt_tokens",
                                    usage.get("input_tokens", 0)))
    completion = _int_or_zero(usage.get("completion_tokens",
                                        usage.get("output_tokens", 0)))
    cached = _int_or_zero(usage.get("cached_tokens",
                                    usage.get("cached_read_tokens", 0)))
    reasoning = _int_or_zero(usage.get("reasoning_tokens", 0))
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        cached = max(cached, _int_or_zero(details.get("cached_tokens", 0)))
    details = usage.get("completion_tokens_details")
    if isinstance(details, dict):
        reasoning = max(reasoning, _int_or_zero(
            details.get("reasoning_tokens", 0)))
    if prompt == 0 and completion == 0 and cached == 0 and reasoning == 0:
        # Present-but-empty usage carries no billable signal.
        if "prompt_tokens" not in usage and "completion_tokens" not in usage \
                and "input_tokens" not in usage and "output_tokens" not in usage \
                and "prompt_tokens_details" not in usage \
                and "completion_tokens_details" not in usage:
            return None
    return (prompt, completion, reasoning, cached)


def usage_cost_cents(usage) -> int | None:
    """Usage-derived cost in integer cents (rounded up); None when missing."""
    tokens = tokens_from_usage(usage)
    if tokens is None:
        return None
    prompt, completion, reasoning, cached = tokens
    price_in, price_out, price_cache = prices()
    # OpenAI-compatible usage: prompt_tokens already includes cached tokens, so the uncached part is billed
    # at the input price and the cached part at the cache-read price (never both at full price).
    uncached = max(prompt - cached, 0)
    usd = (uncached * price_in
           + (completion + reasoning) * price_out
           + cached * price_cache) / 1_000_000.0
    return int(math.ceil(usd * 100.0))


def usage_from_output(out: dict):
    if not isinstance(out, dict):
        return None
    usage = out.get("usage")
    if isinstance(usage, dict) and usage:
        return usage
    calls = out.get("provider_calls")
    if isinstance(calls, list):
        for call in calls:
            if isinstance(call, dict) and isinstance(call.get("usage"), dict) \
                    and call["usage"]:
                return call["usage"]
    return None


def eval_max_cents() -> int:
    try:
        return int(os.getenv("EVO_EVAL_MAX_CENTS", str(EVAL_MAX_DEFAULT)))
    except (TypeError, ValueError):
        return EVAL_MAX_DEFAULT


def check_budget(n_tasks: int, attempts_per_task: int,
                 per_attempt_max: int = PER_ATTEMPT_MAX_CENTS) -> int:
    """Refuse with BudgetExceeded when the worst case exceeds cap or ledger.

    Worst case is tasks x attempts x per-attempt maximum. The explicit
    EVO_EVAL_MAX_CENTS cap is enforced whenever it is set; when it is
    unset, legacy baseline callers (which predate the cap) are not blocked
    by the default, but the ledger check still applies.
    """
    from evoforge import ledger as _ledger

    worst = int(n_tasks) * int(attempts_per_task) * int(per_attempt_max)
    raw = os.getenv("EVO_EVAL_MAX_CENTS")
    if raw is not None:
        cap = eval_max_cents()
        if worst > cap:
            raise BudgetExceeded(
                f"eval budget refused: worst case {worst}c exceeds cap {cap}c")
    try:
        if _ledger.available("default") < worst:
            raise BudgetExceeded("budget exhausted (reserve_cost refused)")
    except BudgetExceeded:
        raise
    except Exception as e:
        raise BudgetExceeded(f"budget exhausted ({type(e).__name__})")
    return worst


_MEASUREMENTS: list[dict] = []
_LATEST: dict[str, dict] = {}


def clear() -> None:
    _MEASUREMENTS.clear()
    _LATEST.clear()


def make_record(*, kind: str, suite_version: str = "v0",
                model: str = "muse-spark-1.3", harness_version: str | None = None,
                harness: str | None = None, n: int = 0, passed: int = 0,
                cost_cents: int | None = None, cost: int | None = None,
                per_family: dict | None = None, evidence_id: str | None = None,
                evidence: str | None = None,
                attempts_total: int | None = None,
                usage_missing: bool = False,
                wilson95: list | tuple | None = None,
                created_at: float | None = None,
                **extra) -> dict:
    import sys
    import os as _os
    _ref = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..",
                                          "..", "..", "docs",
                                          "evoforge-v4.2", "reference_impl"))
    if _ref not in sys.path:
        sys.path.insert(0, _ref)
    import quality_gate as _qg

    if harness_version is None:
        harness_version = harness or "api-sealed-eval/1"
    if cost_cents is None:
        cost_cents = cost if cost is not None else 0
    if evidence_id is None:
        evidence_id = evidence if evidence is not None else ""
    n = int(n)
    passed = int(passed)
    if wilson95 is None:
        lo, hi = _qg.wilson(passed, n)
    else:
        lo, hi = float(wilson95[0]), float(wilson95[1])
    record: dict = {
        "measurement_id": f"m_{uuid.uuid4().hex[:12]}",
        "kind": kind,
        "suite_version": suite_version,
        "model": model,
        "harness_version": harness_version,
        "n": n,
        "passed": passed,
        "pass_rate": (passed / n) if n else 0.0,
        "wilson95": [lo, hi],
        "cost_cents": int(cost_cents),
        "created_at": created_at if created_at is not None else time.time(),
        "per_family": {fam: {"n": v.get("n", 0), "passed": v.get("passed", 0)}
                       for fam, v in (per_family or {}).items()},
        "evidence_id": evidence_id,
    }
    if kind == "PIPELINE" or attempts_total is not None or usage_missing:
        record["attempts_total"] = int(attempts_total or 0)
        record["usage_missing"] = bool(usage_missing)
    return record


def record(measurement: dict) -> dict:
    _MEASUREMENTS.append(measurement)
    _LATEST[measurement["kind"]] = measurement
    return measurement


def latest(kind: str):
    return _LATEST.get(kind)


def history() -> list[dict]:
    return [dict(m) for m in _MEASUREMENTS]


def _public_record(record: dict | None) -> dict:
    if record is None:
        return {"status": "not_measured",
                "reason": "no measurement yet", "record": None}
    return {"status": "measured", "reason": "",
            "record": dict(record), **dict(record)}


def _rate_of(record: dict) -> float:
    if isinstance(record.get("pass_rate"), (int, float)) \
            and not isinstance(record.get("pass_rate"), bool):
        return float(record["pass_rate"])
    n = record.get("n", 0)
    passed = record.get("passed", 0)
    if isinstance(n, (int, float)) and n:
        return float(passed) / float(n)
    return 0.0


def _interval_of(record: dict) -> tuple[float, float]:
    iv = record.get("wilson95")
    if isinstance(iv, (list, tuple)) and len(iv) == 2:
        try:
            return float(iv[0]), float(iv[1])
        except (TypeError, ValueError):
            pass
    import sys as _sys
    import os as _os
    _ref = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..",
                                          "..", "..", "docs",
                                          "evoforge-v4.2", "reference_impl"))
    if _ref not in _sys.path:
        _sys.path.insert(0, _ref)
    import quality_gate as _qg
    try:
        return _qg.wilson(int(record.get("passed", 0)), int(record.get("n", 0)))
    except Exception:
        return 0.0, 1.0


def compare(baseline: dict | None, pipeline: dict | None) -> dict:
    if not isinstance(baseline, dict) and not isinstance(pipeline, dict):
        return {"status": "not_measured",
                "reason": "baseline and pipeline not measured",
                "delta_pp": None, "verdict": None}
    if not isinstance(baseline, dict):
        return {"status": "not_measured", "reason": "baseline not measured",
                "delta_pp": None, "verdict": None}
    if not isinstance(pipeline, dict):
        return {"status": "not_measured", "reason": "pipeline not measured",
                "delta_pp": None, "verdict": None}
    if baseline.get("suite_version") != pipeline.get("suite_version") \
            or baseline.get("model") != pipeline.get("model"):
        return {"status": "not_measured",
                "reason": "suite_version/model mismatch between measurements",
                "delta_pp": None, "verdict": None}
    delta_pp = 100.0 * (_rate_of(pipeline) - _rate_of(baseline))
    blo, bhi = _interval_of(baseline)
    plo, phi = _interval_of(pipeline)
    if plo > bhi:
        verdict = "improved"
    elif phi < blo:
        verdict = "worse"
    else:
        verdict = "no_clear_difference"
    return {"status": "measured", "reason": "", "delta_pp": delta_pp,
            "verdict": verdict}


def cost_per_solved(measurement: dict | None):
    if not isinstance(measurement, dict):
        return None
    passed = measurement.get("passed", 0)
    if isinstance(passed, bool) or not isinstance(passed, (int, float)) \
            or not passed:
        return None
    cost = measurement.get("cost_cents", measurement.get("cost", 0))
    if isinstance(cost, bool) or not isinstance(cost, (int, float)):
        return None
    return int(cost) // int(passed)


cost_per_solved_cents = cost_per_solved
