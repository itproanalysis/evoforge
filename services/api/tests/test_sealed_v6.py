"""Sealed v6: v5's 12 tasks scored by many single-assertion held-out tests.

v5 bundles 4-5 assertions into each of 3 held-out tests, so both lanes tied 3/3 in 11 of the last 12 Arena
matches. v6 (built by tools/build_sealed_v6.py) keeps every v5 goal, starting file and reference fix and keeps
only tests that pass with the fix and fail on the starting files, so partial solutions score partially."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge import arena, sealed_eval  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]


def _tasks(version):
    out = {}
    for f in sorted((ROOT / "evals" / f"sealed_{version}").glob("*.json")):
        for t in json.loads(f.read_text(encoding="utf-8"))["tasks"]:
            out[t["id"]] = t
    return out


def test_v6_loads_and_every_task_measures_the_builder():
    suites = sealed_eval.load_suites("v6")  # structural checks + check_task on every task
    assert len(suites) == 6 and all(len(s["tasks"]) == 2 for s in suites)
    total = 0
    for s in suites:
        for t in s["tasks"]:
            assert t["id"].startswith("SV6-")
            assert {h["kind"] for h in t["heldout"]} == {"boundary", "compositional", "negative"}
            assert len(t["heldout"]) >= 7, t["id"]
            for h in t["heldout"]:
                assert len(re.findall(r"(?m)^def test_", h["code"])) == 1, h["id"]
            total += len(t["heldout"])
    assert total >= 120


def test_v6_keeps_v5_goals_files_and_fixes():
    v5, v6 = _tasks("v5"), _tasks("v6")
    assert len(v6) == 12
    for tid, t in v6.items():
        old = v5[tid.replace("SV6", "SV5")]
        assert (t["goal"], t["files"], t["reference_fix"]) == (old["goal"], old["files"], old["reference_fix"])


def test_v6_is_selectable_everywhere():
    assert "v6" in sealed_eval.SUITE_VERSIONS and "v6" in arena.SUITE_VERSIONS
    assert arena.find_task("v6", "SV6-SS-01")["goal"].startswith("In duration.py")
