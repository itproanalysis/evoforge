"""Critic acceptance (sealed during build, promoted after) — T38: Mission Control opens with a proof card computed from measured history (never hard-coded)."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "apps" / "web"


def _src(rel):
    return (WEB / rel).read_text(encoding="utf-8")


def _components():
    return "".join(p.read_text(encoding="utf-8") for p in (WEB / "components").rglob("*.tsx"))


def test_home_page_renders_a_proof_card_from_performance_history():
    page = _src("app/[locale]/page.tsx")
    assert re.search(r"ProofCard|proof-card|proofCard", page)
    src = page + _components() + _src("lib/evolutionTimeline.ts")
    assert re.search(r"getPerformance", page + _components())
    assert "wilson95" in src or ".lo" in src


def test_card_uses_a_pure_tested_helper():
    lib = _src("lib/evolutionTimeline.ts")
    assert re.search(r"export function (bestHarnessComparison|headlineComparison|proofHeadline)", lib)


def test_card_links_to_performance_and_states_the_rule():
    src = _components()
    assert "/performance" in src
    ko = json.dumps(json.loads(_src("messages/ko.json")), ensure_ascii=False)
    assert re.search(r"신뢰구간|구간이 겹치지", ko)


def test_no_hard_coded_numbers_on_home():
    page = _src("app/[locale]/page.tsx")
    for lit in ("97.2", "58.3", "35/36", "21/36", "85.8"):
        assert lit not in page and lit not in _components()
