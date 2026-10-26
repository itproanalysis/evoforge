-- EvoForge v3.6 Context Plane migration — DRAFT
-- Status: executed only against a throwaway PostgreSQL 16 instance by
--         context_plane_v3_6_tests.sql. NOT applied to any real environment.
-- Replaces legacy/v3.5_contracts/EvoForge_v3.5_Context_Plane_SQL_DRAFT.sql. Fixes (see review report):
--   F-SQL-1 denied reads could not be audited (FK to packet refs + RLS on victim tenant)
--   F-SQL-2 deletion (CR-17) impossible because of FK chain -> tombstone + crypto-shred
--   F-SQL-3 no idempotency (CR-21)              -> UNIQUE idempotency_key / request_id / provider_request_id
--   F-SQL-4 no CHECKs on role/strategy/status    -> closed vocab from contracts/vocabulary.v3.6.json
--   F-SQL-5 lossy item possible without stored original -> trigger enforces ORIGINAL_STORED
--   F-SQL-6 project isolation only in app code   -> RLS on tenant AND project
--   F-SQL-7 refs = blob ids (no expiry/revocation per grant) -> evidence_refs grant table
--   F-SQL-8 review "must read full diff" not checkable -> coverage from access log (range_agg)
-- Requires PostgreSQL >= 14 (multirange). Roles ctx_owner / ctx_gateway / ctx_security are created by infra.

BEGIN;

CREATE SCHEMA IF NOT EXISTS ctx AUTHORIZATION ctx_owner;
CREATE SCHEMA IF NOT EXISTS ctx_sec AUTHORIZATION ctx_owner;
SET LOCAL ROLE ctx_owner;

-- ---------------------------------------------------------------- session context
CREATE OR REPLACE FUNCTION ctx.current_tenant() RETURNS uuid
LANGUAGE sql STABLE AS $$ SELECT nullif(current_setting('app.tenant_id', true), '')::uuid $$;

CREATE OR REPLACE FUNCTION ctx.current_projects() RETURNS uuid[]
LANGUAGE sql STABLE AS $$
  SELECT coalesce(string_to_array(nullif(current_setting('app.project_ids', true), ''), ',')::uuid[], '{}'::uuid[])
$$;

-- ---------------------------------------------------------------- evidence blobs (metadata only; bytes live in encrypted object storage)
CREATE TABLE ctx.evidence_blobs (
  tenant_id             uuid        NOT NULL,
  project_id            uuid        NOT NULL,
  blob_id               uuid        NOT NULL DEFAULT gen_random_uuid(),
  sha256                char(64)    NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes            bigint      NOT NULL CHECK (size_bytes >= 0),
  source_kind           text        NOT NULL CHECK (source_kind IN ('contract.goal','contract.policy','contract.acceptance','git.diff','git.blob','test.junit','test.jest','log.text','json.api','policy.result','html','table','search','other')),
  trust                 text        NOT NULL CHECK (trust IN ('trusted_contract','verified_tool_output','untrusted_content')),
  sensitivity           text        NOT NULL CHECK (sensitivity IN ('public','internal','restricted')),
  storage_region        text        NOT NULL,
  object_storage_key    text,
  dek_ref               text,       -- per-blob data key (envelope encryption under tenant KEK); destroying it = crypto-shred incl. backups
  state                 text        NOT NULL DEFAULT 'PENDING' CHECK (state IN ('PENDING','ACTIVE','SHREDDED')),
  read_back_verified_at timestamptz,
  retention_until       timestamptz,
  legal_hold            boolean     NOT NULL DEFAULT false,
  created_at            timestamptz NOT NULL DEFAULT now(),
  shredded_at           timestamptz,
  PRIMARY KEY (tenant_id, project_id, blob_id),
  CONSTRAINT blob_active_has_object CHECK (state <> 'ACTIVE' OR (object_storage_key IS NOT NULL AND dek_ref IS NOT NULL AND read_back_verified_at IS NOT NULL)),
  CONSTRAINT blob_shredded_is_empty CHECK (state <> 'SHREDDED' OR (object_storage_key IS NULL AND dek_ref IS NULL AND shredded_at IS NOT NULL)),
  CONSTRAINT blob_contract_trust CHECK ((trust = 'trusted_contract') = (source_kind LIKE 'contract.%'))
);
-- intentionally NO unique index on sha256 (no cross-tenant or cross-project dedupe => no existence oracle)

-- ---------------------------------------------------------------- context packets
CREATE TABLE ctx.context_packets (
  tenant_id              uuid        NOT NULL,
  project_id             uuid        NOT NULL,
  packet_id              uuid        NOT NULL DEFAULT gen_random_uuid(),
  run_id                 uuid        NOT NULL,
  task_id                uuid        NOT NULL,
  task_attempt_id        uuid        NOT NULL,
  idempotency_key        text        NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{16,128}$'),
  seat_id                smallint    NOT NULL CHECK (seat_id BETWEEN 1 AND 5),
  function_role          text        NOT NULL CHECK (function_role IN ('planner','builder','critic','verifier','integrator','observer')),
  agent_id               uuid        NOT NULL,
  candidate_id           uuid,
  is_author_of_candidate boolean     NOT NULL,
  channel                text        NOT NULL CHECK (channel IN ('api','mcp','folder','a2a','chat')),
  profile                text        NOT NULL CHECK (profile IN ('SAFE','BALANCED','MAXIMUM')),
  experiment_arm         text        CHECK (experiment_arm IN ('A0_RAW_NOCACHE','A_RAW','B_STRUCTURAL','C_RECOVERABLE','D_RAW_EXPLICIT_CACHE','E_CACHE_AWARE')),
  repo_sha               text        NOT NULL CHECK (repo_sha ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'),
  contract_version       integer     NOT NULL CHECK (contract_version >= 1),
  policy_version         text        NOT NULL,
  policy_hash            char(64)    NOT NULL CHECK (policy_hash ~ '^[0-9a-f]{64}$'),
  tool_schema_hash       char(64)    NOT NULL CHECK (tool_schema_hash ~ '^[0-9a-f]{64}$'),
  evidence_manifest_hash char(64)    NOT NULL CHECK (evidence_manifest_hash ~ '^[0-9a-f]{64}$'),
  lease_epoch            bigint      NOT NULL CHECK (lease_epoch >= 0),
  provider               text        NOT NULL CHECK (provider IN ('openai','anthropic','google','meta','other')),
  model                  text        NOT NULL,
  cache_mode             text        NOT NULL CHECK (cache_mode IN ('NONE','PROVIDER_IMPLICIT','PROVIDER_EXPLICIT')),
  packet_sha256          char(64)    NOT NULL CHECK (packet_sha256 ~ '^[0-9a-f]{64}$'),
  status                 text        NOT NULL DEFAULT 'ISSUED' CHECK (status IN ('ISSUED','STALE','SUPERSEDED','REVOKED')),
  status_reason          text,
  supersedes_packet_id   uuid,
  issued_at              timestamptz NOT NULL DEFAULT now(),
  expires_at             timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, packet_id),
  UNIQUE (tenant_id, project_id, idempotency_key),
  FOREIGN KEY (tenant_id, project_id, supersedes_packet_id) REFERENCES ctx.context_packets (tenant_id, project_id, packet_id),
  CONSTRAINT packet_expiry_after_issue CHECK (expires_at > issued_at),
  CONSTRAINT packet_reviewer_not_author CHECK (function_role NOT IN ('critic','verifier') OR (is_author_of_candidate = false AND candidate_id IS NOT NULL)),
  CONSTRAINT packet_reviewer_channel CHECK (function_role NOT IN ('critic','verifier') OR channel <> 'chat'),
  CONSTRAINT packet_status_reason CHECK (status = 'ISSUED' OR status_reason IS NOT NULL)
);
CREATE INDEX context_packets_task_idx ON ctx.context_packets (tenant_id, project_id, task_id, status);

-- ---------------------------------------------------------------- evidence refs = per-packet grants (opaque, random, expiring, revocable)
CREATE TABLE ctx.evidence_refs (
  ref               text        PRIMARY KEY CHECK (ref ~ '^evr_[0-9a-hjkmnp-tv-z]{26}$'),
  tenant_id         uuid        NOT NULL,
  project_id        uuid        NOT NULL,
  packet_id         uuid        NOT NULL,
  blob_id           uuid        NOT NULL,
  requires_original boolean     NOT NULL,
  selector_scope    text        NOT NULL DEFAULT 'all',
  expires_at        timestamptz NOT NULL,
  revoked_at        timestamptz,
  revoke_reason     text,
  UNIQUE (tenant_id, project_id, packet_id, blob_id),
  UNIQUE (tenant_id, project_id, packet_id, ref),
  FOREIGN KEY (tenant_id, project_id, packet_id) REFERENCES ctx.context_packets (tenant_id, project_id, packet_id),
  FOREIGN KEY (tenant_id, project_id, blob_id)   REFERENCES ctx.evidence_blobs (tenant_id, project_id, blob_id),
  CONSTRAINT ref_revoke_reason CHECK (revoked_at IS NULL OR revoke_reason IS NOT NULL)
);

-- ---------------------------------------------------------------- packet items (fidelity decided per item)
CREATE TABLE ctx.context_items (
  tenant_id        uuid     NOT NULL,
  project_id       uuid     NOT NULL,
  packet_id        uuid     NOT NULL,
  item_id          text     NOT NULL CHECK (item_id ~ '^it_[0-9a-z]{4,32}$'),
  ref              text     NOT NULL,
  fidelity         text     NOT NULL CHECK (fidelity IN ('RAW','STRUCTURAL','RECOVERABLE','REF_ONLY')),
  raw_reason       text     CHECK (raw_reason IN ('POLICY_REQUIRED','UNSUPPORTED_TYPE','PARSE_FAILED','NO_TOKEN_GAIN','FIDELITY_FAILED','VAULT_UNAVAILABLE','NET_COST_WORSE','PROFILE_DISABLED','USER_OVERRIDE')),
  codec_name       text,
  codec_version    text     CHECK (codec_version IS NULL OR codec_version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
  fidelity_passed  boolean,
  view_sha256      char(64) NOT NULL CHECK (view_sha256 ~ '^[0-9a-f]{64}$'),
  view_tokens_est  integer  NOT NULL CHECK (view_tokens_est >= 0),
  segment_index    integer  NOT NULL CHECK (segment_index >= 0),
  PRIMARY KEY (tenant_id, project_id, packet_id, item_id),
  UNIQUE (tenant_id, project_id, packet_id, ref),
  FOREIGN KEY (tenant_id, project_id, packet_id, ref) REFERENCES ctx.evidence_refs (tenant_id, project_id, packet_id, ref),
  CONSTRAINT item_raw_has_reason   CHECK ((fidelity = 'RAW') = (raw_reason IS NOT NULL)),
  CONSTRAINT item_lossy_has_codec  CHECK (fidelity NOT IN ('STRUCTURAL','RECOVERABLE') OR (codec_name IS NOT NULL AND codec_version IS NOT NULL AND fidelity_passed IS TRUE)),
  CONSTRAINT item_nonlossy_no_codec CHECK (fidelity IN ('STRUCTURAL','RECOVERABLE') OR (codec_name IS NULL AND codec_version IS NULL))
);

-- Invariant ORIGINAL_STORED (spec §5): no STRUCTURAL/RECOVERABLE view without an ACTIVE (stored + read-back-verified) original.
-- Approval-grade packets (critic/verifier) need ACTIVE originals for every requires_original ref, even when RAW.
-- Contracts are always RAW/POLICY_REQUIRED.
CREATE OR REPLACE FUNCTION ctx.enforce_item_invariants() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  b ctx.evidence_blobs%ROWTYPE;
  r ctx.evidence_refs%ROWTYPE;
  p ctx.context_packets%ROWTYPE;
BEGIN
  SELECT * INTO r FROM ctx.evidence_refs WHERE ref = NEW.ref;
  SELECT * INTO b FROM ctx.evidence_blobs WHERE tenant_id = r.tenant_id AND project_id = r.project_id AND blob_id = r.blob_id;
  SELECT * INTO p FROM ctx.context_packets WHERE tenant_id = NEW.tenant_id AND project_id = NEW.project_id AND packet_id = NEW.packet_id;
  IF NEW.fidelity IN ('STRUCTURAL','RECOVERABLE') AND b.state <> 'ACTIVE' THEN
    RAISE EXCEPTION 'ORIGINAL_STORED violated: lossy item % on blob in state %', NEW.item_id, b.state USING ERRCODE = 'check_violation';
  END IF;
  IF p.function_role IN ('critic','verifier') AND r.requires_original AND b.state <> 'ACTIVE' THEN
    RAISE EXCEPTION 'approval-grade evidence % has no ACTIVE original', NEW.item_id USING ERRCODE = 'check_violation';
  END IF;
  IF p.function_role IN ('critic','verifier') AND b.source_kind IN ('git.diff','policy.result','test.junit','test.jest') AND NOT r.requires_original THEN
    RAISE EXCEPTION 'reviewer packet must mark % (%) requires_original', NEW.item_id, b.source_kind USING ERRCODE = 'check_violation';
  END IF;
  IF b.source_kind LIKE 'contract.%' AND (NEW.fidelity <> 'RAW' OR NEW.raw_reason <> 'POLICY_REQUIRED') THEN
    RAISE EXCEPTION 'contract item % must be RAW/POLICY_REQUIRED', NEW.item_id USING ERRCODE = 'check_violation';
  END IF;
  IF b.state = 'SHREDDED' THEN
    RAISE EXCEPTION 'blob shredded' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER context_items_invariants BEFORE INSERT OR UPDATE ON ctx.context_items
  FOR EACH ROW EXECUTE FUNCTION ctx.enforce_item_invariants();

-- ---------------------------------------------------------------- state machines
CREATE OR REPLACE FUNCTION ctx.enforce_blob_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.sha256 <> OLD.sha256 OR NEW.size_bytes <> OLD.size_bytes OR NEW.tenant_id <> OLD.tenant_id OR NEW.project_id <> OLD.project_id THEN
    RAISE EXCEPTION 'blob identity is immutable' USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.state <> NEW.state AND NOT ((OLD.state, NEW.state) IN (('PENDING','ACTIVE'), ('PENDING','SHREDDED'), ('ACTIVE','SHREDDED'))) THEN
    RAISE EXCEPTION 'illegal blob transition % -> %', OLD.state, NEW.state USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.state = 'SHREDDED' AND OLD.state <> 'SHREDDED' AND OLD.legal_hold THEN
    RAISE EXCEPTION 'blob under legal hold' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER evidence_blobs_transition BEFORE UPDATE ON ctx.evidence_blobs
  FOR EACH ROW EXECUTE FUNCTION ctx.enforce_blob_transition();

CREATE OR REPLACE FUNCTION ctx.enforce_packet_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF (to_jsonb(NEW) - 'status' - 'status_reason') <> (to_jsonb(OLD) - 'status' - 'status_reason') THEN
    RAISE EXCEPTION 'packet body is immutable; issue a new packet that supersedes it' USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.status <> NEW.status AND NOT ((OLD.status, NEW.status) IN
       (('ISSUED','STALE'), ('ISSUED','SUPERSEDED'), ('ISSUED','REVOKED'), ('STALE','SUPERSEDED'), ('STALE','REVOKED'))) THEN
    RAISE EXCEPTION 'illegal packet transition % -> %', OLD.status, NEW.status USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER context_packets_transition BEFORE UPDATE ON ctx.context_packets
  FOR EACH ROW EXECUTE FUNCTION ctx.enforce_packet_transition();

-- ---------------------------------------------------------------- access log (append-only, NO foreign keys: must record denials for unknown/foreign refs)
CREATE TABLE ctx.evidence_access_log (
  actor_tenant_id  uuid        NOT NULL,
  event_id         uuid        NOT NULL DEFAULT gen_random_uuid(),
  actor_project_id uuid,
  actor_id         uuid        NOT NULL,
  request_id       text        NOT NULL CHECK (request_id ~ '^[A-Za-z0-9._:-]{16,128}$'),
  requested_ref    text        NOT NULL CHECK (length(requested_ref) <= 64),
  claimed_packet_id uuid,
  resolved_blob_id uuid,      -- set only when the ref resolved inside the actor's own tenant
  decision         text        NOT NULL CHECK (decision IN ('ALLOW','DENY_NOT_FOUND','DENY_FORBIDDEN','DENY_EXPIRED','DENY_STALE','DENY_DIGEST','DENY_RATE','DENY_SHREDDED')),
  reason           text        NOT NULL CHECK (reason IN ('review_coverage','builder_context','verification','user_request')),
  range_start      bigint,
  range_end        bigint,
  trace_id         text        NOT NULL,
  occurred_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (actor_tenant_id, event_id),
  UNIQUE (actor_tenant_id, request_id),
  CONSTRAINT access_allow_has_range CHECK (decision <> 'ALLOW' OR (resolved_blob_id IS NOT NULL AND range_start IS NOT NULL AND range_end > range_start AND range_start >= 0))
);

CREATE OR REPLACE FUNCTION ctx.forbid_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege'; END $$;
CREATE TRIGGER evidence_access_log_append_only BEFORE UPDATE OR DELETE ON ctx.evidence_access_log
  FOR EACH ROW EXECUTE FUNCTION ctx.forbid_mutation();

-- platform-level record of cross-tenant / unknown-ref probes (not visible to any tenant)
CREATE TABLE ctx_sec.security_events (
  event_id        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  kind            text        NOT NULL CHECK (kind IN ('UNKNOWN_REF_PROBE','CROSS_TENANT_REF','SELECTOR_REJECTED','RATE_ABUSE','CACHE_NAMESPACE_MISMATCH')),
  actor_tenant_id uuid        NOT NULL,
  actor_id        uuid        NOT NULL,
  requested_ref   text        CHECK (length(requested_ref) <= 64),
  trace_id        text        NOT NULL,
  occurred_at     timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER security_events_append_only BEFORE UPDATE OR DELETE ON ctx_sec.security_events
  FOR EACH ROW EXECUTE FUNCTION ctx.forbid_mutation();

-- ---------------------------------------------------------------- provider usage receipts (money in integer micro-units)
CREATE TABLE ctx.provider_usage_receipts (
  tenant_id           uuid        NOT NULL,
  project_id          uuid        NOT NULL,
  receipt_id          uuid        NOT NULL DEFAULT gen_random_uuid(),
  packet_id           uuid        NOT NULL,
  call_id             uuid        NOT NULL,
  call_purpose        text        NOT NULL CHECK (call_purpose IN ('task_turn','retrieval_turn','review_chunk','review_cross_chunk','rerun','probe')),
  provider            text        NOT NULL CHECK (provider IN ('openai','anthropic','google','meta','other')),
  model               text        NOT NULL,
  provider_request_id text,
  source              text        NOT NULL CHECK (source IN ('provider_billed','estimated')),
  billing_owner       text        NOT NULL CHECK (billing_owner IN ('byok_customer','platform')),
  uncached_input      bigint      NOT NULL CHECK (uncached_input >= 0),
  cache_write         bigint      NOT NULL CHECK (cache_write >= 0),
  cache_write_ttl     text,
  cache_read          bigint      NOT NULL CHECK (cache_read >= 0),
  output_tokens       bigint      NOT NULL CHECK (output_tokens >= 0),
  raw_usage_fields    jsonb,
  cost_micros         bigint      NOT NULL CHECK (cost_micros >= 0),
  currency            char(3)     NOT NULL DEFAULT 'USD' CHECK (currency = 'USD'),
  price_table_version text        NOT NULL,
  recorded_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, project_id, receipt_id),
  UNIQUE (tenant_id, provider, provider_request_id),
  FOREIGN KEY (tenant_id, project_id, packet_id) REFERENCES ctx.context_packets (tenant_id, project_id, packet_id),
  CONSTRAINT receipt_billed_has_request CHECK (source <> 'provider_billed' OR (provider_request_id IS NOT NULL AND raw_usage_fields IS NOT NULL))
);

-- ---------------------------------------------------------------- codec profiles (platform-managed; auto-disable target)
CREATE TABLE ctx.codec_profile_state (
  source_kind   text        NOT NULL,
  codec_name    text        NOT NULL,
  codec_version text        NOT NULL,
  provider      text        NOT NULL DEFAULT '*',
  state         text        NOT NULL CHECK (state IN ('ENABLED','DISABLED')),
  reason        text        NOT NULL,
  changed_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_kind, codec_name, codec_version, provider)
);

-- ---------------------------------------------------------------- review coverage (spec §8): bytes actually delivered to the reviewer
CREATE OR REPLACE FUNCTION ctx.review_coverage(p_tenant uuid, p_project uuid, p_packet uuid)
RETURNS TABLE (ref text, size_bytes bigint, covered_bytes bigint, complete boolean)
LANGUAGE sql STABLE AS $$
  WITH pk AS (
    SELECT * FROM ctx.context_packets WHERE tenant_id = p_tenant AND project_id = p_project AND packet_id = p_packet
  ), req AS (
    SELECT r.ref, b.size_bytes, i.fidelity
    FROM ctx.evidence_refs r
    JOIN pk ON pk.tenant_id = r.tenant_id AND pk.project_id = r.project_id AND pk.packet_id = r.packet_id
    JOIN ctx.evidence_blobs b ON b.tenant_id = r.tenant_id AND b.project_id = r.project_id AND b.blob_id = r.blob_id
    LEFT JOIN ctx.context_items i ON i.tenant_id = r.tenant_id AND i.project_id = r.project_id AND i.packet_id = r.packet_id AND i.ref = r.ref
    WHERE r.requires_original
  ), got AS (
    SELECT l.requested_ref AS ref, range_agg(int8range(l.range_start, l.range_end)) AS mr
    FROM ctx.evidence_access_log l, pk
    WHERE l.actor_tenant_id = pk.tenant_id AND l.actor_id = pk.agent_id AND l.decision = 'ALLOW'
      AND l.claimed_packet_id = pk.packet_id AND l.occurred_at >= pk.issued_at
    GROUP BY l.requested_ref
  )
  SELECT req.ref,
         req.size_bytes,
         CASE WHEN req.fidelity = 'RAW' THEN req.size_bytes
              ELSE coalesce((SELECT sum(upper(x) - lower(x)) FROM unnest(got.mr * int8multirange(int8range(0, req.size_bytes))) x), 0)::bigint END,
         (req.fidelity = 'RAW') OR req.size_bytes = 0 OR coalesce(got.mr @> int8range(0, req.size_bytes), false)
  FROM req LEFT JOIN got ON got.ref = req.ref
$$;

-- Gate used by submit_review(verdict='approve'): raises unless every requires_original ref is fully delivered,
-- the packet is ISSUED and unexpired, the reviewer is not the author, and the packet is pinned to the candidate head SHA.
CREATE OR REPLACE FUNCTION ctx.assert_review_gate(p_tenant uuid, p_project uuid, p_packet uuid, p_candidate_head_sha text)
RETURNS void LANGUAGE plpgsql STABLE AS $$
DECLARE
  p ctx.context_packets%ROWTYPE;
  missing text;
BEGIN
  SELECT * INTO p FROM ctx.context_packets WHERE tenant_id = p_tenant AND project_id = p_project AND packet_id = p_packet;
  IF NOT FOUND THEN RAISE EXCEPTION 'review gate: packet not found' USING ERRCODE = 'no_data_found'; END IF;
  IF p.function_role NOT IN ('critic','verifier') THEN RAISE EXCEPTION 'review gate: % cannot approve', p.function_role USING ERRCODE = 'insufficient_privilege'; END IF;
  IF p.status <> 'ISSUED' THEN RAISE EXCEPTION 'review gate: packet %', p.status USING ERRCODE = 'check_violation'; END IF;
  IF p.expires_at <= now() THEN RAISE EXCEPTION 'review gate: packet expired' USING ERRCODE = 'check_violation'; END IF;
  IF p.repo_sha <> p_candidate_head_sha THEN RAISE EXCEPTION 'review gate: packet pinned to %, candidate head is %', p.repo_sha, p_candidate_head_sha USING ERRCODE = 'check_violation'; END IF;
  SELECT string_agg(c.ref || ' ' || c.covered_bytes || '/' || c.size_bytes, ', ') INTO missing
  FROM ctx.review_coverage(p_tenant, p_project, p_packet) c WHERE NOT c.complete;
  IF missing IS NOT NULL THEN RAISE EXCEPTION 'review gate: incomplete original coverage: %', missing USING ERRCODE = 'check_violation'; END IF;
END $$;

-- Context fencing (blueprint p.29): any change of goal/policy/base SHA marks live packets of the task STALE.
CREATE OR REPLACE FUNCTION ctx.mark_task_packets_stale(p_tenant uuid, p_project uuid, p_task uuid, p_reason text)
RETURNS integer LANGUAGE sql AS $$
  WITH u AS (
    UPDATE ctx.context_packets SET status = 'STALE', status_reason = p_reason
    WHERE tenant_id = p_tenant AND project_id = p_project AND task_id = p_task AND status = 'ISSUED'
    RETURNING 1
  ) SELECT count(*)::integer FROM u
$$;

-- Deletion (CR-17): tombstone + crypto-shred. Returns the object key and DEK ref the worker must destroy.
CREATE OR REPLACE FUNCTION ctx.shred_blob(p_tenant uuid, p_project uuid, p_blob uuid, OUT object_storage_key text, OUT dek_ref text)
LANGUAGE plpgsql AS $$
BEGIN
  SELECT b.object_storage_key, b.dek_ref INTO object_storage_key, dek_ref
  FROM ctx.evidence_blobs b WHERE b.tenant_id = p_tenant AND b.project_id = p_project AND b.blob_id = p_blob FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'blob not found' USING ERRCODE = 'no_data_found'; END IF;
  UPDATE ctx.evidence_blobs b SET state = 'SHREDDED', object_storage_key = NULL, dek_ref = NULL, shredded_at = now()
  WHERE b.tenant_id = p_tenant AND b.project_id = p_project AND b.blob_id = p_blob;
  UPDATE ctx.evidence_refs r SET revoked_at = now(), revoke_reason = 'evidence_shredded'
  WHERE r.tenant_id = p_tenant AND r.project_id = p_project AND r.blob_id = p_blob AND r.revoked_at IS NULL;
  UPDATE ctx.context_packets p SET status = 'REVOKED', status_reason = 'evidence_shredded'
  WHERE p.tenant_id = p_tenant AND p.project_id = p_project AND p.status IN ('ISSUED','STALE')
    AND EXISTS (SELECT 1 FROM ctx.evidence_refs r WHERE r.tenant_id = p.tenant_id AND r.project_id = p.project_id AND r.packet_id = p.packet_id AND r.blob_id = p_blob);
END $$;

-- ---------------------------------------------------------------- RLS: tenant AND project
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['evidence_blobs','context_packets','evidence_refs','context_items','provider_usage_receipts'] LOOP
    EXECUTE format('ALTER TABLE ctx.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE ctx.%I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format($p$CREATE POLICY %I ON ctx.%I
                      USING (tenant_id = ctx.current_tenant() AND project_id = ANY (ctx.current_projects()))
                      WITH CHECK (tenant_id = ctx.current_tenant() AND project_id = ANY (ctx.current_projects()))$p$, t || '_isolation', t);
  END LOOP;
END $$;
ALTER TABLE ctx.evidence_access_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE ctx.evidence_access_log FORCE ROW LEVEL SECURITY;
CREATE POLICY evidence_access_log_isolation ON ctx.evidence_access_log
  USING (actor_tenant_id = ctx.current_tenant()) WITH CHECK (actor_tenant_id = ctx.current_tenant());

-- ---------------------------------------------------------------- grants (no DELETE anywhere; deletion = shred_blob)
REVOKE ALL ON ALL TABLES IN SCHEMA ctx FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA ctx_sec FROM PUBLIC;
GRANT USAGE ON SCHEMA ctx TO ctx_gateway, ctx_security;
GRANT USAGE ON SCHEMA ctx_sec TO ctx_gateway, ctx_security;
GRANT SELECT, INSERT ON ctx.evidence_blobs, ctx.context_packets, ctx.evidence_refs, ctx.context_items, ctx.provider_usage_receipts TO ctx_gateway;
GRANT UPDATE (state, object_storage_key, dek_ref, read_back_verified_at, shredded_at) ON ctx.evidence_blobs TO ctx_gateway;
GRANT UPDATE (status, status_reason) ON ctx.context_packets TO ctx_gateway;
GRANT UPDATE (revoked_at, revoke_reason) ON ctx.evidence_refs TO ctx_gateway;
GRANT SELECT, INSERT ON ctx.evidence_access_log TO ctx_gateway;
GRANT SELECT ON ctx.codec_profile_state TO ctx_gateway;
GRANT INSERT ON ctx_sec.security_events TO ctx_gateway;
GRANT SELECT ON ctx_sec.security_events TO ctx_security;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA ctx TO ctx_gateway;

COMMIT;
