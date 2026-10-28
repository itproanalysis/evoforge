"""Critic acceptance (sealed during build, promoted after) — T39: with the PostgreSQL backend the ledger survives a restart (spend history no longer resets to
0 on every deploy); memory mode is unchanged."""
from __future__ import annotations

import pytest
from test_postgres_kernel import database, funded, psycopg  # noqa: F401

from evoforge import ledger


@pytest.fixture
def pg(funded, monkeypatch):
    scope = funded["scope"]
    monkeypatch.setenv("EVO_STATE_BACKEND", "postgres")
    monkeypatch.setenv("EVO_TENANT_ID", str(scope.tenant_id))
    monkeypatch.setenv("EVO_PROJECT_ID", str(scope.project_id))
    monkeypatch.setenv("DATABASE_URL", funded["dsn"])
    return funded


def _forget():
    """What a redeploy does: the new process starts with empty in-memory ledger structures."""
    for name in ("_spent", "_reserved", "_reservations"):
        obj = getattr(ledger, name)
        obj.clear()
    ledger._overruns.clear()
    if hasattr(ledger, "_loaded"):
        ledger._loaded = False


def test_spend_and_open_reservations_survive_a_restart(pg):
    ledger.configure({"default": 100000})
    a = ledger.reserve(120, "default"); ledger.settle(a, 37)
    b = ledger.reserve(120, "default"); ledger.settle(b, 5)
    c = ledger.reserve(120, "default")  # still open
    before = ledger.snapshot("default")
    _forget()
    after = ledger.snapshot("default")
    assert after["spent_cents"] == before["spent_cents"] == 42
    assert after["reserved_cents"] == before["reserved_cents"] == 120
    ledger.settle(c, 10)  # an open reservation can still be settled after the restart
    assert ledger.snapshot("default")["spent_cents"] == 52


def test_refund_and_unknown_survive_a_restart(pg):
    ledger.configure({"default": 100000})
    r = ledger.reserve(120, "default"); ledger.refund(r)
    u = ledger.reserve(120, "default"); ledger.mark_unknown(u, "TimeoutError")
    _forget()
    snap = ledger.snapshot("default")
    assert snap["spent_cents"] == 0
    assert [x["reservation_id"] if isinstance(x, dict) else x for x in snap["unknown_reservations"]] in ([u], [{"reservation_id": u}]) or u in str(snap["unknown_reservations"])


def test_journal_is_append_only(pg):
    ledger.configure({"default": 100000})
    a = ledger.reserve(120, "default"); ledger.settle(a, 3)
    with psycopg.connect(pg["dsn"], autocommit=True) as conn:
        rows = conn.execute("SELECT count(*) FROM runtime.api_evidence_records WHERE document->>'kind'='ledger_event'").fetchone()[0]
    assert rows >= 2  # reserve + settle recorded as evidence-store events
