-- Application extension; the frozen core/ctx contracts are not modified.
BEGIN;
CREATE SCHEMA IF NOT EXISTS runtime AUTHORIZATION ctx_owner;
SET LOCAL ROLE ctx_owner;

CREATE TABLE IF NOT EXISTS runtime.provider_receipt_documents (
  tenant_id uuid NOT NULL,
  project_id uuid NOT NULL,
  receipt_id uuid NOT NULL,
  call_id uuid NOT NULL,
  -- json preserves provider numeric representations (e.g. 1e20 / -0.0).
  -- jsonb normalization can change them and invalidate a canonical digest.
  document json NOT NULL CHECK (json_typeof(document) = 'object'),
  document_sha256 char(64) NOT NULL CHECK (document_sha256 ~ '^[0-9a-f]{64}$'),
  stored_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, project_id, receipt_id),
  UNIQUE (tenant_id, project_id, call_id),
  FOREIGN KEY (tenant_id, project_id, receipt_id)
    REFERENCES ctx.provider_usage_receipts (tenant_id, project_id, receipt_id),
  CHECK (coalesce(document->>'tenant_id' = tenant_id::text, false)),
  CHECK (coalesce(document->>'project_id' = project_id::text, false)),
  CHECK (coalesce(document->>'receipt_id' = receipt_id::text, false)),
  CHECK (coalesce(document->>'call_id' = call_id::text, false)),
  CHECK (coalesce(document->>'reservation_key' = call_id::text, false)),
  CHECK (coalesce(document->>'schema_version' = 'provider-usage-receipt/v1', false))
);

CREATE OR REPLACE FUNCTION runtime.reject_receipt_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  RAISE EXCEPTION 'receipt documents are append-only' USING ERRCODE = 'insufficient_privilege';
END $$;
DROP TRIGGER IF EXISTS receipt_documents_append_only ON runtime.provider_receipt_documents;
CREATE TRIGGER receipt_documents_append_only BEFORE UPDATE OR DELETE
  ON runtime.provider_receipt_documents FOR EACH ROW EXECUTE FUNCTION runtime.reject_receipt_mutation();

ALTER TABLE runtime.provider_receipt_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime.provider_receipt_documents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS receipt_document_scope ON runtime.provider_receipt_documents;
CREATE POLICY receipt_document_scope ON runtime.provider_receipt_documents
  USING (tenant_id = ctx.current_tenant() AND project_id = ANY(ctx.current_projects()))
  WITH CHECK (tenant_id = ctx.current_tenant() AND project_id = ANY(ctx.current_projects()));
REVOKE ALL ON runtime.provider_receipt_documents FROM PUBLIC;
GRANT USAGE ON SCHEMA runtime TO ctx_gateway;
GRANT SELECT, INSERT ON runtime.provider_receipt_documents TO ctx_gateway;
COMMIT;
