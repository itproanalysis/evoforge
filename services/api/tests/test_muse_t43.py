"""Muse T43 feedback loop: scrub, store, list, promote to a linked mission."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import feedback as feedback_mod  # noqa: E402
from evoforge import missions as missions_store  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)


def setup_function(_):
    missions_store.reset()
    main._evidence.clear()


def _mission(goal="fix login", repo_ref="HEAD", **kw):
    r = c.post("/v1/missions", json={"goal": goal, "repo_ref": repo_ref, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _post_fb(mid, kind="bug", text="it broke"):
    return c.post("/v1/feedback", json={"mission_id": mid, "kind": kind, "text": text})


def test_submit_and_get_roundtrip():
    mid = _mission()["mission_id"]
    r = _post_fb(mid, "missed_case", "edge case missing")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["feedback_id"].startswith("fb_")
    assert body["mission_id"] == mid
    assert body["kind"] == "missed_case"
    assert body["text"] == "edge case missing"
    assert body["promoted_mission_id"] is None
    stored = main._evidence[body["feedback_id"]]
    assert stored["kind"] == "feedback"
    got = c.get("/v1/feedback").json()["feedback"]
    assert len(got) == 1
    item = got[0]
    for k in ("feedback_id", "mission_id", "kind", "text", "created_at",
              "promoted_mission_id"):
        assert k in item, k
    assert item["promoted_mission_id"] is None


def test_unknown_mission_is_404():
    r = _post_fb("msn_nope", "bug", "x")
    assert r.status_code == 404


def test_kind_and_text_validation_is_422():
    mid = _mission()["mission_id"]
    assert _post_fb(mid, "nope", "x").status_code == 422
    assert _post_fb(mid, "bug", "").status_code == 422
    assert _post_fb(mid, "bug", "x" * 2001).status_code == 422
    assert _post_fb(mid, "bug", "x" * 2000).status_code == 201


def test_scrub_redacts_email_and_secrets():
    mid = _mission()["mission_id"]
    raw = ("reach me at ada@example.com with ghp_abcDEF123456 and "
           "AKIAIOSFODNN7EXAMPLE plus sk-live-0123456789abcdef plus "
           "0123456789abcdef0123456789abcdef")
    body = _post_fb(mid, "bug", raw).json()
    text = body["text"]
    assert "ada@example.com" not in text
    assert "[email]" in text
    for secret in ("ghp_abcDEF123456", "AKIAIOSFODNN7EXAMPLE",
                   "sk-live-0123456789abcdef",
                   "0123456789abcdef0123456789abcdef"):
        assert secret not in text
    assert text.count("[secret]") >= 4
    assert "reach me at" in text


def test_list_newest_first_capped_at_100():
    mids = [_mission(goal=f"g{i}")["mission_id"] for i in range(3)]
    ids = [_post_fb(m, "other", f"note {m}").json()["feedback_id"] for m in mids]
    got = c.get("/v1/feedback").json()["feedback"]
    assert [x["feedback_id"] for x in got] == ids[::-1]
    for i in range(101):
        feedback_mod.submit(mids[0], "other", f"bulk {i}")
    got = c.get("/v1/feedback").json()["feedback"]
    assert len(got) == 100


def test_promote_creates_linked_mission_once():
    created = _mission(goal="stabilize retry",
                       target_paths=None)
    mid = created["mission_id"]
    fid = _post_fb(mid, "bug", "still flakes on retry").json()["feedback_id"]
    r = c.post(f"/v1/feedback/{fid}/promote")
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["feedback_id"] == fid
    new_id = first["mission_id"]
    assert new_id != mid
    detail = c.get(f"/v1/missions/{new_id}").json()
    assert detail["goal"] == ("stabilize retry\n\nFollow-up from feedback "
                              "(bug): still flakes on retry")
    assert detail["repo_ref"] == "HEAD"
    again = c.post(f"/v1/feedback/{fid}/promote")
    assert again.status_code in (200, 409), again.text
    assert again.json()["mission_id"] == new_id
    listed = c.get("/v1/feedback").json()["feedback"]
    assert [x for x in listed if x["feedback_id"] == fid][0][
        "promoted_mission_id"] == new_id
    assert len([m for m in c.get("/v1/missions").json()["missions"]
                if m["mission_id"] == new_id]) == 1
    linked = [main._evidence[e] for e in detail["evidence_ids"]]
    assert any(isinstance(d, dict) and d.get("feedback_id") == fid
               for d in linked)


def test_promote_unknown_feedback_is_404():
    assert c.post("/v1/feedback/fb_nope/promote").status_code == 404


def test_scrub_unit_shapes():
    assert feedback_mod.scrub("a@b.co") == "[email]"
    assert "secret" in feedback_mod.scrub("token github_pat_ABCdef123 here")
    assert feedback_mod.scrub("plain words stay") == "plain words stay"
