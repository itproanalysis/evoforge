-- Canonical core.commands owns lifecycle; extension keeps history and served responses.
BEGIN;
SET LOCAL ROLE core_owner;
GRANT REFERENCES (tenant_id,project_id,command_id) ON core.commands TO ctx_owner;
SET LOCAL ROLE ctx_owner;
CREATE TABLE IF NOT EXISTS runtime.api_command_history (
  tenant_id uuid NOT NULL, project_id uuid NOT NULL, command_id uuid NOT NULL,
  ordinal bigint NOT NULL CHECK (ordinal > 0), state text NOT NULL CHECK
    (state IN ('RECEIVED','VALIDATING','AWAITING_CONFIRMATION','PLANNED','DISPATCHED','APPLYING',
               'APPLIED','PARTIAL','BLOCKED','FAILED','REJECTED')),
  occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id,project_id,command_id,ordinal),
  FOREIGN KEY (tenant_id,project_id,command_id) REFERENCES core.commands (tenant_id,project_id,command_id)
);
CREATE TABLE IF NOT EXISTS runtime.api_command_results (
  tenant_id uuid NOT NULL, project_id uuid NOT NULL, command_id uuid NOT NULL,
  document jsonb NOT NULL CHECK (jsonb_typeof(document)='object'),
  evidence_id text GENERATED ALWAYS AS (document #>> '{evidence,id}') STORED NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id,project_id,command_id),
  FOREIGN KEY (tenant_id,project_id,command_id) REFERENCES core.commands (tenant_id,project_id,command_id),
  CONSTRAINT command_result_evidence_fk FOREIGN KEY (tenant_id,project_id,evidence_id)
    REFERENCES runtime.api_evidence_records (tenant_id,project_id,id),
  CONSTRAINT command_result_evidence_shape CHECK (coalesce(jsonb_typeof(document->'evidence')='object'
      AND jsonb_typeof(document #> '{evidence,id}')='string' AND length(evidence_id)>0,false)),
  CHECK (coalesce(document->>'command_id'='cmd_'||replace(command_id::text,'-',''),false))
);
-- Upgrade an earlier, unreleased 004 without editing its immutable responses.
-- Missing/unverifiable evidence aborts the migration instead of inventing it.
ALTER TABLE runtime.api_command_results ADD COLUMN IF NOT EXISTS evidence_id text
  GENERATED ALWAYS AS (document #>> '{evidence,id}') STORED;
ALTER TABLE runtime.api_command_results ALTER COLUMN evidence_id SET NOT NULL;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='runtime.api_command_results'::regclass
                 AND conname='command_result_evidence_fk') THEN
    ALTER TABLE runtime.api_command_results ADD CONSTRAINT command_result_evidence_fk
      FOREIGN KEY (tenant_id,project_id,evidence_id) REFERENCES runtime.api_evidence_records (tenant_id,project_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='runtime.api_command_results'::regclass
                 AND conname='command_result_evidence_shape') THEN
    ALTER TABLE runtime.api_command_results ADD CONSTRAINT command_result_evidence_shape
      CHECK (coalesce(jsonb_typeof(document->'evidence')='object'
        AND jsonb_typeof(document #> '{evidence,id}')='string' AND length(evidence_id)>0,false));
  END IF;
END $$;
CREATE OR REPLACE FUNCTION runtime.check_command_result() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  PERFORM 1 FROM core.commands c JOIN runtime.api_evidence_records e
    ON e.tenant_id=c.tenant_id AND e.project_id=c.project_id AND e.id=NEW.document #>> '{evidence,id}'
    WHERE c.tenant_id=NEW.tenant_id AND c.project_id=NEW.project_id AND c.command_id=NEW.command_id
      AND c.status='APPLIED' AND e.document->>'command_id'='cmd_'||replace(c.command_id::text,'-','')
      AND e.document->'candidate' IS NOT DISTINCT FROM NEW.document->'candidate'
      AND e.document->'gates' IS NOT DISTINCT FROM NEW.document->'gates'
    FOR SHARE OF c;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'command response requires an applied command and matching server evidence' USING ERRCODE='check_violation';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS command_result_state ON runtime.api_command_results;
CREATE TRIGGER command_result_state BEFORE INSERT ON runtime.api_command_results
  FOR EACH ROW EXECUTE FUNCTION runtime.check_command_result();
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['api_command_history','api_command_results'] LOOP
    EXECUTE format('ALTER TABLE runtime.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE runtime.%I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('DROP POLICY IF EXISTS command_scope ON runtime.%I',t);
    EXECUTE format('CREATE POLICY command_scope ON runtime.%I USING (tenant_id=core.current_tenant() AND project_id=ANY(core.current_projects())) WITH CHECK (tenant_id=core.current_tenant() AND project_id=ANY(core.current_projects()))',t);
    EXECUTE format('DROP TRIGGER IF EXISTS command_immutable ON runtime.%I',t);
    EXECUTE format('CREATE TRIGGER command_immutable BEFORE UPDATE OR DELETE ON runtime.%I FOR EACH ROW EXECUTE FUNCTION runtime.reject_binding_mutation()',t);
    EXECUTE format('REVOKE ALL ON runtime.%I FROM PUBLIC',t);
    EXECUTE format('GRANT SELECT,INSERT ON runtime.%I TO core_app',t);
  END LOOP;
END $$;
CREATE OR REPLACE FUNCTION runtime.guard_api_command_completion() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  IF NEW.payload->>'api_kind'='BUILD' AND NEW.status='APPLIED' AND NOT EXISTS (
      SELECT 1 FROM runtime.api_command_results WHERE tenant_id=NEW.tenant_id
        AND project_id=NEW.project_id AND command_id=NEW.command_id) THEN
    RAISE EXCEPTION 'API command completion requires a stored response' USING ERRCODE='check_violation';
  END IF;
  RETURN NULL;
END $$;
GRANT USAGE ON SCHEMA runtime TO core_owner;
SET LOCAL ROLE core_owner;
DROP TRIGGER IF EXISTS api_command_completion ON core.commands;
CREATE CONSTRAINT TRIGGER api_command_completion AFTER INSERT OR UPDATE ON core.commands
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION runtime.guard_api_command_completion();
COMMIT;
