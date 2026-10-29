"""Sealed (Critic) — T78 the first screen shows the measured result (external review: "no proof numbers on the screens";
the judge's first impression is the home page). Under the explanation and above the workspace: the Arena scoreboard
from GET /v1/arena/summary (wins per side, ties, hidden-test totals, cost per side) with a link to the Arena."""
from __future__ import annotations

import json
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


def test_home_reads_the_summary_and_places_it_after_the_intro():
    page = (WEB / "app" / "[locale]" / "page.tsx").read_text(encoding="utf-8")
    assert "getArenaSummary" in page
    i_intro = page.find('tWorkspace("intro")')
    i_board = page.find('tWorkspace("scoreboard-heading")')
    i_bar = page.find("<PromptBar")
    assert -1 < i_intro < i_board < i_bar, "scoreboard sits between the explanation and the input"
    for field in ("wins", "heldout", "cost_cents"):
        assert field in page[i_board:i_bar] or field in page, field
    assert "/arena" in page[i_board:i_bar]


def test_scoreboard_labels_in_both_languages():
    for loc in ("en", "ko"):
        ws = json.loads((WEB / "messages" / f"{loc}.json").read_text(encoding="utf-8"))["workspace"]
        for k in ("scoreboard-heading", "scoreboard-empty"):
            assert isinstance(ws.get(k), str) and ws[k].strip(), (loc, k)
