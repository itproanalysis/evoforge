"""T39 durable ledger over PostgreSQL (live-PG; skips without EVO_TEST_DATABASE_URL)."""
import pytest

from test_postgres_kernel import database, funded  # noqa: F401
from evoforge import ledger
from evoforge import postgres_state


@pytest.fixture(autouse=True)
def pg_scope(funded, monkeypatch):
    scope = funded["scope"]
    monkeypatch.setenv("EVO_STATE_BACKEND", "postgres")
    monkeypatch.setenv("EVO_TENANT_ID", str(scope.tenant_id))
    monkeypatch.setenv("EVO_PROJECT_ID", str(scope.project_id))
    monkeypatch.setenv("DATABASE_URL", funded["dsn"])
    ledger.reset()
    ledger.configure({"default": 100000})
    yield
    ledger.reset()


def _restart_keep_budgets():
    budgets = dict(ledger._budgets)
    ledger._spent.clear()
    ledger._reserved.clear()
    ledger._reservations.clear()
    ledger._overruns.clear()
    ledger._budgets.clear()
    ledger._budgets.update(budgets)
    ledger._loaded = False


def _ledger_docs():
    records = postgres_state.ScopedRecords("records")
    docs = []
    for key in list(records):
        doc = records[key]
        if isinstance(doc, dict) and doc.get("kind") == "ledger_event":
            docs.append(doc)
    return docs


def test_settled_spend_survives_restart(pg_scope):
    rid = ledger.reserve(200)
    ledger.settle(rid, 150)
    before = ledger.snapshot()
    _restart_keep_budgets()
    after = ledger.snapshot()
    assert after["spent_cents"] == before["spent_cents"] == 150
    assert after["reserved_cents"] == 0
    assert len(_ledger_docs()) >= 2


def test_open_reservation_settles_after_restart(pg_scope):
    rid = ledger.reserve(300)
    _restart_keep_budgets()
    assert ledger.snapshot()["reserved_cents"] == 300
    out = ledger.settle(rid, 250)
    assert out["actual"] == 250
    assert ledger.snapshot()["spent_cents"] == 250


def test_unknown_reconcile_and_overrun_survive_restart(pg_scope):
    rid = ledger.reserve(400)
    ledger.mark_unknown(rid, "provider timeout")
    ledger.reconcile(rid, 350, request_id="req-live")
    with pytest.raises(ledger.Overdraft):
        ledger.reserve(10_000_000)
    before = ledger.snapshot()
    _restart_keep_budgets()
    after = ledger.snapshot()
    assert after["spent_cents"] == before["spent_cents"] == 350
    assert after["unknown_reservations"] == []
    assert len(after["overruns"]) == len(before["overruns"]) == 1
    docs = _ledger_docs()
    assert {d["event"] for d in docs} >= {"reserve", "settle", "mark_unknown", "reconcile", "overrun"}
    for d in docs:
        for field in ("reservation_id", "project", "event", "cents", "reason", "ts"):
            assert field in d
