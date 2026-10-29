"""Critic — sealed v3 = v2's 36 tasks unchanged + 12 harder tasks (2 per family) to break the v2 ceiling (pipeline 36/36)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge import sealed_eval  # noqa: E402


def test_v3_extends_v2_without_changing_it():
    v2 = {t["id"][4:]: t for s in sealed_eval.load_suites("v2") for t in s["tasks"]}
    v3 = {t["id"][4:]: t for s in sealed_eval.load_suites("v3") for t in s["tasks"]}
    assert len(v3) == 48 and set(v2) <= set(v3)
    for k in v2:
        for field in ("goal", "files", "reference_fix", "heldout"):
            assert v2[k][field] == v3[k][field], (k, field)


def test_each_family_gains_two_hard_tasks_with_three_kinds():
    fams = {}
    for s in sealed_eval.load_suites("v3"):
        hard = [t for t in s["tasks"] if t["id"].split("-")[-1] in ("07", "08")]
        fams[s["family"]] = hard
        for t in hard:
            assert sorted(h["kind"] for h in t["heldout"]) == ["boundary", "compositional", "negative"]
    assert len(fams) == 6 and all(len(v) == 2 for v in fams.values())
