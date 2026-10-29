"""Sealed (Critic) — T75 live Arena progress (owner: "type and watch the result evolve live"). In production a running
prompt Arena showed no lane events at all: each lane kept its events in a local list until it finished, so the home
"AI status" panel stayed idle for the whole run. While an Arena runs, GET /v1/arena/{id} must show each lane's events
as they happen (and the judge's step), with hidden acceptance test names scrubbed exactly as in the final document."""
from __future__ import annotations

import difflib
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
REFERENCE_MARK = getattr(__import__("evoforge.arena_prompt", fromlist=["x"]), "REFERENCE_MARKER", "<no reference build>")
USAGE = {"prompt_tokens": 1000, "completion_tokens": 200}
PROMPT = "A landing page for a tea shop called Leaf & Cup with a menu of at least three teas and their prices."
FULL = '''def render(state=None):
    items = "".join(f"<li>{n} {p}</li>" for n, p in (("Sencha", "4.5"), ("Earl Grey", "4.0"), ("Chai", "5.0")))
    return f'<main><h1>Leaf and Cup</h1><ul class="menu">{items}</ul></main>'


def preview():
    return render()
'''
ACCEPT = [
    "import xml.etree.ElementTree as ET\n\nimport app\n\n\ndef test_accept_secret_title():\n"
    "    e = ET.fromstring(app.render())\n    assert 'Leaf' in ''.join(e.find('.//h1').itertext())\n",
    "import xml.etree.ElementTree as ET\n\nimport app\n\n\ndef test_accept_secret_menu():\n"
    "    e = ET.fromstring(app.render())\n    assert len(e.findall(\".//ul[@class='menu']/li\")) >= 3\n",
    "import re\nimport xml.etree.ElementTree as ET\n\nimport app\n\n\ndef test_accept_secret_prices():\n"
    "    items = ET.fromstring(app.render()).findall('.//li')\n"
    "    assert len(items) >= 3 and all(re.search(r'\\d+\\.\\d', ''.join(li.itertext())) for li in items)\n",
]


def _settle(limit=300):
    end = time.time() + limit
    while time.time() < end and any(j["status"] in ("queued", "running") for j in c.get("/v1/eval/jobs").json()["jobs"]):
        time.sleep(0.3)


@pytest.fixture
def gate(monkeypatch):
    _settle()
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset(); ledger.configure({"default": 500000})
    release = threading.Event()

    def builder(goal, sha, file_context=None, **k):
        if REFERENCE_MARK not in goal:  # T76: the judge's reference build runs before the lanes
            release.wait(120)  # hold every lane Builder call until the test has looked at the running Arena
        current = next(f["content"] for f in (file_context or []) if f["path"] == "app.py")
        d = "".join(difflib.unified_diff(current.splitlines(True), FULL.splitlines(True), "a/app.py", "b/app.py"))
        return {"diff": d, "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": USAGE}

    def critic(goal, diff, ci="", **k):
        tests = list(ACCEPT)
        if "File contents" in (goal or ""):  # the EvoForge lane's own Critic
            tests = [t.replace("def test_accept_secret_", "def test_lane_") for t in tests]
        return {"sealed_tests": [{"code": t} for t in tests], "stub": False, "usage": USAGE}
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    monkeypatch.setattr(broker_meta, "call_critic", critic)
    yield release
    release.set()
    _settle()


def _roles(doc, side):
    return [e.get("role") for e in (doc["lanes"][side].get("events") or [])]


def test_running_arena_shows_lane_events_live(gate):
    r = c.post("/v1/arena/prompt", json={"prompt": PROMPT})
    assert r.status_code == 202, r.text
    aid = r.json()["arena_id"]
    live = None
    end = time.time() + 60
    while time.time() < end:
        doc = c.get(f"/v1/arena/{aid}").json()
        if doc["status"] == "running" and "builder" in _roles(doc, "single") and "critic" in _roles(doc, "evoforge"):
            live = doc
            break
        time.sleep(0.2)
    assert live is not None, "no live lane events while the Builders were still working"
    assert live["status"] == "running"
    blob = json.dumps(live)
    assert "test_accept_secret" not in blob  # hidden judge test names never appear, live or final
    judge = [e for e in (live.get("events") or []) if e.get("role") == "judge"]
    assert judge and "3" in judge[0]["message"]  # the judge's step: how many acceptance tests were fixed
    for side in ("single", "evoforge"):
        seqs = [e["seq"] for e in live["lanes"][side]["events"]]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    gate.set()
    end = time.time() + 300
    while time.time() < end:
        done = c.get(f"/v1/arena/{aid}").json()
        if done["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.3)
    assert done["status"] == "succeeded"
    for side in ("single", "evoforge"):
        final = done["lanes"][side]["events"]
        assert [e["message"] for e in final][:len(live["lanes"][side]["events"])] == \
            [e["message"] for e in live["lanes"][side]["events"]]  # live events are a prefix of the final ones
    assert "test_accept_secret" not in json.dumps(done)
    assert any(e.get("role") == "judge" for e in done.get("events") or [])


def test_list_shows_live_events_too(gate):
    r = c.post("/v1/arena/prompt", json={"prompt": PROMPT})
    aid = r.json()["arena_id"]
    end = time.time() + 60
    seen = False
    while time.time() < end and not seen:
        arenas = c.get("/v1/arena").json()["arenas"]
        doc = next((a for a in arenas if a["arena_id"] == aid), None)
        seen = bool(doc and doc["status"] == "running" and _roles(doc, "single"))
        time.sleep(0.2)
    gate.set()
    assert seen, "GET /v1/arena (used by the home workspace) must carry the live events as well"
