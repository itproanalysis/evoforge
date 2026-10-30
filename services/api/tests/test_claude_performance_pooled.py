"""Claude — cloud review A1 (2026-10-30): Performance pools repeated measurements of the same suite + harness instead of
showing only the latest, and counts only Critic-feedback pipeline runs (held-out feedback is an upper bound)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge import performance  # noqa: E402


def _r(kind, suite, harness, passed, n, fb=None, stub=False):
    return {"kind": kind, "suite_version": suite, "harness_version": harness, "passed": passed, "n": n,
            "feedback_source": fb, "provider_stub": stub, "cost_cents": 10}


def test_production_v5_shape():
    recs = [_r("X_SINGLE", "v5", "/2", 9, 12, "heldout"), _r("X_SINGLE", "v5", "/3", 10, 12, "heldout"),
            _r("PIPELINE", "v5", "/3", 12, 12, "critic"), _r("X_SINGLE", "v5", "/3", 12, 12, "heldout"),
            _r("PIPELINE", "v5", "/3", 12, 12, "critic"), _r("X_SINGLE", "v5", "/3", 9, 12, "heldout"),
            _r("PIPELINE", "v5", "/3", 11, 12, "critic"),
            _r("X_SINGLE", "v3", "/2", 48, 48, "heldout"), _r("PIPELINE", "v3", "/2", 48, 48, "critic"),
            _r("X_SINGLE", "v2", "/2", 35, 36), _r("PIPELINE", "v2", "/2", 36, 36, None),  # oracle pipeline: excluded
            _r("PIPELINE", "v5", "/3", 12, 12, "critic", stub=True)]  # stub never counts
    rows = {(r["suite_version"], r["harness_version"]): r for r in performance.pooled(recs)}
    v5 = rows[("v5", "/3")]
    assert (v5["single"]["passed"], v5["single"]["n"], v5["single"]["runs"]) == (31, 36, 3)
    assert (v5["evoforge"]["passed"], v5["evoforge"]["n"], v5["evoforge"]["runs"]) == (35, 36, 3)
    assert v5["verdict"] == "not_significant"
    assert rows[("v3", "/2")]["verdict"] == "saturated"
    assert ("v2", "/2") not in rows and ("v5", "/2") not in rows
