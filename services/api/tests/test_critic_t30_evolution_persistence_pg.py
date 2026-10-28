"""Critic acceptance (sealed during build, promoted after) — T30: evolutions and evolution memory survive an API redeploy (PostgreSQL), project scoped.

Today evolution.py/_evolutions and memory.py/_patterns live in process memory, so every deploy erases the autopilot's
history, its learned patterns and the leaderboard built on them (board W14)."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from test_postgres_kernel import database, funded, psycopg  # noqa: F401  (live PG fixtures; module skips without DB)

from fastapi.testclient import TestClient

import main
from evoforge import evolution as evo_engine
from evoforge import memory as evo_memory

c = TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture
def pg(funded, monkeypatch):
    scope = funded["scope"]
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("EVO_STATE_BACKEND", "postgres")
    monkeypatch.setenv("EVO_TENANT_ID", str(scope.tenant_id))
    monkeypatch.setenv("EVO_PROJECT_ID", str(scope.project_id))
    monkeypatch.setenv("DATABASE_URL", funded["dsn"])
    monkeypatch.setenv("EVO_EVOLUTION_MAX_CENTS", "100000")
    return funded


def _forget_process_memory():
    """What an API redeploy does: the new process starts with empty in-memory structures."""
    for name in ("_evolutions", "_locks"):
        obj = getattr(evo_engine, name, None)
        if isinstance(obj, dict):
            obj.clear()
    pats = getattr(evo_memory, "_patterns", None)
    if isinstance(pats, list):
        pats.clear()


def test_migration_creates_rls_forced_tables(pg):
    with psycopg.connect(pg["dsn"], autocommit=True) as conn:
        rows = conn.execute(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='runtime' AND c.relname IN ('api_evolutions','api_evolution_memory')"
        ).fetchall()
    got = {r[0]: (r[1], r[2]) for r in rows}
    assert got.get("api_evolutions") == (True, True), got
    assert got.get("api_evolution_memory") == (True, True), got


def test_evolution_survives_a_redeploy(pg):
    r = c.post("/v1/evolution/start", json={"goal": "persist me", "max_generations": 2, "population": 1})
    assert r.status_code == 201, r.text
    eid = r.json()["evolution_id"]
    assert c.post(f"/v1/evolution/{eid}/step").status_code == 200
    before = c.get(f"/v1/evolution/{eid}").json()
    _forget_process_memory()
    after = c.get(f"/v1/evolution/{eid}")
    assert after.status_code == 200, after.text
    after = after.json()
    assert after["status"] == before["status"] and len(after["generations"]) == len(before["generations"]) == 1
    assert eid in [e["evolution_id"] for e in c.get("/v1/evolution").json()["evolutions"]]
    # It can continue after the redeploy.
    assert c.post(f"/v1/evolution/{eid}/step").status_code == 200
    assert len(c.get(f"/v1/evolution/{eid}").json()["generations"]) == 2


def test_evolutions_are_project_scoped(pg, monkeypatch):
    scope = pg["scope"]
    eid = c.post("/v1/evolution/start", json={"goal": "scoped", "max_generations": 1, "population": 1}).json()["evolution_id"]
    other = uuid4()
    with psycopg.connect(pg["dsn"], autocommit=True) as conn:
        conn.execute("INSERT INTO core.projects(tenant_id,project_id,name) VALUES (%s,%s,'other')", (scope.tenant_id, other))
    monkeypatch.setenv("EVO_PROJECT_ID", str(other))
    _forget_process_memory()
    assert c.get(f"/v1/evolution/{eid}").status_code == 404
    assert eid not in [e["evolution_id"] for e in c.get("/v1/evolution").json()["evolutions"]]


def test_memory_patterns_survive_a_redeploy(pg):
    evo_memory.record("evo_x", "fix bsearch returns index or minus one", "--- a/b.py\n+++ b/b.py\n", 130.0, "ev_run_x")
    _forget_process_memory()
    hits = evo_memory.recall("bsearch index minus one", k=2)
    assert hits and hits[0]["evolution_id"] == "evo_x", hits
    assert any(p["evolution_id"] == "evo_x" for p in evo_memory.public_all())


def test_durable_store_cannot_be_reset(pg):
    from evoforge.postgres_kernel import KernelRejected
    with pytest.raises(KernelRejected):
        evo_engine.reset()
