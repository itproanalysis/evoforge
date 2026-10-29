"""Sealed (Critic) — T56 evolution stats panel (v3.8 §9 allowed vs forbidden values): the replay screen shows, per side,
verified rounds, rate and Wilson 95% interval and cost per verified round from GET /v1/evolution/stats, and states
"not significant" whenever the server says so — no win label without non-overlapping intervals."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"

STATS = {
    "runs": 3, "comparison": "not_significant", "method": "rounds as independent trials",
    "by_side": {
        "evoforge": {"rounds": 10, "verified": 9, "wilson95": [0.5958, 0.9821], "cost_cents": 100,
                     "cost_per_verified_cents": 11},
        "single": {"rounds": 10, "verified": 0, "wilson95": [0.0, 0.2775], "cost_cents": 50,
                   "cost_per_verified_cents": None},
    },
}
EMPTY = {"runs": 0, "comparison": "not_significant", "by_side": {
    "evoforge": {"rounds": 0, "verified": 0, "wilson95": [0, 0], "cost_cents": 0, "cost_per_verified_cents": None},
    "single": {"rounds": 0, "verified": 0, "wilson95": [0, 0], "cost_cents": 0, "cost_per_verified_cents": None}}}

DRIVER = r"""
const fs = require('fs'); const path = require('path');
const web = process.argv[1];
const ts = require(path.join(web, 'node_modules', 'typescript'));
const src = fs.readFileSync(path.join(web, 'lib', 'roundReplay.ts'), 'utf8');
const out = ts.transpileModule(src, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}});
const m = {exports: {}}; new Function('module', 'exports', 'require', out.outputText)(m, m.exports, require);
const L = m.exports; const s = JSON.parse(process.argv[2]); const e = JSON.parse(process.argv[3]);
const better = JSON.parse(process.argv[2]); better.comparison = 'evoforge_better';
console.log(JSON.stringify({s: L.statsView(s), e: L.statsView(e), b: L.statsView(better), n: L.statsView(null)}));
"""


@pytest.fixture(scope="module")
def out():
    node = shutil.which("node")
    if node is None or not (WEB / "node_modules" / "typescript").exists():
        pytest.skip("node + apps/web/node_modules required (npm ci)")
    r = subprocess.run([node, "-e", DRIVER, str(WEB), json.dumps(STATS), json.dumps(EMPTY)], capture_output=True,
                       text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_side_figures(out):
    e, s = out["s"]["evoforge"], out["s"]["single"]
    assert (e["verified"], e["rate"], e["interval"], e["costPerVerified"]) == ("9/10", "90%", "60–98%", "11¢")
    assert (s["verified"], s["rate"], s["interval"], s["costPerVerified"]) == ("0/10", "0%", "0–28%", "—")
    assert out["s"]["runs"] == 3


def test_verdict_comes_only_from_the_server(out):
    assert out["s"]["verdict"] == "not_significant"  # 9/10 vs 0/10 here, but the server said not significant
    assert out["b"]["verdict"] == "evoforge_better"


def test_empty_and_missing(out):
    assert out["e"]["evoforge"]["rate"] == "—" and out["e"]["evoforge"]["interval"] == "—"
    assert out["e"]["runs"] == 0 and out["e"]["verdict"] == "not_significant"
    assert out["n"] is None


def test_panel_wiring():
    comp = (WEB / "components" / "EvolutionStats.tsx").read_text(encoding="utf-8")
    page = (WEB / "app" / "[locale]" / "replay" / "page.tsx").read_text(encoding="utf-8")
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "statsView" in comp and "EvolutionStats" in page
    assert "getEvolutionStats" in api and "/v1/evolution/stats" in api
    for lang in ("en", "ko"):
        rep = json.loads((WEB / "messages" / f"{lang}.json").read_text(encoding="utf-8"))["replay"]
        for key in ("stats-title", "stats-runs", "stats-not-significant", "stats-evoforge-better",
                    "stats-single-better", "stats-method"):
            assert key in rep, (lang, key)
