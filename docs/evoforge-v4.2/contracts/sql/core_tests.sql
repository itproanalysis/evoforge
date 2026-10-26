-- EvoForge v4.0 Core Plane — executable tests for core_DRAFT.sql (throwaway DB, superuser session).
\set ON_ERROR_STOP 1
SET client_min_messages = notice;

CREATE SCHEMA tc;
CREATE FUNCTION tc.ok(cond boolean, label text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN IF cond IS NOT TRUE THEN RAISE EXCEPTION 'FAIL: %', label; END IF; RAISE NOTICE 'ok  %', label; END $$;
CREATE FUNCTION tc.fails(stmt text, pattern text, label text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  BEGIN EXECUTE stmt;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM ~* pattern THEN RAISE NOTICE 'ok  % (%)', label, SQLERRM; RETURN; END IF;
    RAISE EXCEPTION 'FAIL: % raised unexpected error: %', label, SQLERRM;
  END;
  RAISE EXCEPTION 'FAIL: % did not raise', label;
END $$;
CREATE FUNCTION tc.as_tenant(tenant text, projects text) RETURNS void LANGUAGE sql AS $$
  SELECT set_config('app.tenant_id', tenant, false), set_config('app.project_ids', projects, false);
$$;
GRANT USAGE ON SCHEMA tc TO core_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA tc TO core_app;

-- ids
\set A '''a0000000-0000-4000-8000-000000000000'''
\set B '''b0000000-0000-4000-8000-000000000000'''
\set P1 '''a0000000-0001-4000-8000-000000000000'''
\set P2 '''a0000000-0002-4000-8000-000000000000'''
\set BP '''b0000000-0001-4000-8000-000000000000'''
\set BUILDER '''a0000000-0000-4000-8000-0000000000b1'''
\set BUILDER2 '''a0000000-0000-4000-8000-0000000000b2'''
\set CRITIC '''a0000000-0000-4000-8000-0000000000c1'''
\set CHAT '''a0000000-0000-4000-8000-0000000000d1'''
\set USER '''a0000000-0000-4000-8000-00000000aaaa'''
\set RUN '''a0000000-0000-4000-8000-0000000000e1'''
\set TLOW '''a0000000-0000-4000-8000-0000000000f1'''
\set THIGH '''a0000000-0000-4000-8000-0000000000f2'''
\set CLOW '''a0000000-0000-4000-8000-000000000101'''
\set CHIGH '''a0000000-0000-4000-8000-000000000102'''
\set PH '''1111111111111111111111111111111111111111111111111111111111111111'''
\set H1 '''aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'''
\set H2 '''bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'''

SET ROLE core_app;
SELECT tc.as_tenant(:A, :P1);
INSERT INTO core.tenants VALUES (:A, 'Tenant A', 'TEAM', 'ACTIVE', now());
INSERT INTO core.projects (tenant_id, project_id, name) VALUES (:A, :P1, 'api');
SELECT tc.as_tenant(:A, :P2);
INSERT INTO core.projects (tenant_id, project_id, name) VALUES (:A, :P2, 'web');
SELECT tc.as_tenant(:A, :P1);
INSERT INTO core.agents (tenant_id, agent_id, kind, join_state, connection_state, model_family) VALUES
  (:A, :BUILDER,  'provider_api', 'AUTHORIZED', 'READY', 'family-x'),
  (:A, :BUILDER2, 'provider_api', 'AUTHORIZED', 'READY', 'family-x'),
  (:A, :CRITIC,   'provider_api', 'AUTHORIZED', 'READY', 'family-y'),
  (:A, :CHAT,     'mcp_chat',     'PENDING_APPROVAL', 'UNKNOWN', 'family-z');
INSERT INTO core.runs (tenant_id, project_id, run_id, objective_version, topology, harness_version, policy_hash, status)
  VALUES (:A, :P1, :RUN, 1, 'SINGLE', 'h-1.0.0', :PH, 'CREATED');
INSERT INTO core.tasks (tenant_id, project_id, task_id, run_id, risk_level, base_sha) VALUES
  (:A, :P1, :TLOW, :RUN, 'LOW', :H1), (:A, :P1, :THIGH, :RUN, 'HIGH', :H1);

-- ---------------------------------------------------------------- C02/C03/C04 commands
SELECT tc.ok(core.accept_command(:A, :P1, 'cmd-reprio-0001', 'REPRIORITIZE', 0, :USER) =
             core.accept_command(:A, :P1, 'cmd-reprio-0001', 'REPRIORITIZE', 0, :USER), 'C02 replayed command returns the same command_id (20x resend -> 1)');
UPDATE core.projects SET state_version = 5 WHERE project_id = :P1;
SELECT tc.fails($$SELECT core.accept_command('a0000000-0000-4000-8000-000000000000','a0000000-0001-4000-8000-000000000000','cmd-goal-00001','CHANGE_GOAL',4,'a0000000-0000-4000-8000-00000000aaaa')$$,
                'STATE_VERSION_CONFLICT', 'C02 stale expected_state_version -> conflict (HTTP 409)');
SELECT tc.ok(core.accept_command(:A, :P1, 'cmd-stop-00001', 'STOP_ALL', 1, :USER) IS NOT NULL, 'C02 STOP_ALL accepted despite version drift (fast lane)');
SELECT tc.ok((SELECT fast_lane FROM core.commands WHERE idempotency_key = 'cmd-stop-00001'), 'C02 STOP_ALL is routed to the fast lane');
SELECT core.accept_command(:A, :P1, 'cmd-merge-0001', 'APPROVE_MERGE', 5, :USER);
UPDATE core.commands SET status = 'VALIDATING' WHERE idempotency_key = 'cmd-merge-0001';
SELECT tc.fails($$UPDATE core.commands SET status = 'PLANNED' WHERE idempotency_key = 'cmd-merge-0001'$$, 'structured preview', 'C03 risky command cannot skip confirmation');
UPDATE core.commands SET status = 'AWAITING_CONFIRMATION' WHERE idempotency_key = 'cmd-merge-0001';
SELECT tc.fails($$UPDATE core.commands SET status = 'PLANNED' WHERE idempotency_key = 'cmd-merge-0001'$$, 'structured preview', 'C03 confirmation needs confirmed_by');
UPDATE core.commands SET status = 'PLANNED', confirmed_by = :USER, confirmed_at = now() WHERE idempotency_key = 'cmd-merge-0001';
SELECT tc.ok((SELECT status = 'PLANNED' FROM core.commands WHERE idempotency_key = 'cmd-merge-0001'), 'C03 confirmed risky command proceeds');
UPDATE core.commands SET status = 'VALIDATING' WHERE idempotency_key = 'cmd-reprio-0001';
UPDATE core.commands SET status = 'PLANNED' WHERE idempotency_key = 'cmd-reprio-0001';
SELECT tc.fails($$UPDATE core.commands SET status = 'RECEIVED' WHERE idempotency_key = 'cmd-reprio-0001'$$, 'illegal command transition', 'C04 command cannot move backwards');

-- ---------------------------------------------------------------- C05/C06/C15 claim + fencing + task state machine
SELECT tc.fails($$SELECT core.claim_task('a0000000-0000-4000-8000-000000000000','a0000000-0001-4000-8000-000000000000','a0000000-0000-4000-8000-0000000000f1','a0000000-0000-4000-8000-0000000000d1','10 minutes')$$,
                'not authorized', 'C15 unapproved chat agent cannot claim');
SELECT tc.ok(core.claim_task(:A, :P1, :TLOW, :BUILDER, '10 minutes') = 1, 'C05 first claim wins with epoch 1');
SELECT tc.fails($$SELECT core.claim_task('a0000000-0000-4000-8000-000000000000','a0000000-0001-4000-8000-000000000000','a0000000-0000-4000-8000-0000000000f1','a0000000-0000-4000-8000-0000000000b2','10 minutes')$$,
                'CLAIM_LOST', 'C05 second claimer loses while lease is valid');
UPDATE core.tasks SET lease_expires_at = now() - interval '1 second' WHERE task_id = :TLOW;
SELECT tc.ok(core.claim_task(:A, :P1, :TLOW, :BUILDER2, '10 minutes') = 2, 'C05 expired lease re-claimed with epoch 2');
SELECT tc.fails($$SELECT core.assert_fencing('a0000000-0000-4000-8000-000000000000','a0000000-0001-4000-8000-000000000000','a0000000-0000-4000-8000-0000000000f1','a0000000-0000-4000-8000-0000000000b1',1)$$,
                'STALE_WRITE', 'C05 late write from old lease holder rejected (fencing)');
SELECT core.assert_fencing(:A, :P1, :TLOW, :BUILDER2, 2);
SELECT tc.ok(true, 'C05 current holder passes fencing');
SELECT tc.fails($$UPDATE core.tasks SET status = 'VERIFIED' WHERE task_id = 'a0000000-0000-4000-8000-0000000000f1'$$, 'illegal tasks transition', 'C06 CLAIMED -> VERIFIED is illegal');
UPDATE core.tasks SET status = 'RUNNING' WHERE task_id = :TLOW;
UPDATE core.agents SET join_state = 'REVOKED', credential_state = 'REVOKED', execution_state = 'IDLE' WHERE agent_id = :BUILDER;
SELECT tc.fails($$SELECT core.claim_task('a0000000-0000-4000-8000-000000000000','a0000000-0001-4000-8000-000000000000','a0000000-0000-4000-8000-0000000000f2','a0000000-0000-4000-8000-0000000000b1','10 minutes')$$,
                'not authorized', 'C15 revoked agent cannot claim new work');

-- ---------------------------------------------------------------- C07..C10 review independence, gates, merge authorization
INSERT INTO core.candidates (tenant_id, project_id, candidate_id, task_id, author_agent_id, base_sha, head_sha) VALUES
  (:A, :P1, :CLOW, :TLOW, :BUILDER2, :H1, :H2), (:A, :P1, :CHIGH, :THIGH, :BUILDER2, :H1, :H2);
UPDATE core.candidates SET status = 'PATCH_READY'; UPDATE core.candidates SET status = 'BUILD_CHECKED';
UPDATE core.candidates SET status = 'REVIEWED';    UPDATE core.candidates SET status = 'QUALITY_CHECKED';
UPDATE core.candidates SET status = 'PR_CREATED';
SELECT tc.fails($$INSERT INTO core.reviews (tenant_id, project_id, candidate_id, reviewer_agent_id, verdict, head_sha)
  VALUES ('a0000000-0000-4000-8000-000000000000','a0000000-0001-4000-8000-000000000000','a0000000-0000-4000-8000-000000000101','a0000000-0000-4000-8000-0000000000b2','approve','bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb')$$,
  'author cannot review', 'C07 author cannot review own candidate');
SELECT set_config('app.policy_hash', '1111111111111111111111111111111111111111111111111111111111111111', false);
SELECT tc.fails($$UPDATE core.candidates SET status = 'MERGED' WHERE candidate_id = 'a0000000-0000-4000-8000-000000000101'$$, 'gates not passed', 'C08 merge blocked with no gate evidence');
INSERT INTO core.gate_results (tenant_id, project_id, candidate_id, gate, result, head_sha, policy_hash, runner_image_digest, evidence_sha256)
SELECT :A::uuid, :P1::uuid, c, g, CASE WHEN g = 'G2_REQUIRED' THEN 'INCONCLUSIVE' ELSE 'PASS' END, :H2, :PH, 'sha256:img', repeat('e', 64)
FROM unnest(ARRAY['G0_SCOPE','G1_IMPACTED','G2_REQUIRED','GR_REVIEW','G4_MERGE_HEAD']) g, unnest(ARRAY[:CLOW, :CHIGH]::uuid[]) c;
SELECT tc.fails($$UPDATE core.candidates SET status = 'MERGED' WHERE candidate_id = 'a0000000-0000-4000-8000-000000000101'$$, 'G2_REQUIRED=INCONCLUSIVE', 'C08 INCONCLUSIVE is not PASS');
INSERT INTO core.gate_results (tenant_id, project_id, candidate_id, gate, result, head_sha, policy_hash, runner_image_digest, evidence_sha256)
SELECT :A::uuid, :P1::uuid, c, 'G2_REQUIRED', 'PASS', :H2, :PH, 'sha256:img', repeat('e', 64) FROM unnest(ARRAY[:CLOW, :CHIGH]::uuid[]) c;
SELECT tc.fails($$UPDATE core.candidates SET status = 'MERGED' WHERE candidate_id = 'a0000000-0000-4000-8000-000000000101'$$, 'GH_INTEGRITY=MISSING', 'C16 integrity gate (oracle strength + reward-hack + tamper) is mandatory');
INSERT INTO core.gate_results (tenant_id, project_id, candidate_id, gate, result, head_sha, policy_hash, runner_image_digest, evidence_sha256)
SELECT :A::uuid, :P1::uuid, c, 'GH_INTEGRITY', 'PASS', :H2, :PH, 'sha256:img', repeat('e', 64) FROM unnest(ARRAY[:CLOW, :CHIGH]::uuid[]) c;
SELECT tc.fails($$UPDATE core.candidates SET status = 'MERGED' WHERE candidate_id = 'a0000000-0000-4000-8000-000000000101'$$, 'no independent approve', 'C08 merge needs an independent approve');
INSERT INTO core.reviews (tenant_id, project_id, candidate_id, reviewer_agent_id, verdict, head_sha) VALUES
  (:A, :P1, :CLOW, :CRITIC, 'approve', :H2), (:A, :P1, :CHIGH, :CRITIC, 'approve', :H2);
SELECT tc.fails($$SELECT core.authorize_merge('a0000000-0000-4000-8000-000000000000','a0000000-0001-4000-8000-000000000000','a0000000-0000-4000-8000-000000000101','cccccccccccccccccccccccccccccccccccccccc','1111111111111111111111111111111111111111111111111111111111111111')$$,
                'head moved', 'C08 base/head moved after verification -> no merge (CR-10)');
SELECT tc.fails($$UPDATE core.candidates SET status = 'MERGED' WHERE candidate_id = 'a0000000-0000-4000-8000-000000000102'$$, 'requires human approval', 'C08 HIGH risk needs human approval bound to head');
UPDATE core.candidates SET status = 'MERGED' WHERE candidate_id = :CLOW;
SELECT tc.ok((SELECT status = 'MERGED' FROM core.candidates WHERE candidate_id = :CLOW), 'C08 LOW risk merges once gates PASS + independent approve at head');
SELECT tc.fails($$INSERT INTO core.reviews (tenant_id, project_id, candidate_id, reviewer_agent_id, verdict, head_sha)
  VALUES ('a0000000-0000-4000-8000-000000000000','a0000000-0001-4000-8000-000000000000','a0000000-0000-4000-8000-000000000102','a0000000-0000-4000-8000-0000000000c1','changes_requested','bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb')$$,
  'review_blocking_needs_evidence', 'C19 a blocking review needs executable evidence');
INSERT INTO core.reviews (tenant_id, project_id, candidate_id, reviewer_agent_id, verdict, head_sha, evidence_kind, evidence_ref)
  VALUES (:A, :P1, :CHIGH, :CRITIC, 'changes_requested', :H2, 'failing_test', 'tests/test_checkout.py::test_tax_rounding');
INSERT INTO core.approvals (tenant_id, project_id, subject_kind, subject_id, resource_sha, approver_user_id, reauthenticated)
  VALUES (:A, :P1, 'merge', :CHIGH, :H2, :USER, true);
SELECT tc.fails($$UPDATE core.candidates SET status = 'MERGED' WHERE candidate_id = 'a0000000-0000-4000-8000-000000000102'$$, 'later blocking review', 'C09 a later changes_requested blocks merge even with human approval');
SELECT tc.fails($$INSERT INTO core.approvals (tenant_id, project_id, subject_kind, subject_id, resource_sha, approver_user_id, reauthenticated)
  VALUES ('a0000000-0000-4000-8000-000000000000','a0000000-0001-4000-8000-000000000000','deploy','a0000000-0000-4000-8000-000000000102','x','a0000000-0000-4000-8000-00000000aaaa',false)$$,
  'approval_requires_reauth', 'C09 approvals require re-authentication');
-- C17 HIGH risk: human approval alone is not enough; the approve must be qualified + context-independent + spec-first
INSERT INTO core.reviews (tenant_id, project_id, candidate_id, reviewer_agent_id, verdict, head_sha) VALUES (:A, :P1, :CHIGH, :CRITIC, 'approve', :H2);
SELECT tc.fails($$UPDATE core.candidates SET status = 'MERGED' WHERE candidate_id = 'a0000000-0000-4000-8000-000000000102'$$, 'context-independent spec-first', 'C18 HIGH needs a context-independent spec-first approve');
SELECT tc.fails($$INSERT INTO core.reviews (tenant_id, project_id, candidate_id, reviewer_agent_id, verdict, head_sha, context_independent, spec_tests_sealed_at, diff_first_read_at)
  VALUES ('a0000000-0000-4000-8000-000000000000','a0000000-0001-4000-8000-000000000000','a0000000-0000-4000-8000-000000000102','a0000000-0000-4000-8000-0000000000c1','approve','bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', true, now(), now() - interval '1 minute')$$,
  'review_spec_first_order', 'C19 spec tests must be sealed before the diff is read');
INSERT INTO core.reviews (tenant_id, project_id, candidate_id, reviewer_agent_id, verdict, head_sha, context_independent, spec_tests_sealed_at, diff_first_read_at)
  VALUES (:A, :P1, :CHIGH, :CRITIC, 'approve', :H2, true, now() - interval '10 minutes', now() - interval '5 minutes');
SELECT tc.fails($$UPDATE core.candidates SET status = 'MERGED' WHERE candidate_id = 'a0000000-0000-4000-8000-000000000102'$$, 'not qualified', 'C18 the independent approver must be qualified for this risk + harness');
INSERT INTO core.reviewer_qualifications (tenant_id, agent_id, risk_level, harness_version, qualified_at, expires_at, evidence_sha256)
  VALUES (:A, :CRITIC, 'HIGH', 'h-0.9.0', now() - interval '1 day', now() + interval '30 days', repeat('a', 64));
SELECT tc.fails($$UPDATE core.candidates SET status = 'MERGED' WHERE candidate_id = 'a0000000-0000-4000-8000-000000000102'$$, 'not qualified', 'C18 qualification for another harness version does not count');
INSERT INTO core.reviewer_qualifications (tenant_id, agent_id, risk_level, harness_version, qualified_at, expires_at, evidence_sha256)
  VALUES (:A, :CRITIC, 'HIGH', 'h-1.0.0', now() - interval '1 day', now() + interval '30 days', repeat('a', 64));
UPDATE core.candidates SET status = 'MERGED' WHERE candidate_id = :CHIGH;
SELECT tc.ok((SELECT status = 'MERGED' FROM core.candidates WHERE candidate_id = :CHIGH), 'C18 HIGH merges: gates + qualified independent spec-first approve + human approval at head');
-- C16 composition: two live candidates in one DAG_PARALLEL wave => combined run (GC_COMPOSITION) is required
INSERT INTO core.candidates (tenant_id, project_id, candidate_id, task_id, author_agent_id, base_sha, head_sha, wave_id) VALUES
  (:A, :P1, 'a0000000-0000-4000-8000-000000000103', :TLOW, :BUILDER, :H1, :H2, 'a0000000-0000-4000-8000-0000000000a9'),
  (:A, :P1, 'a0000000-0000-4000-8000-000000000104', :TLOW, :BUILDER2, :H1, :H2, 'a0000000-0000-4000-8000-0000000000a9');
UPDATE core.candidates SET status = 'PATCH_READY' WHERE wave_id IS NOT NULL;  UPDATE core.candidates SET status = 'BUILD_CHECKED' WHERE wave_id IS NOT NULL;
UPDATE core.candidates SET status = 'REVIEWED' WHERE wave_id IS NOT NULL;     UPDATE core.candidates SET status = 'QUALITY_CHECKED' WHERE wave_id IS NOT NULL;
UPDATE core.candidates SET status = 'PR_CREATED' WHERE wave_id IS NOT NULL;
INSERT INTO core.gate_results (tenant_id, project_id, candidate_id, gate, result, head_sha, policy_hash, runner_image_digest, evidence_sha256)
SELECT :A::uuid, :P1::uuid, 'a0000000-0000-4000-8000-000000000103'::uuid, g, 'PASS', :H2, :PH, 'sha256:img', repeat('e', 64)
FROM unnest(ARRAY['G0_SCOPE','G1_IMPACTED','G2_REQUIRED','GH_INTEGRITY','GR_REVIEW','G4_MERGE_HEAD']) g;
INSERT INTO core.reviews (tenant_id, project_id, candidate_id, reviewer_agent_id, verdict, head_sha) VALUES (:A, :P1, 'a0000000-0000-4000-8000-000000000103', :CRITIC, 'approve', :H2);
SELECT tc.fails($$UPDATE core.candidates SET status = 'MERGED' WHERE candidate_id = 'a0000000-0000-4000-8000-000000000103'$$, 'GC_COMPOSITION=MISSING', 'C17 a wave with >= 2 live candidates needs the combined-run composition gate');
INSERT INTO core.gate_results (tenant_id, project_id, candidate_id, gate, result, head_sha, policy_hash, runner_image_digest, evidence_sha256)
  VALUES (:A, :P1, 'a0000000-0000-4000-8000-000000000103', 'GC_COMPOSITION', 'FAIL', :H2, :PH, 'sha256:img', repeat('e', 64));
SELECT tc.fails($$UPDATE core.candidates SET status = 'MERGED' WHERE candidate_id = 'a0000000-0000-4000-8000-000000000103'$$, 'GC_COMPOSITION=FAIL', 'C17 interference (FAIL) blocks merge');
INSERT INTO core.gate_results (tenant_id, project_id, candidate_id, gate, result, head_sha, policy_hash, runner_image_digest, evidence_sha256)
  VALUES (:A, :P1, 'a0000000-0000-4000-8000-000000000103', 'GC_COMPOSITION', 'PASS', :H2, :PH, 'sha256:img', repeat('e', 64));
UPDATE core.candidates SET status = 'MERGED' WHERE candidate_id = 'a0000000-0000-4000-8000-000000000103';
SELECT tc.ok((SELECT status = 'MERGED' FROM core.candidates WHERE candidate_id = 'a0000000-0000-4000-8000-000000000103'), 'C17 merges after the combined run passes');
SELECT tc.fails($$UPDATE core.gate_results SET result = 'PASS'$$, 'permission denied|append-only', 'C10 gate results are append-only');
SELECT tc.fails($$DELETE FROM core.reviewer_qualifications$$, 'permission denied|append-only', 'C10 reviewer qualifications are append-only');
SELECT tc.fails($$DELETE FROM core.reviews$$, 'permission denied|append-only', 'C10 reviews are append-only');

-- ---------------------------------------------------------------- C11/C12 events and side effects
INSERT INTO core.domain_events (tenant_id, aggregate_type, aggregate_id, aggregate_version, type, correlation_id, actor_kind, payload)
  VALUES (:A, 'task', :TLOW, 1, 'task.claimed', :RUN, 'agent', '{}');
SELECT tc.fails($$INSERT INTO core.domain_events (tenant_id, aggregate_type, aggregate_id, aggregate_version, type, correlation_id, actor_kind, payload)
  VALUES ('a0000000-0000-4000-8000-000000000000','task','a0000000-0000-4000-8000-0000000000f1',1,'task.claimed','a0000000-0000-4000-8000-0000000000e1','agent','{}')$$,
  'duplicate key', 'C11 one event per (aggregate, version): optimistic concurrency');
INSERT INTO core.side_effect_intents (tenant_id, kind, idempotency_key) VALUES (:A, 'github.create_pr', 'pr:cand-101');
UPDATE core.side_effect_intents SET status = 'SENT' WHERE idempotency_key = 'pr:cand-101';
UPDATE core.side_effect_intents SET status = 'UNKNOWN_EXTERNAL_OUTCOME' WHERE idempotency_key = 'pr:cand-101';
SELECT tc.fails($$UPDATE core.side_effect_intents SET status = 'SENT' WHERE idempotency_key = 'pr:cand-101'$$, 'reconcile UNKNOWN', 'C12 UNKNOWN outcome cannot be blindly retried');
SELECT tc.fails($$UPDATE core.side_effect_intents SET status = 'CONFIRMED' WHERE idempotency_key = 'pr:cand-101'$$, 'intent_confirmed_has_ref', 'C12 reconciliation must record the external id');
UPDATE core.side_effect_intents SET status = 'CONFIRMED', external_ref = 'gh-pr-4711' WHERE idempotency_key = 'pr:cand-101';
SELECT tc.fails($$INSERT INTO core.side_effect_intents (tenant_id, kind, idempotency_key) VALUES ('a0000000-0000-4000-8000-000000000000','github.create_pr','pr:cand-101')$$,
                'duplicate key', 'C12 same side effect cannot be reserved twice');

-- ---------------------------------------------------------------- C13/C14 platform-key spend control + ledger
INSERT INTO core.budgets VALUES (:A, :P1, '2026-10-01', 5000000);   -- $5.00 project cap
SELECT tc.fails($$SELECT core.reserve_cost('a0000000-0000-4000-8000-000000000000','a0000000-0001-4000-8000-000000000000','2026-10-01','call-0001',1000000)$$,
                'CREDIT_EXHAUSTED', 'C13 no prepaid credit -> no provider call');
INSERT INTO core.usage_ledger (tenant_id, entry_kind, customer_micros, idempotency_key, price_table_version)
  VALUES (:A, 'credit_purchase', 20000000, 'pg:order-1', 'pt-2026-10');   -- $20 credit
SELECT core.reserve_cost(:A, :P1, '2026-10-01', 'call-0001', 1500000);
SELECT core.reserve_cost(:A, :P1, '2026-10-01', 'call-0001', 1500000);   -- idempotent
SELECT tc.ok((SELECT count(*) = 1 FROM core.cost_reservations WHERE request_key = 'call-0001'), 'C13 reservation is idempotent');
SELECT core.reserve_cost(:A, :P1, '2026-10-01', 'call-0002', 3000000);
SELECT tc.fails($$SELECT core.reserve_cost('a0000000-0000-4000-8000-000000000000','a0000000-0001-4000-8000-000000000000','2026-10-01','call-0003',600000)$$,
                'BUDGET_EXCEEDED', 'C13 project cap is a hard stop before the call (over-budget execution = 0)');
SELECT core.settle_reservation(:A, :P1, 'call-0001', 1700000, 1400000, NULL, 'pt-2026-10');
SELECT tc.ok((SELECT overrun FROM core.cost_reservations WHERE request_key = 'call-0001'), 'C13 actual > reserved is flagged as estimator overrun');
SELECT tc.ok(core.credit_balance(:A) = 20000000 - 1700000, 'C13 settlement writes the ledger charge (balance 18.3)');
SELECT tc.fails($$INSERT INTO core.usage_ledger (tenant_id, entry_kind, customer_micros, idempotency_key, price_table_version)
  VALUES ('a0000000-0000-4000-8000-000000000000','model_usage',100,'bad-sign','pt')$$, 'ledger_sign', 'C14 charges must be negative in the customer view');
SELECT tc.fails($$UPDATE core.usage_ledger SET customer_micros = 0$$, 'permission denied|append-only', 'C14 ledger is append-only');
SELECT tc.fails($$INSERT INTO core.usage_ledger (tenant_id, entry_kind, customer_micros, reverses_entry_id, idempotency_key, price_table_version)
  SELECT tenant_id, 'adjustment', 999, entry_id, 'rev-bad', 'pt' FROM core.usage_ledger WHERE idempotency_key = 'settle:call-0001'$$,
  'negate the original', 'C14 reversal must exactly negate');
INSERT INTO core.usage_ledger (tenant_id, entry_kind, customer_micros, reverses_entry_id, idempotency_key, price_table_version)
  SELECT tenant_id, 'adjustment', 1700000, entry_id, 'rev-1', 'pt' FROM core.usage_ledger WHERE idempotency_key = 'settle:call-0001';
SELECT tc.fails($$INSERT INTO core.usage_ledger (tenant_id, entry_kind, customer_micros, reverses_entry_id, idempotency_key, price_table_version)
  SELECT tenant_id, 'adjustment', 1700000, entry_id, 'rev-2', 'pt' FROM core.usage_ledger WHERE idempotency_key = 'settle:call-0001'$$,
  'already reversed', 'C14 an entry can be reversed once');
SELECT tc.ok(core.credit_balance(:A) = 20000000, 'C14 balance restored by reversal entry');

-- ---------------------------------------------------------------- C01 isolation
SELECT tc.as_tenant(:A, :P2);
SELECT tc.ok((SELECT count(*) FROM core.tasks) = 0 AND (SELECT count(*) FROM core.commands) = 0, 'C01 same tenant, other project sees no tasks/commands');
RESET ROLE;
INSERT INTO core.tenants VALUES (:B, 'Tenant B', 'PRO', 'ACTIVE', now());
SET ROLE core_app;
SELECT tc.as_tenant(:B, :BP);
SELECT tc.ok((SELECT count(*) FROM core.agents) = 0 AND (SELECT count(*) FROM core.usage_ledger) = 0 AND (SELECT count(*) FROM core.domain_events) = 0,
             'C01 tenant B sees no tenant A agents/ledger/events');
SELECT tc.ok(core.credit_balance(:A) = 0, 'C01 credit balance of another tenant is invisible (RLS inside functions)');
SELECT tc.fails($$INSERT INTO core.agents (tenant_id, agent_id, kind) VALUES ('a0000000-0000-4000-8000-000000000000', gen_random_uuid(), 'a2a')$$,
                'row-level security', 'C01 cannot write into another tenant');
SELECT tc.fails($$DELETE FROM core.tasks$$, 'permission denied', 'C01 app role has no DELETE');
RESET ROLE;
DO $$ BEGIN RAISE NOTICE 'ALL CORE PLANE TESTS PASSED'; END $$;
