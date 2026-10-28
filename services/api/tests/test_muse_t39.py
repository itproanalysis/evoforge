"""T39 memory-mode ledger behavior (no postgres backend)."""
import pytest

from evoforge import ledger


@pytest.fixture(autouse=True)
def memory_mode(monkeypatch):
    monkeypatch.setenv("EVO_STATE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    ledger.reset()
    ledger.configure({"default": 1000})
    yield
    ledger.reset()


def test_reserve_settle_snapshot():
    rid = ledger.reserve(100)
    assert ledger.snapshot()["reserved_cents"] == 100
    out = ledger.settle(rid, 80)
    assert out["actual"] == 80 and out["refunded"] == 20
    snap = ledger.snapshot()
    assert snap["spent_cents"] == 80 and snap["reserved_cents"] == 0


def test_refund_releases():
    rid = ledger.reserve(50)
    ledger.refund(rid)
    snap = ledger.snapshot()
    assert snap["reserved_cents"] == 0 and snap["spent_cents"] == 0
    assert ledger.available() == 1000


def test_mark_unknown_and_reconcile_settle():
    rid = ledger.reserve(60)
    ledger.mark_unknown(rid, "timeout")
    assert ledger.snapshot()["unknown_reservations"] == [rid]
    ledger.reconcile(rid, 55, request_id="req-1")
    snap = ledger.snapshot()
    assert snap["unknown_reservations"] == [] and snap["spent_cents"] == 55


def test_reconcile_none_refunds():
    rid = ledger.reserve(60)
    ledger.mark_unknown(rid, "timeout")
    ledger.reconcile(rid, None)
    assert ledger.snapshot()["reserved_cents"] == 0


def test_overdraft_records_overrun():
    with pytest.raises(ledger.Overdraft):
        ledger.reserve(2000)
    assert ledger.snapshot()["overruns"]
    assert ledger.overruns()


def test_reset_clears():
    rid = ledger.reserve(10)
    ledger.settle(rid, 10)
    ledger.reset()
    ledger.configure({"default": 1000})
    snap = ledger.snapshot()
    assert snap["spent_cents"] == 0 and snap["reserved_cents"] == 0
    assert snap["overruns"] == [] and snap["unknown_reservations"] == []
