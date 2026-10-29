"""T52 round-replay UI (local check): pure round helpers + replay page wiring."""
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
COMP = WEB / "components" / "RoundReplay.tsx"
PAGE = WEB / "app" / "[locale]" / "replay" / "page.tsx"
API = WEB / "lib" / "api.ts"
LAYOUT = WEB / "app" / "[locale]" / "layout.tsx"
TSC = WEB / "node_modules" / "typescript" / "bin" / "tsc"

REQUIRED_KEYS = {
    "title", "first", "latest", "play", "pause", "recorded-run",
    "pending", "failed", "unverified", "ready", "evoforge",
    "single", "empty", "cost", "score", "totals",
}


def _snap(status, passed=2, n=3, cost=120, html="<p>hi</p>"):
    snap = {"status": status, "verified": status == "READY",
            "heldout": {"passed": passed, "n": n}, "cost_cents": cost,
            "elapsed_ms": 50, "source_sha": "abc"}
    if html is not None:
        snap["preview_html"] = html
    return snap


def _run():
    return {
        "run_id": "r1", "app_id": "a", "title": "t", "status": "succeeded",
        "manifest": {"app_id": "a", "rounds": 3, "cost_basis": "m",
                     "runner_cost": "not_measured", "disclosure": "d", "lanes": {}},
        "rounds": [
            {"index": 1, "name": "R1", "goal": "g",
             "sides": {"evoforge": _snap("READY"), "single": _snap("READY", 1, 3)}},
            {"index": 2, "name": "R2", "goal": "g",
             "sides": {"evoforge": _snap("UNVERIFIED"), "single": _snap("PENDING", html=None)}},
            {"index": 3, "name": "R3", "goal": "g",
             "sides": {"evoforge": _snap("PENDING", html=None), "single": _snap("PENDING", html=None)}},
        ],
        "totals": {"evoforge": {"cost_cents": 200, "elapsed_ms": 900, "verified_rounds": 1},
                   "single": {"cost_cents": 150, "elapsed_ms": 800, "verified_rounds": 1}},
    }


@pytest.fixture(scope="module")
def built():
    if not TSC.exists() or not shutil.which("node"):
        pytest.skip("node/typescript not installed in apps/web")
    assert LIB.exists(), "apps/web/lib/roundReplay.ts must exist"
    out = Path(tempfile.mkdtemp())
    # Compile the lib standalone (no api.ts): it must load in isolation.
    r = subprocess.run(
        ["node", str(TSC), str(LIB), "--outDir", str(out),
         "--module", "commonjs", "--target", "es2019",
         "--skipLibCheck", "--esModuleInterop"],
        capture_output=True, text=True, encoding="utf-8", cwd=WEB)
    assert r.returncode == 0, r.stdout + r.stderr
    js = next(out.rglob("roundReplay.js"))
    return js


def _call(js: Path, expr: str, *args):
    payload = json.dumps(list(args))
    code = ("const m=require(%s);const a=JSON.parse(process.argv[1]);"
            "process.stdout.write(JSON.stringify((%s).apply(null,a)));") % (
        json.dumps(str(js)), expr)
    r = subprocess.run(["node", "-e", code, payload], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_round_view_shapes_and_isolation(built):
    run = _run()
    v = _call(built, "m.roundView", run, 1)
    assert v["index"] == 1 and v["name"] == "R1"
    assert v["sides"]["evoforge"]["status"] == "READY"
    assert v["sides"]["evoforge"]["verified"] is True
    assert v["sides"]["evoforge"]["score"] == "2/3"
    assert v["sides"]["evoforge"]["cost"] == "120¢"
    assert v["sides"]["evoforge"]["previewHtml"] == "<p>hi</p>"
    assert v["sides"]["single"]["score"] == "1/3"
    assert _call(built, "m.roundView", run, 9) is None
    pend = _call(built, "m.roundView", run, 2)
    assert pend["sides"]["single"]["status"] == "PENDING"
    assert pend["sides"]["single"]["verified"] is False
    assert pend["sides"]["single"]["score"] == "—"
    assert pend["sides"]["single"]["cost"] == "—"
    assert pend["sides"]["single"]["previewHtml"] is None
    assert pend["sides"]["evoforge"]["previewHtml"] == "<p>hi</p>"
    assert pend["sides"]["evoforge"]["verified"] is False


def test_navigation_helpers(built):
    run = _run()
    assert _call(built, "m.latestCommonRound", run) == 1
    assert _call(built, "m.firstLatest", run) == [1, 1]
    assert _call(built, "m.nextRound", 1, run) == 2
    assert _call(built, "m.nextRound", 3, run) is None
    assert _call(built, "m.latestCommonRound", {"run_id": "x"}) == 0


def test_totals_view(built):
    t = _call(built, "m.totalsView", _run())
    assert t["evoforge"]["cost"] == "200¢"
    assert t["evoforge"]["verified"] == "1/3"
    assert t["single"]["cost"] == "150¢"
    assert t["single"]["verified"] == "1/3"


def _sealed_like_run():
    sha = "sha256:" + "a" * 64
    return {
        "run_id": "evo_fixture", "app_id": "mission_board",
        "title": "Mission Board", "status": "running",
        "manifest": {"app_id": "mission_board", "rounds": 5,
                     "cost_basis": "model_api_usage", "disclosure": "same tests"},
        "rounds": [
            {"index": 1, "name": "Initial Build",
             "sides": {
                 "evoforge": {"status": "READY", "verified": True,
                              "heldout": {"passed": 3, "n": 3}, "cost_cents": 4,
                              "elapsed_ms": 1000, "source_sha": sha,
                              "preview_html": "<p>e1</p>"},
                 "single": {"status": "READY", "verified": True,
                             "heldout": {"passed": 3, "n": 3}, "cost_cents": 1,
                             "elapsed_ms": 1000, "source_sha": sha,
                             "preview_html": "<p>s1</p>"}}},
            {"index": 2, "name": "Feature Growth",
             "sides": {
                 "evoforge": {"status": "READY", "verified": True,
                              "heldout": {"passed": 6, "n": 6}, "cost_cents": 5,
                              "elapsed_ms": 1000, "source_sha": sha,
                              "preview_html": "<p>e2</p>"},
                 "single": {"status": "FAILED", "verified": False,
                             "heldout": {"passed": 2, "n": 6}, "cost_cents": 1,
                             "elapsed_ms": 1000, "source_sha": sha,
                             "preview_html": "<p>s1</p>"}}},
            {"index": 3, "name": "UX Refinement",
             "sides": {
                 "evoforge": {"status": "UNVERIFIED", "verified": False,
                              "heldout": {"passed": 8, "n": 9}, "cost_cents": 6,
                              "elapsed_ms": 1000, "source_sha": sha,
                              "preview_html": "<p>e3</p>"},
                 "single": {"status": "PENDING"}}},
        ],
        "totals": {"evoforge": {"cost_cents": 15, "elapsed_ms": 3000, "verified_rounds": 2},
                   "single": {"cost_cents": 2, "elapsed_ms": 2000, "verified_rounds": 1}},
    }


def test_sealed_fixture_behaviour(built):
    run = _sealed_like_run()
    r1 = _call(built, "m.roundView", run, 1)
    assert r1["sides"]["evoforge"]["score"] == "3/3"
    assert r1["sides"]["evoforge"]["cost"] == "4¢"
    assert r1["sides"]["evoforge"]["previewHtml"] == "<p>e1</p>"
    assert r1["sides"]["single"]["previewHtml"] == "<p>s1</p>"
    r2 = _call(built, "m.roundView", run, 2)
    assert r2["sides"]["evoforge"]["previewHtml"] == "<p>e2</p>"
    assert r2["sides"]["single"]["status"] == "FAILED"
    assert r2["sides"]["single"]["verified"] is False
    assert r2["sides"]["single"]["score"] == "2/6"
    assert r2["sides"]["single"]["cost"] == "1¢"
    assert r2["sides"]["single"]["previewHtml"] == "<p>s1</p>"
    r3 = _call(built, "m.roundView", run, 3)
    assert r3["name"] == "UX Refinement"
    assert r3["sides"]["evoforge"]["verified"] is False
    assert r3["sides"]["evoforge"]["score"] == "8/9"
    assert r3["sides"]["evoforge"]["previewHtml"] == "<p>e3</p>"
    assert r3["sides"]["single"]["status"] == "PENDING"
    assert r3["sides"]["single"]["verified"] is False
    assert r3["sides"]["single"]["score"] == "—"
    assert r3["sides"]["single"]["cost"] == "—"
    assert r3["sides"]["single"]["previewHtml"] is None
    assert _call(built, "m.roundView", run, 4) is None
    assert _call(built, "m.roundView", run, 5) is None
    assert _call(built, "m.latestCommonRound", run) == 2
    assert _call(built, "m.firstLatest", run) == [1, 2]
    assert _call(built, "m.nextRound", 1, run) == 2
    assert _call(built, "m.nextRound", 2, run) == 3
    assert _call(built, "m.nextRound", 3, run) is None
    t = _call(built, "m.totalsView", run)
    assert t["evoforge"]["cost"] == "15¢"
    assert t["evoforge"]["verified"] == "2/5"
    assert t["evoforge"]["elapsed"] == 3000
    assert t["single"]["cost"] == "2¢"
    assert t["single"]["verified"] == "1/5"
    assert t["single"]["elapsed"] == 2000


def test_lib_is_pure():
    src = LIB.read_text(encoding="utf-8")
    assert "roundView" in src and "latestCommonRound" in src
    assert "firstLatest" in src and "nextRound" in src and "totalsView" in src
    assert "fetch(" not in src and "react" not in src.lower()
    lines = [ln.strip() for ln in src.splitlines() if ln.strip() and not ln.strip().startswith("//")]
    assert not any(ln.startswith("import ") or ln.startswith("import{") for ln in lines)
    assert "require(" not in src, "lib must be import-free"


def test_component_wiring():
    src = COMP.read_text(encoding="utf-8")
    assert "fetch(" not in src
    assert "SandboxedPreview" in src
    assert "setInterval" in src and "nextRound" in src
    for token in ("READY", "UNVERIFIED", "FAILED", "PENDING", "recorded-run"):
        assert token in src, token
    assert "grid-cols-1" in src and "768" in src


def test_page_and_api_and_nav():
    page = PAGE.read_text(encoding="utf-8")
    assert "listEvolutionRuns" in page and "getEvolutionRun" in page
    loader = (WEB / "lib" / "replaySelection.ts").read_text(encoding="utf-8")
    assert "RoundReplay" in page and "watchReplaySelection" in page
    assert "5000" in loader and 'status === "running"' in loader
    api = API.read_text(encoding="utf-8")
    assert "listEvolutionRuns" in api and "getEvolutionRun" in api
    assert "/v1/evolution/runs" in api
    layout = LAYOUT.read_text(encoding="utf-8")
    assert "${prefix}/replay" in layout


def test_replay_i18n_keys():
    for name in ("en.json", "ko.json"):
        msgs = json.loads((WEB / "messages" / name).read_text(encoding="utf-8"))
        assert REQUIRED_KEYS <= set(msgs.get("replay", {})), name
