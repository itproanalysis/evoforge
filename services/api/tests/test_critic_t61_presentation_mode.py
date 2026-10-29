"""Sealed (Critic) — T61 presentation mode for the demo video (v3.8 §4.4, VIDEO-01): a 16:9 recording view built only
from a recorded run's snapshots — one frame per round both sides finished, running cost per side, then an R1 vs latest
summary; nothing pending is shown as done, and the view never calls a model."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


def _s(status, passed, n, cost):
    return {"status": status, "verified": status == "READY", "heldout": {"passed": passed, "n": n}, "cost_cents": cost,
            "preview_html": f"<p>{status}{passed}</p>"}


RUN = {"run_id": "job_demo", "status": "succeeded", "manifest": {"rounds": 5, "comparison": "equal_tools"},
       "rounds": [
           {"index": 1, "name": "Initial Build", "sides": {"evoforge": _s("READY", 3, 3, 7), "single": _s("READY", 3, 3, 7)}},
           {"index": 2, "name": "Feature Growth", "sides": {"evoforge": _s("READY", 6, 6, 26), "single": _s("FAILED", 3, 6, 8)}},
           {"index": 3, "name": "UX Refinement", "sides": {"evoforge": _s("READY", 9, 9, 54), "single": {"status": "PENDING"}}},
       ]}
DRIVER = r"""
const fs = require('fs'); const path = require('path');
const web = process.argv[1];
const ts = require(path.join(web, 'node_modules', 'typescript'));
const src = fs.readFileSync(path.join(web, 'lib', 'roundReplay.ts'), 'utf8');
const out = ts.transpileModule(src, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}});
const m = {exports: {}}; new Function('module', 'exports', 'require', out.outputText)(m, m.exports, require);
const L = m.exports; const run = JSON.parse(process.argv[2]);
console.log(JSON.stringify({f: L.presentationFrames(run), e: L.presentationFrames({run_id: 'x', rounds: []}),
                            n: L.presentationFrames(null)}));
"""


@pytest.fixture(scope="module")
def out():
    node = shutil.which("node")
    if node is None or not (WEB / "node_modules" / "typescript").exists():
        pytest.skip("node + apps/web/node_modules required (npm ci)")
    r = subprocess.run([node, "-e", DRIVER, str(WEB), json.dumps(RUN)], capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_one_frame_per_round_both_sides_finished(out):
    f = out["f"]
    rounds = [x for x in f if x["kind"] == "round"]
    assert [x["index"] for x in rounds] == [1, 2]  # R3 single still pending: not shown as a finished comparison
    r2 = rounds[1]
    assert r2["name"] == "Feature Growth"
    assert r2["evoforge"] == {"status": "READY", "score": "6/6", "previewHtml": "<p>READY6</p>"}
    assert r2["single"] == {"status": "FAILED", "score": "3/6", "previewHtml": "<p>FAILED3</p>"}


def test_running_cost_per_side(out):
    rounds = [x for x in out["f"] if x["kind"] == "round"]
    assert rounds[0]["cost"] == {"evoforge": "7¢", "single": "7¢"}
    assert rounds[1]["cost"] == {"evoforge": "33¢", "single": "15¢"}  # cumulative up to that round


def test_summary_frame_compares_first_and_latest(out):
    last = out["f"][-1]
    assert last["kind"] == "summary" and last["first"] == 1 and last["latest"] == 2
    assert last["verified"] == {"evoforge": "2/2", "single": "1/2"}
    assert last["label"] == "Recorded run job_demo"
    assert out["e"] == [] and out["n"] == []


def test_presentation_view_is_wired_and_offline():
    comp = (WEB / "components" / "PresentationView.tsx").read_text(encoding="utf-8")
    page = (WEB / "app" / "[locale]" / "replay" / "page.tsx").read_text(encoding="utf-8")
    assert "presentationFrames" in comp and "SandboxedPreview" in comp
    assert "fetch(" not in comp and "aspect" in comp  # 16:9 frame (aspect-ratio / aspect-video), no network
    assert "present" in page and "PresentationView" in page
