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


def usage_cost_cents(usage, model=None) -> int | None:
    """Usage-derived cost in integer cents (rounded up); None when missing.

    A call on the second Critic provider (CRITIC_API_BASE + CRITIC_API_KEY
    set) whose model is the Critic model (MODEL_CRITIC) is priced at the
    Critic provider's CRITIC_PRICE_* prices, with cache-read tokens at the
    input price; every other call keeps today's EVO_PRICE_* prices.
    """
    from evoforge import collaboration, platform_models
    if collaboration.enabled():
        target = model or collaboration.BUILDER
        if platform_models.is_platform_model(target):
            return platform_models.model_cost_cents(usage, target)
    tokens = tokens_from_usage(usage)
    if tokens is None:
        return None
    prompt, completion, reasoning, cached = tokens
    critic_pair = _critic_price_pair(model)
    if critic_pair is not None:
        price_in, price_out = critic_pair
        price_cache = price_in
    else:
        price_in, price_out, price_cache = prices()
    # OpenAI-compatible usage: prompt_tokens already includes cached tokens, so the uncached part is billed
    # at the input price and the cached part at the cache-read price (never both at full price).
    uncached = max(prompt - cached, 0)
    usd = (uncached * price_in
           + (completion + reasoning) * price_out
           + cached * price_cache) / 1_000_000.0
    return int(math.ceil(usd * 100.0))


def critic_prices() -> tuple[float, float] | None:
    """Critic-provider prices (USD per million tokens: input, output).

    From CRITIC_PRICE_INPUT_PER_MTOK + CRITIC_PRICE_OUTPUT_PER_MTOK, set by
    the owner from the provider's price page; None unless both are set to
    numbers. Prices are never guessed here.
    """
    try:
        raw_in = os.getenv("CRITIC_PRICE_INPUT_PER_MTOK")
        raw_out = os.getenv("CRITIC_PRICE_OUTPUT_PER_MTOK")
        if raw_in is None or raw_out is None:
            return None
        raw_in, raw_out = raw_in.strip(), raw_out.strip()
        if not raw_in or not raw_out:
            return None
        return (float(raw_in), float(raw_out))
    except (TypeError, ValueError, AttributeError):
        return None


def _critic_price_pair(model) -> tuple[float, float] | None:
    """Critic-provider (input, output) prices for this model, else None.

    Applies only when the second Critic provider is configured
    (CRITIC_API_BASE + CRITIC_API_KEY) and the call's model is the Critic
    model (MODEL_CRITIC) with both CRITIC_PRICE_* set.
    """
    if not isinstance(model, str) or not model:
        return None
    if model != os.getenv("MODEL_CRITIC", "muse-spark-1.3"):
        return None
    if not (os.getenv("CRITIC_API_BASE") and os.getenv("CRITIC_API_KEY")):
        return None
    return critic_prices()


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


def output_cost_cents(out) -> int | None:
    """Cost a model output dict at its own model's prices (Critic-aware).

    Critic outputs (model == MODEL_CRITIC on the second provider) are
    priced at the Critic provider's prices, never at Builder prices.
    """
    if not isinstance(out, dict):
        return None
    from evoforge import collaboration, platform_models
    if collaboration.enabled() and isinstance(out.get("provider_calls"), list) and out["provider_calls"]:
        costs = [platform_models.model_cost_cents(c.get("usage"), c.get("model"))
                 for c in out["provider_calls"] if isinstance(c, dict)]
        return None if not costs or any(c is None for c in costs) else sum(costs)
    return usage_cost_cents(usage_from_output(out), model=out.get("model"))


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
    from evoforge.postgres_state import backend
    if backend():
        from evoforge.postgres_kernel import KernelRejected
        raise KernelRejected("durable measurements cannot be cleared")
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
                feedback_source: str = "heldout",
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
    if feedback_source not in ("heldout", "critic"):
        raise ValueError(f"unknown feedback_source: {feedback_source!r}")
    record: dict = {
        "measurement_id": f"m_{uuid.uuid4().hex[:12]}",
        "kind": kind,
        "suite_version": suite_version,
        "model": model,
        "harness_version": harness_version,
        "feedback_source": feedback_source,
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
    from evoforge.postgres_state import backend
    store = backend()
    if store:
        from evoforge.postgres_performance import insert
        return insert(store, measurement)
    _MEASUREMENTS.append(measurement)
    _LATEST[measurement["kind"]] = measurement
    return measurement


def latest(kind: str):
    from evoforge.postgres_state import backend
    store = backend()
    if store:
        from evoforge.postgres_performance import latest as durable_latest
        return durable_latest(store, kind)
    return _LATEST.get(kind)


def history() -> list[dict]:
    from evoforge.postgres_state import backend
    store = backend()
    if store:
        from evoforge.postgres_performance import history as durable_history
        return durable_history(store)
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


POOLED_BASIS = ("Repeated measurements of the same suite and harness are pooled (total passed / total tasks); only "
                "pipeline runs with Critic feedback count, because pipeline runs fed held-out failing-test names are "
                "an upper bound the single call never gets. Better = the 95% Wilson intervals of the pooled rates do "
                "not overlap; both at 100% = saturated (the suite is too easy to separate the two).")


def _wilson(k: int, n: int) -> list:
    if n <= 0:
        return [0.0, 1.0]
    z = 1.96
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


def pooled(records: list[dict] | None = None) -> list[dict]:
    """Single call vs EvoForge pipeline per (suite, harness), each side pooled over its repeated runs."""
    recs = history() if records is None else records
    groups: dict = {}
    for r in recs:
        if not isinstance(r, dict) or r.get("provider_stub"):
            continue
        kind = r.get("kind")
        if kind == "PIPELINE" and r.get("feedback_source") != "critic":
            continue  # held-out feedback: upper bound, not a fair comparison
        if kind not in ("X_SINGLE", "PIPELINE"):
            continue
        key = (r.get("suite_version"), r.get("harness_version"))
        side = groups.setdefault(key, {}).setdefault(kind, {"runs": 0, "passed": 0, "n": 0, "cost_cents": 0})
        try:
            side["passed"] += int(r.get("passed", 0))
            side["n"] += int(r.get("n", 0))
            side["cost_cents"] += int(r.get("cost_cents", 0) or 0)
            side["runs"] += 1
        except (TypeError, ValueError):
            continue
    out = []
    for (suite, harness), sides in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        if "X_SINGLE" not in sides or "PIPELINE" not in sides:
            continue
        view = {}
        for kind, name in (("X_SINGLE", "single"), ("PIPELINE", "evoforge")):
            s = sides[kind]
            view[name] = {**s, "rate": (s["passed"] / s["n"]) if s["n"] else None, "wilson95": _wilson(s["passed"], s["n"])}
        if view["single"]["rate"] == 1.0 and view["evoforge"]["rate"] == 1.0:
            verdict = "saturated"
        elif view["evoforge"]["wilson95"][0] > view["single"]["wilson95"][1]:
            verdict = "evoforge_better"
        elif view["single"]["wilson95"][0] > view["evoforge"]["wilson95"][1]:
            verdict = "single_better"
        else:
            verdict = "not_significant"
        out.append({"suite_version": suite, "harness_version": harness, **view, "verdict": verdict})
    return out
