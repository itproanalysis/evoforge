"""T78 home scoreboard (web only): first screen shows measured Arena results."""
from __future__ import annotations

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
PAGE = WEB / "app" / "[locale]" / "page.tsx"


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _msgs(lang: str) -> dict:
    return json.loads((WEB / "messages" / f"{lang}.json").read_text(encoding="utf-8"))


def test_scoreboard_uses_arena_summary():
    src = _page()
    assert "getArenaSummary" in src
    assert "getArenaSummary()" in src
    assert "/v1/arena/summary" not in src


def test_scoreboard_between_intro_and_workspace():
    src = _page()
    intro = src.index('tWorkspace("intro")')
    heading_key = src.index('tWorkspace("scoreboard-heading")')
    empty_key = src.index('tWorkspace("scoreboard-empty")')
    ws = src.index('tWorkspace("heading")')
    assert intro < heading_key < ws
    assert empty_key > intro


def test_scoreboard_shows_measured_numbers():
    src = _page()
    for token in (
        "wins?.evoforge",
        "wins?.single",
        "wins?.tie",
        "heldout",
        "cost_cents",
        "scored",
    ):
        assert token in src, token
    assert "summary-evoforge-wins" in src
    assert "summary-single-wins" in src
    assert "summary-ties" in src
    assert "summary-heldout-evoforge" in src
    assert "summary-heldout-single" in src
    assert "summary-cost-evoforge" in src
    assert "summary-cost-single" in src
    assert "summary-cost-judge" in src
    assert "summary-scored" in src


def test_scoreboard_links_to_arena_locale_aware():
    src = _page()
    assert re.search(r"""locale\s*===\s*['"]en['"]\s*\?\s*""", src)
    assert "/arena" in src
    assert 'tWorkspace("view-arena")' in src or 'tArena(' in src


def test_scoreboard_messages_en_ko():
    for lang in ("en", "ko"):
        ws = _msgs(lang).get("workspace", {})
        assert isinstance(ws.get("scoreboard-heading"), str) and ws["scoreboard-heading"].strip(), lang
        assert isinstance(ws.get("scoreboard-empty"), str) and ws["scoreboard-empty"].strip(), lang
    en_keys = set(_msgs("en")["workspace"].keys())
    ko_keys = set(_msgs("ko")["workspace"].keys())
    assert en_keys == ko_keys


def test_scoreboard_wraps_without_fixed_widths():
    src = _page()
    start = src.index('tWorkspace("scoreboard-heading")')
    # Scoreboard block: from its section start back a little to its section end.
    sec_start = src.rfind("<section", 0, start)
    sec_end = src.index("</section>", start)
    block = src[sec_start:sec_end]
    assert "flex-wrap" in block or "flex flex-wrap" in block
    assert "375px" not in block
    assert "fixed widths" not in block.lower()
    for pat in (r"w-\[", r"min-w-\[", r"max-w-\[", r"width\s*:"):
        assert not re.search(pat, block), pat
