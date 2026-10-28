import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import main
from evoforge import postgres_state
from evoforge.postgres_kernel import KernelUnavailable


def test_memory_backend_reports_participants_unavailable(monkeypatch):
    monkeypatch.setenv("EVO_STATE_BACKEND", "memory")
    monkeypatch.delenv("EVO_REQUIRE_ID_TOKEN", raising=False)
    response = TestClient(main.app).get("/v1/participants")
    assert response.status_code == 200
    assert response.json() == {"status": "unavailable", "reason": "participant records require PostgreSQL", "participants": [], "has_more": False}


def test_database_failure_is_not_reported_as_empty_participants(monkeypatch):
    monkeypatch.delenv("EVO_REQUIRE_ID_TOKEN", raising=False)
    def unavailable():
        raise KernelUnavailable("private database connection details")
    monkeypatch.setattr(postgres_state, "backend", unavailable)
    response = TestClient(main.app, raise_server_exceptions=False).get("/v1/participants")
    assert response.status_code == 503
    assert response.json() == {"detail": "state storage unavailable"}
