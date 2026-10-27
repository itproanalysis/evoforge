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
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id,project_id,command_id),
  FOREIGN KEY (tenant_id,project_id,command_id) REFERENCES core.commands (tenant_id,project_id,command_id),
  CHECK (coalesce(document->>'command_id'='cmd_'||replace(command_id::text,'-',''),false))
);
CREATE OR REPLACE FUNCTION runtime.check_command_result() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  PERFORM 1 FROM core.commands WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
    AND command_id=NEW.command_id AND status='APPLIED' FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'command response requires an applied command' USING ERRCODE='check_violation';
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
COMMIT;
