"""Critic acceptance (sealed during build, promoted after) — T10 held-out suite comes only from the server-stored Critic review (finding F1)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from critic_helpers import sealed_suite, server_review  # noqa: E402
from evoforge import commands, github, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
STRONG = [{"code": "def test_value():\n    assert result == 3\n"}]
DIFF = "--- a/src/v.py\n+++ b/src/v.py\n@@ -1 +1 @@\n-result = 2\n+result = 3\n"
TRIVIAL = sealed_suite("def test_h():\n    assert 1 == 1\n")
REAL = sealed_suite("from v import result\n\ndef test_h():\n    assert result == 3  # T10_SEALED_MARK\n")
SEEN: list = []


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    ledger.reset()
    ledger.configure({"default": 50000})
    commands.reset()
    SEEN.clear()
    from evoforge import runner

    def fake(source_repo, base_sha, diff, visible_tests, heldout_tests, timeout_s=120, future_shas=None):
        SEEN.append([dict(t) for t in heldout_tests])
        n = len(heldout_tests)
        return {"base": "b" * 40, "hygiene": [],
                "visible": {"pass": 1, "n": 1, "timed_out": False, "exit_code": 0},
                "heldout": {"pass": n, "n": n, "timed_out": False, "exit_code": 0},
                "heldout_kinds": [str(t.get("kind", "")) for t in heldout_tests]}

    monkeypatch.setattr(runner, "run_candidate", fake)
    monkeypatch.setattr(github, "create_pr", lambda *a, **k: {"html_url": "https://github.com/o/r/pull/10"})


def _run(**body):
    return c.post("/v1/runs", json={"source_repo": "C:/repos/p", "base_sha": "b" * 40, "diff": DIFF,
                                   "tests": STRONG, **body})


def test_exploit_client_trivial_suite_without_review_is_refused():
    r = _run(heldout_tests=TRIVIAL)
    assert r.status_code in (404, 409, 422), r.text
    assert SEEN == []  # nothing executed


def test_client_suite_next_to_valid_review_is_rejected(monkeypatch):
    rid = server_review(c, monkeypatch, REAL)
    r = _run(review_evidence_id=rid, heldout_tests=TRIVIAL)
    assert r.status_code == 422, r.text
    assert SEEN == []


def test_empty_client_suite_is_ignored_and_server_suite_runs(monkeypatch):
    rid = server_review(c, monkeypatch, REAL)
    r = _run(review_evidence_id=rid, heldout_tests=[])
    assert r.status_code == 200, r.text
    assert SEEN == [REAL]


def test_valid_review_runs_server_suite_and_unlocks_pr(monkeypatch):
    rid = server_review(c, monkeypatch, REAL)
    r = _run(review_evidence_id=rid)
    assert r.status_code == 200, r.text
    assert SEEN == [REAL]
    j = r.json()
    assert all(g["result"] == "PASS" for g in j["gates"]), j["gates"]
    assert j["run"]["heldout_kinds"] == [t["kind"] for t in REAL]
    assert "T10_SEALED_MARK" not in r.text
    ev = c.get(f"/v1/evidence/{j['evidence_id']}").json()
    assert ev.get("review_evidence_id") == rid or ev.get("data", {}).get("review_evidence_id") == rid
    assert "T10_SEALED_MARK" not in repr(ev)
    assert c.post("/v1/pr/create", json={"evidence_id": j["evidence_id"], "title": "t"}).status_code == 200


def test_stub_review_cannot_back_a_run():
    stub = c.post("/v1/candidates/review", json={"goal_contract": "add numbers", "diff": ""}).json()
    assert stub["stub"] is True
    r = _run(review_evidence_id=stub["evidence_id"])
    assert r.status_code == 409, r.text
    assert SEEN == []


def test_shape_invalid_review_is_409(monkeypatch):
    rid = server_review(c, monkeypatch, REAL[:2])
    assert _run(review_evidence_id=rid).status_code == 409
    assert SEEN == []


def test_unknown_or_non_review_evidence():
    assert _run(review_evidence_id="ev_000000000000").status_code in (404, 409)
    obj = c.post("/v1/objectives", json={"goal": "g"}).json()["evidence_id"]
    assert _run(review_evidence_id=obj).status_code == 409
    assert SEEN == []


def test_missing_review_id_is_rejected():
    r = _run()
    assert r.status_code in (404, 409, 422)
    assert SEEN == []
