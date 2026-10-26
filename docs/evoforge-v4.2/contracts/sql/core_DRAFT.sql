-- EvoForge v4.1 Core Plane migration — DRAFT
-- Status: executed only against a throwaway PostgreSQL 16 database by core_tests.sql. NOT applied anywhere real.
-- Replaces the dangling references of v3.1–v3.4 (schema/core.sql, v3_3_migration.sql, research_evolution_v3_2.sql).
-- Scope: tenancy, provider allowlist (platform keys), agents (4-dimension state), commands (lifecycle + idempotency +
-- optimistic version), runs/tasks/candidates state machines, lease fencing, gate results, reviews, approvals,
-- merge authorization, domain events/outbox/inbox, side-effect intents, budgets/credit reservations, usage ledger.
-- v4.1: integrity + composition gates, evidence-backed blocking reviews, context-independent spec-first HIGH/CRITICAL
--       verification with per-harness reviewer qualification (arXiv:2610.28667, 2603.11078, 2609.25396, 2605.21384).
-- Naming: tenant_id everywhere (UI term "조직"). Money: integer micro-USD. Requires PostgreSQL >= 14.

BEGIN;
CREATE SCHEMA IF NOT EXISTS core AUTHORIZATION core_owner;
SET LOCAL ROLE core_owner;

CREATE OR REPLACE FUNCTION core.current_tenant() RETURNS uuid
LANGUAGE sql STABLE AS $$ SELECT nullif(current_setting('app.tenant_id', true), '')::uuid $$;
CREATE OR REPLACE FUNCTION core.current_projects() RETURNS uuid[]
LANGUAGE sql STABLE AS $$ SELECT coalesce(string_to_array(nullif(current_setting('app.project_ids', true), ''), ',')::uuid[], '{}'::uuid[]) $$;
CREATE OR REPLACE FUNCTION core.forbid_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege'; END $$;

-- ---------------------------------------------------------------- tenancy
CREATE TABLE core.tenants (
  tenant_id  uuid PRIMARY KEY,
  name       text NOT NULL,
  plan       text NOT NULL CHECK (plan IN ('PERSONAL','PRO','TEAM','ENTERPRISE')),
  status     text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SUSPENDED','CLOSING','CLOSED')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE core.projects (
  tenant_id       uuid    NOT NULL REFERENCES core.tenants(tenant_id),
  project_id      uuid    NOT NULL,
  name            text    NOT NULL,
  automation_mode text    NOT NULL DEFAULT 'ASSISTED' CHECK (automation_mode IN ('OBSERVE','ASSISTED','AUTONOMOUS_GUARDED')),
  research_mode   text    NOT NULL DEFAULT 'OFF' CHECK (research_mode IN ('OFF','SUGGEST','EVALUATE','CANARY')),
  context_profile text    NOT NULL DEFAULT 'SAFE' CHECK (context_profile IN ('SAFE','BALANCED')),  -- MAXIMUM is research-plane only
  state_version   bigint  NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, project_id)
);

-- Platform-managed provider keys: the tenant never stores a key; it chooses which provider/models may receive its data.
CREATE TABLE core.provider_allowlist (
  tenant_id       uuid        NOT NULL,
  project_id      uuid        NOT NULL,
  provider        text        NOT NULL CHECK (provider IN ('openai','anthropic','google','meta','other')),
  model_glob      text        NOT NULL,
  data_consent_at timestamptz NOT NULL,
  consented_by    uuid        NOT NULL,
  revoked_at      timestamptz,
  PRIMARY KEY (tenant_id, project_id, provider, model_glob),
  FOREIGN KEY (tenant_id, project_id) REFERENCES core.projects (tenant_id, project_id)
);

-- ---------------------------------------------------------------- agents: four independent state dimensions (p.21)
CREATE TABLE core.agents (
  tenant_id        uuid    NOT NULL REFERENCES core.tenants(tenant_id),
  agent_id         uuid    NOT NULL,
  kind             text    NOT NULL CHECK (kind IN ('provider_api','mcp_chat','folder_chat','a2a')),
  join_state       text    NOT NULL DEFAULT 'REQUESTED' CHECK (join_state IN ('REQUESTED','PENDING_APPROVAL','AUTHORIZED','REVOKED')),
  connection_state text    NOT NULL DEFAULT 'UNKNOWN' CHECK (connection_state IN ('UNKNOWN','PROBING','READY','DEGRADED','OFFLINE')),
  execution_state  text    NOT NULL DEFAULT 'IDLE' CHECK (execution_state IN ('IDLE','ASSIGNED','RUNNING','WAITING_FOR_CLIENT','BLOCKED','FINISHED')),
  credential_state text    NOT NULL DEFAULT 'VALID' CHECK (credential_state IN ('VALID','EXPIRING','EXPIRED','REVOKED')),
  human_relayed    boolean NOT NULL DEFAULT false,
  model_family     text,
  PRIMARY KEY (tenant_id, agent_id),
  CONSTRAINT agent_revoked_is_dead CHECK (join_state <> 'REVOKED' OR (execution_state IN ('IDLE','FINISHED') AND credential_state = 'REVOKED'))
);

CREATE OR REPLACE FUNCTION core.agent_can_work(p_tenant uuid, p_agent uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT coalesce(bool_and(join_state = 'AUTHORIZED' AND connection_state IN ('READY','DEGRADED') AND credential_state IN ('VALID','EXPIRING')), false)
  FROM core.agents WHERE tenant_id = p_tenant AND agent_id = p_agent
$$;

-- ---------------------------------------------------------------- commands (p.08/13/30): one lifecycle
CREATE TABLE core.commands (
  tenant_id              uuid        NOT NULL,
  project_id             uuid        NOT NULL,
  command_id             uuid        NOT NULL DEFAULT gen_random_uuid(),
  idempotency_key        text        NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{8,128}$'),
  kind                   text        NOT NULL CHECK (kind IN ('ASK','FEEDBACK','CHANGE_GOAL','REPRIORITIZE','PAUSE','RESUME','CANCEL','STOP_ALL','REASSIGN',
                                       'BUDGET_DECREASE','BUDGET_INCREASE','REQUEST_REVIEW','APPROVE_MERGE','APPROVE_DEPLOY','ENABLE_AUTOMERGE','PERMISSION_CHANGE',
                                       'CONTEXT_OVERRIDE','SEARCH_RESEARCH','PROPOSE_HARNESS_EXPERIMENT','REQUEST_PROMOTION_REVIEW','ROLLBACK_HARNESS','PAUSE_RESEARCH')),
  scope_run_id           uuid,
  scope_task_id          uuid,
  expected_state_version bigint      NOT NULL,
  actor_user_id          uuid        NOT NULL,
  payload                jsonb       NOT NULL DEFAULT '{}',
  status                 text        NOT NULL DEFAULT 'RECEIVED' CHECK (status IN ('RECEIVED','VALIDATING','AWAITING_CONFIRMATION','PLANNED','DISPATCHED','APPLYING','APPLIED','PARTIAL','BLOCKED','FAILED','REJECTED')),
  fast_lane              boolean     GENERATED ALWAYS AS (kind IN ('STOP_ALL','PAUSE','CANCEL','BUDGET_DECREASE','REPRIORITIZE','REASSIGN')) STORED,
  risky                  boolean     GENERATED ALWAYS AS (kind IN ('APPROVE_MERGE','APPROVE_DEPLOY','BUDGET_INCREASE','ENABLE_AUTOMERGE','PERMISSION_CHANGE','ROLLBACK_HARNESS')) STORED,
  confirmed_by           uuid,
  confirmed_at           timestamptz,
  received_at            timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, project_id, command_id),
  UNIQUE (tenant_id, project_id, idempotency_key),
  FOREIGN KEY (tenant_id, project_id) REFERENCES core.projects (tenant_id, project_id)
);

CREATE OR REPLACE FUNCTION core.enforce_command_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status = NEW.status THEN RETURN NEW; END IF;
  IF NOT ((OLD.status, NEW.status) IN (
      ('RECEIVED','VALIDATING'), ('VALIDATING','REJECTED'), ('VALIDATING','PLANNED'), ('VALIDATING','AWAITING_CONFIRMATION'),
      ('AWAITING_CONFIRMATION','PLANNED'), ('AWAITING_CONFIRMATION','REJECTED'), ('PLANNED','DISPATCHED'),
      ('DISPATCHED','APPLYING'), ('DISPATCHED','APPLIED'), ('DISPATCHED','PARTIAL'), ('DISPATCHED','BLOCKED'), ('DISPATCHED','FAILED'),
      ('APPLYING','APPLIED'), ('APPLYING','PARTIAL'), ('APPLYING','BLOCKED'), ('APPLYING','FAILED'))) THEN
    RAISE EXCEPTION 'illegal command transition % -> %', OLD.status, NEW.status USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.risky AND NEW.status = 'PLANNED' AND (OLD.status <> 'AWAITING_CONFIRMATION' OR NEW.confirmed_by IS NULL) THEN
    RAISE EXCEPTION 'risky command % requires structured preview + explicit confirmation', NEW.kind USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER commands_transition BEFORE UPDATE ON core.commands FOR EACH ROW EXECUTE FUNCTION core.enforce_command_transition();

-- Accept a command: idempotent replay returns the original row; stale expected_state_version raises (HTTP 409).
CREATE OR REPLACE FUNCTION core.accept_command(p_tenant uuid, p_project uuid, p_key text, p_kind text, p_expected bigint,
                                               p_actor uuid, p_payload jsonb DEFAULT '{}', p_run uuid DEFAULT NULL, p_task uuid DEFAULT NULL)
RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE v_id uuid; v_ver bigint;
BEGIN
  SELECT command_id INTO v_id FROM core.commands WHERE tenant_id = p_tenant AND project_id = p_project AND idempotency_key = p_key;
  IF FOUND THEN RETURN v_id; END IF;
  SELECT state_version INTO v_ver FROM core.projects WHERE tenant_id = p_tenant AND project_id = p_project;
  IF NOT FOUND THEN RAISE EXCEPTION 'project not found' USING ERRCODE = 'no_data_found'; END IF;
  -- fast-lane safety commands are never rejected for version drift
  IF p_expected <> v_ver AND p_kind NOT IN ('STOP_ALL','PAUSE','CANCEL','BUDGET_DECREASE') THEN
    RAISE EXCEPTION 'STATE_VERSION_CONFLICT expected % actual %', p_expected, v_ver USING ERRCODE = 'serialization_failure';
  END IF;
  INSERT INTO core.commands (tenant_id, project_id, idempotency_key, kind, scope_run_id, scope_task_id, expected_state_version, actor_user_id, payload)
  VALUES (p_tenant, p_project, p_key, p_kind, p_run, p_task, p_expected, p_actor, p_payload) RETURNING command_id INTO v_id;
  RETURN v_id;
END $$;

-- ---------------------------------------------------------------- runs / tasks / candidates (p.31): three separate state machines
CREATE TABLE core.runs (
  tenant_id         uuid   NOT NULL,
  project_id        uuid   NOT NULL,
  run_id            uuid   NOT NULL DEFAULT gen_random_uuid(),
  objective_version integer NOT NULL CHECK (objective_version >= 1),
  topology          text   NOT NULL CHECK (topology IN ('SINGLE','RACE_2','DAG_PARALLEL','PIPELINE','HIGH_RISK')),
  harness_version   text   NOT NULL,
  policy_hash       char(64) NOT NULL CHECK (policy_hash ~ '^[0-9a-f]{64}$'),
  status            text   NOT NULL DEFAULT 'CREATED' CHECK (status IN ('CREATED','QUEUED','RUNNING','WAITING','PAUSING','PAUSED','CANCELLING','SUCCEEDED','FAILED','CANCELLED')),
  PRIMARY KEY (tenant_id, project_id, run_id),
  FOREIGN KEY (tenant_id, project_id) REFERENCES core.projects (tenant_id, project_id)
);

CREATE TABLE core.tasks (
  tenant_id        uuid   NOT NULL,
  project_id       uuid   NOT NULL,
  task_id          uuid   NOT NULL DEFAULT gen_random_uuid(),
  run_id           uuid   NOT NULL,
  risk_level       text   NOT NULL CHECK (risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')),
  status           text   NOT NULL DEFAULT 'READY' CHECK (status IN ('READY','CLAIMED','RUNNING','WAITING_AGENT','BLOCKED','REVIEW_REQUIRED','VERIFIED','REJECTED','FAILED','CANCELLED')),
  version          bigint NOT NULL DEFAULT 0,
  lease_holder     uuid,
  lease_epoch      bigint NOT NULL DEFAULT 0,
  lease_expires_at timestamptz,
  base_sha         text   CHECK (base_sha ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'),
  PRIMARY KEY (tenant_id, project_id, task_id),
  FOREIGN KEY (tenant_id, project_id, run_id) REFERENCES core.runs (tenant_id, project_id, run_id),
  FOREIGN KEY (tenant_id, lease_holder) REFERENCES core.agents (tenant_id, agent_id)
);

CREATE TABLE core.candidates (
  tenant_id       uuid NOT NULL,
  project_id      uuid NOT NULL,
  candidate_id    uuid NOT NULL DEFAULT gen_random_uuid(),
  task_id         uuid NOT NULL,
  author_agent_id uuid NOT NULL,
  base_sha        text NOT NULL CHECK (base_sha ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'),
  head_sha        text NOT NULL CHECK (head_sha ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'),
  status          text NOT NULL DEFAULT 'PROPOSED' CHECK (status IN ('PROPOSED','PATCH_READY','BUILD_CHECKED','REVIEWED','QUALITY_CHECKED','PR_CREATED','MERGED','REJECTED')),
  wave_id         uuid,       -- DAG_PARALLEL wave; >= 2 live candidates in one wave => GC_COMPOSITION required (p.29/36)
  PRIMARY KEY (tenant_id, project_id, candidate_id),
  FOREIGN KEY (tenant_id, project_id, task_id) REFERENCES core.tasks (tenant_id, project_id, task_id),
  FOREIGN KEY (tenant_id, author_agent_id) REFERENCES core.agents (tenant_id, agent_id)
);

CREATE OR REPLACE FUNCTION core.enforce_state_machines() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE ok boolean;
BEGIN
  IF OLD.status = NEW.status THEN RETURN NEW; END IF;
  IF TG_TABLE_NAME = 'runs' THEN
    ok := (OLD.status, NEW.status) IN (('CREATED','QUEUED'),('QUEUED','RUNNING'),('RUNNING','WAITING'),('WAITING','RUNNING'),
           ('RUNNING','PAUSING'),('WAITING','PAUSING'),('PAUSING','PAUSED'),('PAUSED','QUEUED'),
           ('QUEUED','CANCELLING'),('RUNNING','CANCELLING'),('WAITING','CANCELLING'),('PAUSED','CANCELLING'),('PAUSING','CANCELLING'),('CANCELLING','CANCELLED'),
           ('RUNNING','SUCCEEDED'),('RUNNING','FAILED'),('WAITING','FAILED'));
  ELSIF TG_TABLE_NAME = 'tasks' THEN
    ok := (OLD.status, NEW.status) IN (('READY','CLAIMED'),('CLAIMED','RUNNING'),('CLAIMED','READY'),('RUNNING','REVIEW_REQUIRED'),
           ('RUNNING','BLOCKED'),('RUNNING','WAITING_AGENT'),('WAITING_AGENT','RUNNING'),('WAITING_AGENT','READY'),('BLOCKED','READY'),
           ('REVIEW_REQUIRED','VERIFIED'),('REVIEW_REQUIRED','REJECTED'),('REVIEW_REQUIRED','RUNNING'),('RUNNING','FAILED'))
          OR (NEW.status = 'CANCELLED' AND OLD.status NOT IN ('VERIFIED','REJECTED','FAILED','CANCELLED'));
  ELSE -- candidates
    ok := (OLD.status, NEW.status) IN (('PROPOSED','PATCH_READY'),('PATCH_READY','BUILD_CHECKED'),('BUILD_CHECKED','REVIEWED'),
           ('REVIEWED','QUALITY_CHECKED'),('QUALITY_CHECKED','PR_CREATED'),('PR_CREATED','MERGED'),
           ('PR_CREATED','PATCH_READY'),('QUALITY_CHECKED','PATCH_READY'),('REVIEWED','PATCH_READY'))     -- new head => re-verify
          OR (NEW.status = 'REJECTED' AND OLD.status NOT IN ('MERGED','REJECTED'));
  END IF;
  IF NOT ok THEN
    RAISE EXCEPTION 'illegal % transition % -> %', TG_TABLE_NAME, OLD.status, NEW.status USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER runs_sm BEFORE UPDATE OF status ON core.runs FOR EACH ROW EXECUTE FUNCTION core.enforce_state_machines();
CREATE TRIGGER tasks_sm BEFORE UPDATE OF status ON core.tasks FOR EACH ROW EXECUTE FUNCTION core.enforce_state_machines();
CREATE TRIGGER candidates_sm BEFORE UPDATE OF status ON core.candidates FOR EACH ROW EXECUTE FUNCTION core.enforce_state_machines();

-- Atomic claim (p.29): exactly one agent wins; an expired lease can be re-claimed and bumps the epoch (fencing).
CREATE OR REPLACE FUNCTION core.claim_task(p_tenant uuid, p_project uuid, p_task uuid, p_agent uuid, p_ttl interval)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE v_epoch bigint;
BEGIN
  IF NOT core.agent_can_work(p_tenant, p_agent) THEN
    RAISE EXCEPTION 'agent not authorized/ready' USING ERRCODE = 'insufficient_privilege';
  END IF;
  UPDATE core.tasks SET status = 'CLAIMED', lease_holder = p_agent, lease_epoch = lease_epoch + 1,
         lease_expires_at = now() + p_ttl, version = version + 1
   WHERE tenant_id = p_tenant AND project_id = p_project AND task_id = p_task
     AND (status = 'READY' OR (status = 'CLAIMED' AND lease_expires_at < now()))
  RETURNING lease_epoch INTO v_epoch;
  IF v_epoch IS NULL THEN RAISE EXCEPTION 'CLAIM_LOST' USING ERRCODE = 'lock_not_available'; END IF;
  RETURN v_epoch;
END $$;

-- Every write/PR/merge request presents (task, epoch). A late writer with an old epoch is rejected (STALE_WRITE).
CREATE OR REPLACE FUNCTION core.assert_fencing(p_tenant uuid, p_project uuid, p_task uuid, p_agent uuid, p_epoch bigint)
RETURNS void LANGUAGE plpgsql STABLE AS $$
DECLARE t core.tasks%ROWTYPE;
BEGIN
  SELECT * INTO t FROM core.tasks WHERE tenant_id = p_tenant AND project_id = p_project AND task_id = p_task;
  IF NOT FOUND OR t.lease_holder IS DISTINCT FROM p_agent OR t.lease_epoch <> p_epoch OR t.lease_expires_at < now() THEN
    RAISE EXCEPTION 'STALE_WRITE task % epoch % (current holder %, epoch %)', p_task, p_epoch, t.lease_holder, t.lease_epoch
      USING ERRCODE = 'check_violation';
  END IF;
END $$;

-- ---------------------------------------------------------------- gates, reviews, approvals, merge authorization (p.33/35/36)
CREATE TABLE core.gate_results (
  tenant_id           uuid        NOT NULL,
  project_id          uuid        NOT NULL,
  gate_result_id      uuid        NOT NULL DEFAULT gen_random_uuid(),
  candidate_id        uuid        NOT NULL,
  gate                text        NOT NULL CHECK (gate IN ('G0_SCOPE','G1_IMPACTED','G2_REQUIRED','GH_INTEGRITY','GC_COMPOSITION','G3_BENCHMARK','GR_REVIEW','G4_MERGE_HEAD')),
  result              text        NOT NULL CHECK (result IN ('PASS','FAIL','INCONCLUSIVE','SKIPPED_WITH_REASON')),
  head_sha            text        NOT NULL,
  policy_hash         char(64)    NOT NULL,
  runner_image_digest text        NOT NULL,
  evidence_sha256     char(64)    NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
  skip_reason         text,
  recorded_at         timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id, project_id, gate_result_id),
  FOREIGN KEY (tenant_id, project_id, candidate_id) REFERENCES core.candidates (tenant_id, project_id, candidate_id),
  CONSTRAINT gate_skip_reason CHECK (result <> 'SKIPPED_WITH_REASON' OR skip_reason IS NOT NULL)
);
CREATE TRIGGER gate_results_append_only BEFORE UPDATE OR DELETE ON core.gate_results FOR EACH ROW EXECUTE FUNCTION core.forbid_mutation();

CREATE TABLE core.reviews (
  tenant_id         uuid        NOT NULL,
  project_id        uuid        NOT NULL,
  review_id         uuid        NOT NULL DEFAULT gen_random_uuid(),
  candidate_id      uuid        NOT NULL,
  reviewer_agent_id uuid        NOT NULL,
  verdict           text        NOT NULL CHECK (verdict IN ('approve','changes_requested','reject','comment')),
  head_sha          text        NOT NULL,
  context_packet_id uuid,       -- ctx.context_packets; approve requires ctx.assert_review_gate to have passed (enforced by the service)
  context_independent  boolean NOT NULL DEFAULT false,   -- verifier saw no builder transcript/rationale (p.35)
  spec_tests_sealed_at timestamptz,                        -- phase A: acceptance tests written from the spec, sealed
  diff_first_read_at   timestamptz,                        -- phase B starts: first access to the diff
  evidence_kind     text CHECK (evidence_kind IN ('failing_test','reproducer_script','static_rule_hit','policy_violation')),
  evidence_ref      text,
  recorded_at       timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id, project_id, review_id),
  CONSTRAINT review_blocking_needs_evidence CHECK (verdict NOT IN ('changes_requested','reject') OR (evidence_kind IS NOT NULL AND evidence_ref IS NOT NULL)),
  CONSTRAINT review_spec_first_order CHECK (spec_tests_sealed_at IS NULL OR diff_first_read_at IS NULL OR spec_tests_sealed_at < diff_first_read_at),
  FOREIGN KEY (tenant_id, project_id, candidate_id) REFERENCES core.candidates (tenant_id, project_id, candidate_id),
  FOREIGN KEY (tenant_id, reviewer_agent_id) REFERENCES core.agents (tenant_id, agent_id)
);
CREATE TRIGGER reviews_append_only BEFORE UPDATE OR DELETE ON core.reviews FOR EACH ROW EXECUTE FUNCTION core.forbid_mutation();

CREATE OR REPLACE FUNCTION core.enforce_review_independence() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE c core.candidates%ROWTYPE;
BEGIN
  SELECT * INTO c FROM core.candidates WHERE tenant_id = NEW.tenant_id AND project_id = NEW.project_id AND candidate_id = NEW.candidate_id;
  IF c.author_agent_id = NEW.reviewer_agent_id THEN
    RAISE EXCEPTION 'author cannot review own candidate' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER reviews_independence BEFORE INSERT ON core.reviews FOR EACH ROW EXECUTE FUNCTION core.enforce_review_independence();

-- Reviewer qualification (p.35/37): per agent x risk level x harness version, from the seeded-defect + clean-candidate +
-- finding-precision exam in reference_impl/quality_gate.py::reviewer_qualification. Expires; requalify on harness change.
CREATE TABLE core.reviewer_qualifications (
  tenant_id       uuid        NOT NULL,
  agent_id        uuid        NOT NULL,
  risk_level      text        NOT NULL CHECK (risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')),
  harness_version text        NOT NULL,
  qualified_at    timestamptz NOT NULL DEFAULT now(),
  expires_at      timestamptz NOT NULL,
  evidence_sha256 char(64)    NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
  PRIMARY KEY (tenant_id, agent_id, risk_level, harness_version, qualified_at),
  FOREIGN KEY (tenant_id, agent_id) REFERENCES core.agents (tenant_id, agent_id),
  CONSTRAINT qualification_window CHECK (expires_at > qualified_at)
);
CREATE TRIGGER reviewer_qualifications_append_only BEFORE UPDATE OR DELETE ON core.reviewer_qualifications FOR EACH ROW EXECUTE FUNCTION core.forbid_mutation();

CREATE TABLE core.approvals (
  tenant_id        uuid        NOT NULL,
  project_id       uuid        NOT NULL,
  approval_id      uuid        NOT NULL DEFAULT gen_random_uuid(),
  subject_kind     text        NOT NULL CHECK (subject_kind IN ('merge','deploy','harness_promotion','budget_increase','permission_change')),
  subject_id       uuid        NOT NULL,
  resource_sha     text        NOT NULL,
  approver_user_id uuid        NOT NULL,
  reauthenticated  boolean     NOT NULL,
  decided_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, project_id, approval_id),
  CONSTRAINT approval_requires_reauth CHECK (reauthenticated)
);
CREATE TRIGGER approvals_append_only BEFORE UPDATE OR DELETE ON core.approvals FOR EACH ROW EXECUTE FUNCTION core.forbid_mutation();

-- Merge authorization: deterministic, outside any LLM. Called by the merge worker AND by the candidates trigger below.
CREATE OR REPLACE FUNCTION core.authorize_merge(p_tenant uuid, p_project uuid, p_candidate uuid, p_current_head text, p_policy_hash text)
RETURNS void LANGUAGE plpgsql STABLE AS $$
DECLARE
  c core.candidates%ROWTYPE; t core.tasks%ROWTYPE; v_harness text; missing text;
BEGIN
  SELECT * INTO c FROM core.candidates WHERE tenant_id = p_tenant AND project_id = p_project AND candidate_id = p_candidate;
  IF NOT FOUND THEN RAISE EXCEPTION 'merge: candidate not found' USING ERRCODE = 'no_data_found'; END IF;
  SELECT * INTO t FROM core.tasks WHERE tenant_id = p_tenant AND project_id = p_project AND task_id = c.task_id;
  IF c.head_sha <> p_current_head THEN
    RAISE EXCEPTION 'merge: head moved (verified %, current %)', c.head_sha, p_current_head USING ERRCODE = 'check_violation';
  END IF;
  -- latest result per required gate at this head + policy must be PASS (G3 only when a benchmark was required: absent => not required)
  WITH latest AS (
    SELECT DISTINCT ON (gate) gate, result FROM core.gate_results
    WHERE tenant_id = p_tenant AND project_id = p_project AND candidate_id = p_candidate AND head_sha = p_current_head AND policy_hash = p_policy_hash
    ORDER BY gate, recorded_at DESC
  ), req(gate) AS (VALUES ('G0_SCOPE'),('G1_IMPACTED'),('G2_REQUIRED'),('GH_INTEGRITY'),('GR_REVIEW'),('G4_MERGE_HEAD'))
  SELECT string_agg(r.gate || '=' || coalesce(l.result, 'MISSING'), ', ' ORDER BY r.gate) INTO missing
  FROM (SELECT gate FROM req
        UNION SELECT gate FROM latest WHERE gate = 'G3_BENCHMARK'
        UNION SELECT 'GC_COMPOSITION' WHERE c.wave_id IS NOT NULL AND (
          SELECT count(*) FROM core.candidates w WHERE w.tenant_id = p_tenant AND w.project_id = p_project
             AND w.wave_id = c.wave_id AND w.status <> 'REJECTED') >= 2) r
  LEFT JOIN latest l USING (gate) WHERE l.result IS DISTINCT FROM 'PASS';
  IF missing IS NOT NULL THEN RAISE EXCEPTION 'merge: gates not passed: %', missing USING ERRCODE = 'check_violation'; END IF;
  IF NOT EXISTS (SELECT 1 FROM core.reviews r WHERE r.tenant_id = p_tenant AND r.project_id = p_project AND r.candidate_id = p_candidate
                 AND r.verdict = 'approve' AND r.head_sha = p_current_head AND r.reviewer_agent_id <> c.author_agent_id) THEN
    RAISE EXCEPTION 'merge: no independent approve at current head' USING ERRCODE = 'check_violation';
  END IF;
  IF EXISTS (SELECT 1 FROM core.reviews r WHERE r.tenant_id = p_tenant AND r.project_id = p_project AND r.candidate_id = p_candidate
             AND r.head_sha = p_current_head AND r.verdict IN ('changes_requested','reject')
             AND r.recorded_at > (SELECT max(r2.recorded_at) FROM core.reviews r2 WHERE r2.tenant_id = r.tenant_id AND r2.project_id = r.project_id
                                 AND r2.candidate_id = r.candidate_id AND r2.verdict = 'approve' AND r2.head_sha = p_current_head)) THEN
    RAISE EXCEPTION 'merge: later blocking review exists' USING ERRCODE = 'check_violation';
  END IF;
  IF t.risk_level IN ('HIGH','CRITICAL') AND NOT EXISTS (
       SELECT 1 FROM core.approvals a WHERE a.tenant_id = p_tenant AND a.project_id = p_project AND a.subject_kind = 'merge'
       AND a.subject_id = p_candidate AND a.resource_sha = p_current_head) THEN
    RAISE EXCEPTION 'merge: % risk requires human approval bound to head %', t.risk_level, p_current_head USING ERRCODE = 'check_violation';
  END IF;
  -- v4.1 (ADR-054): HIGH/CRITICAL need an approve at head from a QUALIFIED, CONTEXT-INDEPENDENT, SPEC-FIRST verifier.
  -- A different provider/model family is not required (arXiv:2610.28667); author exclusion still holds.
  IF t.risk_level IN ('HIGH','CRITICAL') THEN
    SELECT harness_version INTO v_harness FROM core.runs WHERE tenant_id = p_tenant AND project_id = p_project AND run_id = t.run_id;
    IF NOT EXISTS (SELECT 1 FROM core.reviews r WHERE r.tenant_id = p_tenant AND r.project_id = p_project AND r.candidate_id = p_candidate
                   AND r.verdict = 'approve' AND r.head_sha = p_current_head AND r.reviewer_agent_id <> c.author_agent_id
                   AND r.context_independent AND r.spec_tests_sealed_at IS NOT NULL AND r.diff_first_read_at IS NOT NULL) THEN
      RAISE EXCEPTION 'merge: % risk requires a context-independent spec-first approve at head', t.risk_level USING ERRCODE = 'check_violation';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM core.reviews r JOIN core.reviewer_qualifications q
                     ON q.tenant_id = r.tenant_id AND q.agent_id = r.reviewer_agent_id AND q.risk_level = t.risk_level
                    AND q.harness_version = v_harness AND q.qualified_at <= now() AND q.expires_at > now()
                   WHERE r.tenant_id = p_tenant AND r.project_id = p_project AND r.candidate_id = p_candidate
                     AND r.verdict = 'approve' AND r.head_sha = p_current_head AND r.reviewer_agent_id <> c.author_agent_id
                     AND r.context_independent AND r.spec_tests_sealed_at IS NOT NULL AND r.diff_first_read_at IS NOT NULL) THEN
      RAISE EXCEPTION 'merge: independent approver is not qualified for % at harness %', t.risk_level, v_harness USING ERRCODE = 'check_violation';
    END IF;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION core.guard_merged() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status = 'MERGED' AND OLD.status <> 'MERGED' THEN
    PERFORM core.authorize_merge(NEW.tenant_id, NEW.project_id, NEW.candidate_id, NEW.head_sha,
                                 nullif(current_setting('app.policy_hash', true), ''));
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER candidates_guard_merged BEFORE UPDATE OF status ON core.candidates FOR EACH ROW EXECUTE FUNCTION core.guard_merged();

-- ---------------------------------------------------------------- events / outbox / inbox / side effects (p.27/40)
CREATE TABLE core.domain_events (
  tenant_id         uuid        NOT NULL,
  event_id          uuid        NOT NULL DEFAULT gen_random_uuid(),
  aggregate_type    text        NOT NULL,
  aggregate_id      uuid        NOT NULL,
  aggregate_version bigint      NOT NULL,
  type              text        NOT NULL,
  schema_version    integer     NOT NULL DEFAULT 1,
  correlation_id    uuid        NOT NULL,
  causation_id      uuid,
  actor_kind        text        NOT NULL CHECK (actor_kind IN ('user','agent','system')),
  actor_id          uuid,
  payload           jsonb       NOT NULL,
  occurred_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, event_id),
  UNIQUE (tenant_id, aggregate_id, aggregate_version)
);
CREATE TRIGGER domain_events_append_only BEFORE UPDATE OR DELETE ON core.domain_events FOR EACH ROW EXECUTE FUNCTION core.forbid_mutation();

CREATE TABLE core.outbox (
  tenant_id    uuid NOT NULL,
  event_id     uuid NOT NULL,
  published_at timestamptz,
  attempts     integer NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, event_id),
  FOREIGN KEY (tenant_id, event_id) REFERENCES core.domain_events (tenant_id, event_id)
);

CREATE TABLE core.inbox_dedup (
  tenant_id    uuid NOT NULL,
  consumer     text NOT NULL,
  event_id     uuid NOT NULL,
  processed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, consumer, event_id)
);

CREATE TABLE core.side_effect_intents (
  tenant_id       uuid NOT NULL,
  intent_id       uuid NOT NULL DEFAULT gen_random_uuid(),
  kind            text NOT NULL CHECK (kind IN ('provider.call','github.create_pr','github.merge','billing.charge')),
  idempotency_key text NOT NULL,
  status          text NOT NULL DEFAULT 'RESERVED' CHECK (status IN ('RESERVED','SENT','CONFIRMED','UNKNOWN_EXTERNAL_OUTCOME','FAILED','COMPENSATED')),
  external_ref    text,
  PRIMARY KEY (tenant_id, intent_id),
  UNIQUE (tenant_id, kind, idempotency_key),
  CONSTRAINT intent_confirmed_has_ref CHECK (status <> 'CONFIRMED' OR external_ref IS NOT NULL)
);

-- Retrying a side effect is allowed only from FAILED. UNKNOWN_EXTERNAL_OUTCOME must be reconciled (lookup) first.
CREATE OR REPLACE FUNCTION core.enforce_intent_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status = NEW.status THEN RETURN NEW; END IF;
  IF NOT ((OLD.status, NEW.status) IN (('RESERVED','SENT'),('SENT','CONFIRMED'),('SENT','FAILED'),('SENT','UNKNOWN_EXTERNAL_OUTCOME'),
          ('UNKNOWN_EXTERNAL_OUTCOME','CONFIRMED'),('UNKNOWN_EXTERNAL_OUTCOME','FAILED'),('FAILED','SENT'),('CONFIRMED','COMPENSATED'))) THEN
    RAISE EXCEPTION 'illegal side-effect transition % -> % (reconcile UNKNOWN before retry)', OLD.status, NEW.status USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER side_effect_intents_transition BEFORE UPDATE ON core.side_effect_intents FOR EACH ROW EXECUTE FUNCTION core.enforce_intent_transition();

-- ---------------------------------------------------------------- platform-key spend control (p.09/39/48)
CREATE TABLE core.budgets (
  tenant_id    uuid   NOT NULL,
  project_id   uuid   NOT NULL,
  period_start date   NOT NULL,
  cap_micros   bigint NOT NULL CHECK (cap_micros >= 0),
  PRIMARY KEY (tenant_id, project_id, period_start),
  FOREIGN KEY (tenant_id, project_id) REFERENCES core.projects (tenant_id, project_id)
);

CREATE TABLE core.cost_reservations (
  tenant_id      uuid        NOT NULL,
  project_id     uuid        NOT NULL,
  request_key    text        NOT NULL,
  period_start   date        NOT NULL,
  reserved_micros bigint     NOT NULL CHECK (reserved_micros > 0),
  actual_micros  bigint      CHECK (actual_micros >= 0),
  status         text        NOT NULL DEFAULT 'RESERVED' CHECK (status IN ('RESERVED','COMMITTED','RELEASED')),
  overrun        boolean     GENERATED ALWAYS AS (actual_micros IS NOT NULL AND actual_micros > reserved_micros) STORED,
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, project_id, request_key),
  FOREIGN KEY (tenant_id, project_id, period_start) REFERENCES core.budgets (tenant_id, project_id, period_start),
  CONSTRAINT reservation_commit_has_actual CHECK (status <> 'COMMITTED' OR actual_micros IS NOT NULL)
);

-- usage ledger: append-only; corrections are reversal entries (p.48)
CREATE TABLE core.usage_ledger (
  tenant_id         uuid        NOT NULL,
  entry_id          uuid        NOT NULL DEFAULT gen_random_uuid(),
  project_id        uuid,
  entry_kind        text        NOT NULL CHECK (entry_kind IN ('credit_purchase','credit_grant','model_usage','runner_minutes','storage','subscription_fee','adjustment','refund')),
  customer_micros   bigint      NOT NULL,   -- signed: credits > 0, charges < 0 (customer balance view)
  provider_cost_micros bigint   NOT NULL DEFAULT 0 CHECK (provider_cost_micros >= 0),  -- our cost (margin analysis)
  receipt_id        uuid,       -- ctx.provider_usage_receipts
  reverses_entry_id uuid,
  idempotency_key   text        NOT NULL,
  price_table_version text      NOT NULL,
  recorded_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, entry_id),
  UNIQUE (tenant_id, idempotency_key),
  FOREIGN KEY (tenant_id, reverses_entry_id) REFERENCES core.usage_ledger (tenant_id, entry_id),
  CONSTRAINT ledger_sign CHECK (
    (entry_kind IN ('credit_purchase','credit_grant','refund') AND customer_micros > 0) OR
    (entry_kind IN ('model_usage','runner_minutes','storage','subscription_fee') AND customer_micros < 0) OR
    entry_kind = 'adjustment')
);
CREATE TRIGGER usage_ledger_append_only BEFORE UPDATE OR DELETE ON core.usage_ledger FOR EACH ROW EXECUTE FUNCTION core.forbid_mutation();

CREATE OR REPLACE FUNCTION core.enforce_reversal() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE o core.usage_ledger%ROWTYPE;
BEGIN
  IF NEW.reverses_entry_id IS NULL THEN RETURN NEW; END IF;
  IF NEW.entry_kind <> 'adjustment' THEN RAISE EXCEPTION 'reversals must be adjustment entries' USING ERRCODE = 'check_violation'; END IF;
  SELECT * INTO o FROM core.usage_ledger WHERE tenant_id = NEW.tenant_id AND entry_id = NEW.reverses_entry_id;
  IF NEW.customer_micros <> -o.customer_micros THEN RAISE EXCEPTION 'reversal must negate the original amount' USING ERRCODE = 'check_violation'; END IF;
  IF EXISTS (SELECT 1 FROM core.usage_ledger WHERE tenant_id = NEW.tenant_id AND reverses_entry_id = NEW.reverses_entry_id) THEN
    RAISE EXCEPTION 'entry already reversed' USING ERRCODE = 'unique_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER usage_ledger_reversal BEFORE INSERT ON core.usage_ledger FOR EACH ROW EXECUTE FUNCTION core.enforce_reversal();

CREATE OR REPLACE FUNCTION core.credit_balance(p_tenant uuid) RETURNS bigint
LANGUAGE sql STABLE AS $$ SELECT coalesce(sum(customer_micros), 0)::bigint FROM core.usage_ledger WHERE tenant_id = p_tenant $$;

-- Reserve BEFORE any provider call. Fails closed if the project cap OR the tenant's prepaid credit would be exceeded.
-- Idempotent on request_key. Serialized per tenant (advisory xact lock) so concurrent reservations cannot overshoot.
CREATE OR REPLACE FUNCTION core.reserve_cost(p_tenant uuid, p_project uuid, p_period date, p_key text, p_amount bigint)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE v_cap bigint; v_used bigint; v_tenant_open bigint; v_credit bigint;
BEGIN
  IF EXISTS (SELECT 1 FROM core.cost_reservations WHERE tenant_id = p_tenant AND project_id = p_project AND request_key = p_key) THEN
    RETURN;
  END IF;
  -- one transaction-scoped lock per tenant serializes cap AND credit checks (no UPDATE privilege on budgets needed)
  PERFORM pg_advisory_xact_lock(hashtextextended('core.credit:' || p_tenant::text, 0));
  SELECT cap_micros INTO v_cap FROM core.budgets WHERE tenant_id = p_tenant AND project_id = p_project AND period_start = p_period;
  IF NOT FOUND THEN RAISE EXCEPTION 'BUDGET_MISSING' USING ERRCODE = 'check_violation'; END IF;
  SELECT coalesce(sum(CASE WHEN status = 'RESERVED' THEN reserved_micros ELSE coalesce(actual_micros, 0) END), 0)
    INTO v_used FROM core.cost_reservations
   WHERE tenant_id = p_tenant AND project_id = p_project AND period_start = p_period AND status IN ('RESERVED','COMMITTED');
  IF v_used + p_amount > v_cap THEN
    RAISE EXCEPTION 'BUDGET_EXCEEDED project cap % used % request %', v_cap, v_used, p_amount USING ERRCODE = 'check_violation';
  END IF;
  SELECT coalesce(sum(reserved_micros), 0) INTO v_tenant_open FROM core.cost_reservations WHERE tenant_id = p_tenant AND status = 'RESERVED';
  v_credit := core.credit_balance(p_tenant);
  IF v_credit - v_tenant_open < p_amount THEN
    RAISE EXCEPTION 'CREDIT_EXHAUSTED balance % open reservations % request %', v_credit, v_tenant_open, p_amount USING ERRCODE = 'check_violation';
  END IF;
  INSERT INTO core.cost_reservations (tenant_id, project_id, request_key, period_start, reserved_micros)
  VALUES (p_tenant, p_project, p_key, p_period, p_amount);
END $$;

-- Settle after the provider responds: commit actual usage and write the ledger charge in the same transaction.
CREATE OR REPLACE FUNCTION core.settle_reservation(p_tenant uuid, p_project uuid, p_key text, p_actual_customer bigint,
                                                   p_actual_provider_cost bigint, p_receipt uuid, p_price_table text)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  UPDATE core.cost_reservations SET status = 'COMMITTED', actual_micros = p_actual_customer
   WHERE tenant_id = p_tenant AND project_id = p_project AND request_key = p_key AND status = 'RESERVED';
  IF NOT FOUND THEN RAISE EXCEPTION 'reservation % not open', p_key USING ERRCODE = 'no_data_found'; END IF;
  INSERT INTO core.usage_ledger (tenant_id, project_id, entry_kind, customer_micros, provider_cost_micros, receipt_id, idempotency_key, price_table_version)
  VALUES (p_tenant, p_project, 'model_usage', -p_actual_customer, p_actual_provider_cost, p_receipt, 'settle:' || p_key, p_price_table);
END $$;

-- ---------------------------------------------------------------- RLS (tenant AND project where the table has project_id)
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['projects','provider_allowlist','commands','runs','tasks','candidates','gate_results','reviews','approvals','budgets','cost_reservations'] LOOP
    EXECUTE format('ALTER TABLE core.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE core.%I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format($p$CREATE POLICY %I ON core.%I USING (tenant_id = core.current_tenant() AND project_id = ANY (core.current_projects()))
                      WITH CHECK (tenant_id = core.current_tenant() AND project_id = ANY (core.current_projects()))$p$, t || '_isolation', t);
  END LOOP;
  FOREACH t IN ARRAY ARRAY['tenants','agents','reviewer_qualifications','domain_events','outbox','inbox_dedup','side_effect_intents','usage_ledger'] LOOP
    EXECUTE format('ALTER TABLE core.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE core.%I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format($p$CREATE POLICY %I ON core.%I USING (tenant_id = core.current_tenant()) WITH CHECK (tenant_id = core.current_tenant())$p$, t || '_isolation', t);
  END LOOP;
END $$;

-- ---------------------------------------------------------------- grants (no DELETE; column-scoped UPDATE)
REVOKE ALL ON ALL TABLES IN SCHEMA core FROM PUBLIC;
GRANT USAGE ON SCHEMA core TO core_app;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA core TO core_app;
GRANT UPDATE (status, confirmed_by, confirmed_at) ON core.commands TO core_app;
GRANT UPDATE (status) ON core.runs TO core_app;
GRANT UPDATE (status, version, lease_holder, lease_epoch, lease_expires_at, base_sha) ON core.tasks TO core_app;
GRANT UPDATE (status, head_sha) ON core.candidates TO core_app;
GRANT UPDATE (join_state, connection_state, execution_state, credential_state) ON core.agents TO core_app;
GRANT UPDATE (state_version) ON core.projects TO core_app;
GRANT UPDATE (published_at, attempts) ON core.outbox TO core_app;
GRANT UPDATE (status, external_ref) ON core.side_effect_intents TO core_app;
GRANT UPDATE (status, actual_micros) ON core.cost_reservations TO core_app;
GRANT UPDATE (revoked_at) ON core.provider_allowlist TO core_app;
GRANT SELECT ON core.tenants TO core_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA core TO core_app;
COMMIT;
