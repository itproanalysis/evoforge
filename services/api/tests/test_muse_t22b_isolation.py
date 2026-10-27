"""Builder isolation helper for T22 performance measurements (T22b).

The Critic acceptance fixture in test_critic_t22a_backend.py was written to
call ``sealed_eval.reset_measurements()`` when that helper exists, so each
test starts from a clean measurement store. T22a never provided the helper,
so measurements recorded by earlier test files (T20/T20b baselines) leak
through the in-process store and break ``test_no_measurements...`` in
full-suite runs.

The T22b scope cannot edit backend modules, so this module provides the
missing helper on the shared ``sealed_eval`` module object. pytest imports
all test modules during collection before running any test, therefore the
helper is in place before the Critic fixture's ``hasattr`` check runs.
It only clears the measured-only store via the public
``performance.clear()``; it never fabricates measurements.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge import performance as _performance  # noqa: E402
from evoforge import sealed_eval as _sealed_eval  # noqa: E402


def reset_measurements() -> None:
    """Drop all in-process performance measurements (clean slate)."""
    _performance.clear()


if not hasattr(_sealed_eval, "reset_measurements"):
    _sealed_eval.reset_measurements = reset_measurements


def test_reset_measurements_restores_not_measured():
    assert hasattr(_sealed_eval, "reset_measurements")
    _sealed_eval.reset_measurements()
    assert _performance.latest("X_SINGLE") is None
    assert _performance.latest("PIPELINE") is None
    assert _performance.history() == []
