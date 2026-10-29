"""Sealed (Critic) — T79 the scoreboard separates equal-tools comparisons. Production 2026-10-30: sealed-v5 matches run
with the original harness gave the single lane a strict hunk-count rule the EvoForge lane does not face, and the single
lane lost one match only for that. A match counts as equal tools when its single lane applied patches tolerantly
(manifest.lanes.single.apply == "tolerant"; prompt Arenas use tolerant by default). /v1/arena/summary adds an
"equal_tools" block with the same fields over those matches only; the home and Arena cards show it first."""
from __future__ import annotations

import json
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


def _doc(aid, winner, s, e, apply, mode=None, judge=None):
    d = {"arena_id": aid, "status": "succeeded", "mode": mode, "created_at": 1.0,
         "verdict": {"winner": winner, "reason": "x"},
         "manifest": {"lanes": {"single": {"apply": apply} if apply else {}, "evoforge": {}}},
         "lanes": {"single": {"status": "succeeded", "heldout": {"passed": s[0], "n": s[1]}, "cost_cents": s[2]},
                   "evoforge": {"status": "succeeded", "heldout": {"passed": e[0], "n": e[1]}, "cost_cents": e[2]}}}
    if judge is not None:
        d["judge_cost_cents"] = judge
    return d


DOCS = [
    _doc("s1", "evoforge", (0, 3, 4), (3, 3, 12), "strict"),          # strict harness: not equal tools
    _doc("s2", "evoforge", (0, 3, 28), (3, 3, 78), None),             # old record without apply -> strict
    _doc("t1", "evoforge", (1, 3, 20), (3, 3, 60), "tolerant"),
    _doc("t2", "tie", (3, 3, 10), (3, 3, 30), "tolerant"),
    _doc("p1", "single", (3, 3, 6), (2, 3, 13), "tolerant", mode="prompt", judge=10),
]


def _seed():
    arena.clear()
    store = arena._store()
    for d in DOCS:
        store[f"arena-{d['arena_id']}"] = {"id": f"arena-{d['arena_id']}", "kind": arena.KIND, "arena": d}


def test_equal_tools_block_counts_only_tolerant_matches():
    _seed()
    s = c.get("/v1/arena/summary").json()
    assert s["scored"] == 5 and s["wins"] == {"evoforge": 3, "single": 1, "tie": 1}  # overall block unchanged
    eq = s["equal_tools"]
    assert eq["scored"] == 3 and eq["wins"] == {"evoforge": 1, "single": 1, "tie": 1}
    assert eq["heldout"] == {"single": {"passed": 7, "n": 9}, "evoforge": {"passed": 8, "n": 9}}
    assert eq["cost_cents"] == {"single": 36, "evoforge": 103, "judge": 10}
    arena.clear()


def test_empty_equal_tools_block_is_zero():
    arena.clear()
    eq = c.get("/v1/arena/summary").json()["equal_tools"]
    assert eq["scored"] == 0 and eq["wins"] == {"evoforge": 0, "single": 0, "tie": 0}


def test_cards_show_equal_tools_first():
    for rel in (("app", "[locale]", "page.tsx"), ("app", "[locale]", "arena", "page.tsx")):
        page = (WEB.joinpath(*rel)).read_text(encoding="utf-8")
        assert "equal_tools" in page, rel
    for loc in ("en", "ko"):
        m = json.loads((WEB / "messages" / f"{loc}.json").read_text(encoding="utf-8"))
        assert m["arena"].get("summary-equal-tools"), loc
