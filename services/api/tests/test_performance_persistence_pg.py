"""Measured results survive new adapters and remain project scoped."""
from uuid import uuid4
import pytest
from test_postgres_kernel import database, funded, psycopg
from evoforge import performance, postgres_state
from evoforge.postgres_kernel import KernelRejected
import main
from fastapi.testclient import TestClient


def test_persisted_measurements_are_evidence_bound_and_project_scoped(funded, monkeypatch):
    scope = funded["scope"]
    project2 = uuid4()
    with psycopg.connect(funded["dsn"], autocommit=True) as conn:
        conn.execute("INSERT INTO core.projects(tenant_id,project_id,name) VALUES (%s,%s,'other')", (scope.tenant_id, project2))
    monkeypatch.setenv("EVO_STATE_BACKEND", "postgres")
    monkeypatch.setenv("EVO_TENANT_ID", str(scope.tenant_id))
    monkeypatch.setenv("EVO_PROJECT_ID", str(scope.project_id))
    monkeypatch.setenv("DATABASE_URL", funded["dsn"])
    postgres_state.backend().write("records", "ev_test", {"id": "ev_test", "suite_version": "v0", "model": "muse-spark-1.3", "X_SINGLE": {"n": 5, "cost_cents": 0}, "scores": [{"score": 1}, {"score": 1}, {"score": 1}, {"score": 0}, {"score": 0}], "provider_stub": False})
    measurement = performance.make_record(kind="X_SINGLE", n=5, passed=3, evidence_id="ev_test")
    measurement["provider_stub"] = False
    performance.record(measurement)
    assert performance.latest("X_SINGLE") == measurement
    assert performance.history() == [measurement]
    public = main.performance()
    assert public["storage"] == "postgres"
    assert public["baseline"]["record"] == measurement
    with pytest.raises(KernelRejected):
        performance.clear()
    with pytest.raises(KernelRejected):
        with postgres_state.backend().kernel._transaction() as conn:
            conn.execute("DELETE FROM runtime.performance_measurements WHERE measurement_id=%s", (measurement["measurement_id"],))
    missing = performance.make_record(kind="PIPELINE", n=1, passed=1, evidence_id="ev_missing")
    with pytest.raises(KernelRejected):
        performance.record(missing)
    changed = dict(measurement, measurement_id="m_changed", passed=5)
    with pytest.raises(KernelRejected):
        performance.record(changed)
    invalid = dict(measurement, measurement_id="m_bool", cost_cents=False)
    with pytest.raises(KernelRejected):
        performance.record(invalid)
    fake_provenance = dict(measurement, measurement_id="m_stub", provider_stub=True)
    with pytest.raises(KernelRejected):
        performance.record(fake_provenance)
    monkeypatch.setenv("EVO_PROJECT_ID", str(project2))
    assert performance.latest("X_SINGLE") is None
    assert performance.history() == []
    monkeypatch.setenv("EVO_PROJECT_ID", str(scope.project_id))
    assert performance.history() == [measurement]


def test_pipeline_http_persists_synthetic_evaluation_with_provenance(funded, monkeypatch):
    scope = funded["scope"]
    monkeypatch.setenv("EVO_STATE_BACKEND", "postgres")
    monkeypatch.setenv("EVO_TENANT_ID", str(scope.tenant_id))
    monkeypatch.setenv("EVO_PROJECT_ID", str(scope.project_id))
    monkeypatch.setenv("DATABASE_URL", funded["dsn"])
    monkeypatch.delenv("EVO_REQUIRE_ID_TOKEN", raising=False)
    monkeypatch.setattr(main, "_eval_budget_or_402", lambda *args: None)
    monkeypatch.setattr(main.sealed_eval_mod, "count_tasks", lambda *_: 2)
    def simulated(suite_version, model, family=None):
        return {"pipeline_id": "test", "suite_version": suite_version, "model": model,
                "PIPELINE": {"n": 2, "cost_cents": 7, "attempts_total": 4},
                "pass_rate_wilson_lo": 0.1, "pass_rate_wilson_hi": 0.9,
                "scaffold": {}, "audit": {}, "scores": [{"score": 1.0}, {"score": 0.0}],
                "tasks": [], "by_family": {}, "reservation_id": "", "reservation_ids": [],
                "provider_stub": True, "attempts_total": 4, "usage_missing": False}
    monkeypatch.setattr(main.sealed_eval_mod, "run_pipeline", simulated)
    client = TestClient(main.app, raise_server_exceptions=False)
    response = client.post("/v1/eval/pipeline", json={"suite_version": "v0", "model": "muse-spark-1.3"})
    assert response.status_code == 201, response.text
    reported = client.get("/v1/performance")
    assert reported.status_code == 200
    record = reported.json()["pipeline"]["record"]
    assert record["provider_stub"] is True and record["evidence_id"] == response.json()["evidence_id"]
    assert performance.latest("PIPELINE") == record
