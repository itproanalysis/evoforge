-- Durable private API evidence; roles and frozen contracts must already exist.
BEGIN;
SET LOCAL ROLE core_owner;
GRANT REFERENCES (tenant_id,project_id) ON core.projects TO ctx_owner;
SET LOCAL ROLE ctx_owner;
CREATE TABLE IF NOT EXISTS runtime.api_evidence_records (
  tenant_id uuid NOT NULL, project_id uuid NOT NULL, id text NOT NULL,
  document jsonb NOT NULL CHECK (jsonb_typeof(document)='object'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id,project_id,id),
  FOREIGN KEY (tenant_id,project_id) REFERENCES core.projects (tenant_id,project_id),
  CHECK (coalesce(document->>'id'=id,false))
);
CREATE TABLE IF NOT EXISTS runtime.api_evidence_events (
  tenant_id uuid NOT NULL, project_id uuid NOT NULL, id text NOT NULL,
  document jsonb NOT NULL CHECK (jsonb_typeof(document)='object'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id,project_id,id),
  FOREIGN KEY (tenant_id,project_id) REFERENCES core.projects (tenant_id,project_id),
  CHECK (coalesce(document->>'id'=id,false))
);
CREATE TABLE IF NOT EXISTS runtime.api_evidence_links (
  tenant_id uuid NOT NULL, project_id uuid NOT NULL,
  evidence_id text NOT NULL, stage text NOT NULL CHECK
    (stage IN ('ObjectiveVersion','Task','Candidate','Gate','Review','PR','Outcome')),
  event_id text NOT NULL,
  PRIMARY KEY (tenant_id,project_id,evidence_id,stage),
  FOREIGN KEY (tenant_id,project_id,evidence_id) REFERENCES runtime.api_evidence_records (tenant_id,project_id,id),
  FOREIGN KEY (tenant_id,project_id,event_id) REFERENCES runtime.api_evidence_events (tenant_id,project_id,id)
);
CREATE INDEX IF NOT EXISTS api_evidence_event_links ON runtime.api_evidence_links (tenant_id,project_id,event_id);
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['api_evidence_records','api_evidence_events','api_evidence_links'] LOOP
    EXECUTE format('ALTER TABLE runtime.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE runtime.%I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('DROP POLICY IF EXISTS evidence_scope ON runtime.%I',t);
    EXECUTE format('CREATE POLICY evidence_scope ON runtime.%I USING (tenant_id=core.current_tenant() AND project_id=ANY(core.current_projects())) WITH CHECK (tenant_id=core.current_tenant() AND project_id=ANY(core.current_projects()))',t);
    EXECUTE format('DROP TRIGGER IF EXISTS evidence_immutable ON runtime.%I',t);
    EXECUTE format('CREATE TRIGGER evidence_immutable BEFORE UPDATE OR DELETE ON runtime.%I FOR EACH ROW EXECUTE FUNCTION runtime.reject_binding_mutation()',t);
    EXECUTE format('REVOKE ALL ON runtime.%I FROM PUBLIC',t);
    EXECUTE format('GRANT SELECT,INSERT ON runtime.%I TO core_app',t);
  END LOOP;
END $$;
COMMIT;
