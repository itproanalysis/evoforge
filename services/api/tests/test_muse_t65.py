"""Muse — T65 Arena prompt bar: the Arena page has a prompt input at the bottom and
shows a prompt-arena view (judge-written acceptance suite, unscorable warning,
judge cost apart from the lanes' costs) above the two lanes' SandboxedPreview."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
PROMPT_DOC = {
    "arena_id": "job_p", "status": "succeeded", "mode": "prompt",
    "prompt": "A landing page for Coffee Corner",
    "judge_cost_cents": 42,
    "manifest": {"acceptance_count": 3, "acceptance_dropped": 1,
                 "acceptance_hash": "sha256:" + "ab" * 32,
                 "prompt_hash": "sha256:" + "cd" * 32,
                 "judge": "An independent judge wrote the tests.",
                 "lanes": {"single": {"apply": "tolerant"},
                           "evoforge": {"apply": "tolerant"}}},
    "verdict": {"winner": "evoforge", "reason": "3/3 vs 1/3"},
    "lanes": {"single": {"status": "succeeded"},
              "evoforge": {"status": "succeeded"}},
}
DRIVER = r"""
const fs = require('fs'); const path = require('path');
const web = process.argv[1];
const ts = require(path.join(web, 'node_modules', 'typescript'));
const src = fs.readFileSync(path.join(web, 'lib', 'arenaStatus.ts'), 'utf8');
const out = ts.transpileModule(src, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}});
const m = {exports: {}}; new Function('module', 'exports', 'require', out.outputText)(m, m.exports, require);
const L = m.exports; const d = JSON.parse(process.argv[2]);
const running = Object.assign({}, d, {status: 'running'});
const thin = Object.assign({}, d, {manifest: {acceptance_count: 2, acceptance_dropped: 0}, verdict: {winner: 'single'}});
const unscore = Object.assign({}, d, {verdict: {winner: 'unscorable'}});
const bench = Object.assign({}, d, {mode: 'benchmark'});
const nocost = Object.assign({}, d); delete nocost.judge_cost_cents;
console.log(JSON.stringify({
  ok: L.promptArenaView(d),
  run: L.promptArenaView(running),
  thin: L.promptArenaView(thin),
  unscore: L.promptArenaView(unscore),
  bench: L.promptArenaView(bench),
  missing: L.promptArenaView(null),
  nocost: L.promptArenaView(nocost),
}));
"""


@pytest.fixture(scope="module")
def out():
    node = shutil.which("node")
    if node is None or not (WEB / "node_modules" / "typescript").exists():
        pytest.skip("node + apps/web/node_modules required (npm ci)")
    r = subprocess.run([node, "-e", DRIVER, str(WEB), json.dumps(PROMPT_DOC)],
                       capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_prompt_arena_view(out):
    v = out["ok"]
    assert v["prompt"] == "A landing page for Coffee Corner"
    assert v["acceptanceCount"] == 3 and v["dropped"] == 1
    assert v["scorable"] is True and v["winner"] == "evoforge"
    assert v["judgeCost"] == "42¢" and v["judge"] == "An independent judge wrote the tests."
    assert out["run"]["scorable"] is None and out["run"]["winner"] is None
    assert out["thin"]["scorable"] is False and out["thin"]["winner"] is None
    assert out["unscore"]["scorable"] is False and out["unscore"]["winner"] is None
    assert out["bench"] is None and out["missing"] is None
    assert out["nocost"]["judgeCost"] == "—"


def test_prompt_api_and_bar():
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "export function postPromptArena" in api
    assert "/v1/arena/prompt" in api
    head = api.split("export function postPromptArena", 1)[1].split("}", 1)[0]
    assert "critic" in head and "tolerant" in head
    bar = (WEB / "components" / "PromptBar.tsx").read_text(encoding="utf-8")
    assert "<textarea" in bar and "maxLength={2000}" in bar
    assert "2000" in bar  # character counter bound
    assert "prompt-placeholder" in bar and "prompt-start" in bar
    assert '"critic"' in bar and "postPromptArena" in bar
    assert "fixed" in bar and "bottom" in bar
    assert "getArenaLimits" in bar and "confirm(" in bar
    assert "planFits" in bar and "rounds" in bar
    assert "limit-reached" in bar and "arena_id" in bar


def test_prompt_page_and_i18n():
    page = (WEB / "app" / "[locale]" / "arena" / "page.tsx").read_text(encoding="utf-8")
    assert "PromptBar" in page and "promptArenaView" in page
    assert "prompt-unscorable" in page and "prompt-judge-cost" in page
    assert "prompt-acceptance" in page
    assert "SandboxedPreview" in page
    assert "pb-40" in page or "paddingBottom" in page
    for locale in ("en", "ko"):
        msgs = json.loads((WEB / "messages" / f"{locale}.json").read_text(encoding="utf-8"))
        arena = msgs["arena"]
        for key in ("prompt-placeholder", "prompt-start", "prompt-unscorable",
                    "prompt-judge-cost"):
            assert isinstance(arena.get(key), str) and arena[key].strip(), (locale, key)
