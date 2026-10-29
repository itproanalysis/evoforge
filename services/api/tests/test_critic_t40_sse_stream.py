"""Critic acceptance (sealed during build, promoted after) — T40: Mission Control gets live updates over SSE (GET /v1/stream) instead of 5 s polling."""
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


def _frames(text):
    out = []
    for block in text.split("\n\n"):
        data = [ln[5:].strip() for ln in block.splitlines() if ln.startswith("data:")]
        if data:
            out.append(json.loads("\n".join(data)))
    return out


def test_stream_replays_mission_events_after_a_cursor():
    r0 = c.get("/v1/stream", params={"limit": 500, "wait": 0})
    assert r0.status_code == 200 and r0.headers["content-type"].startswith("text/event-stream")
    seen = _frames(r0.text)
    cursor = max((f["seq"] for f in seen), default=0)  # newest event so far (other tests share the process bus)
    m = c.post("/v1/missions", json={"goal": "sse probe", "repo_ref": "HEAD"}).json()
    r = c.get("/v1/stream", params={"after": cursor, "limit": 500, "wait": 2})
    frames = _frames(r.text)
    assert any(f.get("type", "").startswith("mission") and f.get("mission_id") == m["mission_id"] for f in frames), frames
    assert all(f["seq"] > cursor for f in frames) and [f["seq"] for f in frames] == sorted(f["seq"] for f in frames)


def test_stream_frames_carry_no_code_or_secrets():
    c.post("/v1/missions", json={"goal": "sse leak probe", "repo_ref": "HEAD"})
    text = c.get("/v1/stream", params={"limit": 200, "wait": 0}).text
    assert "def test_" not in text and "MODEL_API_KEY" not in text and "+++ " not in text


def test_proxy_streams_and_page_uses_eventsource_with_polling_fallback():
    route = (WEB / "app" / "api" / "evoforge" / "[...path]" / "route.ts").read_text(encoding="utf-8")
    policy = (WEB / "lib" / "proxyPolicy.ts").read_text(encoding="utf-8")
    assert "/v1/stream" in policy
    assert "text/event-stream" in route or "upstream.body" in route
    page = (WEB / "app" / "[locale]" / "page.tsx").read_text(encoding="utf-8")
    assert "EventSource" in page and re.search(r"setInterval|setTimeout", page), "SSE first, polling as fallback"
