"""Builder-side checks for T54 live AI panel + command bar (v3.8 D3 Mission Control)."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "apps" / "web"
LIB = WEB / "lib" / "roundReplay.ts"
API = WEB / "lib" / "api.ts"
PANEL = WEB / "components" / "AgentPanel.tsx"
BAR = WEB / "components" / "CommandBar.tsx"
PAGE = WEB / "app" / "[locale]" / "replay" / "page.tsx"
TSC = WEB / "node_modules" / "typescript" / "bin" / "tsc"

REQUIRED_KEYS = {
    "start", "cost-warning", "state-received", "state-queued",
    "state-running", "state-applied", "state-rejected", "state-failed",
    "agents", "idle", "active", "done",
}


def _ev(seq, role, message):
    return {"seq": seq, "ts": 1700000000 + seq, "role": role, "message": message}


def _run(status="running"):
    return {
        "run_id": "r1", "app_id": "a", "title": "t", "status": status,
        "rounds": [
            {"index": 1, "name": "R1", "sides": {
                "evoforge": {"status": "READY", "events": [
                    _ev(1, "builder", "b1"), _ev(2, "critic", "c1"),
                    _ev(3, "runner", "r1"), _ev(4, "gate", "g1")]},
                "single": {"status": "READY", "events": [
                    _ev(1, "builder", "sb1"), _ev(2, "runner", "sr1"),
                    _ev(3, "gate", "sg1")]},
            }},
            {"index": 2, "name": "R2", "sides": {
                "evoforge": {"status": "READY", "events": [_ev(5, "builder", "b2")]},
                "single": {"status": "PENDING", "events": []},
            }},
        ],
    }


@pytest.fixture(scope="module")
def built():
    if not TSC.exists() or not shutil.which("node"):
        pytest.skip("node/typescript not installed in apps/web")
    assert LIB.exists()
    out = Path(tempfile.mkdtemp())
    r = subprocess.run(
        ["node", str(TSC), str(LIB), "--outDir", str(out),
         "--module", "commonjs", "--target", "es2019",
         "--skipLibCheck", "--esModuleInterop"],
        capture_output=True, text=True, encoding="utf-8", cwd=WEB)
    assert r.returncode == 0, r.stdout + r.stderr
    return next(out.rglob("roundReplay.js"))


def _call(js: Path, expr: str, *args):
    payload = json.dumps(list(args))
    code = ("const m=require(%s);const a=JSON.parse(process.argv[1]);"
            "process.stdout.write(JSON.stringify((%s).apply(null,a)));") % (
        json.dumps(str(js)), expr)
    r = subprocess.run(["node", "-e", code, payload],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_agent_panel_live_rows(built):
    rows = _call(built, "m.agentPanel", _run("running"), "evoforge")
    assert [x["role"] for x in rows] == ["builder", "critic", "runner", "gate"]
    by = {x["role"]: x for x in rows}
    assert by["builder"] == {"role": "builder", "state": "active", "message": "b2"}
    assert by["critic"] == {"role": "critic", "state": "done", "message": "c1"}
    assert by["runner"] == {"role": "runner", "state": "done", "message": "r1"}
    assert by["gate"] == {"role": "gate", "state": "done", "message": "g1"}


def test_agent_panel_single_lane_never_invents_critic(built):
    rows = _call(built, "m.agentPanel", _run("running"), "single")
    by = {x["role"]: x for x in rows}
    assert by["critic"] == {"role": "critic", "state": "idle", "message": None}
    assert by["gate"]["state"] == "active" and by["gate"]["message"] == "sg1"
    assert by["builder"]["state"] == "done"


def test_agent_panel_done_when_not_running(built):
    rows = _call(built, "m.agentPanel", _run("succeeded"), "evoforge")
    by = {x["role"]: x for x in rows}
    assert by["builder"] == {"role": "builder", "state": "done", "message": "b2"}
    empty = _call(built, "m.agentPanel", {"run_id": "x", "status": "running"}, "evoforge")
    assert all(x["state"] == "idle" and x["message"] is None for x in empty)


def test_command_state_mapping(built):
    assert _call(built, "m.commandState", None, None) == {"state": "RECEIVED", "reason": None}
    assert _call(built, "m.commandState", 409, "running") == {"state": "REJECTED", "reason": "busy"}
    assert _call(built, "m.commandState", 402, None) == {"state": "REJECTED", "reason": "budget"}
    assert _call(built, "m.commandState", 422, None) == {"state": "REJECTED", "reason": "invalid"}
    assert _call(built, "m.commandState", 500, None) == {"state": "REJECTED", "reason": "error"}
    assert _call(built, "m.commandState", 202, "running") == {"state": "RUNNING", "reason": None}
    assert _call(built, "m.commandState", 202, "succeeded") == {"state": "APPLIED", "reason": None}
    assert _call(built, "m.commandState", 202, "failed") == {"state": "FAILED", "reason": None}
    assert _call(built, "m.commandState", 202, None) == {"state": "QUEUED", "reason": None}


def test_lib_stays_pure():
    src = LIB.read_text(encoding="utf-8")
    assert "agentPanel" in src and "commandState" in src
    assert "fetch(" not in src and "react" not in src.lower()
    lines = [ln.strip() for ln in src.splitlines() if ln.strip() and not ln.strip().startswith("//")]
    assert not any(ln.startswith("import ") or ln.startswith("import{") for ln in lines)
    assert "require(" not in src


def test_api_start_and_apps():
    src = API.read_text(encoding="utf-8")
    assert "startEvolutionRun" in src and "listEvolutionApps" in src
    assert "/v1/evolution/runs" in src and "/v1/evolution/apps" in src
    body = src[src.index("startEvolutionRun"):src.index("startEvolutionRun") + 1200]
    assert "POST" in body and "status" in body and "body" in body
    assert "402" in src and "409" in src and "422" in src


def test_agent_panel_component():
    src = PANEL.read_text(encoding="utf-8")
    assert "agentPanel" in src
    for token in ("builder", "critic", "runner", "gate", "active", "done", "idle"):
        assert token in src, token
    assert "evoforge" in src and "single" in src


def test_command_bar_component():
    src = BAR.read_text(encoding="utf-8")
    assert "listEvolutionApps" in src and "startEvolutionRun" in src
    assert "commandState" in src
    assert "fixed" in src and "bottom" in src
    assert "upper bound" in src and "critic" in src and "heldout" in src
    assert "cost-warning" in src


def test_page_wires_panel_and_bar():
    src = PAGE.read_text(encoding="utf-8")
    assert "AgentPanel" in src and "CommandBar" in src
    assert "RoundReplay" in src and "onStarted" in src


def test_replay_i18n_keys():
    for name in ("en.json", "ko.json"):
        msgs = json.loads((WEB / "messages" / name).read_text(encoding="utf-8"))
        assert REQUIRED_KEYS <= set(msgs.get("replay", {})), name
