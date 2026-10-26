-- EvoForge v3.5 context plane migrations: DRAFT ONLY / NOT APPLIED
-- Assumes tenants/projects/tasks and auth context exist; adjust FK references to baseline schema.
-- Default deny; do not deploy without RLS verification, encryption key setup, and access testing.
CREATE TABLE IF NOT EXISTS evidence_blobs_v35 (
 tenant_id uuid NOT NULL,
 project_id uuid NOT NULL,
 blob_id uuid NOT NULL DEFAULT gen_random_uuid(),
 source_sha256 char(64) NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
 object_storage_key text NOT NULL,
 content_type text NOT NULL,
 sensitivity text NOT NULL CHECK (sensitivity IN ('public','internal','restricted')),
 key_ref text NOT NULL,
 storage_region text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz,
 PRIMARY KEY (tenant_id, project_id, blob_id)
);
ALTER TABLE evidence_blobs_v35 ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_blobs_v35 FORCE ROW LEVEL SECURITY;
CREATE POLICY evidence_blobs_isolation_v35 ON evidence_blobs_v35
 USING (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid)
 WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid);

CREATE TABLE IF NOT EXISTS context_packets_v35 (
 tenant_id uuid NOT NULL,
 project_id uuid NOT NULL,
 packet_id uuid NOT NULL DEFAULT gen_random_uuid(),
 task_id uuid NOT NULL,
 role text NOT NULL,
 strategy text NOT NULL,
 policy_version text NOT NULL,
 repo_sha char(40) NOT NULL,
 manifest_sha256 char(64) NOT NULL,
 status text NOT NULL DEFAULT 'CREATED',
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (tenant_id, project_id, packet_id)
);
ALTER TABLE context_packets_v35 ENABLE ROW LEVEL SECURITY;
ALTER TABLE context_packets_v35 FORCE ROW LEVEL SECURITY;
CREATE POLICY context_packets_isolation_v35 ON context_packets_v35
 USING (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid)
 WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid);

CREATE TABLE IF NOT EXISTS context_packet_refs_v35 (
 tenant_id uuid NOT NULL,
 project_id uuid NOT NULL,
 packet_id uuid NOT NULL,
 blob_id uuid NOT NULL,
 selector text,
 requires_original boolean NOT NULL DEFAULT false,
 PRIMARY KEY (tenant_id, project_id, packet_id, blob_id),
 FOREIGN KEY (tenant_id, project_id, packet_id) REFERENCES context_packets_v35(tenant_id,project_id,packet_id),
 FOREIGN KEY (tenant_id, project_id, blob_id) REFERENCES evidence_blobs_v35(tenant_id,project_id,blob_id)
);
ALTER TABLE context_packet_refs_v35 ENABLE ROW LEVEL SECURITY;
ALTER TABLE context_packet_refs_v35 FORCE ROW LEVEL SECURITY;
CREATE POLICY context_packet_refs_isolation_v35 ON context_packet_refs_v35
 USING (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid)
 WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid);

CREATE TABLE IF NOT EXISTS evidence_reads_v35 (
 tenant_id uuid NOT NULL,
 project_id uuid NOT NULL,
 event_id uuid NOT NULL DEFAULT gen_random_uuid(),
 packet_id uuid NOT NULL,
 blob_id uuid NOT NULL,
 actor_id uuid NOT NULL,
 allow_access boolean NOT NULL,
 reason text,
 read_bytes bigint NOT NULL DEFAULT 0,
 occurred_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (tenant_id,project_id,event_id),
 FOREIGN KEY (tenant_id,project_id,packet_id,blob_id) REFERENCES context_packet_refs_v35(tenant_id,project_id,packet_id,blob_id)
);
ALTER TABLE evidence_reads_v35 ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_reads_v35 FORCE ROW LEVEL SECURITY;
CREATE POLICY evidence_reads_isolation_v35 ON evidence_reads_v35
 USING (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid)
 WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid);
-- Further controls: revoke direct table SELECT from customer roles, use authenticated gateway,
-- check project membership + evidence sensitivity + actor capability before every retrieval,
-- no cross-tenant dedupe, audit denied reads separately, include retention and delete workflows.
