"""Sealed (Critic) — T63 EvoCore strategies panel (v3.8 §5, "AI that evolves how AI builds" made visible): the champion
build strategy, every candidate's verified rate and Wilson interval, whether it could be promoted (lower bound above
the champion's upper bound — computed by the server rule, shown not invented), and the decision history."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
OVERVIEW = {
    "champion": {"strategy_id": "st_aaaaaaaaaa", "since": 0,
                 "strategy": {"max_attempts": 3, "accumulate_critic": True, "retire_stale": True}},
    "candidates": [
        {"strategy_id": "st_aaaaaaaaaa", "runs": 2,
         "strategy": {"max_attempts": 3, "accumulate_critic": True, "retire_stale": True},
         "evoforge": {"rounds": 10, "verified": 2, "wilson95": [0.0567, 0.5098]}},
        {"strategy_id": "st_bbbbbbbbbb", "runs": 2,
         "strategy": {"max_attempts": 1, "accumulate_critic": False, "retire_stale": False},
         "evoforge": {"rounds": 10, "verified": 10, "wilson95": [0.7225, 1.0]}},
        {"strategy_id": "st_cccccccccc", "runs": 1,
         "strategy": {"max_attempts": 2, "accumulate_critic": True, "retire_stale": False},
         "evoforge": {"rounds": 5, "verified": 3, "wilson95": [0.2307, 0.8824]}},
    ],
    "decisions": [{"promoted": "st_aaaaaaaaaa", "previous": "st_zzzzzzzzzz", "at": 1}],
}
DRIVER = r"""
const fs = require('fs'); const path = require('path');
const web = process.argv[1];
const ts = require(path.join(web, 'node_modules', 'typescript'));
const src = fs.readFileSync(path.join(web, 'lib', 'roundReplay.ts'), 'utf8');
const out = ts.transpileModule(src, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}});
const m = {exports: {}}; new Function('module', 'exports', 'require', out.outputText)(m, m.exports, require);
const L = m.exports; const o = JSON.parse(process.argv[2]);
console.log(JSON.stringify({v: L.strategiesView(o), n: L.strategiesView(null)}));
"""


@pytest.fixture(scope="module")
def out():
    node = shutil.which("node")
    if node is None or not (WEB / "node_modules" / "typescript").exists():
        pytest.skip("node + apps/web/node_modules required (npm ci)")
    r = subprocess.run([node, "-e", DRIVER, str(WEB), json.dumps(OVERVIEW)], capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_champion_first_and_rows(out):
    v = out["v"]
    assert v["champion"] == {"id": "st_aaaaaaaaaa", "label": "3 attempts · accumulate critic · retire stale"}
    rows = v["rows"]
    assert rows[0]["id"] == "st_aaaaaaaaaa" and rows[0]["isChampion"] is True
    lean = next(r for r in rows if r["id"] == "st_bbbbbbbbbb")
    assert lean["label"] == "1 attempt · this round's critic only · keep stale"
    assert (lean["verified"], lean["rate"], lean["interval"], lean["runs"]) == ("10/10", "100%", "72–100%", 2)


def test_promotable_follows_the_server_rule(out):
    rows = {r["id"]: r for r in out["v"]["rows"]}
    assert rows["st_bbbbbbbbbb"]["promotable"] is True  # 0.72 > champion upper 0.51
    assert rows["st_cccccccccc"]["promotable"] is False  # 0.23 overlaps
    assert rows["st_aaaaaaaaaa"]["promotable"] is False  # the champion itself


def test_decisions_and_empty(out):
    assert out["v"]["decisions"] == [{"promoted": "st_aaaaaaaaaa", "previous": "st_zzzzzzzzzz"}]
    assert out["n"] is None


def test_panel_wiring():
    comp = (WEB / "components" / "StrategiesPanel.tsx").read_text(encoding="utf-8")
    page = (WEB / "app" / "[locale]" / "replay" / "page.tsx").read_text(encoding="utf-8")
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "strategiesView" in comp and "StrategiesPanel" in page
    assert "getEvolutionStrategies" in api and "/v1/evolution/strategies" in api
    assert "promoteEvolutionStrategy" in api and "/v1/evolution/strategies/promote" in api
    assert "NEXT_PUBLIC_EVO_OPERATOR_CONTROLS" in comp  # promoting is an operator action
    for lang in ("en", "ko"):
        rep = json.loads((WEB / "messages" / f"{lang}.json").read_text(encoding="utf-8"))["replay"]
        for key in ("strategies-title", "strategies-champion", "strategies-promote", "strategies-promotable",
                    "strategies-history"):
            assert key in rep, (lang, key)
