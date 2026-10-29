"""T63 evolution strategies panel on the replay screen."""
from __future__ import annotations

import json
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
LIB = WEB / "lib" / "roundReplay.ts"
API = WEB / "lib" / "api.ts"
COMP = WEB / "components" / "StrategiesPanel.tsx"
PAGE = WEB / "app" / "[locale]" / "replay" / "page.tsx"


def test_strategies_view_shapes_and_labels():
    src = LIB.read_text(encoding="utf-8")
    assert "export function strategiesView" in src
    assert "return null" in src
    assert "strategyLabel" in src or "strategiesView" in src
    for token in ("attempt", "accumulate critic", "this round's critic only",
                  "retire stale", "keep stale", "promotable", "isChampion",
                  "Math.round", "–", "—", "decisions"):
        assert token in src, token


def test_api_strategies_getter_and_promote():
    src = API.read_text(encoding="utf-8")
    assert "export function getEvolutionStrategies" in src
    assert "export function promoteEvolutionStrategy" in src
    assert "/v1/evolution/strategies" in src
    assert "/v1/evolution/strategies/promote" in src
    assert "status" in src and "body" in src


def test_component_champion_table_promote_history():
    src = COMP.read_text(encoding="utf-8")
    assert "strategiesView" in src
    assert "getEvolutionStrategies" in src
    assert "promoteEvolutionStrategy" in src
    assert 'useTranslations("replay")' in src
    assert "NEXT_PUBLIC_EVO_OPERATOR_CONTROLS" in src
    for token in ("strategies-title", "strategies-champion", "strategies-promote",
                  "strategies-promotable", "strategies-history"):
        assert token in src, token
    assert "data-interval-bar" in src or "interval-bar" in src


def test_page_shows_panel_below_stats():
    src = PAGE.read_text(encoding="utf-8")
    assert "StrategiesPanel" in src
    assert "EvolutionStats" in src
    assert src.index("EvolutionStats") < src.index("StrategiesPanel")


def test_i18n_keys_en_and_ko():
    for lang in ("en", "ko"):
        msgs = json.loads((WEB / "messages" / f"{lang}.json").read_text(encoding="utf-8"))
        rep = msgs.get("replay")
        assert isinstance(rep, dict), lang
        for key in ("strategies-title", "strategies-champion", "strategies-promote",
                    "strategies-promotable", "strategies-history"):
            assert key in rep, (lang, key)
