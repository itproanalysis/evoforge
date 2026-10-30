"""Sealed (Critic) — T86 polish from the cloud review 2026-10-30 (B7, C8-C11): English pages must not show Korean or
Korean-formatted dates, one language switcher per screen, a title per page, a clean verify card, plain Performance
wording, and no self-undermining provider wording."""
from __future__ import annotations

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
LOCALE_APP = WEB / "app" / "[locale]"
ROUTES = ["arena", "replay", "evidence", "performance", "verify", "lab", "evolution", "leaderboard", "share"]


def _tsx():
    return list(LOCALE_APP.rglob("*.tsx")) + list((WEB / "components").rglob("*.tsx"))


def _msgs(loc):
    return json.loads((WEB / "messages" / f"{loc}.json").read_text(encoding="utf-8"))


def _strings(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from _strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from _strings(x)
    elif isinstance(v, str):
        yield v


def test_no_hardcoded_korean_in_pages_or_components():
    hits = []
    for f in _tsx():
        if f.name == "LanguageSwitcher.tsx":
            continue  # the "한국어" option label is the one legitimate Korean string
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if s.startswith(("//", "*", "/*", "{/*")):
                continue
            if re.search(r"[가-힣]", s):
                hits.append(f"{f.relative_to(WEB).as_posix()}:{i}")
    assert not hits, hits[:10]


def test_dates_follow_the_page_locale():
    bad = []
    for f in _tsx():
        src = f.read_text(encoding="utf-8")
        for pat in (r"toLocale(?:Date|Time)?String\(\s*\)", r"toLocale(?:Date|Time)?String\(\s*undefined",
                    r"DateTimeFormat\(\s*['\"]ko-KR['\"]", r"DateTimeFormat\(\s*undefined"):
            if re.search(pat, src):
                bad.append((f.relative_to(WEB).as_posix(), pat))
    assert not bad, bad


def test_one_language_switcher_per_screen():
    rail = (WEB / "components" / "FeatureRail.tsx").read_text(encoding="utf-8")
    assert rail.count("<LanguageSwitcher") == 1, "only the mobile More menu keeps a switcher"
    layout = (LOCALE_APP / "layout.tsx").read_text(encoding="utf-8")
    i = layout.index("<LanguageSwitcher")
    assert "hidden md:" in layout[max(0, i - 300):i + 80], "the header switcher is desktop-only"


def test_every_page_has_its_own_title():
    for loc in ("en", "ko"):
        titles = _msgs(loc).get("titles", {})
        for r in ROUTES + ["home"]:
            assert isinstance(titles.get(r), str) and titles[r].strip(), (loc, r)
        assert not any("Mission Control" in t or "미션 컨트롤" in t for t in titles.values()), loc
    for r in ROUTES:
        lay = LOCALE_APP / r / "layout.tsx"
        assert lay.is_file(), r
        src = lay.read_text(encoding="utf-8")
        assert "generateMetadata" in src and "titles" in src, r
    root = (LOCALE_APP / "layout.tsx").read_text(encoding="utf-8")
    assert "titles" in root


def test_verify_card_is_clean_and_light():
    src = (LOCALE_APP / "verify" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    assert "Ed25519 signed" not in src  # wording comes from messages, once
    assert "<dt>sealed</dt>" not in src and not re.search(r"\{cert\.sealed_count\}\s*\(", src)
    assert not re.search(r"background(?:Color)?\s*:\s*['\"]#(?:0|1|2)[0-9a-fA-F]{2,5}['\"]", src)
    assert not re.search(r"\bbg-(?:black|gray-9\d\d|slate-9\d\d|zinc-9\d\d)\b", src)
    for loc in ("en", "ko"):
        v = _msgs(loc)["verify"]
        assert sum("Ed25519" in s for s in _strings(v)) <= 1, loc


def test_performance_and_provider_wording_is_plain():
    perf = (LOCALE_APP / "performance" / "page.tsx").read_text(encoding="utf-8")
    adoption = (WEB / "components" / "AdoptionHistory.tsx").read_text(encoding="utf-8")
    for loc in ("en", "ko"):
        flat = "\n".join(_strings(_msgs(loc)))
        assert "GET /api/evoforge" not in flat and "/api/evoforge/v1" not in flat, loc
        assert not re.search(r"/1\s*→\s*/2", flat), loc
        assert "Harness adoption history" not in flat, loc
        assert "not independently verified" not in flat and "독립적으로 검증되지 않음" not in flat, loc
    for src in (perf, adoption):
        assert "GET /api/evoforge" not in src and not re.search(r"/1\s*→\s*/2", src)
