"""Critic acceptance (sealed during build, promoted after) — T9 Mission Control shows the real ledger (static source checks; browser check by Critic)."""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
API = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")


def _mission_control_page() -> str:
    """Mission Control page moved under app/[locale]/ during i18n; resolve dynamically."""
    candidates = [
        WEB / "app" / "page.tsx",
        WEB / "app" / "[locale]" / "page.tsx",
        *sorted((WEB / "app").rglob("page.tsx")),
    ]
    for p in candidates:
        if p.is_file():
            return p.read_text(encoding="utf-8")
    raise FileNotFoundError(f"no Mission Control page.tsx under {WEB / 'app'}")


PAGE = _mission_control_page()


def test_get_ledger_client():
    assert re.search(r"export\s+(async\s+)?function\s+getLedger\s*\(", API)
    assert "/v1/ledger" in API
    for field in ("spent_cents", "reserved_cents", "unknown_reservations", "overruns"):
        assert field in API, field


def test_page_uses_ledger_not_estimate():
    assert "getLedger" in PAGE
    assert "추정치" not in PAGE and "provider_billed 없음" not in PAGE
    assert not re.search(r"Spent \(est\.\)", PAGE)
    for field in ("spent_cents", "reserved_cents", "unknown_reservations"):
        assert field in PAGE, field


def test_budget_exhausted_message():
    # Post-i18n the 402 mapping lives in lib/apiErrors.ts + messages/*.json.
    errors_ts = WEB / "lib" / "apiErrors.ts"
    if errors_ts.is_file():
        text = errors_ts.read_text(encoding="utf-8")
        assert "402" in text and "budget-exhausted" in text
        return
    assert "402" in PAGE


def test_no_float_money():
    assert not re.search(r"(spent|reserved)_cents\s*/\s*100(?!\s*\))", PAGE) or "toFixed" not in PAGE
    assert "parseFloat" not in PAGE
