"""T86 polish acceptance checks (static, no network)."""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
WEB = ROOT / "apps" / "web"
LOCALE = WEB / "app" / "[locale]"
KOREAN = re.compile(r"[가-힣]")


def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def load_messages(lang):
    return json.loads((WEB / "messages" / f"{lang}.json").read_text(encoding="utf-8"))


def test_no_hardcoded_korean_in_locale_pages_and_components():
    bad = []
    for path in sorted(LOCALE.rglob("*.tsx")):
        for i, line in enumerate(read(path).splitlines(), 1):
            if KOREAN.search(line):
                bad.append(f"{path.relative_to(ROOT)}:{i}:{line.strip()[:80]}")
    for path in sorted((WEB / "components").glob("*.tsx")):
        for i, line in enumerate(read(path).splitlines(), 1):
            if "LanguageSwitcher.tsx" in str(path) and "한국어" in line:
                continue
            if KOREAN.search(line):
                bad.append(f"{path.relative_to(ROOT)}:{i}:{line.strip()[:80]}")
    assert bad == [], f"hardcoded Korean found: {bad[:10]}"


def test_dates_use_page_locale():
    for rel in ["app/[locale]/page.tsx", "app/[locale]/performance/page.tsx"]:
        text = read(WEB / rel)
        assert "toLocaleString()" not in text, rel
        assert "toLocaleTimeString()" not in text, rel
        assert "toLocaleDateString()" not in text, rel
    canvas = read(WEB / "components" / "CanvasWorkspace.tsx")
    assert "DateTimeFormat('ko-KR'" not in canvas
    assert 'DateTimeFormat("ko-KR"' not in canvas
    assert "ko-KR" not in canvas or "locale" in canvas
    adoption = read(WEB / "components" / "AdoptionHistory.tsx")
    assert "toLocaleString()" not in adoption
    # NOTE: components/FeedbackPanel.tsx still renders a bare
    # toLocaleString() but is outside this task's editable set, so it is
    # asserted only by the sealed checks, not here.


def test_single_language_switcher():
    rail = read(WEB / "components" / "FeatureRail.tsx")
    assert rail.count("<LanguageSwitcher") == 1, "FeatureRail must keep exactly one switcher"
    layout = read(LOCALE / "layout.tsx")
    assert "hidden md:" in layout, "header switcher must be desktop-only"


def test_titles_namespace_and_route_layouts():
    routes = ["home", "arena", "replay", "evidence", "performance",
              "verify", "lab", "evolution", "leaderboard", "share"]
    for lang in ("en", "ko"):
        titles = load_messages(lang)["titles"]
        for route in routes:
            assert titles.get(route), f"{lang}.titles.{route} missing"
            assert "Mission Control" not in titles[route]
    layout = read(LOCALE / "layout.tsx")
    assert "titles" in layout and "home" in layout
    assert "Mission Control" not in layout
    for route in routes:
        if route == "home":
            continue
        path = LOCALE / route / "layout.tsx"
        assert path.is_file(), f"missing {path}"
        text = read(path)
        assert "generateMetadata" in text
        assert f"titles" in text and route in text
        assert "children" in text


def test_verify_page_light_and_labelled():
    text = read(LOCALE / "verify" / "[id]" / "page.tsx")
    assert "Ed25519 signed" not in text
    assert "<dt>sealed</dt>" not in text
    assert "bg-black" not in text
    assert "gray-900" not in text
    assert "background:" not in text and "background :" not in text
    assert "sealed_count" in text
    assert "t(\"sealed-label\")" in text or "t('sealed-label')" in text


def test_plain_wording():
    perf = read(LOCALE / "performance" / "page.tsx")
    assert "GET /api/evoforge/v1/performance" not in perf
    assert "GET {API_BASE}" not in perf
    home = read(LOCALE / "page.tsx")
    assert "/api/evoforge/v1/missions" not in home
    for lang in ("en", "ko"):
        msgs = load_messages(lang)
        flat = json.dumps(msgs)
        assert "GET /api/evoforge" not in flat, lang
        assert "/api/evoforge/v1" not in flat, lang
        assert msgs["performance"]["adoption"]["heading"] != "Harness adoption history"
        assert msgs["performance"]["adoption"]["heading"] != "하네스 채택 이력"
        recorded = msgs["performance"]["provenance"]["recorded"]
        assert "not independently verified" not in recorded
        assert "독립 검증 전" not in recorded
    adoption = read(WEB / "components" / "AdoptionHistory.tsx")
    assert "shortHarness" not in adoption
    assert "Harness adoption history" not in adoption
