"""Sealed (Critic) — T58 left feature rail (v3.8 §2.1, owner's layout: far-left feature tabs): six primary entries in a
fixed order, every link points at a page that exists, the current page is marked, secondary pages are grouped, and
small screens collapse the rail instead of squeezing the content."""
from __future__ import annotations

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
RAIL = WEB / "components" / "FeatureRail.tsx"
PRIMARY = ["/", "/arena", "/replay", "/evidence", "/performance", "/lab"]
SECONDARY = ["/evolution", "/leaderboard"]  # /verify has no index page (only /verify/<cert>)


def _src():
    return RAIL.read_text(encoding="utf-8")


def test_rail_lists_six_primary_entries_in_order():
    src = _src()
    pos = []
    for p in PRIMARY:
        token = f'"{p}"'
        assert token in src, p
        pos.append(src.index(token))
    assert pos == sorted(pos), "primary entries out of order"
    assert 'aria-label' in src and "<nav" in src


def test_every_link_points_at_an_existing_page():
    src = _src()
    for p in PRIMARY + SECONDARY:
        assert f'"{p}"' in src, p
        page = WEB / "app" / "[locale]" / p.strip("/") / "page.tsx"
        assert page.exists(), f"rail links to a missing page: {p or '/'}"


def test_active_page_is_marked_and_secondary_is_grouped():
    src = _src()
    assert "aria-current" in src and "usePathname" in src
    assert "<details" in src or "aria-expanded" in src  # secondary pages behind a disclosure, not mixed in
    for p in SECONDARY:
        assert src.index(f'"{p}"') > src.index('"/lab"')


def test_small_screens_collapse_and_layout_uses_the_rail():
    src = _src()
    assert re.search(r"\b(md|lg):(flex|block|w-)", src) and re.search(r"\bhidden\b", src)
    layout = (WEB / "app" / "[locale]" / "layout.tsx").read_text(encoding="utf-8")
    assert "FeatureRail" in layout


def test_labels_are_translated():
    for lang in ("en", "ko"):
        nav = json.loads((WEB / "messages" / f"{lang}.json").read_text(encoding="utf-8"))["navigation"]
        for key in ("mission-control", "arena", "replay", "evidence", "performance", "improvement-lab", "more"):
            assert key in nav, (lang, key)
