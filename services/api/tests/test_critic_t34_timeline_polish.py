"""Critic acceptance (sealed during build, promoted after) — T34: the evolution timeline reads well with real production data (seen 2026-10-29)."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "apps" / "web"
COMP = (WEB / "components" / "EvolutionTimeline.tsx").read_text(encoding="utf-8")


def test_chart_width_follows_the_container():
    assert re.search(r"viewBox=", COMP), "the SVG keeps a viewBox"
    assert re.search(r'width="100%"|width:\s*"100%"|w-full', COMP), "the chart fills its card instead of a fixed narrow width"


def test_x_labels_include_time_of_day():
    assert re.search(r"toLocaleTimeString|toLocaleString|getHours|getUTCHours|toISOString|DateTimeFormat|hour\s*:", COMP), \
        "several measurements share a date; labels must show the time too"


def test_harness_marker_label_is_not_truncated():
    assert re.search(r"api-sealed-eval|harness", COMP)
    assert re.search(r"<title>|textAnchor|text-anchor", COMP)
    assert "replace(\"api-sealed-eval\"" in COMP or "shortHarness" in COMP or ".split(\"/\")" in COMP, \
        "show a short harness label (e.g. /2) with the full name in a <title>"


def test_family_names_do_not_break_mid_word():
    assert re.search(r"whitespace-nowrap|white-space:\s*nowrap|truncate", COMP)


def test_segment_header_states_the_measured_verdict_honestly():
    msgs = json.loads((WEB / "messages" / "ko.json").read_text(encoding="utf-8"))
    flat = json.dumps(msgs, ensure_ascii=False)
    assert "no_clear_difference" in COMP or "verdict" in COMP
    assert re.search(r"차이 불분명|명확한 차이 없음|구간이 겹", flat), "an overlapping-interval result must be labelled as unclear"
