"""Critic acceptance (sealed during build, promoted after) — T31: /v1/evolution/{id}/run returns at once and runs generations in the background (the web
proxy cuts requests at 300 s); the web polls; /verify shows whether a certificate is really signed."""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta  # noqa: E402
from evoforge import evolution as evo_engine  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "apps" / "web"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVOLUTION_MAX_CENTS", "100000")
    evo_engine.reset()
    yield
    _wait_idle()


def _wait_idle(timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        evs = c.get("/v1/evolution").json().get("evolutions", [])
        if not any(e.get("run_active") for e in evs):
            return
        time.sleep(0.2)


def _slow_builder(gate):
    real = broker_meta.call_builder

    def slow(*a, **k):
        gate.wait(10)
        return real(*a, **k)
    return slow


def _start(gens=2):
    r = c.post("/v1/evolution/start", json={"goal": "async run probe", "max_generations": gens, "population": 1})
    assert r.status_code == 201, r.text
    return r.json()["evolution_id"]


def _wait_terminal(eid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        body = c.get(f"/v1/evolution/{eid}").json()
        if body["status"] != "RUNNING" and not body.get("run_active"):
            return body
        time.sleep(0.2)
    pytest.fail("evolution did not finish")


def test_run_returns_202_before_generations_finish(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(broker_meta, "call_builder", _slow_builder(gate))
    eid = _start()
    t0 = time.time()
    r = c.post(f"/v1/evolution/{eid}/run")
    elapsed = time.time() - t0
    gate.set()
    assert r.status_code == 202, r.text
    assert elapsed < 5, f"/run blocked {elapsed:.1f}s; generations must run outside the request"
    assert r.json()["evolution_id"] == eid and r.json().get("run_active") is True
    done = _wait_terminal(eid)
    assert done["status"] == "EXHAUSTED" and len(done["generations"]) == 2, "offline runs exhaust honestly"
    assert done.get("run_active") is False


def test_second_run_or_step_while_active_is_409(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(broker_meta, "call_builder", _slow_builder(gate))
    eid = _start()
    assert c.post(f"/v1/evolution/{eid}/run").status_code == 202
    second = c.post(f"/v1/evolution/{eid}/run")
    step = c.post(f"/v1/evolution/{eid}/step")
    gate.set()
    assert second.status_code == 409, second.text
    assert step.status_code == 409, step.text
    _wait_terminal(eid)


def test_run_on_terminal_evolution_is_rejected():
    eid = _start(gens=1)
    assert c.post(f"/v1/evolution/{eid}/run").status_code == 202
    _wait_terminal(eid)
    again = c.post(f"/v1/evolution/{eid}/run")
    assert again.status_code in (200, 409), again.text
    assert c.get(f"/v1/evolution/{eid}").json()["status"] == "EXHAUSTED"


def test_unknown_evolution_run_is_404():
    assert c.post("/v1/evolution/evo_missing/run").status_code == 404


def test_background_failure_is_recorded_not_lost(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("builder exploded")
    monkeypatch.setattr(main, "_evolution_step_locked", lambda eid: (_ for _ in ()).throw(RuntimeError("step crashed")))
    eid = _start()
    assert c.post(f"/v1/evolution/{eid}/run").status_code == 202
    end = time.time() + 30
    while time.time() < end:
        body = c.get(f"/v1/evolution/{eid}").json()
        if not body.get("run_active"):
            break
        time.sleep(0.2)
    assert body.get("run_active") is False
    assert body.get("run_error") and "step crashed" in body["run_error"], body


# ---- web ----

def _read(rel):
    return (WEB / rel).read_text(encoding="utf-8")


def test_evolution_page_polls_instead_of_waiting_on_run():
    page = _read("app/[locale]/evolution/page.tsx")
    assert re.search(r"setInterval|setTimeout", page), "the page must poll the evolution while a run is active"
    assert "run_active" in page or "runActive" in page


def test_verify_page_shows_signed_or_unsigned_honestly():
    page = _read("app/[locale]/verify/[id]/page.tsx")
    assert re.search(r"\.signed\b", page), "the page must read cert.signed"
    assert "/v1/proof/key" in page or "getProofKey" in page + _read("lib/api.ts")
    ko = json.loads(_read("messages/ko.json"))
    en = json.loads(_read("messages/en.json"))
    flat_ko = json.dumps(ko, ensure_ascii=False)
    flat_en = json.dumps(en)
    assert "Ed25519" in flat_en and "Ed25519" in flat_ko
    assert re.search(r"[Uu]nsigned|not signed", flat_en)
