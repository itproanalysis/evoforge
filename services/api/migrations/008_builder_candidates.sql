-- Receipt/Git verified Builder proposals; no canonical status or approval shortcuts.
BEGIN;
SET LOCAL ROLE core_owner;
GRANT REFERENCES (tenant_id,project_id,candidate_id) ON core.candidates TO ctx_owner;
SET LOCAL ROLE ctx_owner;
CREATE TABLE IF NOT EXISTS runtime.builder_candidate_evidence (
  tenant_id uuid NOT NULL, project_id uuid NOT NULL, candidate_id uuid NOT NULL, call_id uuid NOT NULL,
  evidence_id text NOT NULL, receipt_id uuid NOT NULL,
  base_sha text NOT NULL CHECK (base_sha ~ '^[a-f0-9]{40}$'),
  head_sha text NOT NULL CHECK (head_sha ~ '^[a-f0-9]{40}$'),
  tree_sha text NOT NULL CHECK (tree_sha ~ '^[a-f0-9]{40}$'),
  evidence_sha256 char(64) NOT NULL CHECK (evidence_sha256 ~ '^[a-f0-9]{64}$'),
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id,project_id,call_id),
  UNIQUE (tenant_id,project_id,candidate_id),
  UNIQUE (tenant_id,project_id,evidence_id),
  FOREIGN KEY (tenant_id,project_id,candidate_id) REFERENCES core.candidates (tenant_id,project_id,candidate_id),
  FOREIGN KEY (tenant_id,project_id,call_id) REFERENCES runtime.builder_call_bindings (tenant_id,project_id,call_id),
  FOREIGN KEY (tenant_id,project_id,evidence_id) REFERENCES runtime.api_evidence_records (tenant_id,project_id,id),
  FOREIGN KEY (tenant_id,project_id,receipt_id) REFERENCES runtime.provider_receipt_documents (tenant_id,project_id,receipt_id)
);
ALTER TABLE runtime.builder_candidate_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime.builder_candidate_evidence FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS builder_candidate_scope ON runtime.builder_candidate_evidence;
CREATE POLICY builder_candidate_scope ON runtime.builder_candidate_evidence
  USING (tenant_id=core.current_tenant() AND project_id=ANY(core.current_projects()))
  WITH CHECK (tenant_id=core.current_tenant() AND project_id=ANY(core.current_projects()));
DROP TRIGGER IF EXISTS builder_candidate_immutable ON runtime.builder_candidate_evidence;
CREATE TRIGGER builder_candidate_immutable BEFORE UPDATE OR DELETE ON runtime.builder_candidate_evidence
  FOR EACH ROW EXECUTE FUNCTION runtime.reject_binding_mutation();
REVOKE ALL ON runtime.builder_candidate_evidence FROM PUBLIC;
GRANT SELECT,INSERT ON runtime.builder_candidate_evidence TO core_app;
COMMIT;
