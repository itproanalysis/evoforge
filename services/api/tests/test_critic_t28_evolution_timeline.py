"""Critic acceptance (sealed during build, promoted after) — T28: the performance page shows measured evolution as a timeline (intervals, harness changes,
suite breaks, per-family heatmap) computed by a pure, tested function — never invented numbers."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "apps" / "web"
LIB = WEB / "lib" / "evolutionTimeline.ts"
PAGE = WEB / "app" / "[locale]" / "performance" / "page.tsx"
TSC = WEB / "node_modules" / "typescript" / "bin" / "tsc"


def _rec(mid, kind, suite, harness, passed, n, lo, hi, t, fam=None):
    return {"measurement_id": mid, "kind": kind, "suite_version": suite, "model": "muse-spark-1.3",
            "harness_version": harness, "n": n, "passed": passed, "pass_rate": passed / n, "wilson95": [lo, hi],
            "cost_cents": 100, "created_at": t, "per_family": fam or {"simple_sequential": {"n": 2, "passed": 1}},
            "evidence_id": "ev_" + mid}


HISTORY = [
    _rec("m4", "X_SINGLE", "v1", "api-sealed-eval/2", 12, 12, 0.758, 1.0, 400.0,
         {"simple_sequential": {"n": 2, "passed": 2}, "chat_dropout": {"n": 2, "passed": 2}}),
    _rec("m1", "X_SINGLE", "v0", "api-sealed-eval/1", 2, 12, 0.047, 0.448, 100.0),
    _rec("m2", "X_SINGLE", "v1", "api-sealed-eval/1", 5, 12, 0.193, 0.680, 200.0),
    _rec("m3", "PIPELINE", "v1", "api-sealed-eval/1", 7, 12, 0.320, 0.807, 300.0),
]


@pytest.fixture(scope="module")
def built():
    if not TSC.exists() or not shutil.which("node"):
        pytest.skip("node/typescript not installed in apps/web")
    assert LIB.exists(), "apps/web/lib/evolutionTimeline.ts must exist"
    out = Path(tempfile.mkdtemp())
    r = subprocess.run(["node", str(TSC), str(LIB), "--outDir", str(out), "--module", "commonjs", "--target", "es2019",
                        "--skipLibCheck", "--strict", "--esModuleInterop"], capture_output=True, text=True, cwd=WEB)
    assert r.returncode == 0, r.stdout + r.stderr
    js = next(out.rglob("evolutionTimeline.js"))
    return js


def _call(js: Path, history):
    code = ("const m=require(%s);const h=JSON.parse(process.argv[1]);"
            "process.stdout.write(JSON.stringify(m.buildTimeline(h)));") % json.dumps(str(js))
    r = subprocess.run(["node", "-e", code, json.dumps(history)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_segments_split_by_suite_in_time_order(built):
    tl = _call(built, HISTORY)
    segs = tl["segments"]
    assert [s["suite_version"] for s in segs] == ["v0", "v1"], "suite change must start a new, non-comparable segment"
    assert [p["measurement_id"] for p in segs[1]["points"]] == ["m2", "m3", "m4"], "points ordered by created_at"


def test_points_carry_measured_rate_and_interval_unchanged(built):
    tl = _call(built, HISTORY)
    p = {pt["measurement_id"]: pt for s in tl["segments"] for pt in s["points"]}
    assert p["m1"]["passed"] == 2 and p["m1"]["n"] == 12
    assert abs(p["m1"]["pass_rate"] - 2 / 12) < 1e-9
    assert p["m4"]["lo"] == 0.758 and p["m4"]["hi"] == 1.0, "intervals come from the record, not recomputed or rounded"
    assert p["m3"]["kind"] == "PIPELINE" and p["m3"]["harness_version"] == "api-sealed-eval/1"


def test_harness_changes_are_marked_inside_a_segment(built):
    tl = _call(built, HISTORY)
    v1 = tl["segments"][1]
    marks = v1["harnessChanges"]
    assert len(marks) == 1 and marks[0]["from"] == "api-sealed-eval/1" and marks[0]["to"] == "api-sealed-eval/2"
    assert v1["points"][marks[0]["index"]]["measurement_id"] == "m4"
    assert tl["segments"][0]["harnessChanges"] == []


def test_family_grid_uses_per_family_counts(built):
    tl = _call(built, HISTORY)
    grid = tl["segments"][1]["families"]
    fam = {row["family"]: row for row in grid}
    cell = next(c for c in fam["chat_dropout"]["cells"] if c["measurement_id"] == "m4")
    assert cell["passed"] == 2 and cell["n"] == 2
    missing = [c for c in fam["chat_dropout"]["cells"] if c["measurement_id"] == "m2"]
    assert missing and missing[0]["n"] in (0, None), "a family absent from a record is empty, not zero-of-something"


def test_empty_history_is_an_empty_timeline(built):
    assert _call(built, [])["segments"] == []


# ---- page wiring (source) ----

def _page():
    return PAGE.read_text(encoding="utf-8")


def test_page_renders_the_timeline_from_history():
    page = _page()
    assert "buildTimeline" in page, "the performance page must use buildTimeline on /v1/performance history"
    assert re.search(r"\.history\b", page)
    assert "<svg" in page or "EvolutionTimeline" in page


def test_timeline_has_accessible_text_and_reduced_motion():
    src = _page() + "".join(p.read_text(encoding="utf-8") for p in (WEB / "components").rglob("*.tsx"))
    assert "<title" in src or "aria-label" in src, "points need accessible labels"
    assert "prefers-reduced-motion" in src or "motion-reduce" in src or "useReducedMotion" in src


def test_no_hard_coded_measurement_numbers_in_the_page():
    page = _page()
    for literal in ("16.7", "0.167", "12/12", "75.8"):
        assert literal not in page


def test_timeline_strings_are_localized_in_both_languages():
    ko = json.loads((WEB / "messages" / "ko.json").read_text(encoding="utf-8"))
    en = json.loads((WEB / "messages" / "en.json").read_text(encoding="utf-8"))

    def keys(d, p=""):
        out = set()
        for k, v in d.items():
            out |= keys(v, p + k + ".") if isinstance(v, dict) else {p + k}
        return out
    assert keys(ko) == keys(en)
    assert any("timeline" in k.lower() for k in keys(ko))
