"""Muse (Builder) - T69 home workspace on / (web only).

arenaAgentPanel maps a lane's recorded events to four agent rows, and the
home page becomes the workspace: AI status left, implementation right,
PromptBar at the bottom, Mission Control preserved in a collapsible section.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"

DRIVER = """import { arenaAgentPanel } from "./arenaStatus.ts";
const ev = (seq, role, message) => ({ seq, ts: seq, role, message });
const lane = (status, events) => ({ status, attempts: 1,
  heldout: { passed: 1, n: 2 }, outcome: "passed", cost_cents: 0,
  usage_missing: false, elapsed_ms: 1, diff: "", events });
const doc = (status, single, evoforge, extra) => Object.assign(
  { arena_id: "a", status, mode: "prompt", prompt: "make a page",
    suite_version: "v2", task_id: "t", model: "m", goal: "g", created_at: 7,
    lanes: { single, evoforge }, verdict: { winner: "tie", reason: "r" } },
  extra || {});
const runningLane = lane("running", [ev(1, "builder", "b1"), ev(2, "critic", "c1")]);
const running = doc("running", runningLane, lane("running", [ev(1, "builder", "b")]));
const finishedLane = doc("running", lane("succeeded", [ev(1, "builder", "b1"), ev(2, "critic", "c1")]), lane("running", []));
const settled = doc("succeeded", lane("running", [ev(1, "builder", "b1")]), lane("running", [ev(1, "runner", "r1")]));
const failed = doc("failed", lane("failed", [ev(1, "gate", "g1")]), lane("failed", []));
const sysNewest = doc("running", lane("running", [ev(1, "builder", "b1"), ev(2, "system", "boot")]), lane("running", []));
const multi = doc("running", lane("running", [ev(1, "builder", "old"), ev(3, "builder", "new"), ev(2, "runner", "r")]), lane("running", []));
const tieOrder = doc("running", lane("running", [ev(5, "builder", "first"), ev(5, "critic", "second")]), lane("running", []));
const noLanes = { arena_id: "x", status: "running" };
console.log(JSON.stringify({
  nullDoc: arenaAgentPanel(null, "evoforge"),
  noLanes: arenaAgentPanel(noLanes, "single"),
  runSingle: arenaAgentPanel(running, "single"),
  runEvo: arenaAgentPanel(running, "evoforge"),
  finishedLane: arenaAgentPanel(finishedLane, "single"),
  settled: arenaAgentPanel(settled, "single"),
  settledEvo: arenaAgentPanel(settled, "evoforge"),
  failed: arenaAgentPanel(failed, "single"),
  sysNewest: arenaAgentPanel(sysNewest, "single"),
  multi: arenaAgentPanel(multi, "single"),
  tieOrder: arenaAgentPanel(tieOrder, "single"),
}));
"""


def _run_driver(tmp_path: Path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node required (the Cloud Build test image has none; CI web job runs it)")
    for name in ("arenaStatus.ts", "api.ts"):
        shutil.copy(WEB / "lib" / name, tmp_path / name)
    text = (tmp_path / "arenaStatus.ts").read_text(encoding="utf-8")
    (tmp_path / "arenaStatus.ts").write_text(
        text.replace('from "./api"', 'from "./api.ts"'), encoding="utf-8"
    )
    driver = tmp_path / "driver.mjs"
    driver.write_text(DRIVER, encoding="utf-8")
    r = subprocess.run([node, str(driver)], capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _by_role(rows):
    return {row["role"]: row for row in rows}


def test_agent_panel_null_doc_is_all_idle(tmp_path):
    out = _run_driver(tmp_path)
    rows = out["nullDoc"]
    assert [r["role"] for r in rows] == ["builder", "critic", "runner", "gate"]
    for row in rows:
        assert row["state"] == "idle" and row["message"] is None
    rows = out["noLanes"]
    assert [r["role"] for r in rows] == ["builder", "critic", "runner", "gate"]
    assert all(r["state"] == "idle" and r["message"] is None for r in rows)


def test_agent_panel_running_lane_newest_is_active(tmp_path):
    out = _run_driver(tmp_path)
    rows = _by_role(out["runSingle"])
    assert rows["critic"] == {"role": "critic", "state": "active", "message": "c1"}
    assert rows["builder"] == {"role": "builder", "state": "done", "message": "b1"}
    assert rows["runner"]["state"] == "idle" and rows["runner"]["message"] is None
    assert rows["gate"]["state"] == "idle" and rows["gate"]["message"] is None
    evo = _by_role(out["runEvo"])
    assert evo["builder"]["state"] == "active" and evo["builder"]["message"] == "b"


def test_agent_panel_never_invents_activity(tmp_path):
    out = _run_driver(tmp_path)
    # Finished lane: newest role is done, never active.
    fin = _by_role(out["finishedLane"])
    assert fin["critic"]["state"] == "done" and fin["critic"]["message"] == "c1"
    assert all(r["state"] != "active" for r in out["finishedLane"])
    # Settled/failed arena: no active rows even with a running lane.
    for key in ("settled", "settledEvo", "failed"):
        assert all(r["state"] != "active" for r in out[key]), key
    settled = _by_role(out["settled"])
    assert settled["builder"]["state"] == "done"
    # Lane-newest event from an unknown role: no agent row goes active.
    sys_rows = out["sysNewest"]
    assert all(r["state"] != "active" for r in sys_rows)
    assert _by_role(sys_rows)["builder"]["state"] == "done"


def test_agent_panel_message_is_role_newest(tmp_path):
    out = _run_driver(tmp_path)
    multi = _by_role(out["multi"])
    assert multi["builder"]["message"] == "new"
    assert multi["builder"]["state"] == "active"
    assert multi["runner"]["message"] == "r" and multi["runner"]["state"] == "done"
    # Equal seq: the later recorded event wins.
    tie = _by_role(out["tieOrder"])
    assert tie["critic"]["state"] == "active" and tie["critic"]["message"] == "second"
    assert tie["builder"]["state"] == "done"


def test_home_workspace_wiring():
    status = (WEB / "lib" / "arenaStatus.ts").read_text(encoding="utf-8")
    assert "export function arenaAgentPanel" in status
    page = (WEB / "app" / "[locale]" / "page.tsx").read_text(encoding="utf-8")
    for token in (
        "arenaAgentPanel",
        "previewView",
        "SandboxedPreview",
        "PromptBar",
        "listArenas",
        "getArena",
        "setInterval",
        "/arena",
        "/replay",
        "state-dot-",
        "active",
        "onStarted",
    ):
        assert token in page, token
    # Collapsible Mission Control below the workspace; behaviour preserved.
    assert "<details" in page or "aria-expanded" in page
    for token in (
        "ProofCard",
        "EventSource",
        "getPerformance",
        "listMissions",
        "getParticipants",
        "listOutcomes",
        "postMission",
    ):
        assert token in page, token
    # Responsive stacking for narrow screens.
    assert "768" in page
    assert "md:grid-cols-3" in page or "md:flex-row" in page


def test_home_workspace_i18n():
    page = (WEB / "app" / "[locale]" / "page.tsx").read_text(encoding="utf-8")
    assert 'useTranslations("workspace")' in page
    keys = set()
    for lang in ("en", "ko"):
        raw = (WEB / "messages" / f"{lang}.json").read_text(encoding="utf-8")
        msgs = json.loads(raw)
        ws = msgs.get("workspace")
        assert isinstance(ws, dict) and ws, lang
        for key in (
            "heading",
            "ai-status-heading",
            "implementation-heading",
            "view-arena",
            "view-replay",
        ):
            assert isinstance(ws.get(key), str) and ws[key].strip(), (lang, key)
        keys.add(tuple(sorted(ws.keys())))
    assert len(keys) == 1, "en + ko workspace keys must match"
