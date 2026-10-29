"""Muse (Builder) — T61 presentation mode sanity checks."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
LIB = WEB / "lib" / "roundReplay.ts"


def _side(status, passed, n, cost, html):
    d = {"status": status, "heldout": {"passed": passed, "n": n},
         "cost_cents": cost, "preview_html": html}
    return d


RUN = {
    "run_id": "evo_fixture",
    "manifest": {"comparison_mode": "same tests"},
    "rounds": [
        {"index": 1, "name": "Initial Build",
         "sides": {"evoforge": _side("READY", 3, 3, 4, "<p>e1</p>"),
                   "single": _side("READY", 3, 3, 1, "<p>s1</p>")}},
        {"index": 2, "name": "Feature Growth",
         "sides": {"evoforge": _side("READY", 6, 6, 5, "<p>e2</p>"),
                   "single": _side("FAILED", 2, 6, 1, "<p>s2</p>")}},
        {"index": 3, "name": "UX Refinement",
         "sides": {"evoforge": _side("UNVERIFIED", 8, 9, 6, "<p>e3</p>"),
                   "single": {"status": "PENDING"}}},
    ],
}

DRIVER = r"""
const fs = require('fs'); const path = require('path');
const ts = require(path.join(process.argv[1], 'node_modules', 'typescript'));
const src = fs.readFileSync(path.join(process.argv[1], 'lib', 'roundReplay.ts'), 'utf8');
const out = ts.transpileModule(src, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}});
const m = {exports: {}}; new Function('module', 'exports', 'require', out.outputText)(m, m.exports, require);
const L = m.exports; const run = JSON.parse(process.argv[2]);
console.log(JSON.stringify({frames: L.presentationFrames(run), empty: L.presentationFrames(null)}));
"""


def _frames():
    node = shutil.which("node")
    if node is None or not (WEB / "node_modules" / "typescript").exists():
        import pytest
        pytest.skip("node + apps/web/node_modules required (npm ci)")
    r = subprocess.run([node, "-e", DRIVER, str(WEB), json.dumps(RUN)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_presentation_frames_rounds_and_summary():
    out = _frames()
    assert out["empty"] == []
    frames = out["frames"]
    assert len(frames) == 3
    assert frames[0]["kind"] == "round" and frames[0]["index"] == 1
    assert frames[0]["name"] == "Initial Build"
    assert frames[0]["evoforge"]["score"] == "3/3"
    assert frames[0]["evoforge"]["previewHtml"] == "<p>e1</p>"
    assert frames[0]["cost"] == {"evoforge": "4¢", "single": "1¢"}
    assert frames[1]["cost"] == {"evoforge": "9¢", "single": "2¢"}
    s = frames[2]
    assert s["kind"] == "summary"
    assert (s["first"], s["latest"]) == (1, 2)
    assert s["verified"] == {"evoforge": "2/2", "single": "1/2"}
    assert s["label"] == "Recorded run evo_fixture"


def test_presentation_view_and_page_wiring():
    comp = (WEB / "components" / "PresentationView.tsx").read_text(encoding="utf-8")
    page = (WEB / "app" / "[locale]" / "replay" / "page.tsx").read_text(encoding="utf-8")
    assert "SandboxedPreview" in comp
    assert "fetch(" not in comp
    assert ("aspect-video" in comp or "16 / 9" in comp)
    assert "PresentationView" in page and "present=1" in page
    for lang in ("en", "ko"):
        msgs = json.loads((WEB / "messages" / f"{lang}.json").read_text(encoding="utf-8"))
        rep = msgs.get("replay")
        assert isinstance(rep, dict), lang
        for key in ("present", "next", "previous", "exit"):
            assert key in rep, (lang, key)
