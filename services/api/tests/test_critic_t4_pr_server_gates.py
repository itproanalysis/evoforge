"""Critic acceptance (sealed during build, promoted after) — T4 PRs only from server-stored, all-PASS gate evidence."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import github  # noqa: E402
from critic_helpers import sealed_suite, server_review  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
HELDOUT = ["compositional", "negative", "boundary"]
STRONG = [{"code": "def test_value():\n    assert result == 3\n"}]
DIFF = "--- a/src/v.py\n+++ b/src/v.py\n@@ -1 +1 @@\n-result = 2\n+result = 3\n"


RUN: dict = {}


@pytest.fixture(autouse=True)
def fake_runner(monkeypatch):
    """T5: PR evidence must come from a server run; stub the Runner with the requested counts."""
    from evoforge import runner

    def fake(source_repo, base_sha, diff, visible_tests, heldout_tests, timeout_s=120, future_shas=None):
        return {"base": "b" * 40, "hygiene": [],
                "visible": {"pass": RUN["vis_pass"], "n": RUN["vis_n"], "timed_out": False, "exit_code": 0},
                "heldout": {"pass": RUN["held_pass"], "n": RUN["held_n"], "timed_out": False, "exit_code": 0},
                "heldout_kinds": [str(t.get("kind", "")) for t in heldout_tests]}

    monkeypatch.setattr(runner, "run_candidate", fake)
    MP.append(monkeypatch)
    yield
    MP.clear()


MP: list = []


def _evaluate(diff=DIFF, heldout_kinds=HELDOUT, **kw):
    RUN.clear()
    RUN.update({"vis_pass": 10, "vis_n": 10, "held_pass": 10, "held_n": 10, **kw})
    review = server_review(c, MP[-1], sealed_suite(kinds=heldout_kinds))  # T10: held-out from the server
    r = c.post("/v1/runs", json={"source_repo": "C:/repos/proj", "base_sha": "b" * 40, "diff": diff,
                                 "tests": STRONG, "review_evidence_id": review})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def captured(monkeypatch):
    calls = []

    def fake(diff, title, body, branch, base="main", **kw):
        calls.append({"diff": diff, "title": title, "body": body, "branch": branch, "base": base})
        return {"html_url": "https://github.com/o/r/pull/9", "number": 9}

    monkeypatch.setattr(github, "create_pr", fake)
    if hasattr(main, "create_pr"):
        monkeypatch.setattr(main, "create_pr", fake)
    return calls


def test_evaluate_stores_diff_tests_gates():
    out = c.post("/v1/gates/evaluate", json={
        "diff": DIFF, "tests": STRONG, "heldout_kinds": HELDOUT,
        "vis_pass": 9, "vis_n": 10, "held_pass": 9, "held_n": 10}).json()
    ev = c.get(f"/v1/evidence/{out['evidence_id']}").json()
    assert ev["diff"] == DIFF and ev["tests"] == STRONG
    assert ev["gates"] == out["gates"]


def test_run_evidence_stores_diff_tests_gates_run():
    out = _evaluate()
    ev = c.get(f"/v1/evidence/{out['evidence_id']}").json()
    assert ev["diff"] == DIFF and ev["tests"] == STRONG
    assert ev["gates"] == out["gates"] and ev["run"]["heldout"]["n"] == 10


def test_pr_from_all_pass_evidence_uses_stored_diff(captured):
    out = _evaluate()
    assert all(g["result"] == "PASS" for g in out["gates"]), out
    r = c.post("/v1/pr/create", json={
        "evidence_id": out["evidence_id"], "title": "fix v", "body": "intro",
        "diff": "--- a/evil\n+++ b/evil\n@@ -0,0 +1 @@\n+pwn\n",
        "gates": [{"gate": "GH_INTEGRITY", "result": "PASS"}]})
    assert r.status_code == 200, r.text
    assert len(captured) == 1
    call = captured[0]
    assert call["diff"] == DIFF
    assert call["body"].startswith("intro")
    for g in out["gates"]:
        assert f"{g['gate']}={g['result']}" in call["body"]
    assert f"Evidence: {out['evidence_id']}" in call["body"]
    j = r.json()
    assert j["source_evidence_id"] == out["evidence_id"]
    assert j["pr"]["html_url"].endswith("/pull/9")
    ev = c.get(f"/v1/evidence/{j['evidence_id']}").json()
    assert ev["source_evidence_id"] == out["evidence_id"]
    assert "https://github.com/o/r/pull/9" in str(ev)


def test_pr_refused_when_any_gate_not_pass(captured):
    out = _evaluate(held_pass=1)  # held-out gap -> GH_INTEGRITY FAIL
    bad = [g["gate"] for g in out["gates"] if g["result"] != "PASS"]
    assert bad
    r = c.post("/v1/pr/create", json={"evidence_id": out["evidence_id"], "title": "t",
                                      "gates": [{"gate": "GH_INTEGRITY", "result": "PASS"}]})
    assert r.status_code == 409
    assert all(name in r.json()["detail"] for name in bad)
    assert captured == []


def test_pr_refused_for_inconclusive(captured):
    out = _evaluate(vis_pass=0, vis_n=0)  # no execution evidence -> INCONCLUSIVE
    assert any(g["result"] == "INCONCLUSIVE" for g in out["gates"])
    r = c.post("/v1/pr/create", json={"evidence_id": out["evidence_id"], "title": "t"})
    assert r.status_code == 409 and captured == []


def test_unknown_evidence_404(captured):
    r = c.post("/v1/pr/create", json={"evidence_id": "ev_doesnotexist", "title": "t"})
    assert r.status_code == 404 and captured == []


def test_non_gate_evidence_409(captured):
    eid = c.post("/v1/objectives", json={"goal": "g"}).json()["evidence_id"]
    r = c.post("/v1/pr/create", json={"evidence_id": eid, "title": "t"})
    assert r.status_code == 409 and captured == []


def test_missing_evidence_id_is_422(captured):
    r = c.post("/v1/pr/create", json={"diff": DIFF, "title": "t", "gates": []})
    assert r.status_code == 422 and captured == []


def test_runtime_error_400_and_patch_error_409(monkeypatch):
    from evoforge.patch import PatchError
    out = _evaluate()
    for exc, code in [(RuntimeError("missing GITHUB_TOKEN"), 400), (PatchError("hunk does not apply"), 409)]:
        def boom(*a, _e=exc, **k):
            raise _e
        monkeypatch.setattr(github, "create_pr", boom)
        if hasattr(main, "create_pr"):
            monkeypatch.setattr(main, "create_pr", boom)
        r = c.post("/v1/pr/create", json={"evidence_id": out["evidence_id"], "title": "t"})
        assert r.status_code == code, (exc, r.text)
