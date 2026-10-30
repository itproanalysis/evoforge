"""Sealed (Critic) — T59 Arena page shows the fairness manifest (T48) and both lanes' rendered previews (T49), offers the
Critic-feedback mode (T50), and only the operator build can start a paid arena (v3.8 §4.3: live dual runs are paid)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
H = "sha256:" + "ab" * 32
DOC = {
    "arena_id": "job_x", "status": "succeeded",
    "manifest": {"task_spec_hash": H, "heldout_hash": "sha256:" + "cd" * 32, "base_tree_sha": "ef" * 20,
                 "cost_basis": "model_api_usage", "runner_cost": "not_measured", "disclosure": "Same task, same tests.",
                 "lanes": {"single": {"harness": "api-sealed-eval/1", "max_attempts": 1, "feedback": "none"},
                           "evoforge": {"harness": "api-sealed-eval/2", "max_attempts": 3, "feedback": "critic"}}},
    "lanes": {"single": {"status": "succeeded", "preview_source": "base", "preview_html": "<p>base</p>"},
              "evoforge": {"status": "succeeded", "preview_source": "candidate", "preview_html": "<svg/>"}},
}
DRIVER = r"""
const fs = require('fs'); const path = require('path');
const web = process.argv[1];
const ts = require(path.join(web, 'node_modules', 'typescript'));
const src = fs.readFileSync(path.join(web, 'lib', 'arenaStatus.ts'), 'utf8');
const out = ts.transpileModule(src, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}});
const m = {exports: {}}; new Function('module', 'exports', 'require', out.outputText)(m, m.exports, require);
const L = m.exports; const d = JSON.parse(process.argv[2]);
const held = JSON.parse(process.argv[2]); held.manifest.lanes.evoforge.feedback = 'heldout_failing_test_names';
const none = {status: 'succeeded', preview_source: 'none', preview_error: 'timeout'};
const running = {status: 'running'};
console.log(JSON.stringify({
  m: L.manifestView(d), mh: L.manifestView(held), m0: L.manifestView({arena_id: 'x'}),
  pe: L.previewView(d.lanes.evoforge), ps: L.previewView(d.lanes.single), pn: L.previewView(none),
  pr: L.previewView(running),
}));
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


def test_manifest_view(out):
    m = out["m"]
    assert m["spec"] == "ab" * 6 and m["heldout"] == "cd" * 6 and m["baseTree"] == "ef" * 6  # first 12 hex chars
    assert m["single"] == {"harness": "api-sealed-eval/1", "attempts": 1, "feedback": "none"}
    assert m["evoforge"] == {"harness": "api-sealed-eval/2", "attempts": 3, "feedback": "critic"}
    assert m["upperBound"] is False and m["disclosure"] == "Same task, same tests."
    assert out["mh"]["upperBound"] is True  # held-out failing names = oracle signal, must be flagged
    assert out["m0"] is None


def test_preview_view(out):
    assert out["pe"] == {"html": "<svg/>", "source": "candidate", "error": None}
    assert out["ps"] == {"html": "<p>base</p>", "source": "base", "error": None}
    assert out["pn"] == {"html": None, "source": "none", "error": "timeout"}
    assert out["pr"] == {"html": None, "source": "pending", "error": None}  # nothing shown before the lane finishes


def test_page_wiring_and_operator_gate():
    page = (WEB / "app" / "[locale]" / "arena" / "page.tsx").read_text(encoding="utf-8")
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "SandboxedPreview" in page and "manifestView" in page and "previewView" in page
    # Owner decision 2026-10-30 (T84/T85): the daily run limit replaces the operator-only start; spend confirm stays.
    assert "getArenaLimits" in page and "confirm(" in page
    assert '"critic"' in page
    assert '"v4"' in api and "feedback" in api.split("export function postArena", 1)[1].split("}", 1)[0]
