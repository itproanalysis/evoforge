-- Existing core candidates remain authoritative. Store only the Runner/G2 binding.
BEGIN;
SET LOCAL ROLE core_owner;
GRANT REFERENCES (tenant_id,project_id,candidate_id) ON core.candidates TO ctx_owner;
GRANT REFERENCES (tenant_id,project_id,gate_result_id) ON core.gate_results TO ctx_owner;
SET LOCAL ROLE ctx_owner;
CREATE TABLE IF NOT EXISTS runtime.candidate_run_evidence (
  tenant_id uuid NOT NULL, project_id uuid NOT NULL, candidate_id uuid NOT NULL,
  evidence_id text NOT NULL, call_id uuid NOT NULL, gate_result_id uuid NOT NULL,
  head_sha text NOT NULL CHECK (head_sha ~ '^([a-f0-9]{40}|[a-f0-9]{64})$'),
  policy_hash char(64) NOT NULL CHECK (policy_hash ~ '^[a-f0-9]{64}$'),
  evidence_sha256 char(64) NOT NULL CHECK (evidence_sha256 ~ '^[a-f0-9]{64}$'),
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id,project_id,candidate_id,evidence_id),
  FOREIGN KEY (tenant_id,project_id,candidate_id) REFERENCES core.candidates (tenant_id,project_id,candidate_id),
  FOREIGN KEY (tenant_id,project_id,evidence_id) REFERENCES runtime.api_evidence_records (tenant_id,project_id,id),
  FOREIGN KEY (tenant_id,project_id,call_id) REFERENCES runtime.builder_call_bindings (tenant_id,project_id,call_id),
  FOREIGN KEY (tenant_id,project_id,gate_result_id) REFERENCES core.gate_results (tenant_id,project_id,gate_result_id)
);
ALTER TABLE runtime.candidate_run_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime.candidate_run_evidence FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS candidate_run_scope ON runtime.candidate_run_evidence;
CREATE POLICY candidate_run_scope ON runtime.candidate_run_evidence
  USING (tenant_id=core.current_tenant() AND project_id=ANY(core.current_projects()))
  WITH CHECK (tenant_id=core.current_tenant() AND project_id=ANY(core.current_projects()));
DROP TRIGGER IF EXISTS candidate_run_immutable ON runtime.candidate_run_evidence;
CREATE TRIGGER candidate_run_immutable BEFORE UPDATE OR DELETE ON runtime.candidate_run_evidence
  FOR EACH ROW EXECUTE FUNCTION runtime.reject_binding_mutation();
REVOKE ALL ON runtime.candidate_run_evidence FROM PUBLIC;
GRANT SELECT,INSERT ON runtime.candidate_run_evidence TO core_app;
COMMIT;
