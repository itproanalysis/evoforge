"""Disposable PostgreSQL regression for the one-shot migration ledger."""
import importlib.util
from pathlib import Path
import pytest
from test_postgres_kernel import database, funded, psycopg

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("migrate_pg_codex", ROOT / "infra/gcp/migrate_once.py")
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


def test_recovery_excludes_011_and_real_sql_creates_table(funded, monkeypatch):
    dsn = funded["dsn"]  # fixture creates and later drops its own disposable database
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP TABLE runtime.performance_measurements")
        conn.execute("CREATE SCHEMA IF NOT EXISTS ops")
        conn.execute("CREATE TABLE ops.applied_files(path text PRIMARY KEY, applied_at timestamptz DEFAULT now())")
    monkeypatch.setattr(migrate, "SSLMODE", "disable")
    monkeypatch.setattr(migrate, "FILES", [
        "services/api/migrations/010_candidate_pr_evidence.sql",
        "services/api/migrations/011_performance_measurements.sql",
    ])
    migrate._recover_initial_provisioning(dsn)
    assert migrate._already_applied(dsn, migrate.FILES[0])
    assert not migrate._already_applied(dsn, migrate.FILES[1])
    with pytest.raises(RuntimeError, match="operator reconciliation"):
        migrate._check_marker(dsn, migrate.FILES[1])
    sql = (ROOT / migrate.FILES[1]).read_text(encoding="utf-8")
    migrate.run(dsn, sql, migrate.FILES[1])
    migrate._mark_applied(dsn, migrate.FILES[1])
    assert migrate._already_applied(dsn, migrate.FILES[1])
    migrate._check_marker(dsn, migrate.FILES[1])
