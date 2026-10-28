"""Sealed (Critic) — T43 Feedback Intelligence (blueprint §18): feedback on a mission becomes a linked improvement
mission (closed loop, R18-1), links are checked (R18-2), personal data and secrets are scrubbed (R18-3)."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


def _mission(goal="add div(a, b)"):
    r = c.post("/v1/missions", json={"goal": goal, "repo_ref": "HEAD"})
    assert r.status_code == 201, r.text
    return r.json()["mission_id"]


def test_feedback_is_stored_with_its_link_and_listed_newest_first():
    mid = _mission()
    a = c.post("/v1/feedback", json={"mission_id": mid, "kind": "missed_case", "text": "div(0, 5) should return 0.0"})
    b = c.post("/v1/feedback", json={"mission_id": mid, "kind": "bug", "text": "negative divisor case"})
    assert a.status_code == 201 and b.status_code == 201, (a.text, b.text)
    items = c.get("/v1/feedback").json()["feedback"]
    ids = [x["feedback_id"] for x in items]
    assert ids.index(b.json()["feedback_id"]) < ids.index(a.json()["feedback_id"])
    assert all(x["mission_id"] == mid for x in items[:2])


def test_unknown_link_is_refused():
    r = c.post("/v1/feedback", json={"mission_id": "msn_doesnotexist", "kind": "bug", "text": "x"})
    assert r.status_code == 404
    assert c.post("/v1/feedback", json={"mission_id": _mission(), "kind": "nonsense", "text": "x"}).status_code == 422


def test_personal_data_and_secrets_are_scrubbed_before_storage():
    mid = _mission()
    text = "contact me at jane.doe@example.com, token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 and sk-live_abcdefghijklmnop1234"
    fid = c.post("/v1/feedback", json={"mission_id": mid, "kind": "bug", "text": text}).json()["feedback_id"]
    blob = json.dumps(c.get("/v1/feedback").json())
    assert "jane.doe@example.com" not in blob and "ghp_ABCDEF" not in blob and "sk-live_abc" not in blob
    stored = json.dumps({k: v for k, v in main._evidence.items() if isinstance(v, dict) and v.get("kind") == "feedback"})
    assert "jane.doe@example.com" not in stored and fid in stored


def test_promote_creates_a_linked_improvement_mission():
    mid = _mission("add div(a, b) that raises ValueError on b == 0")
    fid = c.post("/v1/feedback", json={"mission_id": mid, "kind": "missed_case", "text": "div(0, 5) must return 0.0"}).json()["feedback_id"]
    r = c.post(f"/v1/feedback/{fid}/promote")
    assert r.status_code == 201, r.text
    new_mid = r.json()["mission_id"]
    assert new_mid != mid
    m = c.get(f"/v1/missions/{new_mid}").json()
    assert "div(0, 5) must return 0.0" in m["goal"] and "add div" in m["goal"]
    fb = next(x for x in c.get("/v1/feedback").json()["feedback"] if x["feedback_id"] == fid)
    assert fb["promoted_mission_id"] == new_mid
    again = c.post(f"/v1/feedback/{fid}/promote")
    assert again.status_code in (200, 409) and new_mid in again.text  # idempotent: no second mission


def test_web_has_feedback_form_and_proxy_routes():
    policy = (WEB / "lib" / "proxyPolicy.ts").read_text(encoding="utf-8")
    assert "/v1/feedback" in policy
    src = "".join(p.read_text(encoding="utf-8") for p in (WEB / "app" / "[locale]").rglob("*.tsx")) + \
          "".join(p.read_text(encoding="utf-8") for p in (WEB / "components").rglob("*.tsx"))
    assert re.search(r"postFeedback|createFeedback|sendFeedback", src) and re.search(r"promoteFeedback", src)
