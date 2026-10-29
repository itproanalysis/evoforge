"""T58 left feature rail (static web checks)."""
from __future__ import annotations

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
RAIL = WEB / "components" / "FeatureRail.tsx"
LAYOUT = WEB / "app" / "[locale]" / "layout.tsx"
EN = WEB / "messages" / "en.json"
KO = WEB / "messages" / "ko.json"

MAIN_ORDER = ["/", "/arena", "/replay", "/evidence", "/performance", "/lab"]
MORE_ORDER = ["/evolution", "/leaderboard"]  # /verify has no index page; it is not in the rail


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_rail_lists_paths_in_order():
    src = _read(RAIL)
    paths = re.findall(r'path:\s*["\']([^"\']+)["\']', src)
    assert paths[:6] == MAIN_ORDER, paths
    tail = paths[6:]
    assert MORE_ORDER[:2] == [p for p in tail if p in MORE_ORDER][:2], paths
    assert src.index('"/lab"') < src.index('"/leaderboard"')
    assert "/verify" not in src  # no index page: no dead or disabled entry


def test_rail_links_only_existing_pages():
    src = _read(RAIL)
    hrefs = re.findall(r'href=\{([^}]+)\}', src)
    assert hrefs, "rail must render links"
    assert "${prefix}${path}" in src
    linked = re.findall(r'path:\s*["\']([^"\']+)["\']', src)
    for p in linked:
        page = WEB / "app" / "[locale]" / (p.lstrip("/") + "/page.tsx" if p != "/" else "page.tsx")
        assert page.exists(), f"rail links to a missing page: {p}"


def test_rail_nav_accessibility_and_active():
    src = _read(RAIL)
    assert "'use client'" in src or '"use client"' in src
    assert "usePathname" in src
    assert "<nav" in src and "aria-label=" in src
    assert "aria-current" in src and re.search(r"['\"]page['\"]", src)
    assert "${prefix}${path}" in src
    assert ("<details" in src) or ("aria-expanded" in src)


def test_rail_responsive_and_drawer():
    src = _read(RAIL)
    assert re.search(r"hidden\s+md:flex", src), "desktop rail must hide below md"
    assert "md:hidden" in src, "mobile bar/drawer must hide on md+"
    assert "<button" in src or ("<details" in src and "<summary" in src)
    assert "fixed" in src


def test_layout_uses_rail_beside_main():
    src = _read(LAYOUT)
    assert "<FeatureRail" in src
    assert "FeatureRail" in src and "from" in src
    assert "LanguageSwitcher" in src
    assert "/replay" in src
    assert re.search(r"flex(-1|\s)", src)


def test_navigation_i18n_keys():
    for path in (EN, KO):
        nav = json.loads(path.read_text(encoding="utf-8"))["navigation"]
        for key in ("mission-control", "arena", "replay", "evidence",
                    "performance", "improvement-lab", "autopilot",
                    "leaderboard", "more"):
            assert nav.get(key), f"{path.name} navigation.{key} missing"
