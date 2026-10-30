"""T67 prompt-chain UI (web only)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"

DRIVER = r"""
const fs = require('fs'); const path = require('path');
const web = process.argv[1];
const ts = require(path.join(web, 'node_modules', 'typescript'));
const src = fs.readFileSync(path.join(web, 'lib', 'arenaStatus.ts'), 'utf8');
const out = ts.transpileModule(src, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}});
const m = {exports: {}}; new Function('module', 'exports', 'require', out.outputText)(m, m.exports, require);
const L = m.exports;
const lane = (passed, n, html, status) => ({status: status || 'succeeded', attempts: 1,
  heldout: {passed, n}, outcome: 'passed', cost_cents: 0, preview_html: html});
const mk = (o) => Object.assign({arena_id: 'a1', mode: 'prompt', status: 'succeeded', prompt: 'p1',
  round_index: 1, manifest: {acceptance_count: 3}, verdict: {winner: 'evoforge', reason: 'r'},
  lanes: {single: lane(1, 3, '<s1>', 'succeeded'), evoforge: lane(2, 3, '<e1>', 'succeeded')}}, o || {});
const fin = mk({});
const run = mk({arena_id: 'a2', round_index: 2, status: 'running', prompt: 'p2',
  lanes: {single: lane(0, 3, '<s>', 'running'), evoforge: lane(0, 3, '<e>', 'running')}});
const unsc = mk({arena_id: 'a3', round_index: 3, verdict: {winner: 'unscorable', reason: 'x'}});
const few = mk({arena_id: 'a4', round_index: 4, manifest: {acceptance_count: 2}, verdict: {winner: 'evoforge', reason: 'r'}});
console.log(JSON.stringify({
  followOk: L.canFollowUp(fin),
  followRun: L.canFollowUp(run),
  followSealed: L.canFollowUp({arena_id: 's', mode: 'sealed', status: 'succeeded'}),
  followNull: L.canFollowUp(null),
  emptyNull: L.promptChainView(null),
  emptyArr: L.promptChainView([]),
  emptyObj: L.promptChainView({rounds: []}),
  rows: L.promptChainView({rounds: [run, few, unsc, fin]}),
  arrForm: L.promptChainView([fin]),
}));
"""


def _run_driver():
    node = shutil.which("node")
    if node is None or not (WEB / "node_modules" / "typescript").exists():
        import pytest
        pytest.skip("node + apps/web/node_modules required (npm ci)")
    r = subprocess.run([node, "-e", DRIVER, str(WEB)], capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_chain_view_and_follow_gate():
    out = _run_driver()
    assert out["followOk"] is True
    assert out["followRun"] is False
    assert out["followSealed"] is False
    assert out["followNull"] is False
    assert out["emptyNull"] == [] and out["emptyArr"] == [] and out["emptyObj"] == []
    rows = out["rows"]
    assert [x["round"] for x in rows] == [1, 2, 3, 4]
    r1 = rows[0]
    assert (r1["arenaId"], r1["prompt"], r1["running"]) == ("a1", "p1", False)
    assert (r1["single"], r1["evoforge"]) == ("1/3", "2/3")
    assert (r1["singlePreview"], r1["evoforgePreview"]) == ("<s1>", "<e1>")
    assert r1["winner"] == "evoforge" and r1["unscorable"] is False
    r2 = rows[1]
    assert r2["running"] is True and r2["winner"] is None
    assert (r2["single"], r2["evoforge"]) == ("—", "—")
    assert r2["singlePreview"] is None and r2["evoforgePreview"] is None
    assert rows[2]["unscorable"] is True and rows[2]["winner"] is None
    assert rows[3]["unscorable"] is True and rows[3]["winner"] is None
    assert len(out["arrForm"]) == 1


def test_chain_wiring():
    status = (WEB / "lib" / "arenaStatus.ts").read_text(encoding="utf-8")
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    bar = (WEB / "components" / "PromptBar.tsx").read_text(encoding="utf-8")
    page = (WEB / "app" / "[locale]" / "arena" / "page.tsx").read_text(encoding="utf-8")
    assert "canFollowUp" in status and "promptChainView" in status
    assert "postPromptFollowup" in api and "getPromptChain" in api
    assert "/v1/arena/" in api and "followup" in api and "chain" in api
    assert "postPromptFollowup" in bar and "canFollowUp" in bar
    assert "prompt-followup-placeholder" in bar and "prompt-followup-start" in bar
    assert "getArenaLimits" in bar and "confirm(" in bar
    assert "planFits" in bar and "rounds" in bar
    assert "promptChainView" in page and "getPromptChain" in page
    assert "canFollowUp" in page and "SandboxedPreview" in page
    assert "prompt-chain-title" in page and "setInterval" in page
    for lang in ("en", "ko"):
        msgs = json.loads((WEB / "messages" / f"{lang}.json").read_text(encoding="utf-8"))
        flat = json.dumps(msgs)
        for key in ("prompt-followup-placeholder", "prompt-followup-start", "prompt-chain-title"):
            assert f'"{key}"' in flat, (lang, key)
