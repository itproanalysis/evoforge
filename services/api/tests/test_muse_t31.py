"""T31: background evolution runs (proxy-safe) + verify signature status UI data."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient

import main
from evoforge import evolution as evo_engine

client = TestClient(main.app)


def setup_function(_):
    evo_engine.reset()


def _start(max_generations=2, population=1):
    r = client.post("/v1/evolution/start", json={
        "goal": "t31 probe", "max_generations": max_generations,
        "population": population})
    assert r.status_code == 201, r.text
    return r.json()["evolution_id"]


def _wait_until(eid, pred, timeout=30.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = client.get(f"/v1/evolution/{eid}").json()
        if pred(last):
            return last
        time.sleep(0.05)
    return last


def _wait_terminal(eid, timeout=30.0):
    return _wait_until(
        eid,
        lambda d: not d.get("run_active") and d.get("status") != "RUNNING",
        timeout)


def test_fresh_run_returns_202_immediately_then_completes():
    """Fresh runs go to background: fast 202, pollable to EXHAUSTED."""
    eid = _start()
    t0 = time.monotonic()
    r = client.post(f"/v1/evolution/{eid}/run")
    elapsed = time.monotonic() - t0
    assert r.status_code == 202, r.text
    assert elapsed < 5, f"/run blocked {elapsed:.2f}s; must return outside the request"
    body = r.json()
    assert body["evolution_id"] == eid
    assert body["status"] == "RUNNING"
    assert body["run_active"] is True
    done = _wait_terminal(eid)
    assert done["status"] == "EXHAUSTED"
    assert done["run_active"] is False
    assert done["run_error"] is None
    assert len(done["generations"]) == 2


def test_run_unknown_404_and_terminal_200_without_new_run():
    assert client.post("/v1/evolution/evo_nope/run").status_code == 404
    assert client.get("/v1/evolution/evo_nope").status_code == 404
    eid = _start(max_generations=1)
    r = client.post(f"/v1/evolution/{eid}/run")
    assert r.status_code == 202, r.text
    final = _wait_terminal(eid)
    assert final["status"] in ("CONVERGED", "EXHAUSTED", "CANCELLED")
    n = len(final["generations"])
    again = client.post(f"/v1/evolution/{eid}/run")
    assert again.status_code == 200, again.text
    assert again.json()["evolution_id"] == eid
    assert again.json()["run_active"] is False
    assert len(again.json()["generations"]) == n  # no new run started


def test_step_and_rerun_conflict_while_background_active(monkeypatch):
    """Blocked worker: /step and /run conflict with 409 until it drains."""
    import threading
    started = threading.Event()
    release = threading.Event()

    orig = main._evolution_step_locked

    def slow(evolution_id):
        started.set()
        assert release.wait(timeout=30)
        return orig(evolution_id)

    monkeypatch.setattr(main, "_evolution_step_locked", slow)
    eid = _start(max_generations=3)
    t0 = time.monotonic()
    r = client.post(f"/v1/evolution/{eid}/run")
    assert time.monotonic() - t0 < 5
    assert r.status_code == 202, r.text
    assert started.wait(timeout=30)
    assert client.post(f"/v1/evolution/{eid}/step").status_code == 409
    assert client.post(f"/v1/evolution/{eid}/run").status_code == 409
    mid = client.get(f"/v1/evolution/{eid}").json()
    assert mid["run_active"] is True
    assert mid["status"] == "RUNNING"
    release.set()
    final = _wait_terminal(eid)
    assert final["run_active"] is False
    assert final["status"] == "EXHAUSTED"
    assert len(final["generations"]) == 3


def test_background_failure_is_recorded_not_lost(monkeypatch):
    """Worker exceptions stop the run and surface as run_error (not a 500)."""
    def boom(evolution_id):
        raise ValueError("slow kaboom " + "x" * 500)
    monkeypatch.setattr(main, "_evolution_step_locked", boom)
    eid = _start()
    r = client.post(f"/v1/evolution/{eid}/run")
    assert r.status_code == 202, r.text
    final = _wait_until(
        eid, lambda d: not d.get("run_active") and d.get("run_error"))
    assert final is not None
    assert final["run_active"] is False
    assert final["run_error"] is not None
    assert "ValueError" in final["run_error"]
    assert len(final["run_error"]) <= 300


def test_stepped_run_drains_inline_200():
    """Legacy interactive path: step once, then /run finishes inline with 200."""
    eid = _start()
    s = client.post(f"/v1/evolution/{eid}/step")
    assert s.status_code == 200, s.text
    r = client.post(f"/v1/evolution/{eid}/run")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "EXHAUSTED"
    assert len(r.json()["generations"]) == 2


def test_list_and_detail_include_run_flags():
    eid = _start()
    body = client.get("/v1/evolution").json()
    rows = [e for e in body["evolutions"] if e["evolution_id"] == eid]
    assert rows and rows[0]["run_active"] is False
    assert rows[0]["run_error"] is None
    detail = client.get(f"/v1/evolution/{eid}").json()
    assert detail["run_active"] is False
    assert detail["run_error"] is None
