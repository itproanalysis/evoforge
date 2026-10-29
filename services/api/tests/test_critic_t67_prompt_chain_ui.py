"""Sealed (Critic) — T67 prompt-chain UI: after a prompt arena finishes the bottom bar sends follow-ups to that arena;
the page shows the chain R1..Rn with each round's request, both sides' cumulative scores and the winner (none when a
round is unscorable or still running), and selecting a round shows that round's two previews."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


def _lane(p, n, html):
    return {"status": "succeeded", "heldout": {"passed": p, "n": n}, "preview_source": "candidate", "preview_html": html}


CHAIN = {"rounds": [
    {"arena_id": "a1", "mode": "prompt", "status": "succeeded", "round_index": 1, "prompt": "coffee page",
     "manifest": {"acceptance_count": 3}, "verdict": {"winner": "evoforge"},
     "lanes": {"single": _lane(1, 3, "<p>s1</p>"), "evoforge": _lane(3, 3, "<p>e1</p>")}},
    {"arena_id": "a2", "mode": "prompt", "status": "succeeded", "round_index": 2, "prompt": "add footer",
     "manifest": {"acceptance_count": 2}, "verdict": {"winner": "unscorable"},
     "lanes": {"single": _lane(2, 2, "<p>s2</p>"), "evoforge": _lane(2, 2, "<p>e2</p>")}},
    {"arena_id": "a3", "mode": "prompt", "status": "running", "round_index": 3, "prompt": "dark mode",
     "manifest": {}, "lanes": {"single": {"status": "running"}, "evoforge": {"status": "running"}}},
]}
DRIVER = r"""
const fs = require('fs'); const path = require('path');
const web = process.argv[1];
const ts = require(path.join(web, 'node_modules', 'typescript'));
const src = fs.readFileSync(path.join(web, 'lib', 'arenaStatus.ts'), 'utf8');
const out = ts.transpileModule(src, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}});
const m = {exports: {}}; new Function('module', 'exports', 'require', out.outputText)(m, m.exports, require);
const L = m.exports; const ch = JSON.parse(process.argv[2]);
console.log(JSON.stringify({rows: L.promptChainView(ch), empty: L.promptChainView({rounds: []}), none: L.promptChainView(null),
  can: [L.canFollowUp(ch.rounds[0]), L.canFollowUp(ch.rounds[2]), L.canFollowUp({mode: 'sealed', status: 'succeeded'}), L.canFollowUp(null)]}));
"""


@pytest.fixture(scope="module")
def out():
    node = shutil.which("node")
    if node is None or not (WEB / "node_modules" / "typescript").exists():
        pytest.skip("node + apps/web/node_modules required (npm ci)")
    r = subprocess.run([node, "-e", DRIVER, str(WEB), json.dumps(CHAIN)], capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_chain_rows(out):
    r1, r2, r3 = out["rows"]
    assert (r1["round"], r1["prompt"], r1["arenaId"]) == (1, "coffee page", "a1")
    assert (r1["single"], r1["evoforge"], r1["winner"]) == ("1/3", "3/3", "evoforge")
    assert (r1["singlePreview"], r1["evoforgePreview"]) == ("<p>s1</p>", "<p>e1</p>")
    assert r2["winner"] is None and r2["unscorable"] is True  # unscorable round: no winner
    assert r3["winner"] is None and r3["running"] is True and r3["single"] == "—"
    assert out["empty"] == [] and out["none"] == []


def test_follow_up_only_from_a_finished_prompt_arena(out):
    assert out["can"] == [True, False, False, False]


def test_wiring():
    page = (WEB / "app" / "[locale]" / "arena" / "page.tsx").read_text(encoding="utf-8")
    bar = (WEB / "components" / "PromptBar.tsx").read_text(encoding="utf-8")
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "promptChainView" in page and "canFollowUp" in page
    assert "postPromptFollowup" in api and "/followup" in api and "getPromptChain" in api and "/chain" in api
    assert "postPromptFollowup" in bar or "onFollowup" in bar
    for lang in ("en", "ko"):
        flat = (WEB / "messages" / f"{lang}.json").read_text(encoding="utf-8")
        for key in ("prompt-followup-placeholder", "prompt-followup-start", "prompt-chain-title"):
            assert f'"{key}"' in flat, (lang, key)
