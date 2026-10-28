"""Critic — sealed v4 (visual, North Star A4): 12 UI tasks whose render() returns XHTML/SVG, scored by held-out DOM tests;
each fixed module also has preview() for the sandboxed side-by-side render."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge import sealed_eval  # noqa: E402


def test_v4_has_two_visual_tasks_per_family_with_three_kinds():
    suites = sealed_eval.load_suites("v4")
    assert len(suites) == 6 and all(len(s["tasks"]) == 2 for s in suites)
    for s in suites:
        for t in s["tasks"]:
            assert t["id"].startswith("SV4-")
            assert sorted(h["kind"] for h in t["heldout"]) == ["boundary", "compositional", "negative"]
            assert all("xml.etree.ElementTree" in h["code"] for h in t["heldout"]), t["id"]
            assert "render(" in t["goal"] and "preview()" in t["goal"]


def test_every_visual_task_exposes_render_and_preview():
    for s in sealed_eval.load_suites("v4"):
        for t in s["tasks"]:
            src = "\n".join(t["files"].values())
            assert "def render(" in src and "def preview(" in src, t["id"]
