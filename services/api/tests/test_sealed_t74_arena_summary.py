"""Sealed (Critic) — T74 Arena scoreboard (external review: "no proof numbers on screen; run matches and fill the
numbers"). GET /v1/arena/summary aggregates EVERY stored Arena (not only the newest page): wins / ties per side,
unscorable and inconclusive kept apart (never counted as a result), held-out totals and model cost per side over the
scored comparisons only, plus judge cost. The Arena page shows it."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import arena  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


def _lane(passed, n, cost):
    return {"status": "succeeded", "heldout": {"passed": passed, "n": n}, "cost_cents": cost}


def _doc(aid, status, winner, s, e, judge=None, mode="prompt", t=0.0):
    d = {"arena_id": aid, "status": status, "mode": mode, "created_at": t,
         "verdict": {"winner": winner, "reason": "x"} if winner else None,
         "lanes": {"single": _lane(*s), "evoforge": _lane(*e)}}
    if judge is not None:
        d["judge_cost_cents"] = judge
    return d


DOCS = [
    _doc("a1", "succeeded", "evoforge", (1, 3, 6), (3, 3, 13), judge=10, t=1),
    _doc("a2", "succeeded", "tie", (3, 3, 4), (3, 3, 11), judge=9, t=2),
    _doc("a3", "succeeded", "single", (2, 2, 5), (1, 2, 20), mode=None, t=3),
    _doc("a4", "succeeded", "unscorable", (0, 0, 7), (0, 0, 12), judge=8, t=4),
    _doc("a5", "succeeded", "inconclusive", (0, 3, 3), (0, 3, 9), judge=5, t=5),
    _doc("a6", "failed", None, (0, 0, 0), (0, 0, 0), t=6),
    _doc("a7", "running", None, (0, 0, 0), (0, 0, 0), t=7),
] + [_doc(f"b{i}", "succeeded", "tie", (1, 1, 1), (1, 1, 2), judge=1, t=10 + i) for i in range(25)]


def _seed():
    arena.clear()
    store = arena._store()
    for d in DOCS:
        store[f"arena-{d['arena_id']}"] = {"id": f"arena-{d['arena_id']}", "kind": arena.KIND, "arena": d}


def test_summary_counts_every_arena_and_keeps_non_results_apart():
    _seed()
    r = c.get("/v1/arena/summary")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["total"] == 32 and s["running"] == 1 and s["failed"] == 1
    assert s["scored"] == 28  # a1, a2, a3 + 25 ties; more than one list page (LIST_LIMIT)
    assert s["wins"] == {"evoforge": 1, "single": 1, "tie": 26}
    assert s["unscorable"] == 1 and s["inconclusive"] == 1
    assert s["heldout"] == {"single": {"passed": 6 + 25, "n": 8 + 25}, "evoforge": {"passed": 7 + 25, "n": 8 + 25}}
    assert s["cost_cents"] == {"single": 15 + 25, "evoforge": 44 + 50, "judge": 19 + 25}
    assert all(isinstance(v, int) for v in s["cost_cents"].values())  # money is integer cents
    assert isinstance(s.get("basis"), str) and "scored" in s["basis"]
    arena.clear()


def test_empty_summary_is_zero_not_missing():
    arena.clear()
    s = c.get("/v1/arena/summary").json()
    assert s["total"] == 0 and s["scored"] == 0 and s["wins"] == {"evoforge": 0, "single": 0, "tie": 0}
    assert s["cost_cents"] == {"single": 0, "evoforge": 0, "judge": 0}


def test_arena_page_shows_the_summary():
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "getArenaSummary" in api and "/v1/arena/summary" in api
    page = (WEB / "app" / "[locale]" / "arena" / "page.tsx").read_text(encoding="utf-8")
    assert "getArenaSummary" in page
    import json
    for loc in ("en", "ko"):
        m = json.loads((WEB / "messages" / f"{loc}.json").read_text(encoding="utf-8"))
        assert m["arena"].get("summary-heading"), loc
