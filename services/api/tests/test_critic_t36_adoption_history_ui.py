"""Critic acceptance (sealed during build, promoted after) — T36: /performance shows the harness adoption history (T35 decisions) and can start an A/B run."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "apps" / "web"


def _src(rel):
    return (WEB / rel).read_text(encoding="utf-8")


def test_api_client_has_decision_and_abtest_calls():
    api = _src("lib/api.ts")
    assert "/v1/eval/decisions" in api and "/v1/eval/abtest" in api
    assert re.search(r"export (async )?function (listDecisions|getDecisions)", api)
    assert re.search(r"export (async )?function (startAbTest|runAbTest|postAbTest)", api)


def test_performance_page_renders_decisions_with_intervals_and_verdict():
    page = _src("app/[locale]/performance/page.tsx")
    comp = "".join(p.read_text(encoding="utf-8") for p in (WEB / "components").rglob("*.tsx"))
    src = page + comp
    assert re.search(r"listDecisions|getDecisions", src)
    for field in ("champion", "challenger", "verdict", "decision", "wilson95"):
        assert field in src, field
    assert re.search(r"adopt", src) and re.search(r"keep", src)


def test_abtest_button_polls_the_job_and_is_disabled_while_active():
    src = _src("app/[locale]/performance/page.tsx") + "".join(
        p.read_text(encoding="utf-8") for p in (WEB / "components").rglob("*.tsx"))
    assert re.search(r"startAbTest|runAbTest|postAbTest", src)
    assert re.search(r"getEvalJob", src) and re.search(r"setInterval|setTimeout", src)
    assert re.search(r"disabled=\{[^}]*(active|busy|running)", src, re.I)


def test_no_hard_coded_results():
    page = _src("app/[locale]/performance/page.tsx")
    for lit in ("58.3", "91.7", "21/36", "adopted\": true"):
        assert lit not in page


def test_strings_localized_in_both_languages():
    ko = json.loads(_src("messages/ko.json")); en = json.loads(_src("messages/en.json"))

    def keys(d, p=""):
        out = set()
        for k, v in d.items():
            out |= keys(v, p + k + ".") if isinstance(v, dict) else {p + k}
        return out
    assert keys(ko) == keys(en)
    flat = json.dumps(ko, ensure_ascii=False)
    assert re.search(r"채택", flat) and re.search(r"유지", flat)
