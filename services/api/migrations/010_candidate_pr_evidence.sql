-- Attach the server-owned PR run to a Builder candidate without rewriting
-- pre-existing immutable bindings or changing canonical kernel contracts.
BEGIN;
SET LOCAL ROLE ctx_owner;
ALTER TABLE runtime.builder_candidate_evidence
  ADD COLUMN IF NOT EXISTS pr_source_evidence_id text,
  ADD COLUMN IF NOT EXISTS pr_source_evidence_sha256 char(64);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='runtime.builder_candidate_evidence'::regclass
                 AND conname='builder_candidate_pr_source_pair') THEN
    ALTER TABLE runtime.builder_candidate_evidence ADD CONSTRAINT builder_candidate_pr_source_pair CHECK (
      (pr_source_evidence_id IS NULL AND pr_source_evidence_sha256 IS NULL) OR
      (pr_source_evidence_id IS NOT NULL AND length(pr_source_evidence_id) BETWEEN 1 AND 256
       AND pr_source_evidence_sha256 IS NOT NULL AND pr_source_evidence_sha256 ~ '^[a-f0-9]{64}$'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='runtime.builder_candidate_evidence'::regclass
                 AND conname='builder_candidate_pr_source_fk') THEN
    ALTER TABLE runtime.builder_candidate_evidence ADD CONSTRAINT builder_candidate_pr_source_fk
      FOREIGN KEY (tenant_id,project_id,pr_source_evidence_id)
      REFERENCES runtime.api_evidence_records (tenant_id,project_id,id);
  END IF;
END $$;
COMMIT;
