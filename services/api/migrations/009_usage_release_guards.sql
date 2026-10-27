-- Application extension: serialize scoped receipt writers and reservation
-- releases without changing canonical functions, policies or financial history.
BEGIN;
SET LOCAL ROLE ctx_owner;
SELECT set_config('evo.usage_added_schema_create',
  (NOT has_schema_privilege('core_owner','runtime','CREATE'))::text,true);
GRANT USAGE,CREATE ON SCHEMA runtime TO core_owner;

SET LOCAL ROLE core_owner;
CREATE OR REPLACE FUNCTION runtime.lock_usage_reservation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE reservation_status text;
BEGIN
  IF TG_OP<>'INSERT' OR TG_TABLE_SCHEMA<>'ctx' OR TG_TABLE_NAME<>'provider_usage_receipts'
     OR NEW.tenant_id IS DISTINCT FROM core.current_tenant()
     OR NOT coalesce(NEW.project_id=ANY(core.current_projects()),false) THEN
    RAISE EXCEPTION 'invalid scoped receipt source' USING ERRCODE='insufficient_privilege'; END IF;
  -- The core owner sees only the current RLS scope. ctx_gateway receives no
  -- core table privileges. Calls outside canonical reservations remain valid.
  SELECT status INTO reservation_status FROM core.cost_reservations
    WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
      AND request_key=NEW.call_id::text FOR UPDATE;
  IF reservation_status='RELEASED' THEN
    RAISE EXCEPTION 'receipt conflicts with released reservation' USING ERRCODE='check_violation'; END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION runtime.lock_usage_reservation() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION runtime.lock_usage_reservation() TO ctx_owner;

SET LOCAL ROLE ctx_owner;
DROP TRIGGER IF EXISTS usage_reservation_lock ON ctx.provider_usage_receipts;
CREATE TRIGGER usage_reservation_lock BEFORE INSERT ON ctx.provider_usage_receipts
  FOR EACH ROW EXECUTE FUNCTION runtime.lock_usage_reservation();

CREATE OR REPLACE FUNCTION runtime.reject_usage_release() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  IF TG_OP<>'UPDATE' OR TG_TABLE_SCHEMA<>'core' OR TG_TABLE_NAME<>'cost_reservations' THEN
    RAISE EXCEPTION 'invalid reservation source' USING ERRCODE='insufficient_privilege'; END IF;
  IF NEW.status='RELEASED' AND OLD.status IS DISTINCT FROM 'RELEASED' THEN
    IF NEW.tenant_id IS DISTINCT FROM ctx.current_tenant()
       OR NOT coalesce(NEW.project_id=ANY(ctx.current_projects()),false) THEN
      RAISE EXCEPTION 'invalid scoped release source' USING ERRCODE='insufficient_privilege'; END IF;
    -- UPDATE already holds the same row lock acquired by receipt INSERT.
    -- This separate statement sees usage committed during that lock wait.
    IF EXISTS (SELECT 1 FROM ctx.provider_usage_receipts WHERE tenant_id=NEW.tenant_id
        AND project_id=NEW.project_id AND call_id::text=NEW.request_key) THEN
      RAISE EXCEPTION 'recorded usage requires receipt reconciliation' USING ERRCODE='check_violation'; END IF;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION runtime.reject_usage_release() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION runtime.reject_usage_release() TO core_owner;

SET LOCAL ROLE core_owner;
DROP TRIGGER IF EXISTS usage_release_guard ON core.cost_reservations;
CREATE TRIGGER usage_release_guard BEFORE UPDATE ON core.cost_reservations
  FOR EACH ROW EXECUTE FUNCTION runtime.reject_usage_release();

SET LOCAL ROLE ctx_owner;
DO $$ BEGIN
  IF current_setting('evo.usage_added_schema_create')='true' THEN
    REVOKE CREATE ON SCHEMA runtime FROM core_owner;
  END IF;
END $$;
COMMIT;
