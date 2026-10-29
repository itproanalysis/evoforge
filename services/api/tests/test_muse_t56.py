"""T56 evolution stats panel on the replay screen (measured values only)."""
from __future__ import annotations

import json
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
LIB = WEB / "lib" / "roundReplay.ts"
API = WEB / "lib" / "api.ts"
COMP = WEB / "components" / "EvolutionStats.tsx"
PAGE = WEB / "app" / "[locale]" / "replay" / "page.tsx"


def test_stats_view_shapes_and_passthrough():
    src = LIB.read_text(encoding="utf-8")
    assert "export function statsView" in src
    # null in -> null out
    assert "return null" in src
    # verdict is the server comparison, never computed on the client
    assert "stats.comparison" in src or "s.comparison" in src
    assert "verdict" in src
    # V fields and formats
    for token in ("verified", "rate", "interval", "costPerVerified", "Math.round", "–", "¢", "—"):
        assert token in src, token


def test_api_getter_and_proxy_path():
    src = API.read_text(encoding="utf-8")
    assert "export function getEvolutionStats" in src
    assert "/v1/evolution/stats" in src


def test_component_two_cards_verdict_runs_method():
    src = COMP.read_text(encoding="utf-8")
    assert "statsView" in src and "getEvolutionStats" in src
    assert 'useTranslations("replay")' in src
    assert "data-verdict" in src
    assert "stats-not-significant" in src
    assert "stats-evoforge-better" in src
    assert "stats-single-better" in src
    assert "stats-runs" in src and "stats-method" in src
    assert "evoforge" in src and "single" in src
    # interval bar per side
    assert "data-interval-bar" in src or "interval-bar" in src
    assert "stats-verified" in src and "stats-cost-per-verified" in src


def test_page_shows_panel_above_run_list():
    src = PAGE.read_text(encoding="utf-8")
    assert "EvolutionStats" in src
    assert src.index("EvolutionStats") < src.index("runs.length")


def test_i18n_keys_en_and_ko():
    for lang in ("en", "ko"):
        msgs = json.loads((WEB / "messages" / f"{lang}.json").read_text(encoding="utf-8"))
        rep = msgs.get("replay")
        assert isinstance(rep, dict), lang
        for key in ("stats-title", "stats-runs", "stats-not-significant",
                    "stats-evoforge-better", "stats-single-better", "stats-method"):
            assert key in rep, (lang, key)
