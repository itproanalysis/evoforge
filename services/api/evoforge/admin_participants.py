"""Read project-linked agent activity using the existing scoped Trust Kernel."""
from evoforge import postgres_state


def list_participants():
    store = postgres_state.backend()
    if store is None:
        return {"status": "unavailable", "reason": "participant records require PostgreSQL", "participants": [], "has_more": False}
    tenant, project = store.scope
    with store.kernel._transaction() as conn:
        rows = conn.execute("""
            WITH participation AS (
              SELECT lease_holder AS agent_id, 'lease_holder' AS role FROM core.tasks
               WHERE tenant_id=%s AND project_id=%s AND lease_holder IS NOT NULL
              UNION
              SELECT author_agent_id, 'builder' FROM core.candidates
               WHERE tenant_id=%s AND project_id=%s
              UNION
              SELECT reviewer_agent_id, 'reviewer' FROM core.reviews
               WHERE tenant_id=%s AND project_id=%s
            )
            SELECT a.agent_id, a.kind, a.join_state, a.connection_state,
                   a.execution_state, a.credential_state,
                   array_agg(DISTINCT p.role ORDER BY p.role) AS roles
              FROM participation p JOIN core.agents a
                ON a.tenant_id=%s AND a.agent_id=p.agent_id
             GROUP BY a.agent_id, a.kind, a.join_state, a.connection_state,
                      a.execution_state, a.credential_state
             ORDER BY a.agent_id LIMIT 1001
        """, (tenant, project, tenant, project, tenant, project, tenant)).fetchall()
    return {"status": "available", "participants": [
        {**row, "agent_id": str(row["agent_id"])} for row in rows[:1000]
    ], "has_more": len(rows) > 1000}
