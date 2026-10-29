"""Sealed (Critic) — T81 the scoreboard states its own significance (v3.6 rule: no claim the data does not support).
Production v5 with equal tools: EvoForge solved 12/12, single 9/12, paired 3-0 with 9 ties — not significant at n=12.
The equal-tools block adds task-level counts (a match is "solved" by a side when its held-out passed == n > 0), 95%
Wilson intervals for both, and the exact two-sided sign test over decisive matches; the cards say whether it is
significant (p < 0.05) in plain words."""
from __future__ import annotations

import json
import math
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


def _doc(aid, winner, s, e):
    return {"arena_id": aid, "status": "succeeded", "created_at": 1.0,
            "verdict": {"winner": winner, "reason": "x"},
            "manifest": {"lanes": {"single": {"apply": "tolerant"}, "evoforge": {}}},
            "lanes": {"single": {"heldout": {"passed": s, "n": 3}, "cost_cents": 5},
                      "evoforge": {"heldout": {"passed": e, "n": 3}, "cost_cents": 9}}}


def _seed(docs):
    arena.clear()
    store = arena._store()
    for d in docs:
        store[f"arena-{d['arena_id']}"] = {"id": f"arena-{d['arena_id']}", "kind": arena.KIND, "arena": d}


def _wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c_ = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(c_ - h, 3), round(c_ + h, 3)


V5 = ([_doc(f"w{i}", "evoforge", 0, 3) for i in range(3)] + [_doc(f"t{i}", "tie", 3, 3) for i in range(9)])


def test_v5_shape_is_not_significant():
    _seed(V5)
    st = c.get("/v1/arena/summary").json()["equal_tools"]["stats"]
    assert st["tasks"] == 12 and st["solved"] == {"single": 9, "evoforge": 12}
    assert st["wilson95"]["single"] == list(_wilson(9, 12)) and st["wilson95"]["evoforge"] == list(_wilson(12, 12))
    assert st["decisive"] == {"evoforge": 3, "single": 0}
    assert abs(st["sign_test_p"] - 0.25) < 1e-9 and st["significant"] is False
    arena.clear()


def test_six_zero_is_significant_and_ties_do_not_count():
    _seed([_doc(f"w{i}", "evoforge", 1, 3) for i in range(6)] + [_doc("t", "tie", 3, 3)])
    st = c.get("/v1/arena/summary").json()["equal_tools"]["stats"]
    assert st["decisive"] == {"evoforge": 6, "single": 0}
    assert abs(st["sign_test_p"] - 2 * 0.5 ** 6) < 1e-9 and st["significant"] is True
    assert st["tasks"] == 7 and st["solved"] == {"single": 1, "evoforge": 7}  # single 1/3 in the wins is not "solved"
    arena.clear()


def test_no_decisive_matches_has_no_p_value():
    _seed([_doc("t", "tie", 3, 3)])
    st = c.get("/v1/arena/summary").json()["equal_tools"]["stats"]
    assert st["sign_test_p"] is None and st["significant"] is False
    arena.clear()


def test_cards_say_it_in_words():
    for rel in (("app", "[locale]", "page.tsx"), ("app", "[locale]", "arena", "page.tsx")):
        assert "sign_test_p" in (WEB.joinpath(*rel)).read_text(encoding="utf-8"), rel
    for loc in ("en", "ko"):
        a = json.loads((WEB / "messages" / f"{loc}.json").read_text(encoding="utf-8"))["arena"]
        assert a.get("summary-significant") and a.get("summary-not-significant"), loc
