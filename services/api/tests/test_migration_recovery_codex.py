"""Migration recovery must never mark future files as already executed."""
import importlib.util
import io
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("migrate_once_codex", ROOT / "infra/gcp/migrate_once.py")
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


class Connection:
    def __init__(self, marked):
        self.marked = marked
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def cursor(self): return self
    def execute(self, query, params=None):
        if query.startswith("INSERT INTO ops.applied_files"):
            self.marked.add(params[0])
    def fetchone(self): return [0]
    def commit(self): pass


@pytest.mark.parametrize("recover", [False, True])
def test_recovery_never_skips_011_or_later(monkeypatch, recover):
    legacy = ["docs/evoforge-v4.2/contracts/sql/core_DRAFT.sql",
              "services/api/migrations\\001_receipt_documents.sql",
              "services/api/migrations/010_candidate_pr_evidence.sql"]
    future = ["services/api/migrations/011_performance_measurements.sql",
              "services/api/migrations/012_future.sql"]
    seed = "infra/gcp/seed_hackathon.sql"
    marked, executed = set(), []
    monkeypatch.setattr(migrate, "FILES", legacy + future + [seed])
    monkeypatch.setenv("SQLROOT_PW", "synthetic-root")
    monkeypatch.setenv("SQLAPP_PW", "synthetic-app")
    if recover:
        monkeypatch.setenv("EVO_RECOVER_INITIAL_PROVISIONING", "1")
    else:
        monkeypatch.delenv("EVO_RECOVER_INITIAL_PROVISIONING", raising=False)
    monkeypatch.setattr(migrate.psycopg, "connect", lambda *a, **k: Connection(marked))
    monkeypatch.setattr(migrate, "run", lambda conn, sql, label, setup="": executed.append(label))
    monkeypatch.setattr(migrate, "_already_applied", lambda conn, path: path in marked)
    monkeypatch.setattr(migrate, "_mark_applied", lambda conn, path: marked.add(path))
    monkeypatch.setattr("builtins.open", lambda *a, **k: io.StringIO("-- test"))
    assert migrate.main() == 0
    assert all(path in executed for path in future + [seed])
    if recover:
        assert all(path not in executed for path in legacy)
    else:
        assert all(path in executed for path in legacy)


def test_ledger_connection_failure_is_not_treated_as_unapplied(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("database unavailable")
    monkeypatch.setattr(migrate.psycopg, "connect", fail)
    with pytest.raises(RuntimeError, match="migration ledger unavailable"):
        migrate._already_applied("synthetic", "future.sql")


def test_false_011_marker_stops_without_changing_ledger(monkeypatch):
    marked = set()
    monkeypatch.setattr(migrate.psycopg, "connect", lambda *a, **k: Connection(marked))
    with pytest.raises(RuntimeError, match="operator reconciliation"):
        migrate._check_marker("synthetic", "services/api/migrations/011_performance_measurements.sql")
    assert marked == set()
