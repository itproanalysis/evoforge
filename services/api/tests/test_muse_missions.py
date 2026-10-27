"""T18 mission lifecycle tests (Builder-owned; test_critic_* names belong to the Critic)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)
os.environ["EVO_PROJECT_BUDGET_CENTS"] = "50000"

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta, ledger  # noqa: E402
from evoforge import missions as missions_store  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)


def setup_function(_):
    ledger.reset()
    ledger.configure({"default": 50000})
    missions_store.reset()
    main._evidence.clear()


def _git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def local_remote(tmp_path, monkeypatch):
    """Configured GitHub repo backed by a local bare clone (offline, T17-style)."""
    w = tmp_path / "work"
    w.mkdir()
    _git(w, "init", "-q", "-b", "main")
    (w / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8", newline="")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    base = _git(w, "rev-parse", "HEAD")
    root = tmp_path / "gh"
    (root / "owner").mkdir(parents=True)
    _git(tmp_path, "clone", "-q", "--bare", str(w), str(root / "owner" / "proj.git"))
    monkeypatch.setenv("GITHUB_REPO", "owner/proj")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_t18_canary")
    monkeypatch.setenv("EVO_GITHUB_GIT_BASE", str(root).replace("\\", "/"))
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    return {"base": base}


def _create(goal="fix login", **kw):
    body = {"goal": goal, "repo_ref": "HEAD", **kw}
    r = c.post("/v1/missions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_and_detail_stage_pointers():
    out = _create()
    assert out["state"] == "CREATED" and out["mission_id"].startswith("msn_")
    d = c.get(f"/v1/missions/{out['mission_id']}").json()
    assert d["state"] == "CREATED" and d["goal"] == "fix login"
    for k in ("generate_evidence_id", "review_evidence_id", "run_evidence_id", "pr_evidence_id"):
        assert d[k] is None, k
    assert out["evidence_id"] in d["evidence_ids"]
    assert c.get(f"/v1/evidence/{out['evidence_id']}").status_code == 200


def test_create_validation_and_risk_confirm():
    assert c.post("/v1/missions", json={"goal": " ", "repo_ref": "HEAD"}).status_code == 400
    assert c.post("/v1/missions", json={"goal": "g", "repo_ref": " "}).status_code == 400
    r = c.post("/v1/missions", json={"goal": "g", "repo_ref": "HEAD", "risk": "HIGH"})
    assert r.status_code == 409 and "confirm" in r.json()["detail"]
    r = c.post("/v1/missions", json={"goal": "g", "repo_ref": "HEAD", "risk": "CRITICAL",
                                     "confirm": True})
    assert r.status_code == 201
    r = c.post("/v1/missions", json={"goal": "g", "repo_ref": "HEAD",
                                     "target_paths": ["../evil"]})
    assert r.status_code == 400


def test_unknown_mission_404():
    assert c.get("/v1/missions/msn_nope").status_code == 404
    assert c.post("/v1/missions/msn_nope/advance", json={"to": "GENERATED"}).status_code == 404
    assert c.post("/v1/missions/msn_nope/cancel").status_code == 404


def test_advance_generate_review_then_stub_run_409():
    mid = _create()["mission_id"]
    assert c.post(f"/v1/missions/{mid}/advance", json={"to": "REVIEWED"}).status_code == 409
    r = c.post(f"/v1/missions/{mid}/advance", json={"to": "GENERATED"})
    assert r.status_code == 200 and r.json()["state"] == "GENERATED"
    r = c.post(f"/v1/missions/{mid}/advance", json={"to": "REVIEWED"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "REVIEWED"
    # Sealed code never in HTTP: the stub review stores real code server-side.
    assert "def test_" not in json.dumps(body)
    d = c.get(f"/v1/missions/{mid}").json()
    assert d["review_evidence_id"] == body["evidence_id"]
    assert "def test_" not in json.dumps(d)
    # Stub reviews cannot back a run: 409 with reason, mission stays REVIEWED.
    r = c.post(f"/v1/missions/{mid}/advance", json={"to": "RAN"})
    assert r.status_code == 409 and "stub" in r.json()["detail"].lower()
    assert c.get(f"/v1/missions/{mid}").json()["state"] == "REVIEWED"


def test_branch_ref_with_target_paths_stub_path(local_remote):
    """Branch repo_ref + target_paths works offline: ref resolves via ls-remote,
    context loads from the configured repo, stub Builder/Critic still reply."""
    out = _create(goal="fix add", repo_ref="main", target_paths=["calc.py"])
    mid = out["mission_id"]
    r = c.post(f"/v1/missions/{mid}/advance", json={"to": "GENERATED"})
    assert r.status_code == 200, r.text
    r = c.post(f"/v1/missions/{mid}/advance", json={"to": "REVIEWED"})
    assert r.status_code == 200, r.text
    assert "def test_" not in r.text  # sealed code never in HTTP
    r = c.post(f"/v1/missions/{mid}/advance", json={"to": "RAN"})
    assert r.status_code == 409 and "stub" in r.json()["detail"].lower()
    assert c.get(f"/v1/missions/{mid}").json()["state"] == "REVIEWED"


def test_full_chain_with_fakes(local_remote, monkeypatch):
    from evoforge import github, runner

    held = [{"kind": k, "code": f"def test_h_{k}():\n    assert 1 == 1\n"}
            for k in ("compositional", "negative", "boundary")]
    monkeypatch.setattr(broker_meta, "call_critic",
                        lambda *a, **k: {"sealed_tests": held,
                                         "review": {"result": "PASS", "findings": []},
                                         "stub": False, "model": "muse-spark-1.3"})

    def fake_builder(goal, repo_sha, file_context=None, **kw):
        assert isinstance(file_context, list) and any(
            e.get("path") == "calc.py" and "return a - b" in e.get("content", "")
            for e in file_context if isinstance(e, dict))
        return {"diff": ("--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n"
                         " def add(a, b):\n-    return a - b\n+    return a + b\n"),
                "tests": [{"code": "from calc import add\n\ndef test_v():\n"
                                   "    assert add(2, 3) == 5\n"}],
                "stub": False}

    monkeypatch.setattr(broker_meta, "call_builder", fake_builder)

    def fake_run(source_repo, base_sha, diff, visible_tests, heldout_tests, timeout_s=120,
                 future_shas=None):
        # Configured GitHub repo ('') at the resolved base SHA.
        assert source_repo == "" and re.fullmatch(r"[0-9a-fA-F]{40}", base_sha)
        assert base_sha == local_remote["base"]
        return {"base": "b" * 40, "hygiene": [],
                "visible": {"pass": 1, "n": 1, "timed_out": False, "exit_code": 0},
                "heldout": {"pass": 3, "n": 3, "timed_out": False, "exit_code": 0},
                "heldout_kinds": [t["kind"] for t in heldout_tests]}

    monkeypatch.setattr(runner, "run_candidate", fake_run)
    calls = []
    monkeypatch.setattr(github, "create_pr",
                        lambda diff, title, body, branch, base="main", **kw:
                        (calls.append((diff, title, body)), {"html_url": "https://github.com/o/r/pull/7",
                                                            "number": 7})[1])
    mid = _create(goal="fix add", repo_ref="main", target_paths=["calc.py"])["mission_id"]
    states = []
    for to in ("GENERATED", "REVIEWED", "RAN", "PR_OPENED"):
        r = c.post(f"/v1/missions/{mid}/advance", json={"to": to})
        assert r.status_code == 200, (to, r.text)
        states.append(r.json()["state"])
    assert states == ["GENERATED", "REVIEWED", "RAN", "PR_OPENED"]
    assert len(calls) == 1
    d = c.get(f"/v1/missions/{mid}").json()
    assert all(d[k] for k in ("generate_evidence_id", "review_evidence_id",
                              "run_evidence_id", "pr_evidence_id"))
    assert d["pr_url"] == "https://github.com/o/r/pull/7"
    assert len(set(d["evidence_ids"])) == len(d["evidence_ids"])  # one chain, no dupes
    # Terminal state rejects further advance.
    assert c.post(f"/v1/missions/{mid}/advance", json={"to": "FAILED"}).status_code == 409
    assert c.post(f"/v1/missions/{mid}/cancel").status_code == 409


def test_cancel_from_reviewed_blocks_advance_and_keeps_evidence():
    mid = _create()["mission_id"]
    c.post(f"/v1/missions/{mid}/advance", json={"to": "GENERATED"})
    c.post(f"/v1/missions/{mid}/advance", json={"to": "REVIEWED"})
    before = c.get(f"/v1/missions/{mid}").json()["evidence_ids"]
    r = c.post(f"/v1/missions/{mid}/cancel")
    assert r.status_code == 200 and r.json()["state"] == "CANCELLED"
    r = c.post(f"/v1/missions/{mid}/advance", json={"to": "RAN"})
    assert r.status_code == 409
    after = c.get(f"/v1/missions/{mid}").json()
    assert after["state"] == "CANCELLED" and after["evidence_ids"] == before
    for eid in before:  # cancel never deletes evidence
        assert c.get(f"/v1/evidence/{eid}").status_code == 200


def test_illegal_skip_and_bad_target_rejected():
    mid = _create()["mission_id"]
    assert c.post(f"/v1/missions/{mid}/advance", json={"to": "RAN"}).status_code == 409
    assert c.post(f"/v1/missions/{mid}/advance", json={"to": "NOPE"}).status_code == 422
    assert c.get(f"/v1/missions/{mid}").json()["state"] == "CREATED"


def test_dashboard_matches_server_counts():
    m1 = _create(goal="one")["mission_id"]
    m2 = _create(goal="two")["mission_id"]
    c.post(f"/v1/missions/{m1}/advance", json={"to": "GENERATED"})
    snap = ledger.snapshot("default")
    d = c.get("/v1/dashboard").json()
    assert d["missions_by_state"]["CREATED"] == 1
    assert d["missions_by_state"]["GENERATED"] == 1
    assert sum(d["missions_by_state"].values()) == 2
    assert d["active_missions"] == 2 and d["blocked_merges"] == 0
    assert d["spent_cents"] == snap["spent_cents"]
    assert d["reserved_cents"] == snap["reserved_cents"]
    assert d["unknown_holds"] == len(snap["unknown_reservations"])
    items = c.get("/v1/missions").json()["missions"]
    assert {m["mission_id"] for m in items} == {m1, m2}
    for m in items:
        assert set(m) == {"mission_id", "state", "goal", "updated_at", "evidence_ids"}


def test_proxy_cases_cover_missions():
    cases = json.loads((Path(__file__).resolve().parents[3] / "apps" / "web" / "lib"
                        / "proxyPolicy.cases.json").read_text(encoding="utf-8"))
    table = {tuple(e["path_segments"]): e["expected"] for e in cases}
    assert table[("v1", "missions")] == "/v1/missions"
    assert table[("v1", "dashboard")] == "/v1/dashboard"
    assert table[("v1", "missions", "msn-abc123")] == "/v1/missions/msn-abc123"
    assert table[("v1", "missions", "msn-abc123", "advance")] == "/v1/missions/msn-abc123/advance"
    assert table[("v1", "missions", "msn-abc123", "cancel")] == "/v1/missions/msn-abc123/cancel"
    for segs in [("v1", "missions", "x", "..", "kernel"), ("v1", "missions", ".."),
                 ("v1", "missions", "abc", "extra"), ("v1", "missions", "abc", "delete"),
                 ("v1", "dashboard", "x"), ("v1", "missionsextra")]:
        assert table[segs] is None, segs
