-- Project RLS hides sibling reservations from core.reserve_cost. Keep that
-- function and policy intact, and add a private tenant-wide credit guard.
BEGIN;
SET LOCAL ROLE ctx_owner;
SELECT set_config('evo.credit_added_schema_create',
  (NOT has_schema_privilege('core_owner','runtime','CREATE'))::text,true);
GRANT USAGE,CREATE ON SCHEMA runtime TO core_owner;
SET LOCAL ROLE core_owner;
CREATE TABLE IF NOT EXISTS runtime.tenant_credit_hold_events (
  tenant_id uuid NOT NULL, project_id uuid NOT NULL, reservation_key text NOT NULL,
  event_kind text NOT NULL CHECK (event_kind IN ('RESERVE','RELEASE')),
  amount_micros bigint NOT NULL,
  origin text NOT NULL CHECK (origin IN ('BACKFILL','TRIGGER')),
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id,project_id,reservation_key,event_kind),
  FOREIGN KEY (tenant_id,project_id,reservation_key)
    REFERENCES core.cost_reservations (tenant_id,project_id,request_key),
  CHECK ((event_kind='RESERVE' AND amount_micros>0) OR (event_kind='RELEASE' AND amount_micros<0))
);

-- Both tables belong to core_owner. Hold the source write lock while its owner
-- backfills all tenants; restore FORCE RLS in this transaction before commit.
-- Runtime callers never get wider project visibility or table privileges.
LOCK TABLE core.cost_reservations IN SHARE ROW EXCLUSIVE MODE;
ALTER TABLE core.cost_reservations NO FORCE ROW LEVEL SECURITY;
ALTER TABLE runtime.tenant_credit_hold_events NO FORCE ROW LEVEL SECURITY;
INSERT INTO runtime.tenant_credit_hold_events
  (tenant_id,project_id,reservation_key,event_kind,amount_micros,origin)
  SELECT tenant_id,project_id,request_key,'RESERVE',reserved_micros,'BACKFILL'
  FROM core.cost_reservations ON CONFLICT DO NOTHING;
INSERT INTO runtime.tenant_credit_hold_events
  (tenant_id,project_id,reservation_key,event_kind,amount_micros,origin)
  SELECT tenant_id,project_id,request_key,'RELEASE',-reserved_micros,'BACKFILL'
  FROM core.cost_reservations WHERE status IN ('COMMITTED','RELEASED') ON CONFLICT DO NOTHING;
ALTER TABLE core.cost_reservations FORCE ROW LEVEL SECURITY;
ALTER TABLE runtime.tenant_credit_hold_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime.tenant_credit_hold_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS credit_hold_tenant ON runtime.tenant_credit_hold_events;
CREATE POLICY credit_hold_tenant ON runtime.tenant_credit_hold_events
  USING (tenant_id=core.current_tenant()) WITH CHECK (tenant_id=core.current_tenant());
DROP TRIGGER IF EXISTS credit_hold_immutable ON runtime.tenant_credit_hold_events;
CREATE TRIGGER credit_hold_immutable BEFORE UPDATE OR DELETE ON runtime.tenant_credit_hold_events
  FOR EACH ROW EXECUTE FUNCTION core.forbid_mutation();
REVOKE ALL ON runtime.tenant_credit_hold_events FROM PUBLIC,core_app;

CREATE OR REPLACE FUNCTION runtime.tenant_open_reserved_micros() RETURNS numeric
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
  SELECT coalesce(sum(amount_micros),0) FROM runtime.tenant_credit_hold_events
    WHERE tenant_id=core.current_tenant()
$$;
REVOKE ALL ON FUNCTION runtime.tenant_open_reserved_micros() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION runtime.tenant_open_reserved_micros() TO core_app;

CREATE OR REPLACE FUNCTION runtime.track_tenant_credit_hold() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE credit bigint; held numeric;
BEGIN
  IF TG_RELID<>'core.cost_reservations'::regclass OR TG_TABLE_SCHEMA<>'core'
     OR TG_TABLE_NAME<>'cost_reservations' OR NEW.tenant_id IS DISTINCT FROM core.current_tenant() THEN
    RAISE EXCEPTION 'invalid credit hold source' USING ERRCODE='insufficient_privilege'; END IF;
  IF TG_OP='INSERT' THEN
    IF NEW.status<>'RESERVED' THEN
      RAISE EXCEPTION 'reservation must start reserved' USING ERRCODE='check_violation'; END IF;
    -- Same lock as the canonical reservation function; no extra external call.
    PERFORM pg_advisory_xact_lock(hashtextextended('core.credit:'||NEW.tenant_id::text,0));
    -- One statement snapshot keeps credit and releases coherent when another
    -- transaction settles concurrently. Releases need no additional credit lock.
    SELECT core.credit_balance(NEW.tenant_id),coalesce(sum(amount_micros),0)
      INTO credit,held FROM runtime.tenant_credit_hold_events WHERE tenant_id=NEW.tenant_id;
    IF credit-held<NEW.reserved_micros THEN
      RAISE EXCEPTION 'CREDIT_EXHAUSTED tenant-wide open reservations' USING ERRCODE='check_violation'; END IF;
    INSERT INTO runtime.tenant_credit_hold_events
      (tenant_id,project_id,reservation_key,event_kind,amount_micros,origin)
      VALUES (NEW.tenant_id,NEW.project_id,NEW.request_key,'RESERVE',NEW.reserved_micros,'TRIGGER');
  ELSIF TG_OP='UPDATE' THEN
    IF (NEW.tenant_id,NEW.project_id,NEW.request_key,NEW.period_start,NEW.reserved_micros)
       IS DISTINCT FROM (OLD.tenant_id,OLD.project_id,OLD.request_key,OLD.period_start,OLD.reserved_micros) THEN
      RAISE EXCEPTION 'reservation binding is immutable' USING ERRCODE='check_violation'; END IF;
    IF NEW.status IS DISTINCT FROM OLD.status THEN
      IF OLD.status<>'RESERVED' OR NEW.status NOT IN ('COMMITTED','RELEASED') THEN
        RAISE EXCEPTION 'closed reservation cannot be reopened' USING ERRCODE='check_violation'; END IF;
      INSERT INTO runtime.tenant_credit_hold_events
        (tenant_id,project_id,reservation_key,event_kind,amount_micros,origin)
        VALUES (NEW.tenant_id,NEW.project_id,NEW.request_key,'RELEASE',-NEW.reserved_micros,'TRIGGER');
    END IF;
  ELSE RAISE EXCEPTION 'invalid credit hold operation' USING ERRCODE='insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION runtime.track_tenant_credit_hold() FROM PUBLIC;
DROP TRIGGER IF EXISTS tenant_credit_hold ON core.cost_reservations;
CREATE TRIGGER tenant_credit_hold AFTER INSERT OR UPDATE ON core.cost_reservations
  FOR EACH ROW EXECUTE FUNCTION runtime.track_tenant_credit_hold();
SET LOCAL ROLE ctx_owner;
DO $$ BEGIN
  IF current_setting('evo.credit_added_schema_create')='true' THEN
    REVOKE CREATE ON SCHEMA runtime FROM core_owner;
  END IF;
END $$;
COMMIT;
