"""Sealed (Critic) — T84 owner: "라운드별로 미션 다르게 지정할수있게" + public runs with a daily limit.
POST /v1/arena/prompt takes an optional "rounds" list: the missions for round 2, 3, ... The server runs round 1, then
each next mission as a follow-up of the previous round (each lane continues from its own code), all inside the one
started job, so the chain shows R1..Rn with their own prompts. Anyone may start runs, bounded by a daily limit
(EVO_PUBLIC_DAILY_RUNS, default 20; a round counts as one run; a plan reserves all its rounds when it starts);
GET /v1/arena/limits reports it; over the limit -> 429 and nothing starts."""
from __future__ import annotations

import difflib
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
from evoforge import arena, arena_prompt, broker_meta, ledger  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
MARK = arena_prompt.REFERENCE_MARKER
USAGE = {"prompt_tokens": 1000, "completion_tokens": 200}
R1 = "A landing page for a coffee shop called Coffee Corner with a menu of at least three drinks and their prices."
R2 = "Add a footer that shows the opening hours 7:00-19:00."
R3 = "Add a tagline paragraph with class tagline that says Fresh every morning."
MENU = ('def render(state=None):\n    items = "".join(f"<li>{n} {p}</li>" for n, p in (("Latte", "4.5"), ("Mocha", "5.0"), '
        '("Americano", "3.5")))\n    return f\'<main><h1>Coffee Corner</h1><ul class="menu">{items}</ul>EXTRA</main>\'\n\n\n'
        'def preview():\n    return render()\n')
PAGES = {1: MENU.replace("EXTRA", ""),
         2: MENU.replace("EXTRA", "<footer>Open 7:00-19:00</footer>"),
         3: MENU.replace("EXTRA", "<p class=\"tagline\">Fresh every morning</p><footer>Open 7:00-19:00</footer>")}
H = "import re\nimport xml.etree.ElementTree as ET\n\nimport app\n\n\n"
TESTS = {
    1: [H + "def test_accept_title():\n    assert 'Coffee' in ''.join(ET.fromstring(app.render()).find('.//h1').itertext())\n",
        H + "def test_accept_menu():\n    assert len(ET.fromstring(app.render()).findall(\".//ul[@class='menu']/li\")) >= 3\n",
        H + "def test_accept_prices():\n    items = ET.fromstring(app.render()).findall('.//li')\n"
            "    assert len(items) >= 3 and all(re.search(r'\\d+\\.\\d', ''.join(li.itertext())) for li in items)\n"],
    2: [H + "def test_accept_footer():\n    assert '7:00-19:00' in ''.join(ET.fromstring(app.render()).find('.//footer').itertext())\n"],
    3: [H + "def test_accept_tagline():\n    e = ET.fromstring(app.render()).find(\".//p[@class='tagline']\")\n"
            "    assert e is not None and 'Fresh' in ''.join(e.itertext())\n"],
}


def _round_of(goal: str) -> int:
    return 3 if R3 in goal else 2 if R2 in goal else 1


def _settle(limit=600):
    end = time.time() + limit
    while time.time() < end and any(j["status"] in ("queued", "running") for j in c.get("/v1/eval/jobs").json()["jobs"]):
        time.sleep(0.3)


@pytest.fixture
def stubs(monkeypatch):
    _settle()
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.delenv("EVO_PUBLIC_DAILY_RUNS", raising=False)
    monkeypatch.setenv("EVO_EVAL_MAX_CENTS", "100000")
    ledger.reset(); ledger.configure({"default": 500000})
    arena.clear()
    goals, lock = [], threading.Lock()

    def builder(goal, sha, file_context=None, **k):
        current = next(f["content"] for f in (file_context or []) if f["path"] == "app.py")
        if MARK not in goal:
            with lock:
                goals.append(goal)
        target = PAGES[_round_of(goal)]
        d = "".join(difflib.unified_diff(current.splitlines(True), target.splitlines(True), "a/app.py", "b/app.py"))
        return {"diff": d, "tests": [], "rationale": "x", "stub": False, "model": "muse-spark-1.3",
                "provider_calls": [], "usage": USAGE}

    def critic(goal, diff, ci="", **k):
        tests = TESTS[_round_of(goal or "")]
        if "File contents" in (goal or ""):
            tests = [t.replace("def test_accept_", "def test_lane_") for t in tests]
        return {"sealed_tests": [{"code": t} for t in tests], "stub": False, "usage": USAGE}
    monkeypatch.setattr(broker_meta, "call_builder", builder)
    monkeypatch.setattr(broker_meta, "call_critic", critic)
    yield goals
    _settle()
    arena.clear()


def test_round_plan_runs_each_mission_as_its_own_round(stubs):
    r = c.post("/v1/arena/prompt", json={"prompt": R1, "rounds": [R2, R3]})
    assert r.status_code == 202, r.text
    root = r.json()["arena_id"]
    _settle()
    rounds = c.get(f"/v1/arena/{root}/chain").json()["rounds"]
    assert [x["round_index"] for x in rounds] == [1, 2, 3]
    assert [x["prompt"] for x in rounds] == [R1, R2, R3]
    assert [x["status"] for x in rounds] == ["succeeded"] * 3, [x.get("error") for x in rounds]
    assert rounds[1]["parent_id"] == rounds[0]["arena_id"] and rounds[2]["parent_id"] == rounds[1]["arena_id"]
    assert all(x["root_id"] == root for x in rounds)
    assert c.get(f"/v1/arena/{root}").json()["plan"] == [R1, R2, R3]
    assert any(R3 in g for g in stubs) and any(R2 in g and R3 not in g for g in stubs)  # each round got its mission
    assert rounds[2]["lanes"]["evoforge"]["heldout"]["n"] >= 3  # inherited + the round's own tests


def test_plan_validation(stubs):
    for bad in ([R2, ""], ["x" * 2001], [R2] * 5):
        r = c.post("/v1/arena/prompt", json={"prompt": R1, "rounds": bad})
        assert r.status_code == 422, (bad[:1], r.status_code)
    assert c.get("/v1/eval/jobs").json()["jobs"] == [] or all(
        j["status"] not in ("queued", "running") for j in c.get("/v1/eval/jobs").json()["jobs"])


def test_daily_limit_counts_rounds_and_blocks_over_limit(stubs, monkeypatch):
    lim = c.get("/v1/arena/limits").json()
    assert lim["daily_limit"] == 20 and lim["used_today"] == 0 and lim["remaining"] == 20  # default
    monkeypatch.setenv("EVO_PUBLIC_DAILY_RUNS", "3")
    r = c.post("/v1/arena/prompt", json={"prompt": R1, "rounds": [R2, R3, R2]})
    assert r.status_code == 429, r.text  # 4 rounds > 3 left: nothing starts
    r = c.post("/v1/arena/prompt", json={"prompt": R1, "rounds": [R2, R3]})
    assert r.status_code == 202, r.text
    lim = c.get("/v1/arena/limits").json()
    assert lim == {**lim, "daily_limit": 3, "used_today": 3, "remaining": 0}  # the plan reserved its 3 rounds
    _settle()
    r = c.post("/v1/arena/prompt", json={"prompt": R1})
    assert r.status_code == 429 and "limit" in r.text.lower()
    root = c.get("/v1/arena").json()["arenas"]
    assert c.get("/v1/arena/limits").json()["used_today"] == 3
    assert len([a for a in root if a.get("mode") == "prompt"]) == 3
