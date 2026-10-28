-- Evidence-linked measured performance; no changes to canonical merge or billing.
BEGIN;
SET LOCAL ROLE ctx_owner;
CREATE TABLE IF NOT EXISTS runtime.performance_measurements (
  tenant_id uuid NOT NULL, project_id uuid NOT NULL,
  measurement_id text NOT NULL, evidence_id text NOT NULL,
  document jsonb NOT NULL, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id, project_id, measurement_id),
  FOREIGN KEY (tenant_id,project_id,evidence_id)
    REFERENCES runtime.api_evidence_records (tenant_id,project_id,id),
  CHECK (coalesce(jsonb_typeof(document)='object'
    AND document->>'measurement_id'=measurement_id
    AND document->>'evidence_id'=evidence_id
    AND document->>'kind' IN ('X_SINGLE','PIPELINE'),false))
);
ALTER TABLE runtime.performance_measurements ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime.performance_measurements FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS performance_scope ON runtime.performance_measurements;
CREATE POLICY performance_scope ON runtime.performance_measurements
  USING (tenant_id=core.current_tenant() AND project_id=ANY(core.current_projects()))
  WITH CHECK (tenant_id=core.current_tenant() AND project_id=ANY(core.current_projects()));
DROP TRIGGER IF EXISTS performance_immutable ON runtime.performance_measurements;
CREATE TRIGGER performance_immutable BEFORE UPDATE OR DELETE ON runtime.performance_measurements
  FOR EACH ROW EXECUTE FUNCTION runtime.reject_binding_mutation();
REVOKE ALL ON runtime.performance_measurements FROM PUBLIC;
GRANT SELECT,INSERT ON runtime.performance_measurements TO core_app;
COMMIT;
