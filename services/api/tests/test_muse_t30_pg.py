"""T30 live-PG tests: evolutions and memory survive new processes and stay scoped."""
from uuid import uuid4

import pytest
from test_postgres_kernel import database, funded, psycopg  # noqa: F401

from evoforge import evolution as evo
from evoforge import memory as mem
from evoforge import postgres_state
from evoforge.postgres_kernel import KernelRejected


def _pg(monkeypatch, funded):
    scope = funded["scope"]
    monkeypatch.setenv("EVO_STATE_BACKEND", "postgres")
    monkeypatch.setenv("EVO_TENANT_ID", str(scope.tenant_id))
    monkeypatch.setenv("EVO_PROJECT_ID", str(scope.project_id))
    monkeypatch.setenv("DATABASE_URL", funded["dsn"])
    return scope


def test_evolution_survives_redeploy_and_stays_scoped(funded, monkeypatch):
    scope = _pg(monkeypatch, funded)
    e = evo.start("durable goal alpha", "HEAD", max_generations=3, population=1)
    eid = e["evolution_id"]
    cand = {"gates": [{"gate": "G0", "result": "FAIL"}],
            "run": {"visible": {"pass": 0, "n": 1}, "heldout": {"pass": 0, "n": 1}},
            "generate_evidence_id": "ev_1", "run_evidence_id": "ev_2"}
    gen = evo.record_generation(eid, [cand])
    assert gen["converged"] is False
    # A converged evolution is terminal, so persistence of CONVERGED uses its own row.
    conv = evo.start("durable goal beta", "HEAD", max_generations=2, population=1)
    passing = {"gates": [{"gate": "G0", "result": "PASS"}],
               "run": {"visible": {"pass": 1, "n": 1}, "heldout": {"pass": 1, "n": 1}},
               "generate_evidence_id": "ev_1", "run_evidence_id": "ev_2"}
    evo.record_generation(conv["evolution_id"], [passing])
    # Simulate an API redeploy: drop every process-local copy.
    evo._evolutions.clear()
    again = evo.get(eid)
    assert again is not None and len(again["generations"]) == 1
    assert again["status"] == "RUNNING"
    assert again["best"] is not None
    assert evo.get(conv["evolution_id"])["status"] == "CONVERGED"
    assert sorted(x["evolution_id"] for x in evo.list_all()) == sorted([eid, conv["evolution_id"]])
    fresh = postgres_state.backend()
    assert fresh is not None
    evo.cancel(eid)
    evo._evolutions.clear()
    assert evo.get(eid)["status"] == "CANCELLED"
    with pytest.raises(KernelRejected):
        evo.reset()
    with pytest.raises(KernelRejected):
        mem.reset()
    other = uuid4()
    with psycopg.connect(funded["dsn"], autocommit=True) as conn:
        conn.execute("INSERT INTO core.projects(tenant_id,project_id,name) VALUES (%s,%s,'other')",
                     (scope.tenant_id, other))
    monkeypatch.setenv("EVO_PROJECT_ID", str(other))
    assert evo.get(eid) is None and evo.list_all() == []
    monkeypatch.setenv("EVO_PROJECT_ID", str(scope.project_id))
    assert evo.get(eid)["status"] == "CANCELLED"


def test_memory_survives_redeploy_and_rejects_nonfinite(funded, monkeypatch):
    scope = _pg(monkeypatch, funded)
    pat = mem.record("evo_mem_1", "durable login flow", "diff-body", 110.0, "ev_run")
    assert pat["evolution_id"] == "evo_mem_1"
    mem._patterns.clear()
    assert mem.record("evo_mem_1", "changed", "other", 1.0, None)["pattern_id"] == pat["pattern_id"]
    mem._patterns.clear()
    assert [p["evolution_id"] for p in mem.recall("login flow")] == ["evo_mem_1"]
    assert "login" in mem.hint_block("login flow")
    pub = mem.public_all()
    assert pub[0]["proof_path"] == "/v1/proof/ev_run"
    with pytest.raises(KernelRejected):
        mem.record("evo_bad", "goal words", "d", float("inf"), None)
    from evoforge.postgres_evolutions import EvolutionStore
    with pytest.raises(KernelRejected):
        EvolutionStore(postgres_state.backend().kernel).upsert(
            {"evolution_id": "evo_nan", "nan": float("nan")})
    other = uuid4()
    with psycopg.connect(funded["dsn"], autocommit=True) as conn:
        conn.execute("INSERT INTO core.projects(tenant_id,project_id,name) VALUES (%s,%s,'other')",
                     (scope.tenant_id, other))
    monkeypatch.setenv("EVO_PROJECT_ID", str(other))
    assert mem.recall("login flow") == [] and mem.public_all() == []
    monkeypatch.setenv("EVO_PROJECT_ID", str(scope.project_id))
    assert [p["evolution_id"] for p in mem.recall("login flow")] == ["evo_mem_1"]
