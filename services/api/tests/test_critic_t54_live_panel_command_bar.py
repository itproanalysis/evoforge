"""Sealed (Critic) — T54 live AI panel + command bar on the evolution screen (v3.8 §2.2 D3, v3.6 CMD-01): each role's
state comes only from recorded events; a command shows RECEIVED/QUEUED/REJECTED from the real HTTP answer and
RUNNING/APPLIED/FAILED from the real run status — never "done" before the server says so."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


def _ev(seq, role, msg):
    return {"seq": seq, "ts": 1000 + seq, "role": role, "message": msg}


RUN = {
    "run_id": "evo_live", "status": "running", "manifest": {"rounds": 5},
    "rounds": [
        {"index": 1, "name": "Initial Build", "sides": {
            "evoforge": {"status": "READY", "events": [_ev(1, "critic", "Critic suite: 3 tests (3 new)"),
                                                      _ev(2, "builder", "attempt 1/3"), _ev(3, "runner", "3/3 passed"),
                                                      _ev(4, "gate", "READY")]},
            "single": {"status": "READY", "events": [_ev(1, "builder", "one call"), _ev(2, "runner", "3/3 passed")]}}},
        {"index": 2, "name": "Feature Growth", "sides": {
            "evoforge": {"status": "PENDING", "events": [_ev(5, "critic", "Critic suite: 6 tests (3 new)"),
                                                        _ev(6, "builder", "attempt 1/3")]},
            "single": {"status": "PENDING"}}},
    ],
}

DRIVER = r"""
const fs = require('fs'); const path = require('path');
const web = process.argv[1];
const ts = require(path.join(web, 'node_modules', 'typescript'));
const src = fs.readFileSync(path.join(web, 'lib', 'roundReplay.ts'), 'utf8');
const out = ts.transpileModule(src, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}});
const m = {exports: {}}; new Function('module', 'exports', 'require', out.outputText)(m, m.exports, require);
const L = m.exports; const run = JSON.parse(process.argv[2]);
const done = JSON.parse(JSON.stringify(run)); done.status = 'succeeded';
console.log(JSON.stringify({
  evo: L.agentPanel(run, 'evoforge'), single: L.agentPanel(run, 'single'), evoDone: L.agentPanel(done, 'evoforge'),
  c202: L.commandState(202, null), c409: L.commandState(409, null), c402: L.commandState(402, null),
  c422: L.commandState(422, null), cRun: L.commandState(202, 'running'), cOk: L.commandState(202, 'succeeded'),
  cFail: L.commandState(202, 'failed'), cNone: L.commandState(null, null),
}));
"""


@pytest.fixture(scope="module")
def out():
    node = shutil.which("node")
    if node is None or not (WEB / "node_modules" / "typescript").exists():
        pytest.skip("node + apps/web/node_modules required (npm ci)")
    r = subprocess.run([node, "-e", DRIVER, str(WEB), json.dumps(RUN)], capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _by_role(panel):
    return {p["role"]: p for p in panel}


def test_agent_panel_comes_from_the_latest_events(out):
    evo = _by_role(out["evo"])
    assert [p["role"] for p in out["evo"]] == ["builder", "critic", "runner", "gate"]
    assert evo["builder"]["message"] == "attempt 1/3" and evo["builder"]["state"] == "active"  # newest event, run running
    assert evo["critic"]["message"] == "Critic suite: 6 tests (3 new)" and evo["critic"]["state"] == "done"
    assert evo["runner"]["message"] == "3/3 passed" and evo["gate"]["message"] == "READY"


def test_roles_without_events_are_idle_not_invented(out):
    single = _by_role(out["single"])
    assert single["critic"]["state"] == "idle" and single["critic"]["message"] is None  # the single lane has no Critic
    assert single["gate"]["state"] == "idle"
    assert all(p["state"] != "active" for p in out["evoDone"])  # nothing is active once the run has finished


def test_command_state_follows_the_server(out):
    assert out["c202"] == {"state": "QUEUED", "reason": None}
    assert out["c409"]["state"] == "REJECTED" and out["c409"]["reason"] == "busy"
    assert out["c402"]["state"] == "REJECTED" and out["c402"]["reason"] == "budget"
    assert out["c422"]["state"] == "REJECTED" and out["c422"]["reason"] == "invalid"
    assert out["cRun"]["state"] == "RUNNING" and out["cOk"]["state"] == "APPLIED" and out["cFail"]["state"] == "FAILED"
    assert out["cNone"] == {"state": "RECEIVED", "reason": None}  # sent, no answer yet


def test_command_bar_and_panel_wiring():
    bar = (WEB / "components" / "CommandBar.tsx").read_text(encoding="utf-8")
    panel = (WEB / "components" / "AgentPanel.tsx").read_text(encoding="utf-8")
    page = (WEB / "app" / "[locale]" / "replay" / "page.tsx").read_text(encoding="utf-8")
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "startEvolutionRun" in api and "/v1/evolution/runs" in api
    assert "startEvolutionRun" in bar and "commandState" in bar
    assert "agentPanel" in panel
    assert "CommandBar" in page and "AgentPanel" in page
    for lang in ("en", "ko"):
        msgs = json.loads((WEB / "messages" / f"{lang}.json").read_text(encoding="utf-8"))
        rep = msgs["replay"]
        for key in ("start", "cost-warning", "state-received", "state-queued", "state-running", "state-applied",
                    "state-rejected", "state-failed", "agents", "idle", "active", "done"):
            assert key in rep, (lang, key)
