-- EvoForge v3.6 Context Plane — executable tests for context_plane_v3_6_DRAFT.sql
-- Run on a THROWAWAY database as a superuser:
--   psql -v ON_ERROR_STOP=1 -f 00_roles (inline below) -f context_plane_v3_6_DRAFT.sql -f context_plane_v3_6_tests.sql
-- Every check raises on failure; the script ends with 'ALL CONTEXT PLANE TESTS PASSED'.
\set ON_ERROR_STOP 1
SET client_min_messages = notice;

CREATE SCHEMA t;
CREATE FUNCTION t.ok(cond boolean, label text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN IF cond IS NOT TRUE THEN RAISE EXCEPTION 'FAIL: %', label; END IF; RAISE NOTICE 'ok  %', label; END $$;
CREATE FUNCTION t.fails(stmt text, pattern text, label text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  BEGIN EXECUTE stmt;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM ~* pattern THEN RAISE NOTICE 'ok  % (%)', label, SQLERRM; RETURN; END IF;
    RAISE EXCEPTION 'FAIL: % raised unexpected error: %', label, SQLERRM;
  END;
  RAISE EXCEPTION 'FAIL: % did not raise', label;
END $$;
CREATE FUNCTION t.new_ref() RETURNS text LANGUAGE sql VOLATILE AS $$
  SELECT 'evr_' || string_agg(substr('0123456789abcdefghjkmnpqrstvwxyz', 1 + floor(random() * 32)::int, 1), '') FROM generate_series(1, 26)
$$;
CREATE FUNCTION t.as_tenant(tenant uuid, projects text) RETURNS void LANGUAGE sql AS $$
  SELECT set_config('app.tenant_id', tenant::text, false), set_config('app.project_ids', projects, false);
$$;
GRANT USAGE ON SCHEMA t TO ctx_gateway, ctx_security;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA t TO ctx_gateway, ctx_security;
CREATE TABLE t.ids (k text PRIMARY KEY, v text NOT NULL);
GRANT SELECT, INSERT ON t.ids TO ctx_gateway;
CREATE FUNCTION t.id(key text) RETURNS text LANGUAGE sql STABLE AS $$ SELECT v FROM t.ids WHERE k = key $$;

-- fixed identities
INSERT INTO t.ids VALUES
 ('A',  '0000000a-0000-4000-8000-000000000000'), ('B',  '0000000b-0000-4000-8000-000000000000'),
 ('A1', '0000000a-0001-4000-8000-000000000000'), ('A2', '0000000a-0002-4000-8000-000000000000'),
 ('B1', '0000000b-0001-4000-8000-000000000000'),
 ('critic_agent', '00000004-0000-4000-8000-000000000000'), ('builder_agent', '00000002-0000-4000-8000-000000000000'),
 ('cand', '0000c000-0000-4000-8000-000000000000'), ('task', '0000d000-0000-4000-8000-000000000000'),
 ('head', repeat('ab', 20)), ('diff_blob', '0000b000-0000-4000-8000-000000000001'), ('log_blob', '0000b000-0000-4000-8000-000000000002'),
 ('goal_blob', '0000b000-0000-4000-8000-000000000003'), ('critic_pkt', '0000e000-0000-4000-8000-000000000001'),
 ('builder_pkt', '0000e000-0000-4000-8000-000000000002');
INSERT INTO t.ids SELECT 'ref_' || n, t.new_ref() FROM unnest(ARRAY['diff','log','goal','b_log','b_goal']) n;

SET ROLE ctx_gateway;
SELECT t.as_tenant(t.id('A')::uuid, t.id('A1'));

-- ---------------------------------------------------------------- fixtures for tenant A / project A1
INSERT INTO ctx.evidence_blobs (tenant_id, project_id, blob_id, sha256, size_bytes, source_kind, trust, sensitivity, storage_region)
VALUES (t.id('A')::uuid, t.id('A1')::uuid, t.id('diff_blob')::uuid, repeat('1', 64), 1000, 'git.diff',     'verified_tool_output', 'restricted', 'kr-1'),
       (t.id('A')::uuid, t.id('A1')::uuid, t.id('log_blob')::uuid,  repeat('2', 64), 50000, 'test.junit',  'verified_tool_output', 'internal',   'kr-1'),
       (t.id('A')::uuid, t.id('A1')::uuid, t.id('goal_blob')::uuid, repeat('3', 64), 800,  'contract.goal', 'trusted_contract',   'internal',   'kr-1');

INSERT INTO ctx.context_packets (tenant_id, project_id, packet_id, run_id, task_id, task_attempt_id, idempotency_key, seat_id, function_role, agent_id,
  candidate_id, is_author_of_candidate, channel, profile, repo_sha, contract_version, policy_version, policy_hash, tool_schema_hash, evidence_manifest_hash,
  lease_epoch, provider, model, cache_mode, packet_sha256, expires_at)
VALUES
 (t.id('A')::uuid, t.id('A1')::uuid, t.id('critic_pkt')::uuid, gen_random_uuid(), t.id('task')::uuid, gen_random_uuid(), 'task-d000:attempt-1:seat-4:v1',
  4, 'critic', t.id('critic_agent')::uuid, t.id('cand')::uuid, false, 'mcp', 'SAFE', t.id('head'), 3, 'policy-7', repeat('4',64), repeat('5',64), repeat('6',64),
  12, 'anthropic', 'claude-opus-5-5', 'PROVIDER_EXPLICIT', repeat('7',64), now() + interval '1 hour'),
 (t.id('A')::uuid, t.id('A1')::uuid, t.id('builder_pkt')::uuid, gen_random_uuid(), t.id('task')::uuid, gen_random_uuid(), 'task-d000:attempt-1:seat-2:v1',
  2, 'builder', t.id('builder_agent')::uuid, t.id('cand')::uuid, true, 'api', 'SAFE', t.id('head'), 3, 'policy-7', repeat('4',64), repeat('5',64), repeat('6',64),
  12, 'openai', 'gpt-5.6', 'PROVIDER_IMPLICIT', repeat('8',64), now() + interval '1 hour');

INSERT INTO ctx.evidence_refs (ref, tenant_id, project_id, packet_id, blob_id, requires_original, expires_at) VALUES
 (t.id('ref_diff'), t.id('A')::uuid, t.id('A1')::uuid, t.id('critic_pkt')::uuid, t.id('diff_blob')::uuid, true,  now() + interval '1 hour'),
 (t.id('ref_log'),  t.id('A')::uuid, t.id('A1')::uuid, t.id('critic_pkt')::uuid, t.id('log_blob')::uuid,  true,  now() + interval '1 hour'),
 (t.id('ref_goal'), t.id('A')::uuid, t.id('A1')::uuid, t.id('critic_pkt')::uuid, t.id('goal_blob')::uuid, true,  now() + interval '1 hour'),
 (t.id('ref_b_log'),  t.id('A')::uuid, t.id('A1')::uuid, t.id('builder_pkt')::uuid, t.id('log_blob')::uuid, false, now() + interval '1 hour'),
 (t.id('ref_b_goal'), t.id('A')::uuid, t.id('A1')::uuid, t.id('builder_pkt')::uuid, t.id('goal_blob')::uuid, true, now() + interval '1 hour');

-- ---------------------------------------------------------------- T04/T05 ORIGINAL_STORED + item shape
SELECT t.fails($$INSERT INTO ctx.context_items VALUES ('$$ || t.id('A') || $$','$$ || t.id('A1') || $$','$$ || t.id('builder_pkt') || $$','it_blog1','$$ || t.id('ref_b_log') || $$',
  'STRUCTURAL',NULL,'junit.structural','1.1.0',true,repeat('9',64),200,3)$$, 'ORIGINAL_STORED', 'T04 lossy view on PENDING blob rejected (CR-02)');

UPDATE ctx.evidence_blobs SET state = 'ACTIVE', object_storage_key = 's3://vault/a/a1/' || blob_id, dek_ref = 'kms://dek/' || blob_id, read_back_verified_at = now()
 WHERE blob_id IN (t.id('diff_blob')::uuid, t.id('log_blob')::uuid, t.id('goal_blob')::uuid);

SELECT t.fails($$INSERT INTO ctx.context_items VALUES ('$$ || t.id('A') || $$','$$ || t.id('A1') || $$','$$ || t.id('builder_pkt') || $$','it_blog1','$$ || t.id('ref_b_log') || $$',
  'STRUCTURAL',NULL,'junit.structural','1.1.0',NULL,repeat('9',64),200,3)$$, 'item_lossy_has_codec', 'T05 lossy view without passed fidelity gate rejected');
SELECT t.fails($$INSERT INTO ctx.context_items VALUES ('$$ || t.id('A') || $$','$$ || t.id('A1') || $$','$$ || t.id('builder_pkt') || $$','it_blog1','$$ || t.id('ref_b_log') || $$',
  'RAW',NULL,NULL,NULL,NULL,repeat('9',64),200,3)$$, 'item_raw_has_reason', 'T05 RAW without raw_reason rejected');

INSERT INTO ctx.context_items VALUES (t.id('A')::uuid, t.id('A1')::uuid, t.id('builder_pkt')::uuid, 'it_blog1', t.id('ref_b_log'),
  'STRUCTURAL', NULL, 'junit.structural', '1.1.0', true, repeat('9',64), 200, 3);
SELECT t.ok(true, 'T04 lossy view accepted once original is ACTIVE');

-- ---------------------------------------------------------------- T06 contracts are never summarized
SELECT t.fails($$INSERT INTO ctx.context_items VALUES ('$$ || t.id('A') || $$','$$ || t.id('A1') || $$','$$ || t.id('builder_pkt') || $$','it_bgoal','$$ || t.id('ref_b_goal') || $$',
  'RECOVERABLE',NULL,'text.summary','1.0.0',true,repeat('9',64),50,1)$$, 'contract item', 'T06 summarized contract rejected');
INSERT INTO ctx.context_items VALUES (t.id('A')::uuid, t.id('A1')::uuid, t.id('builder_pkt')::uuid, 'it_bgoal', t.id('ref_b_goal'),
  'RAW', 'POLICY_REQUIRED', NULL, NULL, NULL, repeat('9',64), 200, 1);

-- ---------------------------------------------------------------- T07/T08 reviewer packet rules
SELECT t.fails($$INSERT INTO ctx.context_packets (tenant_id, project_id, run_id, task_id, task_attempt_id, idempotency_key, seat_id, function_role, agent_id,
  candidate_id, is_author_of_candidate, channel, profile, repo_sha, contract_version, policy_version, policy_hash, tool_schema_hash, evidence_manifest_hash,
  lease_epoch, provider, model, cache_mode, packet_sha256, expires_at)
  VALUES ('$$ || t.id('A') || $$','$$ || t.id('A1') || $$',gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),'author-reviews-own-candidate-1',2,'critic',gen_random_uuid(),
  gen_random_uuid(),true,'api','SAFE',repeat('a',40),1,'p',repeat('4',64),repeat('5',64),repeat('6',64),0,'openai','gpt-5.6','NONE',repeat('7',64),now()+interval '1h')$$,
  'packet_reviewer_not_author', 'T07 author cannot receive a reviewer packet');
SELECT t.fails($$INSERT INTO ctx.context_packets (tenant_id, project_id, run_id, task_id, task_attempt_id, idempotency_key, seat_id, function_role, agent_id,
  candidate_id, is_author_of_candidate, channel, profile, repo_sha, contract_version, policy_version, policy_hash, tool_schema_hash, evidence_manifest_hash,
  lease_epoch, provider, model, cache_mode, packet_sha256, expires_at)
  VALUES ('$$ || t.id('A') || $$','$$ || t.id('A1') || $$',gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),'chat-session-as-approver-1',4,'critic',gen_random_uuid(),
  gen_random_uuid(),false,'chat','SAFE',repeat('a',40),1,'p',repeat('4',64),repeat('5',64),repeat('6',64),0,'openai','gpt-5.6','NONE',repeat('7',64),now()+interval '1h')$$,
  'packet_reviewer_channel', 'T07 chat channel cannot be an approver (CR-14)');

-- critic packet items: diff as STRUCTURAL entry view (original must be retrieved), log RAW, goal RAW
INSERT INTO ctx.context_items VALUES
 (t.id('A')::uuid, t.id('A1')::uuid, t.id('critic_pkt')::uuid, 'it_diff', t.id('ref_diff'), 'REF_ONLY', NULL, NULL, NULL, NULL, repeat('a',64), 0, 3),
 (t.id('A')::uuid, t.id('A1')::uuid, t.id('critic_pkt')::uuid, 'it_logs', t.id('ref_log'),  'RAW', 'POLICY_REQUIRED', NULL, NULL, NULL, repeat('b',64), 12500, 3),
 (t.id('A')::uuid, t.id('A1')::uuid, t.id('critic_pkt')::uuid, 'it_goal', t.id('ref_goal'), 'RAW', 'POLICY_REQUIRED', NULL, NULL, NULL, repeat('c',64), 200, 1);
SELECT t.ok(true, 'T08 reviewer packet items accepted with requires_original refs');

-- ---------------------------------------------------------------- T09 idempotency (CR-21)
SELECT t.fails($$INSERT INTO ctx.context_packets (tenant_id, project_id, run_id, task_id, task_attempt_id, idempotency_key, seat_id, function_role, agent_id,
  candidate_id, is_author_of_candidate, channel, profile, repo_sha, contract_version, policy_version, policy_hash, tool_schema_hash, evidence_manifest_hash,
  lease_epoch, provider, model, cache_mode, packet_sha256, expires_at)
  SELECT tenant_id, project_id, run_id, task_id, task_attempt_id, idempotency_key, seat_id, function_role, agent_id, candidate_id, is_author_of_candidate, channel,
  profile, repo_sha, contract_version, policy_version, policy_hash, tool_schema_hash, evidence_manifest_hash, lease_epoch, provider, model, cache_mode, packet_sha256, expires_at
  FROM ctx.context_packets WHERE packet_id = '$$ || t.id('critic_pkt') || $$'$$, 'duplicate key', 'T09 replayed packet creation is idempotent (CR-21)');

-- ---------------------------------------------------------------- T12 review coverage gate (CR-08)
INSERT INTO ctx.evidence_access_log (actor_tenant_id, actor_project_id, actor_id, request_id, requested_ref, claimed_packet_id, resolved_blob_id, decision, reason, range_start, range_end, trace_id)
VALUES (t.id('A')::uuid, t.id('A1')::uuid, t.id('critic_agent')::uuid, 'req-cov-000000001', t.id('ref_diff'), t.id('critic_pkt')::uuid, t.id('diff_blob')::uuid, 'ALLOW', 'review_coverage', 0, 400, 'tr-1'),
       (t.id('A')::uuid, t.id('A1')::uuid, t.id('critic_agent')::uuid, 'req-cov-000000002', t.id('ref_diff'), t.id('critic_pkt')::uuid, t.id('diff_blob')::uuid, 'ALLOW', 'review_coverage', 300, 700, 'tr-2'),
       -- same bytes delivered to a DIFFERENT actor do not count
       (t.id('A')::uuid, t.id('A1')::uuid, t.id('builder_agent')::uuid, 'req-cov-000000003', t.id('ref_diff'), t.id('critic_pkt')::uuid, t.id('diff_blob')::uuid, 'ALLOW', 'review_coverage', 700, 1000, 'tr-3');
SELECT t.ok((SELECT covered_bytes = 700 AND NOT complete FROM ctx.review_coverage(t.id('A')::uuid, t.id('A1')::uuid, t.id('critic_pkt')::uuid) WHERE ref = t.id('ref_diff')),
            'T12 overlapping ranges merged: 700/1000, incomplete; other actor''s reads ignored (T13)');
SELECT t.fails($$SELECT ctx.assert_review_gate('$$ || t.id('A') || $$','$$ || t.id('A1') || $$','$$ || t.id('critic_pkt') || $$','$$ || t.id('head') || $$')$$,
               'incomplete original coverage', 'T12 approve blocked until full diff delivered');
INSERT INTO ctx.evidence_access_log (actor_tenant_id, actor_project_id, actor_id, request_id, requested_ref, claimed_packet_id, resolved_blob_id, decision, reason, range_start, range_end, trace_id)
VALUES (t.id('A')::uuid, t.id('A1')::uuid, t.id('critic_agent')::uuid, 'req-cov-000000004', t.id('ref_diff'), t.id('critic_pkt')::uuid, t.id('diff_blob')::uuid, 'ALLOW', 'review_coverage', 650, 1000, 'tr-4');
SELECT t.ok((SELECT bool_and(complete) FROM ctx.review_coverage(t.id('A')::uuid, t.id('A1')::uuid, t.id('critic_pkt')::uuid)), 'T12 coverage complete (RAW items count as delivered)');
SELECT ctx.assert_review_gate(t.id('A')::uuid, t.id('A1')::uuid, t.id('critic_pkt')::uuid, t.id('head'));
SELECT t.ok(true, 'T12 approve gate passes at pinned head SHA');
SELECT t.fails($$SELECT ctx.assert_review_gate('$$ || t.id('A') || $$','$$ || t.id('A1') || $$','$$ || t.id('critic_pkt') || $$','$$ || repeat('cd', 20) || $$')$$,
               'pinned to', 'T12 approve blocked when candidate head moved (CR-10)');
SELECT t.fails($$SELECT ctx.assert_review_gate('$$ || t.id('A') || $$','$$ || t.id('A1') || $$','$$ || t.id('builder_pkt') || $$','$$ || t.id('head') || $$')$$,
               'cannot approve', 'T12 builder packet cannot approve');

-- ---------------------------------------------------------------- T10/T11 audit of denials; append-only
INSERT INTO ctx.evidence_access_log (actor_tenant_id, actor_project_id, actor_id, request_id, requested_ref, decision, reason, trace_id)
VALUES (t.id('A')::uuid, t.id('A1')::uuid, t.id('builder_agent')::uuid, 'req-deny-00000001', t.new_ref(), 'DENY_NOT_FOUND', 'builder_context', 'tr-5');
INSERT INTO ctx_sec.security_events (kind, actor_tenant_id, actor_id, requested_ref, trace_id)
VALUES ('UNKNOWN_REF_PROBE', t.id('A')::uuid, t.id('builder_agent')::uuid, t.new_ref(), 'tr-5');
SELECT t.ok(true, 'T10 denial for unknown/foreign ref is auditable (fixes F-SQL-1, CR-06/07)');
SELECT t.fails($$SELECT count(*) FROM ctx_sec.security_events$$, 'permission denied', 'T10 tenants/gateway cannot read platform security events');
SELECT t.fails($$UPDATE ctx.evidence_access_log SET decision = 'ALLOW'$$, 'permission denied|append-only', 'T11 access log not updatable');
SELECT t.fails($$DELETE FROM ctx.evidence_access_log$$, 'permission denied|append-only', 'T11 access log not deletable');
SELECT t.fails($$INSERT INTO ctx.evidence_access_log (actor_tenant_id, actor_id, request_id, requested_ref, decision, reason, trace_id)
  VALUES ('$$ || t.id('A') || $$', gen_random_uuid(), 'req-cov-000000001', 'evr_x', 'DENY_RATE', 'builder_context', 'tr-6')$$, 'duplicate key', 'T10 retrieval request_id is idempotent');

-- ---------------------------------------------------------------- T17 usage receipts
SELECT t.fails($$INSERT INTO ctx.provider_usage_receipts (tenant_id, project_id, packet_id, call_id, call_purpose, provider, model, source, billing_owner,
  uncached_input, cache_write, cache_read, output_tokens, cost_micros, price_table_version)
  VALUES ('$$ || t.id('A') || $$','$$ || t.id('A1') || $$','$$ || t.id('critic_pkt') || $$',gen_random_uuid(),'task_turn','anthropic','claude-opus-5-5','provider_billed','platform',
  100,2000,0,300,12345,'pt-2026-10')$$, 'receipt_billed_has_request', 'T17 billed receipt needs provider request id (CR-13)');
INSERT INTO ctx.provider_usage_receipts (tenant_id, project_id, packet_id, call_id, call_purpose, provider, model, provider_request_id, source, billing_owner,
  uncached_input, cache_write, cache_read, output_tokens, raw_usage_fields, cost_micros, price_table_version)
VALUES (t.id('A')::uuid, t.id('A1')::uuid, t.id('critic_pkt')::uuid, gen_random_uuid(), 'retrieval_turn', 'anthropic', 'claude-opus-5-5', 'msg_01', 'provider_billed', 'platform',
  100, 2000, 18000, 150, '{"cache_creation_input_tokens":2000,"cache_read_input_tokens":18000,"input_tokens":100}', 12345, 'pt-2026-10');
SELECT t.fails($$INSERT INTO ctx.provider_usage_receipts (tenant_id, project_id, packet_id, call_id, call_purpose, provider, model, provider_request_id, source, billing_owner,
  uncached_input, cache_write, cache_read, output_tokens, raw_usage_fields, cost_micros, price_table_version)
  VALUES ('$$ || t.id('A') || $$','$$ || t.id('A1') || $$','$$ || t.id('critic_pkt') || $$',gen_random_uuid(),'task_turn','anthropic','claude-opus-5-5','msg_01','provider_billed','platform',
  1,1,1,1,'{}',1,'pt')$$, 'duplicate key', 'T17 provider usage ingest is idempotent');

-- ---------------------------------------------------------------- T19 formats
SELECT t.fails($$INSERT INTO ctx.evidence_refs (ref, tenant_id, project_id, packet_id, blob_id, requires_original, expires_at)
  VALUES ('evref-000000000001','$$ || t.id('A') || $$','$$ || t.id('A1') || $$','$$ || t.id('critic_pkt') || $$','$$ || t.id('diff_blob') || $$',true,now())$$,
  'evidence_refs_ref_check', 'T19 sequential/guessable ref format rejected');
SELECT t.fails($$INSERT INTO ctx.context_packets (tenant_id, project_id, run_id, task_id, task_attempt_id, idempotency_key, seat_id, function_role, agent_id,
  candidate_id, is_author_of_candidate, channel, profile, repo_sha, contract_version, policy_version, policy_hash, tool_schema_hash, evidence_manifest_hash,
  lease_epoch, provider, model, cache_mode, packet_sha256, expires_at)
  VALUES ('$$ || t.id('A') || $$','$$ || t.id('A1') || $$',gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),'bad-role-packet-0001',1,'banana',gen_random_uuid(),
  NULL,false,'api','SAFE',repeat('a',64),1,'p',repeat('4',64),repeat('5',64),repeat('6',64),0,'openai','gpt-5.6','NONE',repeat('7',64),now()+interval '1h')$$,
  'function_role_check', 'T19 unknown role rejected (v3.5 accepted ''banana'')');

-- ---------------------------------------------------------------- T21 approval-grade evidence needs an ACTIVE original even when RAW (CR-16)
INSERT INTO ctx.evidence_blobs (tenant_id, project_id, blob_id, sha256, size_bytes, source_kind, trust, sensitivity, storage_region)
VALUES (t.id('A')::uuid, t.id('A1')::uuid, '0000b000-0000-4000-8000-000000000009', repeat('d', 64), 10, 'git.diff', 'verified_tool_output', 'restricted', 'kr-1');
INSERT INTO t.ids VALUES ('ref_pending', t.new_ref());
INSERT INTO ctx.evidence_refs (ref, tenant_id, project_id, packet_id, blob_id, requires_original, expires_at)
VALUES (t.id('ref_pending'), t.id('A')::uuid, t.id('A1')::uuid, t.id('critic_pkt')::uuid, '0000b000-0000-4000-8000-000000000009', true, now() + interval '1 hour');
SELECT t.fails($$INSERT INTO ctx.context_items VALUES ('$$ || t.id('A') || $$','$$ || t.id('A1') || $$','$$ || t.id('critic_pkt') || $$','it_pend','$$ || t.id('ref_pending') || $$',
  'RAW','VAULT_UNAVAILABLE',NULL,NULL,NULL,repeat('9',64),3,3)$$, 'approval-grade evidence', 'T21 reviewer cannot get RAW(VAULT_UNAVAILABLE) diff without stored original (CR-16)');

-- ---------------------------------------------------------------- T01/T02/T03/T20 isolation
SELECT t.as_tenant(t.id('B')::uuid, t.id('B1'));
SELECT t.ok((SELECT count(*) FROM ctx.evidence_blobs) = 0 AND (SELECT count(*) FROM ctx.context_packets) = 0 AND (SELECT count(*) FROM ctx.evidence_refs) = 0,
            'T01 tenant B sees no tenant A blobs/packets/refs (CR-06)');
SELECT t.ok((SELECT count(*) FROM ctx.evidence_access_log) = 0, 'T20 tenant B cannot read tenant A access log');
SELECT t.ok((SELECT count(*) FROM ctx.review_coverage(t.id('A')::uuid, t.id('A1')::uuid, t.id('critic_pkt')::uuid)) = 0, 'T01 coverage function leaks nothing cross-tenant');
SELECT t.fails($$INSERT INTO ctx.evidence_blobs (tenant_id, project_id, sha256, size_bytes, source_kind, trust, sensitivity, storage_region)
  VALUES ('$$ || t.id('A') || $$','$$ || t.id('A1') || $$',repeat('1',64),1,'log.text','untrusted_content','internal','kr-1')$$,
  'row-level security', 'T03 cannot write into another tenant');
SELECT t.as_tenant(t.id('A')::uuid, t.id('A2'));
SELECT t.ok((SELECT count(*) FROM ctx.evidence_blobs) = 0, 'T02 same tenant, other project sees nothing (CR-07)');

-- ---------------------------------------------------------------- T14 staleness (CR-22)
SELECT t.as_tenant(t.id('A')::uuid, t.id('A1'));
SELECT t.ok(ctx.mark_task_packets_stale(t.id('A')::uuid, t.id('A1')::uuid, t.id('task')::uuid, 'contract_version 3 -> 4') = 2, 'T14 goal change marks both live packets STALE');
SELECT t.fails($$SELECT ctx.assert_review_gate('$$ || t.id('A') || $$','$$ || t.id('A1') || $$','$$ || t.id('critic_pkt') || $$','$$ || t.id('head') || $$')$$,
               'packet STALE', 'T14 approve blocked on STALE packet even with full coverage');
SELECT t.fails($$UPDATE ctx.context_packets SET status = 'ISSUED', status_reason = NULL WHERE packet_id = '$$ || t.id('critic_pkt') || $$'$$, 'illegal packet transition', 'T14 STALE cannot be revived');

-- ---------------------------------------------------------------- T15/T18 deletion = tombstone + crypto-shred (CR-17)
SELECT t.fails($$DELETE FROM ctx.evidence_blobs$$, 'permission denied', 'T18 no hard DELETE for the gateway');
RESET ROLE;
UPDATE ctx.evidence_blobs SET legal_hold = true WHERE blob_id = t.id('diff_blob')::uuid;   -- compliance role in real life
SET ROLE ctx_gateway;
SELECT t.as_tenant(t.id('A')::uuid, t.id('A1'));
SELECT t.fails($$SELECT * FROM ctx.shred_blob('$$ || t.id('A') || $$','$$ || t.id('A1') || $$','$$ || t.id('diff_blob') || $$')$$, 'legal hold', 'T15 legal hold blocks shredding');
SELECT t.ok((SELECT object_storage_key LIKE 's3://%' AND dek_ref LIKE 'kms://%' FROM ctx.shred_blob(t.id('A')::uuid, t.id('A1')::uuid, t.id('log_blob')::uuid)),
            'T15 shred returns object key + DEK for destruction');
SELECT t.ok((SELECT state = 'SHREDDED' AND object_storage_key IS NULL FROM ctx.evidence_blobs WHERE blob_id = t.id('log_blob')::uuid)
        AND (SELECT bool_and(revoked_at IS NOT NULL) FROM ctx.evidence_refs WHERE blob_id = t.id('log_blob')::uuid)
        AND (SELECT bool_and(status = 'REVOKED') FROM ctx.context_packets WHERE task_id = t.id('task')::uuid),
            'T15 refs revoked and dependent packets REVOKED (no approval on deleted evidence)');
SELECT t.fails($$UPDATE ctx.evidence_blobs SET state = 'ACTIVE', object_storage_key = 'x', dek_ref = 'y', read_back_verified_at = now() WHERE blob_id = '$$ || t.id('log_blob') || $$'$$,
               'illegal blob transition', 'T15 shredded blob cannot be resurrected');
SELECT t.fails($$INSERT INTO ctx.context_items VALUES ('$$ || t.id('A') || $$','$$ || t.id('A1') || $$','$$ || t.id('builder_pkt') || $$','it_again','$$ || t.id('ref_b_log') || $$',
  'RAW','USER_OVERRIDE',NULL,NULL,NULL,repeat('9',64),200,3)$$, 'duplicate key|shredded', 'T15 shredded evidence cannot be re-issued');

RESET ROLE;
DO $$ BEGIN RAISE NOTICE 'ALL CONTEXT PLANE TESTS PASSED'; END $$;
