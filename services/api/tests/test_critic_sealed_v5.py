"""Critic — sealed v5: 12 rule-dense tasks (2 per family) calibrated against single-shot Muse Spark 1.3.

v3 saturated (single shot 48/48 with harness /2 and a 32k budget), so it cannot show an orchestration effect. v5
calibration (3-4 local samples per task) found single-shot misses, mostly large rewrites whose diff does not apply
(semver: /2 1/4, /3 2/4); some tasks stayed easy and are kept so the suite is not cherry-picked."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge import sealed_eval  # noqa: E402


def test_v5_has_two_hard_tasks_per_family():
    suites = sealed_eval.load_suites("v5")  # structural checks + check_task on every task
    assert len(suites) == 6 and all(len(s["tasks"]) == 2 for s in suites)
    for s in suites:
        for t in s["tasks"]:
            assert t["id"].startswith("SV5-")
            assert sorted(h["kind"] for h in t["heldout"]) == ["boundary", "compositional", "negative"]
            assert len(t["goal"]) > 400, t["id"]  # every rule a test checks is stated in the goal


def test_v5_is_selectable_everywhere():
    from evoforge import arena
    assert "v5" in sealed_eval.SUITE_VERSIONS and "v5" in arena.SUITE_VERSIONS
