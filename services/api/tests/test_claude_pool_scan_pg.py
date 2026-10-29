"""Claude — production outage fix (release 18): bounded PostgreSQL connection pool + one-query kind scans.

Release 17 crashed at startup on "remaining connection slots are reserved" and the dashboard/performance/outcomes
endpoints passed the 40 s proxy timeout: every transaction opened its own connection and every list endpoint read
ids, then each document in its own transaction."""
from __future__ import annotations

import threading

import pytest
from test_postgres_kernel import database, funded, psycopg  # noqa: F401  (live PG fixtures; module skips without DB)

from evoforge import postgres_kernel, postgres_state


@pytest.fixture
def pg(funded, monkeypatch):
    scope = funded["scope"]
    monkeypatch.setenv("EVO_STATE_BACKEND", "postgres")
    monkeypatch.setenv("EVO_TENANT_ID", str(scope.tenant_id))
    monkeypatch.setenv("EVO_PROJECT_ID", str(scope.project_id))
    monkeypatch.setenv("DATABASE_URL", funded["dsn"])
    postgres_kernel.close_pools()
    yield funded
    postgres_kernel.close_pools()


def _backends(dsn):
    with psycopg.connect(dsn, autocommit=True) as conn:
        return conn.execute("SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend'").fetchone()[0]


def test_pool_off_by_default(pg, monkeypatch):
    monkeypatch.delenv("EVO_PG_POOL_SIZE", raising=False)
    assert postgres_kernel._pool_for(pg["dsn"]) is None


def test_pool_bounds_connections_and_reuses_them(pg, monkeypatch):
    monkeypatch.setenv("EVO_PG_POOL_SIZE", "3")
    records = postgres_state.ScopedRecords("records")
    before = _backends(pg["dsn"])
    errors = []

    def work(i):
        try:
            for j in range(10):
                records[f"pool-{i}-{j}"] = {"id": f"pool-{i}-{j}", "kind": "pool_probe", "n": j}
                assert records[f"pool-{i}-{j}"]["n"] == j
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    pool = postgres_kernel._pool_for(pg["dsn"])
    assert pool is not None and pool._open <= 3
    assert _backends(pg["dsn"]) - before <= 3


def test_failed_transaction_does_not_poison_the_pool(pg, monkeypatch):
    monkeypatch.setenv("EVO_PG_POOL_SIZE", "1")
    records = postgres_state.ScopedRecords("records")
    records["immut-1"] = {"id": "immut-1", "kind": "pool_probe"}
    with pytest.raises(postgres_kernel.KernelRejected):
        records["immut-1"] = {"id": "immut-1", "kind": "changed"}
    assert records["immut-1"]["kind"] == "pool_probe"  # the single pooled connection still works


def test_scan_returns_only_the_kind_in_one_query(pg):
    records = postgres_state.ScopedRecords("records")
    for i in range(5):
        records[f"scan-a-{i}"] = {"id": f"scan-a-{i}", "kind": "scan_a", "i": i}
    records["scan-b-0"] = {"id": "scan-b-0", "kind": "scan_b"}
    records["scan-run-0"] = {"id": "scan-run-0", "run": {"heldout": {"pass": 1, "n": 1}}}
    got = postgres_state.scan(records, kind="scan_a")
    assert [k for k, _ in got] == [f"scan-a-{i}" for i in range(5)]
    assert all(d["kind"] == "scan_a" for _, d in got)
    assert [k for k, _ in postgres_state.scan(records, has="run")] == ["scan-run-0"]


def test_scan_on_plain_dict_and_memory_mode(monkeypatch):
    monkeypatch.setenv("EVO_STATE_BACKEND", "memory")
    store = {"a": {"kind": "x"}, "b": {"kind": "y"}, "c": "not a dict", "d": {"run": {}}}
    assert postgres_state.scan(store, kind="x") == [("a", {"kind": "x"})]
    assert postgres_state.scan(store, has="run") == [("d", {"run": {}})]
    mem = postgres_state.ScopedRecords("records")
    mem["k"] = {"id": "k", "kind": "x"}
    assert postgres_state.scan(mem, kind="x") == [("k", {"id": "k", "kind": "x"})]


def test_nested_transaction_does_not_deadlock_a_full_pool(pg, monkeypatch):
    monkeypatch.setenv("EVO_PG_POOL_SIZE", "1")
    monkeypatch.setenv("EVO_PG_POOL_WAIT_S", "2")
    store = postgres_state.backend()
    with store.kernel._transaction() as outer:
        outer.execute("SELECT 1")
        assert store.keys("records") is not None  # needs a second connection while the only slot is held
    assert postgres_kernel._pool_for(pg["dsn"])._open <= 2
