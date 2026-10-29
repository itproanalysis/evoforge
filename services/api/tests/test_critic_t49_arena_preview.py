"""Sealed (Critic) — T49 Arena on v3/v4 + per-lane sandboxed preview (North Star A4, v3.6 UX-02): on a visual task each
lane returns the HTML/SVG its final code renders via preview(), produced in an isolated subprocess (no secrets, timeout,
size cap), so the two results can be seen side by side; the web renders it only in a script-less sandboxed iframe."""
from __future__ import annotations

import difflib
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta, ledger, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
VIS = "SV4-AO-01"  # barchart.py, preview() draws 5 bars
SVG = "{http://www.w3.org/2000/svg}"


def _task(sv, tid):
    return next(t for s in sealed_eval.load_suites(sv) for t in s["tasks"] if t["id"] == tid)


def _overcount(diff):
    return re.sub(r"^@@ -(\d+),(\d+) \+(\d+),(\d+) @@",
                  lambda m: f"@@ -{m.group(1)},{int(m.group(2)) + 1} +{m.group(3)},{int(m.group(4)) + 1} @@", diff, flags=re.M)


def _with_preview(body):
    """Diff that keeps barchart.py's render and replaces preview() with `body`."""
    old = _task("v4", VIS)["files"]["barchart.py"]
    new = old.split("def preview():")[0] + "import os\n\n\ndef preview():\n" + body
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "a/barchart.py", "b/barchart.py"))


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset(); ledger.configure({"default": 500000})
    yield
    end = time.time() + 120
    while time.time() < end and any(j["status"] in ("queued", "running") for j in c.get("/v1/eval/jobs").json()["jobs"]):
        time.sleep(0.2)


def _builder(monkeypatch, diff):
    monkeypatch.setattr(broker_meta, "call_builder", lambda goal, sha, file_context=None, **k: {
        "diff": diff, "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
        "provider_calls": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 200}})


def _run(sv, tid):
    r = c.post("/v1/arena", json={"suite_version": sv, "task_id": tid})
    assert r.status_code == 202, r.text
    aid = r.json()["arena_id"]
    end = time.time() + 300
    while time.time() < end:
        a = c.get(f"/v1/arena/{aid}").json()
        if a["status"] in ("succeeded", "failed"):
            return a
        time.sleep(0.3)
    pytest.fail("arena did not finish")


def test_visual_task_returns_a_rendered_preview_per_lane(monkeypatch):
    _builder(monkeypatch, _task("v4", VIS)["reference_fix"])
    a = _run("v4", VIS)
    assert a["verdict"]["winner"] == "tie"
    for name in ("single", "evoforge"):
        lane = a["lanes"][name]
        assert lane["preview_source"] == "candidate", lane.get("preview_error")
        svg = ET.fromstring(lane["preview_html"])
        assert len(svg.findall(SVG + "rect")) == 5


def test_lane_whose_diff_did_not_apply_previews_the_base(monkeypatch):
    _builder(monkeypatch, _overcount(_task("v4", VIS)["reference_fix"]))
    a = _run("v4", VIS)
    single, evo = a["lanes"]["single"], a["lanes"]["evoforge"]
    assert single["outcome"] == "apply_failed" and single["preview_source"] == "base"
    assert evo["outcome"] == "passed" and evo["preview_source"] == "candidate"
    heights = [r.get("height") for r in ET.fromstring(evo["preview_html"]).findall(SVG + "rect")]
    assert heights and max(int(h) for h in heights) == 100  # scaled by the fix; the base draws raw values


def test_preview_process_gets_no_server_secrets(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_sealedT49secretvalue")
    monkeypatch.setenv("EVO_PROOF_SIGNING_KEY", "sealed-t49-signing-secret")
    _builder(monkeypatch, _with_preview(
        "    return '<p>' + os.environ.get('GITHUB_TOKEN', 'none') + os.environ.get('EVO_PROOF_SIGNING_KEY', '') + '</p>'\n"))
    a = _run("v4", VIS)
    blob = repr(a)
    assert "ghp_sealedT49secretvalue" not in blob and "sealed-t49-signing-secret" not in blob
    assert a["lanes"]["evoforge"]["preview_source"] == "candidate"


def test_runaway_or_huge_preview_is_cut_off_not_hung(monkeypatch):
    _builder(monkeypatch, _with_preview("    while True:\n        pass\n"))
    t0 = time.time()
    a = _run("v4", VIS)
    assert time.time() - t0 < 240
    lane = a["lanes"]["evoforge"]
    assert lane["preview_source"] == "none" and "timeout" in lane["preview_error"].lower()
    _builder(monkeypatch, _with_preview("    return '<p>' + 'x' * 300000 + '</p>'\n"))
    lane = _run("v4", VIS)["lanes"]["evoforge"]
    assert lane["preview_source"] == "none" and len(lane.get("preview_html") or "") <= 65536
    assert "large" in lane["preview_error"].lower()


def test_non_visual_task_has_no_preview_and_v3_is_accepted(monkeypatch):
    t = _task("v2", "SV2-SS-01")
    _builder(monkeypatch, t["reference_fix"])
    a = _run("v2", "SV2-SS-01")
    assert all(a["lanes"][n]["preview_source"] == "none" and not a["lanes"][n].get("preview_html")
               for n in ("single", "evoforge"))
    assert c.post("/v1/arena", json={"suite_version": "v3", "task_id": "SV3-NOPE-99"}).status_code == 404
    assert c.post("/v1/arena", json={"suite_version": "v9", "task_id": VIS}).status_code == 422


def test_web_preview_component_is_a_scriptless_sandboxed_iframe():
    src = (WEB / "components" / "SandboxedPreview.tsx").read_text(encoding="utf-8")
    assert "<iframe" in src and "srcDoc" in src and 'sandbox=""' in src
    assert "allow-scripts" not in src and "allow-same-origin" not in src
    assert "dangerouslySetInnerHTML" not in src
