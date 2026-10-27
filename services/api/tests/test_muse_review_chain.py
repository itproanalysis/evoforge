"""T19 Review-into-run chain + ledger footer wording (Builder-owned; test_critic_* names belong to the Critic)."""
from __future__ import annotations

import os
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
from critic_helpers import server_review  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)

MARK = "T19_SEALED_MARK_9031"
SEALED = [{"kind": k, "code": f"from calc import add\n# {MARK}\ndef test_h_{k}():\n    assert 1 == 1\n"}
          for k in ("compositional", "negative", "boundary")]
DIFF = "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"
VIS = [{"code": "from calc import add\n\ndef test_v():\n    assert add(2, 3) == 5\n"}]
STAGES = ["ObjectiveVersion", "Task", "Candidate", "Gate", "Review", "PR", "Outcome"]


def setup_function(_):
    ledger.reset()
    ledger.configure({"default": 50000})
    missions_store.reset()
    main._evidence.clear()


@pytest.fixture
def fake_runner(monkeypatch):
    from evoforge import runner

    def fake(source_repo, base_sha, diff, visible_tests, heldout_tests,
             timeout_s=120, future_shas=None):
        return {"base": "b" * 40, "hygiene": [],
                "visible": {"pass": 1, "n": 1, "timed_out": False, "exit_code": 0},
                "heldout": {"pass": 3, "n": 3, "timed_out": False, "exit_code": 0},
                "heldout_kinds": [t["kind"] for t in heldout_tests]}

    monkeypatch.setattr(runner, "run_candidate", fake)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)


def _chain_map(eid):
    r = c.get(f"/v1/evidence/{eid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["stage"] for x in body["chain"]] == STAGES
    return body, {x["stage"]: x["event_id"] for x in body["chain"]}


def test_run_links_review_event_and_pr_preserves(fake_runner, monkeypatch):
    review_eid = server_review(c, monkeypatch, SEALED)
    _, review_chain = _chain_map(review_eid)
    assert review_chain["Review"]

    r = c.post("/v1/runs", json={"source_repo": "", "base_sha": "b" * 40,
                                 "diff": DIFF, "tests": VIS,
                                 "review_evidence_id": review_eid})
    assert r.status_code == 200, r.text
    run_eid = r.json()["evidence_id"]
    assert MARK not in r.text
    _, run_chain = _chain_map(run_eid)
    assert run_chain["Review"] == review_chain["Review"]
    assert run_chain["Candidate"] and run_chain["Gate"]

    # The shared Review event drills down to the sealed summary, never code.
    ev = c.get(f"/v1/events/{run_chain['Review']}")
    assert ev.status_code == 200, ev.text
    view = ev.json()
    assert view["stage"] == "Review" and view["id"] == review_chain["Review"]
    assert view["summary"].get("sealed_count") == 3
    assert sorted(view["summary"].get("sealed_kinds", [])) == ["boundary", "compositional", "negative"]
    assert MARK not in ev.text and "def test_" not in ev.text

    # The review evidence itself is untouched: still exactly one Review link.
    _, review_chain_after = _chain_map(review_eid)
    assert review_chain_after == review_chain

    from evoforge import github
    monkeypatch.setattr(github, "create_pr",
                        lambda *a, **k: {"html_url": "https://github.com/o/r/pull/19"})
    pr = c.post("/v1/pr/create", json={"evidence_id": run_eid, "title": "t19"})
    assert pr.status_code == 200, pr.text
    pr_eid = pr.json()["evidence_id"]
    _, pr_chain = _chain_map(pr_eid)
    assert pr_chain["Review"] == review_chain["Review"]
    assert pr_chain["Candidate"] == run_chain["Candidate"] and pr_chain["Gate"] == run_chain["Gate"]
    assert pr_chain["PR"]


def test_stub_review_run_409_creates_no_run_evidence(fake_runner, monkeypatch):
    stub_eid = server_review(c, monkeypatch, SEALED, stub=True)
    before = set(main._evidence)
    r = c.post("/v1/runs", json={"source_repo": "", "base_sha": "b" * 40,
                                 "diff": DIFF, "tests": VIS,
                                 "review_evidence_id": stub_eid})
    assert r.status_code == 409, r.text
    assert "stub" in r.json()["detail"].lower()
    assert set(main._evidence) == before
    assert not [eid for eid, ev in main._evidence.items()
                if ev.get("review_evidence_id") == stub_eid]


def test_missing_review_stage_renders_null_not_500():
    out = c.post("/v1/commands/generate",
                 json={"goal": "t19 gen", "idempotency_key": "t19-gen"}).json()
    body, chain = _chain_map(out["evidence"]["id"])
    assert chain["Review"] is None
    assert body["id"] == out["evidence"]["id"]


def test_mission_run_chain_carries_review(monkeypatch):
    held = [{"kind": k, "code": f"def test_h_{k}():\n    assert 1 == 1\n"}
            for k in ("compositional", "negative", "boundary")]
    monkeypatch.setattr(broker_meta, "call_critic",
                        lambda *a, **k: {"sealed_tests": held,
                                         "review": {"result": "PASS", "findings": []},
                                         "stub": False, "model": "muse-spark-1.3"})
    monkeypatch.setattr(broker_meta, "call_builder",
                        lambda goal, sha, file_context=None, **k:
                        {"diff": DIFF, "tests": VIS, "stub": False})
    from evoforge import runner
    monkeypatch.setattr(runner, "run_candidate",
                        lambda *a, **k: {"base": "b" * 40, "hygiene": [],
                                         "visible": {"pass": 1, "n": 1, "timed_out": False,
                                                     "exit_code": 0},
                                         "heldout": {"pass": 3, "n": 3, "timed_out": False,
                                                     "exit_code": 0},
                                         "heldout_kinds": ["compositional", "negative",
                                                           "boundary"]})
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    r = c.post("/v1/missions", json={"goal": "t19 mission", "repo_ref": "b" * 40})
    assert r.status_code == 201, r.text
    mid = r.json()["mission_id"]
    for to in ("GENERATED", "REVIEWED", "RAN"):
        r = c.post(f"/v1/missions/{mid}/advance", json={"to": to})
        assert r.status_code == 200, (to, r.text)
    d = c.get(f"/v1/missions/{mid}").json()
    _, review_chain = _chain_map(d["review_evidence_id"])
    _, run_chain = _chain_map(d["run_evidence_id"])
    assert review_chain["Review"]
    assert run_chain["Review"] == review_chain["Review"]


def _footer_text() -> str:
    base = Path(__file__).resolve().parents[3] / "apps" / "web"
    parts = []
    for rel in ("app/layout.tsx", "app/[locale]/layout.tsx",
                "messages/ko.json", "messages/en.json"):
        p = base / rel
        if p.is_file():
            parts.append(p.read_text(encoding="utf-8"))
    assert parts, "no web footer sources found"
    return "\n".join(parts)


def test_footer_has_real_ledger_wording():
    text = _footer_text()
    assert "추정치" not in text
    assert "estimate" not in text.lower()
    assert "provider_billed" in text
    assert "/v1/ledger" in text
    assert "UNKNOWN" in text


def test_evidence_page_shows_review_drilldown():
    text = (Path(__file__).resolve().parents[3] / "apps" / "web" / "app"
            / "evidence" / "page.tsx").read_text(encoding="utf-8")
    assert "Review" in text
    assert "/v1/events/" in text
