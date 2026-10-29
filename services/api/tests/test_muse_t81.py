"""T81 scoreboard significance (API)."""
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


def _doc(aid, winner, s, e, apply):
    return {"arena_id": aid, "status": "succeeded", "created_at": 1.0,
            "verdict": {"winner": winner, "reason": "x"},
            "manifest": {"lanes": {"single": {"apply": apply}, "evoforge": {}}},
            "lanes": {"single": {"status": "succeeded", "heldout": {"passed": s[0], "n": s[1]}, "cost_cents": 0},
                      "evoforge": {"status": "succeeded", "heldout": {"passed": e[0], "n": e[1]}, "cost_cents": 0}}}


def _seed(docs):
    arena.clear()
    store = arena._store()
    for d in docs:
        store[f"arena-{d['arena_id']}"] = {"id": f"arena-{d['arena_id']}", "kind": arena.KIND, "arena": d}


def test_stats_empty():
    _seed([])
    eq = c.get("/v1/arena/summary").json()["equal_tools"]
    st = eq["stats"]
    assert st["tasks"] == 0
    assert st["solved"] == {"single": 0, "evoforge": 0}
    assert st["wilson95"] == {"single": None, "evoforge": None}
    assert st["decisive"] == {"evoforge": 0, "single": 0}
    assert st["sign_test_p"] is None
    assert st["significant"] is False
    arena.clear()


def test_stats_production_example():
    docs = []
    for i in range(9):
        docs.append(_doc(f"t{i}", "tie", (2, 2), (2, 2), "tolerant"))
    for i in range(9, 12):
        docs.append(_doc(f"t{i}", "evoforge", (0, 2), (2, 2), "tolerant"))
    _seed(docs)
    eq = c.get("/v1/arena/summary").json()["equal_tools"]
    st = eq["stats"]
    assert st["tasks"] == 12
    assert st["solved"] == {"single": 9, "evoforge": 12}
    assert st["decisive"] == {"evoforge": 3, "single": 0}
    assert abs(st["sign_test_p"] - 0.25) < 1e-9
    assert st["significant"] is False
    assert st["wilson95"]["evoforge"] == [0.757, 1.0]
    assert st["wilson95"]["single"] == [0.468, 0.911]
    arena.clear()
