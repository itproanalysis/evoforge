"""Sealed (Critic) — T69 home workspace (owner's page vision: feature tabs far left, AI status on the left of the main
area, the implementation on the right, the input at the bottom; watch the result evolve live). The AI panel for an
Arena comes only from recorded lane events; the existing Mission Control features stay available."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


def _ev(seq, role, msg):
    return {"seq": seq, "ts": seq, "role": role, "message": msg}


DOC = {"arena_id": "job_x", "mode": "prompt", "status": "running", "lanes": {
    "evoforge": {"status": "running", "events": [_ev(1, "critic", "Critic wrote 4 tests"), _ev(2, "builder", "attempt 1/3"),
                                                 _ev(3, "runner", "attempt 1 critic 3/4 failed"), _ev(4, "builder", "attempt 2/3")]},
    "single": {"status": "succeeded", "events": [_ev(1, "builder", "one call"), _ev(2, "gate", "single: passed")]}}}
DRIVER = r"""
const fs = require('fs'); const path = require('path');
const web = process.argv[1];
const ts = require(path.join(web, 'node_modules', 'typescript'));
const src = fs.readFileSync(path.join(web, 'lib', 'arenaStatus.ts'), 'utf8');
const out = ts.transpileModule(src, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}});
const m = {exports: {}}; new Function('module', 'exports', 'require', out.outputText)(m, m.exports, require);
const L = m.exports; const d = JSON.parse(process.argv[2]);
const done = JSON.parse(process.argv[2]); done.status = 'succeeded';
console.log(JSON.stringify({e: L.arenaAgentPanel(d, 'evoforge'), s: L.arenaAgentPanel(d, 'single'),
  ed: L.arenaAgentPanel(done, 'evoforge'), n: L.arenaAgentPanel(null, 'evoforge')}));
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


def _by(rows):
    return {r["role"]: r for r in rows}


def test_agent_panel_from_arena_events(out):
    e = _by(out["e"])
    assert [r["role"] for r in out["e"]] == ["builder", "critic", "runner", "gate"]
    assert e["builder"]["state"] == "active" and e["builder"]["message"] == "attempt 2/3"
    assert e["critic"]["state"] == "done" and e["runner"]["message"] == "attempt 1 critic 3/4 failed"
    assert e["gate"]["state"] == "idle" and e["gate"]["message"] is None


def test_finished_lane_and_single_have_no_invented_activity(out):
    s = _by(out["s"])
    assert s["critic"]["state"] == "idle"  # the single lane has no Critic
    assert all(r["state"] != "active" for r in out["s"])  # that lane already finished
    assert all(r["state"] != "active" for r in out["ed"])
    assert out["n"] == [{"role": r, "state": "idle", "message": None} for r in ("builder", "critic", "runner", "gate")]


def test_home_layout_keeps_mission_control():
    page = (WEB / "app" / "[locale]" / "page.tsx").read_text(encoding="utf-8")
    assert "PromptBar" in page and "SandboxedPreview" in page and "arenaAgentPanel" in page
    assert "EventSource" in page and "getDashboard" in page or "dashboard" in page  # Mission Control features remain
    assert "<details" in page or "aria-expanded" in page  # moved into a collapsible section, not deleted
