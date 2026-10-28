-- Durable autopilot evolutions and evolution memory; process memory is lost on redeploy.
BEGIN;
SET LOCAL ROLE ctx_owner;
CREATE TABLE IF NOT EXISTS runtime.api_evolutions (
  tenant_id uuid NOT NULL, project_id uuid NOT NULL, evolution_id text NOT NULL,
  document jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id, project_id, evolution_id),
  FOREIGN KEY (tenant_id, project_id) REFERENCES core.projects (tenant_id, project_id)
);
CREATE TABLE IF NOT EXISTS runtime.api_evolution_memory (
  tenant_id uuid NOT NULL, project_id uuid NOT NULL,
  pattern_id text NOT NULL, evolution_id text NOT NULL,
  document jsonb NOT NULL, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id, project_id, pattern_id),
  FOREIGN KEY (tenant_id, project_id) REFERENCES core.projects (tenant_id, project_id)
);
ALTER TABLE runtime.api_evolutions ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime.api_evolutions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS evolution_scope ON runtime.api_evolutions;
CREATE POLICY evolution_scope ON runtime.api_evolutions
  USING (tenant_id=core.current_tenant() AND project_id=ANY(core.current_projects()))
  WITH CHECK (tenant_id=core.current_tenant() AND project_id=ANY(core.current_projects()));
ALTER TABLE runtime.api_evolution_memory ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime.api_evolution_memory FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS evolution_memory_scope ON runtime.api_evolution_memory;
CREATE POLICY evolution_memory_scope ON runtime.api_evolution_memory
  USING (tenant_id=core.current_tenant() AND project_id=ANY(core.current_projects()))
  WITH CHECK (tenant_id=core.current_tenant() AND project_id=ANY(core.current_projects()));
DROP TRIGGER IF EXISTS evolution_memory_immutable ON runtime.api_evolution_memory;
CREATE TRIGGER evolution_memory_immutable BEFORE UPDATE OR DELETE ON runtime.api_evolution_memory
  FOR EACH ROW EXECUTE FUNCTION runtime.reject_binding_mutation();
REVOKE ALL ON runtime.api_evolutions FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON runtime.api_evolutions TO core_app;
REVOKE ALL ON runtime.api_evolution_memory FROM PUBLIC;
GRANT SELECT, INSERT ON runtime.api_evolution_memory TO core_app;
COMMIT;
