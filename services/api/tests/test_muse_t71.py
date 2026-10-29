"""Muse (Builder) - T71 plain first screen (web only).

English is the default locale, the home page explains itself above the
workspace, and internal codes no longer appear in user-facing text.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"

EDITABLE_TSX = [
    WEB / "app" / "[locale]" / "page.tsx",
    WEB / "app" / "[locale]" / "performance" / "page.tsx",
    WEB / "app" / "[locale]" / "lab" / "page.tsx",
    WEB / "app" / "[locale]" / "layout.tsx",
    WEB / "app" / "[locale]" / "evidence" / "page.tsx",
    WEB / "components" / "AdoptionHistory.tsx",
    WEB / "components" / "EvolutionTimeline.tsx",
]

BANNED = ["X_SINGLE", "PIPELINE", "WVI", "W10", "D-054", "GH_INTEGRITY", "AT-20"]


def _messages(lang: str) -> dict:
    return json.loads((WEB / "messages" / f"{lang}.json").read_text(encoding="utf-8"))


def _values(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _values(v)
    elif isinstance(node, list):
        for v in node:
            yield from _values(v)
    elif isinstance(node, str):
        yield node


def test_middleware_english_default():
    src = (WEB / "middleware.ts").read_text(encoding="utf-8")
    assert re.search(r"defaultLocale:\s*'en'", src), "defaultLocale must be 'en'"
    assert re.search(r"locales:\s*\[\s*'en'\s*,\s*'ko'\s*\]", src)
    assert re.search(r"localePrefix:\s*'as-needed'", src)
    assert "defaultLocale: 'ko'" not in src


def test_unprefixed_links_follow_the_english_default():
    layout = (WEB / "app" / "[locale]" / "layout.tsx").read_text(encoding="utf-8")
    assert re.search(r"""locale\s*===\s*['"]en['"]\s*\?\s*''""", layout), \
        "layout prefix must treat 'en' as the unprefixed default"
    perf = (WEB / "app" / "[locale]" / "performance" / "page.tsx").read_text(encoding="utf-8")
    assert re.search(r"""locale\s*===\s*['"]en['"]\s*\?\s*""", perf), \
        "performance evidence links must treat 'en' as the unprefixed default"


def test_workspace_intro_keys_in_both_locales():
    en = _messages("en")["workspace"]
    ko = _messages("ko")["workspace"]
    for key in ("intro", "intro-step-1", "intro-step-2", "intro-step-3"):
        assert isinstance(en.get(key), str) and en[key].strip(), ("en", key)
        assert isinstance(ko.get(key), str) and ko[key].strip(), ("ko", key)
    assert 60 <= len(en["intro"]) <= 400, len(en["intro"])
    assert 60 <= len(ko["intro"]) <= 400, len(ko["intro"])
    assert "single" in en["intro"].lower(), "English intro must mention 'single'"
    assert "test" in en["intro"].lower(), "English intro must mention 'test'"


def test_home_page_renders_intro_above_workspace():
    page = (WEB / "app" / "[locale]" / "page.tsx").read_text(encoding="utf-8")
    for key in ('tWorkspace("intro")', 'tWorkspace("intro-step-1")',
                'tWorkspace("intro-step-2")', 'tWorkspace("intro-step-3")'):
        assert key in page, key
    intro_pos = page.index('tWorkspace("intro")')
    assert intro_pos < page.index("tWorkspace(\"heading\")"), \
        "the intro must render above the workspace"


def test_no_internal_codes_in_message_values():
    for lang in ("en", "ko"):
        for value in _values(_messages(lang)):
            for token in BANNED:
                assert token not in value, (lang, token, value[:80])
            assert not re.search(r"SEC-\d", value), (lang, value[:80])


def _jsx_text(src: str) -> str:
    # Drop quoted/template string literals (code + API values), then drop
    # everything inside {...} expressions, leaving JSX text nodes.
    # PIPELINE_STEPS is a code identifier (state-machine constant), not text.
    src = src.replace("PIPELINE_STEPS", "")
    no_strings = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|`(?:[^`\\]|\\.)*`", "", src)
    out = []
    depth = 0
    for ch in no_strings:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def test_no_internal_codes_in_visible_jsx_text():
    for path in EDITABLE_TSX:
        text = _jsx_text(path.read_text(encoding="utf-8"))
        for token in BANNED:
            assert token not in text, (path.name, token)
        assert not re.search(r"SEC-\d", text), path.name


def test_plain_words_replaced_the_codes():
    en = json.dumps(_messages("en"), ensure_ascii=False)
    assert "single AI baseline" in en
    assert "EvoForge pipeline" in en
    assert "verified improvement" in en
    page = (WEB / "app" / "[locale]" / "page.tsx").read_text(encoding="utf-8")
    assert "single AI baseline" in page and "EvoForge pipeline" in page


def test_api_kind_values_untouched():
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    assert '"X_SINGLE" | "PIPELINE"' in api
    perf = (WEB / "app" / "[locale]" / "performance" / "page.tsx").read_text(encoding="utf-8")
    assert 'startEvalJob(kind === "baseline" ? "X_SINGLE" : "PIPELINE")' in perf
    assert 'kind === "X_SINGLE"' in perf
