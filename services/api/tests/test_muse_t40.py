"""Muse T40 live updates: SSE stream of mission/eval-job events.

The stream log is process-global, so every test captures the current max
seq first and reads cursor-relative (`after=<mark>`); nothing here assumes
the backlog starts empty.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)
os.environ["EVO_PROJECT_BUDGET_CENTS"] = "50000"

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import eval_jobs, ledger  # noqa: E402
from evoforge import missions as missions_store  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)

SAFE_KEYS = {"seq", "type", "mission_id", "job_id", "state", "status", "ts"}


def setup_function(_):
    ledger.reset()
    ledger.configure({"default": 50000})
    missions_store.reset()
    main._evidence.clear()
    eval_jobs.clear()


def _mark():
    """Current max stream seq; events published after this are ours."""
    return int(main._STREAM_SEQ)


def _read(mark, **qs):
    params = {"after": mark, "limit": 500, "wait": 0, **qs}
    r = c.get("/v1/stream", params=params)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream"), r.headers
    return r.text


def _frames(text):
    out = []
    for chunk in text.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        lines = chunk.splitlines()
        assert len(lines) == 2, lines
        assert lines[0].startswith("id: "), lines
        assert lines[1].startswith("data: "), lines
        seq = int(lines[0][4:].strip())
        data = json.loads(lines[1][6:])
        assert data["seq"] == seq
        out.append(data)
    return out


def _create(goal="stream canary"):
    r = c.post("/v1/missions", json={"goal": goal, "repo_ref": "HEAD"})
    assert r.status_code == 201, r.text
    return r.json()


def test_mission_created_event():
    mark = _mark()
    out = _create()
    frames = [f for f in _frames(_read(mark)) if f.get("mission_id") == out["mission_id"]]
    assert frames, out
    created = frames[0]
    assert created["type"] == "mission.created"
    assert created["state"] == "CREATED"
    assert isinstance(created["seq"], int) and created["seq"] > mark
    assert isinstance(created["ts"], (int, float))
    for f in frames:
        assert set(f) <= SAFE_KEYS, f


def test_advance_and_cancel_events():
    mark = _mark()
    mid = _create()["mission_id"]
    r = c.post(f"/v1/missions/{mid}/advance", json={"to": "GENERATED"})
    assert r.status_code == 200, r.text
    r = c.post(f"/v1/missions/{mid}/cancel")
    assert r.status_code == 200, r.text
    frames = [f for f in _frames(_read(mark)) if f.get("mission_id") == mid]
    types = [(f["type"], f["state"]) for f in frames]
    assert ("mission.created", "CREATED") in types
    assert ("mission.advanced", "GENERATED") in types
    assert ("mission.cancelled", "CANCELLED") in types
    seqs = [f["seq"] for f in frames]
    assert seqs == sorted(seqs)
    assert "def test_" not in _read(mark)


def test_after_and_limit():
    mark = _mark()
    a = _create("first")["mission_id"]
    mid_a = next(f["seq"] for f in _frames(_read(mark)) if f.get("mission_id") == a)
    b = _create("second")["mission_id"]
    tail = _frames(_read(mid_a))
    assert tail, "expected events after seq of first mission"
    assert all(f["seq"] > mid_a for f in tail)
    assert any(f.get("mission_id") == b for f in tail)
    assert not any(f.get("mission_id") == a for f in tail)
    one = _frames(_read(mark, limit=1))
    assert len(one) == 1
    many = _frames(_read(0, limit=1000))
    assert len(many) <= 500


def test_eval_job_updated_event():
    mark = _mark()
    job = eval_jobs.create_job(kind="X_SINGLE", runner=lambda: {"ok": True})
    deadline = time.time() + 30
    last = None
    while time.time() < deadline:
        last = c.get(f"/v1/eval/jobs/{job['job_id']}").json()
        if last["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    assert last is not None and last["status"] == "succeeded", last
    frames = [f for f in _frames(_read(mark)) if f.get("job_id") == job["job_id"]]
    assert frames, "expected eval_job.updated events"
    assert all(f["type"] == "eval_job.updated" for f in frames)
    statuses = [f["status"] for f in frames]
    assert "queued" in statuses
    assert "succeeded" in statuses
    for f in frames:
        assert set(f) <= SAFE_KEYS, f


def test_wait_returns_early_on_new_event():
    mark = _mark()
    holder: dict = {}

    def _poll():
        r = c.get("/v1/stream", params={"after": mark, "limit": 1, "wait": 10})
        holder["status"] = r.status_code
        holder["text"] = r.text
        holder["elapsed"] = time.time() - holder["start"]

    holder["start"] = time.time()
    t = threading.Thread(target=_poll, daemon=True)
    t.start()
    time.sleep(0.5)
    out = _create("late arrival")
    t.join(timeout=15)
    assert not t.is_alive(), "stream did not return after a new event"
    assert holder.get("status") == 200
    assert holder.get("elapsed", 999) < 9, holder.get("elapsed")
    frames = [f for f in _frames(holder["text"]) if f.get("mission_id") == out["mission_id"]]
    assert frames and frames[0]["type"] == "mission.created"
