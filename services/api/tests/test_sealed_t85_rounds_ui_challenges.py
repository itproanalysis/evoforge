"""Sealed (Critic) — T85 owner: per-round missions from the input, fun challenges, anyone may start within the daily
limit (owner decision 2026-10-30, replaces the operator-only start). The input can hold missions for up to 5 rounds
(add / remove), challenge presets fill them, the start shows today's remaining runs from GET /v1/arena/limits and is
disabled when a plan would not fit; the spend confirmation stays."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
DRIVER = r"""
const fs = require('fs'); const path = require('path');
const web = process.argv[1];
const ts = require(path.join(web, 'node_modules', 'typescript'));
const src = fs.readFileSync(path.join(web, 'lib', 'challenges.ts'), 'utf8');
const out = ts.transpileModule(src, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}});
const m = {exports: {}}; new Function('module', 'exports', 'require', out.outputText)(m, m.exports, require);
console.log(JSON.stringify({challenges: m.exports.CHALLENGES, fits: [m.exports.planFits(3, 2), m.exports.planFits(3, 3), m.exports.planFits(null, 1)]}));
"""


@pytest.fixture(scope="module")
def lib():
    node = shutil.which("node")
    if node is None or not (WEB / "node_modules" / "typescript").exists():
        pytest.skip("node + apps/web/node_modules required (npm ci)")
    r = subprocess.run([node, "-e", DRIVER, str(WEB)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_challenges_are_multi_round_and_bilingual(lib):
    ch = lib["challenges"]
    assert len(ch) >= 5 and len({c["id"] for c in ch}) == len(ch)
    for c in ch:
        for loc in ("en", "ko"):
            assert c["title"][loc].strip()
            rounds = c["rounds"][loc]
            assert 2 <= len(rounds) <= 5, (c["id"], loc)
            assert all(10 <= len(r) <= 300 for r in rounds), (c["id"], loc)
        assert len(c["rounds"]["en"]) == len(c["rounds"]["ko"])


def test_plan_fits_the_remaining_daily_runs(lib):
    # planFits(remaining, rounds): a plan of N rounds needs N runs; unknown remaining (null) never blocks the UI
    # (the server still enforces the limit).
    assert lib["fits"] == [True, True, True]


def test_plan_fits_rejects_over_limit():
    node = shutil.which("node")
    if node is None or not (WEB / "node_modules" / "typescript").exists():
        pytest.skip("node required")
    drv = DRIVER.replace("fits: [m.exports.planFits(3, 2), m.exports.planFits(3, 3), m.exports.planFits(null, 1)]",
                         "fits: [m.exports.planFits(2, 3), m.exports.planFits(0, 1)]")
    r = subprocess.run([node, "-e", drv, str(WEB)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["fits"] == [False, False]


def test_prompt_bar_rounds_limits_and_public_start():
    bar = (WEB / "components" / "PromptBar.tsx").read_text(encoding="utf-8")
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "getArenaLimits" in bar and "planFits" in bar and "CHALLENGES" in bar
    assert "rounds" in bar and "confirm(" in bar  # spend confirmation stays
    assert "NEXT_PUBLIC_EVO_OPERATOR_CONTROLS" not in bar  # the daily limit replaces the operator-only start
    assert "export function getArenaLimits" in api and "/v1/arena/limits" in api
    post = api.split("export function postPromptArena", 1)[1].split("\n}", 1)[0]
    assert "rounds" in post
    for loc in ("en", "ko"):
        m = json.loads((WEB / "messages" / f"{loc}.json").read_text(encoding="utf-8"))
        for k in ("add-round", "remove-round", "remaining-today", "limit-reached", "challenges"):
            assert m.get("plan", {}).get(k), (loc, k)
