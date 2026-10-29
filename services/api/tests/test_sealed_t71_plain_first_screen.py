"""Sealed (Critic) — T71 first screen a judge understands (external review): English by default, a one-paragraph
explanation of the product on the home page, and no internal codes (X_SINGLE, PIPELINE, WVI, W10, D-054,
GH_INTEGRITY, AT-20...) in text a user reads."""
from __future__ import annotations

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
CODES = re.compile(r"\bX_SINGLE\b|\bPIPELINE\b|\bWVI\b|\bW\d{1,2}\b|\bD-\d{3}\b|\bGH_INTEGRITY\b|\bAT-\d+\b|\bSEC-\d+\b")


def _strings(v, path=""):
    if isinstance(v, dict):
        for k, x in v.items():
            yield from _strings(x, f"{path}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from _strings(x, f"{path}[{i}]")
    elif isinstance(v, str):
        yield path, v


def _messages(locale):
    return json.loads((WEB / "messages" / f"{locale}.json").read_text(encoding="utf-8"))


def test_english_is_the_default_locale():
    mw = (WEB / "middleware.ts").read_text(encoding="utf-8")
    assert re.search(r"defaultLocale:\s*['\"]en['\"]", mw), "unprefixed URLs must render English"
    assert re.search(r"locales:\s*\[[^\]]*['\"]ko['\"]", mw), "Korean stays available under /ko"


def test_no_internal_codes_in_user_text():
    for locale in ("en", "ko"):
        hits = [(p, s) for p, s in _strings(_messages(locale)) if CODES.search(s)]
        assert not hits, f"{locale}: {hits[:5]}"


def test_no_internal_codes_in_jsx_text():
    hits = []
    for f in list((WEB / "app" / "[locale]").rglob("*.tsx")) + list((WEB / "components").rglob("*.tsx")):
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r">([^<>{}]*)<", src):  # literal JSX text between tags (code has quotes/operators)
            text = m.group(1)
            if not re.search(r"[\"'`=&|;]", text) and CODES.search(text):
                hits.append((f.relative_to(WEB).as_posix(), m.group(1).strip()[:60]))
    assert not hits, hits[:8]


def test_home_explains_the_product_first():
    for locale in ("en", "ko"):
        ws = _messages(locale)["workspace"]
        intro = ws.get("intro")
        assert isinstance(intro, str) and 60 <= len(intro) <= 400, (locale, intro)
        for k in ("intro-step-1", "intro-step-2", "intro-step-3"):
            assert isinstance(ws.get(k), str) and ws[k].strip(), (locale, k)
    en = _messages("en")["workspace"]["intro"].lower()
    assert "single" in en and ("test" in en or "check" in en), "say what is compared and how it is judged"
    page = (WEB / "app" / "[locale]" / "page.tsx").read_text(encoding="utf-8")
    i_intro = page.find('tWorkspace("intro")')
    assert i_intro != -1 and all(f'tWorkspace("intro-step-{n}")' in page for n in (1, 2, 3))
    assert i_intro < page.find("<PromptBar"), "the explanation comes before the workspace input"
