"""Project isolation against the real PostgreSQL roles and RLS policies."""
from uuid import uuid4

from test_postgres_kernel import database, funded, psycopg
from evoforge.admin_participants import list_participants
from fastapi.testclient import TestClient
import main


def test_only_project_linked_agents_are_returned(funded, monkeypatch):
    scope = funded["scope"]
    first, other, run, task, candidate, reviewer = (uuid4() for _ in range(6))
    other_project, other_run, other_task = uuid4(), uuid4(), uuid4()
    with psycopg.connect(funded["dsn"], autocommit=True) as c:
        c.execute("INSERT INTO core.projects(tenant_id,project_id,name) VALUES (%s,%s,'other')", (scope.tenant_id, other_project))
        for agent in (first, other, reviewer):
            c.execute("INSERT INTO core.agents(tenant_id,agent_id,kind) VALUES (%s,%s,'provider_api')", (scope.tenant_id, agent))
        for project, rid in ((scope.project_id, run), (other_project, other_run)):
            c.execute("INSERT INTO core.runs(tenant_id,project_id,run_id,objective_version,topology,harness_version,policy_hash) VALUES (%s,%s,%s,1,'SINGLE','h',repeat('a',64))", (scope.tenant_id, project, rid))
        for project, rid, tid, agent in ((scope.project_id,run,task,first), (other_project,other_run,other_task,other)):
            c.execute("INSERT INTO core.tasks(tenant_id,project_id,task_id,run_id,risk_level,lease_holder) VALUES (%s,%s,%s,%s,'LOW',%s)", (scope.tenant_id, project, tid, rid, agent))
        c.execute("INSERT INTO core.candidates(tenant_id,project_id,candidate_id,task_id,author_agent_id,base_sha,head_sha) VALUES (%s,%s,%s,%s,%s,repeat('a',40),repeat('b',40))", (scope.tenant_id, scope.project_id, candidate, task, first))
        c.execute("INSERT INTO core.reviews(tenant_id,project_id,candidate_id,reviewer_agent_id,verdict,head_sha) VALUES (%s,%s,%s,%s,'comment',repeat('b',40))", (scope.tenant_id, scope.project_id, candidate, reviewer))
    monkeypatch.setenv("EVO_STATE_BACKEND", "postgres")
    monkeypatch.setenv("EVO_TENANT_ID", str(scope.tenant_id))
    monkeypatch.setenv("EVO_PROJECT_ID", str(scope.project_id))
    monkeypatch.setenv("DATABASE_URL", funded["dsn"])
    result = list_participants()
    assert result["status"] == "available" and not result["has_more"]
    participants = {row["agent_id"]: row for row in result["participants"]}
    assert set(participants) == {str(first), str(reviewer)}
    assert participants[str(first)]["roles"] == ["builder", "lease_holder"]
    assert participants[str(reviewer)]["roles"] == ["reviewer"]
    monkeypatch.delenv("EVO_REQUIRE_ID_TOKEN", raising=False)
    response = TestClient(main.app).get("/v1/participants")
    assert response.status_code == 200 and response.json() == result
