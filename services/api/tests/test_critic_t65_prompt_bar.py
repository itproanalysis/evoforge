"""Sealed (Critic) — T65 Arena prompt bar (owner: the Arena has a prompt input at the bottom and compares what the user
asks for). The view shows the user's prompt, how the judge's acceptance suite was formed (count, dropped, scorable or
not) and the judge cost separately from the lanes; a run with too few tests never shows a winner."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
DOC = {"arena_id": "job_p", "mode": "prompt", "status": "succeeded", "prompt": "A coffee shop landing page",
       "judge_cost_cents": 4,
       "manifest": {"acceptance_count": 3, "acceptance_dropped": 1, "acceptance_hash": "sha256:" + "a" * 64,
                    "prompt_hash": "sha256:" + "b" * 64, "judge": "independent Critic, written before the lanes"},
       "verdict": {"winner": "evoforge", "reason": "evoforge wins 3-1"}}
DRIVER = r"""
const fs = require('fs'); const path = require('path');
const web = process.argv[1];
const ts = require(path.join(web, 'node_modules', 'typescript'));
const src = fs.readFileSync(path.join(web, 'lib', 'arenaStatus.ts'), 'utf8');
const out = ts.transpileModule(src, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}});
const m = {exports: {}}; new Function('module', 'exports', 'require', out.outputText)(m, m.exports, require);
const L = m.exports; const d = JSON.parse(process.argv[2]);
const un = JSON.parse(process.argv[2]); un.manifest.acceptance_count = 1; un.verdict = {winner: 'unscorable', reason: 'x'};
const run = JSON.parse(process.argv[2]); run.status = 'running'; delete run.verdict;
console.log(JSON.stringify({v: L.promptArenaView(d), u: L.promptArenaView(un), r: L.promptArenaView(run),
  s: L.promptArenaView({arena_id: 'y', mode: 'sealed'}), n: L.promptArenaView(null)}));
"""


@pytest.fixture(scope="module")
def out():
    node = shutil.which("node")
    if node is None or not (WEB / "node_modules" / "typescript").exists():
        pytest.skip("node + apps/web/node_modules required (npm ci)")
    r = subprocess.run([node, "-e", DRIVER, str(WEB), json.dumps(DOC)], capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_prompt_view(out):
    v = out["v"]
    assert v["prompt"] == "A coffee shop landing page"
    assert (v["acceptanceCount"], v["dropped"], v["scorable"], v["judgeCost"]) == (3, 1, True, "4¢")
    assert v["winner"] == "evoforge" and v["judge"].startswith("independent Critic")


def test_unscorable_and_running_show_no_winner(out):
    assert out["u"]["scorable"] is False and out["u"]["winner"] is None
    assert out["r"]["winner"] is None and out["r"]["scorable"] is None  # nothing decided while running
    assert out["s"] is None and out["n"] is None  # only prompt-mode arenas get this view


def test_prompt_bar_wiring():
    page = (WEB / "app" / "[locale]" / "arena" / "page.tsx").read_text(encoding="utf-8")
    bar = (WEB / "components" / "PromptBar.tsx").read_text(encoding="utf-8")
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "PromptBar" in page and "promptArenaView" in page
    assert "<textarea" in bar and "maxLength={2000}" in bar.replace(" ", "")
    assert "fixed" in bar or "sticky" in bar  # always visible at the bottom
    # Owner decision 2026-10-30 (T84/T85): anyone may start, bounded by the server's daily run limit; spend confirm stays.
    assert "getArenaLimits" in bar and "confirm(" in bar
    assert "postPromptArena" in api and "/v1/arena/prompt" in api
    for lang in ("en", "ko"):
        a = json.loads((WEB / "messages" / f"{lang}.json").read_text(encoding="utf-8"))
        flat = json.dumps(a)
        for key in ("prompt-placeholder", "prompt-start", "prompt-unscorable", "prompt-judge-cost"):
            assert f'"{key}"' in flat, (lang, key)
