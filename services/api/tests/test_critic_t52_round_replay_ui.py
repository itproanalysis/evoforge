"""Sealed (Critic) — T52 R1-R5 Replay UI (v3.8 §3, SNAP-02..05): pick a round and see both sides' real previews, scores,
costs and status for that same round; First<->Latest; auto replay that never calls the network; a pending or failed
side is never filled with another round's or the other side's result."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
LIB = WEB / "lib" / "roundReplay.ts"


def _side(status, passed, n, cost, html):
    return {"status": status, "verified": status == "READY", "heldout": {"passed": passed, "n": n},
            "cost_cents": cost, "elapsed_ms": 1000, "source_sha": "sha256:" + "a" * 64, "preview_html": html}


RUN = {
    "run_id": "evo_fixture", "app_id": "mission_board", "title": "Mission Board", "status": "running",
    "manifest": {"app_id": "mission_board", "rounds": 5, "cost_basis": "model_api_usage", "disclosure": "same tests"},
    "rounds": [
        {"index": 1, "name": "Initial Build", "sides": {"evoforge": _side("READY", 3, 3, 4, "<p>e1</p>"),
                                                        "single": _side("READY", 3, 3, 1, "<p>s1</p>")}},
        {"index": 2, "name": "Feature Growth", "sides": {"evoforge": _side("READY", 6, 6, 5, "<p>e2</p>"),
                                                         "single": _side("FAILED", 2, 6, 1, "<p>s1</p>")}},
        {"index": 3, "name": "UX Refinement", "sides": {"evoforge": _side("UNVERIFIED", 8, 9, 6, "<p>e3</p>"),
                                                        "single": {"status": "PENDING"}}},
    ],
    "totals": {"evoforge": {"cost_cents": 15, "elapsed_ms": 3000, "verified_rounds": 2},
               "single": {"cost_cents": 2, "elapsed_ms": 2000, "verified_rounds": 1}},
}

DRIVER = r"""
const fs = require('fs'); const path = require('path');
const ts = require(path.join(process.argv[1], 'node_modules', 'typescript'));
const src = fs.readFileSync(path.join(process.argv[1], 'lib', 'roundReplay.ts'), 'utf8');
const out = ts.transpileModule(src, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}});
const m = {exports: {}}; new Function('module', 'exports', 'require', out.outputText)(m, m.exports, require);
const L = m.exports; const run = JSON.parse(process.argv[2]);
console.log(JSON.stringify({
  r2: L.roundView(run, 2), r3: L.roundView(run, 3), r9: L.roundView(run, 9),
  latest: L.latestCommonRound(run), fl: L.firstLatest(run),
  next: [L.nextRound(1, run), L.nextRound(2, run), L.nextRound(3, run)],
  totals: L.totalsView(run),
}));
"""


@pytest.fixture(scope="module")
def out():
    node = shutil.which("node")
    if node is None or not (WEB / "node_modules" / "typescript").exists():
        pytest.skip("node + apps/web/node_modules required (npm ci)")
    r = subprocess.run([node, "-e", DRIVER, str(WEB), json.dumps(RUN)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_round_view_shows_each_sides_own_result_for_that_round(out):
    e, s = out["r2"]["sides"]["evoforge"], out["r2"]["sides"]["single"]
    assert out["r2"]["index"] == 2 and out["r2"]["name"] == "Feature Growth"
    assert (e["status"], e["verified"], e["score"], e["cost"], e["previewHtml"]) == ("READY", True, "6/6", "5¢", "<p>e2</p>")
    assert (s["status"], s["verified"], s["score"]) == ("FAILED", False, "2/6")
    assert s["previewHtml"] == "<p>s1</p>"  # its own (unchanged) code, labelled FAILED, never the other side's


def test_pending_and_missing_rounds_are_not_filled(out):
    s3 = out["r3"]["sides"]["single"]
    assert s3["status"] == "PENDING" and s3["previewHtml"] is None and s3["verified"] is False
    assert out["r3"]["sides"]["evoforge"]["verified"] is False  # UNVERIFIED is not verified
    assert out["r9"] is None


def test_first_latest_and_auto_replay_order(out):
    assert out["latest"] == 2  # last round where neither side is pending
    assert out["fl"] == [1, 2]
    assert out["next"] == [2, 3, None]  # replay stops at the last recorded round; no wraparound


def test_totals_per_side(out):
    t = out["totals"]
    assert t["evoforge"]["cost"] == "15¢" and t["evoforge"]["verified"] == "2/5"
    assert t["single"]["cost"] == "2¢" and t["single"]["verified"] == "1/5"


def test_component_and_page_wiring():
    comp = (WEB / "components" / "RoundReplay.tsx").read_text(encoding="utf-8")
    page = (WEB / "app" / "[locale]" / "replay" / "page.tsx").read_text(encoding="utf-8")
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    layout = (WEB / "app" / "[locale]" / "layout.tsx").read_text(encoding="utf-8")
    assert "SandboxedPreview" in comp and "roundReplay" in comp
    assert "fetch(" not in comp, "replay component must not call the network"
    assert "setInterval" in comp or "setTimeout" in comp
    assert "/v1/evolution/runs" in api and ("getEvolutionRun" in page or "listEvolutionRuns" in page)
    assert "/replay" in layout
    for lang in ("en", "ko"):
        msgs = json.loads((WEB / "messages" / f"{lang}.json").read_text(encoding="utf-8"))
        rep = msgs.get("replay")
        assert isinstance(rep, dict), lang
        for key in ("title", "first", "latest", "play", "recorded-run", "pending", "failed", "unverified", "ready"):
            assert key in rep, (lang, key)
