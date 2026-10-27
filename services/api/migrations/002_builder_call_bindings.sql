-- Application preflight extension. Frozen ctx/core SQL remains unchanged.
BEGIN;
SET LOCAL ROLE core_owner;
GRANT USAGE ON SCHEMA core TO ctx_owner;
GRANT REFERENCES (tenant_id, project_id, request_key) ON core.cost_reservations TO ctx_owner;
GRANT REFERENCES (tenant_id, project_id, task_id) ON core.tasks TO ctx_owner;
GRANT REFERENCES (tenant_id, agent_id) ON core.agents TO ctx_owner;
SET LOCAL ROLE ctx_owner;

CREATE TABLE IF NOT EXISTS runtime.builder_call_bindings (
  tenant_id uuid NOT NULL,
  project_id uuid NOT NULL,
  call_id uuid NOT NULL,
  reservation_key text NOT NULL CHECK (reservation_key = call_id::text),
  packet_id uuid NOT NULL,
  task_id uuid NOT NULL,
  agent_id uuid NOT NULL,
  lease_epoch bigint NOT NULL CHECK (lease_epoch > 0),
  provider text NOT NULL CHECK (provider = 'meta'),
  model text NOT NULL CHECK (length(model) > 0),
  price_table_version text NOT NULL CHECK (length(price_table_version) > 0),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id, project_id, call_id),
  FOREIGN KEY (tenant_id, project_id, reservation_key)
    REFERENCES core.cost_reservations (tenant_id, project_id, request_key),
  FOREIGN KEY (tenant_id, project_id, packet_id)
    REFERENCES ctx.context_packets (tenant_id, project_id, packet_id),
  FOREIGN KEY (tenant_id, project_id, task_id)
    REFERENCES core.tasks (tenant_id, project_id, task_id),
  FOREIGN KEY (tenant_id, agent_id) REFERENCES core.agents (tenant_id, agent_id)
);
CREATE OR REPLACE FUNCTION runtime.reject_binding_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  RAISE EXCEPTION 'provider call bindings are immutable' USING ERRCODE = 'insufficient_privilege';
END $$;
DROP TRIGGER IF EXISTS builder_call_binding_immutable ON runtime.builder_call_bindings;
CREATE TRIGGER builder_call_binding_immutable BEFORE UPDATE OR DELETE
  ON runtime.builder_call_bindings FOR EACH ROW EXECUTE FUNCTION runtime.reject_binding_mutation();
ALTER TABLE runtime.builder_call_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime.builder_call_bindings FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS builder_call_scope ON runtime.builder_call_bindings;
CREATE POLICY builder_call_scope ON runtime.builder_call_bindings
  USING (tenant_id = core.current_tenant() AND project_id = ANY(core.current_projects()))
  WITH CHECK (tenant_id = core.current_tenant() AND project_id = ANY(core.current_projects()));
REVOKE ALL ON runtime.builder_call_bindings FROM PUBLIC;
GRANT USAGE ON SCHEMA runtime TO core_app;
GRANT SELECT, INSERT ON runtime.builder_call_bindings TO core_app;
COMMIT;
