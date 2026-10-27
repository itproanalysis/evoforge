-- Durable application missions; the canonical core approval path is unchanged.
BEGIN;
SET LOCAL ROLE ctx_owner;
CREATE TABLE IF NOT EXISTS runtime.api_missions (
  tenant_id uuid NOT NULL, project_id uuid NOT NULL, mission_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id,project_id,mission_id),
  FOREIGN KEY (tenant_id,project_id) REFERENCES core.projects (tenant_id,project_id)
);
CREATE TABLE IF NOT EXISTS runtime.api_mission_versions (
  tenant_id uuid NOT NULL, project_id uuid NOT NULL, mission_id text NOT NULL,
  version bigint NOT NULL CHECK (version>0), document jsonb NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id,project_id,mission_id,version),
  FOREIGN KEY (tenant_id,project_id,mission_id) REFERENCES runtime.api_missions (tenant_id,project_id,mission_id),
  CHECK (coalesce(jsonb_typeof(document)='object' AND document->>'mission_id'=mission_id
    AND jsonb_typeof(document->'goal')='string' AND length(document->>'goal')>0
    AND jsonb_typeof(document->'repo_ref')='string' AND length(document->>'repo_ref')>0
    AND document->>'risk' IN ('LOW','MEDIUM','HIGH','CRITICAL')
    AND jsonb_typeof(document->'confirmed')='boolean'
    AND (document->>'risk' NOT IN ('HIGH','CRITICAL') OR document->'confirmed'='true'::jsonb)
    AND document->>'state' IN ('CREATED','GENERATED','REVIEWED','RAN','PR_OPENED','CANCELLED','FAILED'),false))
);
CREATE INDEX IF NOT EXISTS api_evidence_mission_lookup
  ON runtime.api_evidence_records(tenant_id,project_id,(document->>'mission_id'));

CREATE OR REPLACE FUNCTION runtime.mission_review_calls_valid(t uuid,p uuid,m text,d jsonb)
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE ids jsonb; n integer; valid boolean;
BEGIN
  ids:=d->'provider_evidence_ids';
  IF ids IS NULL THEN RETURN true; END IF;
  IF jsonb_typeof(ids) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
  n:=jsonb_array_length(ids);
  IF n=0 THEN RETURN true; END IF;
  -- Phase A can finish with unusable/truncated tests, without a Phase B call.
  IF n>2 OR EXISTS (SELECT 1 FROM jsonb_array_elements(ids) v
      WHERE jsonb_typeof(v)<>'string' OR v#>>'{}'='') THEN RETURN false; END IF;
  SELECT count(*)=n AND count(DISTINCT e.id)=n AND bool_and(coalesce(
      e.document->>'kind'='provider_call'
      AND e.document->>'phase'=CASE refs.pos WHEN 1 THEN 'critic_spec' ELSE 'critic_review' END
      AND (e.document->>'mission_id' IS NULL OR e.document->>'mission_id'=m),false)) INTO valid
    FROM jsonb_array_elements_text(ids) WITH ORDINALITY refs(eid,pos)
    JOIN runtime.api_evidence_records e ON e.tenant_id=t AND e.project_id=p AND e.id=refs.eid;
  RETURN coalesce(valid,false);
END $$;

CREATE OR REPLACE FUNCTION runtime.mission_stage_valid(t uuid,p uuid,m text,s text,e text,stages jsonb)
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE d jsonb; required text[]; run_doc jsonb;
BEGIN
  SELECT document INTO d FROM runtime.api_evidence_records
    WHERE tenant_id=t AND project_id=p AND id=e AND document->>'mission_id'=m;
  IF NOT FOUND THEN RETURN false; END IF;
  IF s='generate' THEN
    IF jsonb_typeof(d->'candidate') IS DISTINCT FROM 'object'
       OR jsonb_typeof(d->'gates') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
    required:=ARRAY['Task','Candidate','Gate'];
  ELSIF s='review' THEN
    IF jsonb_typeof(d->'review') IS DISTINCT FROM 'object'
       OR NOT runtime.mission_review_calls_valid(t,p,m,d) THEN RETURN false; END IF;
    required:=ARRAY['Review'];
  ELSIF s='run' THEN
    IF jsonb_typeof(d->'run') IS DISTINCT FROM 'object'
       OR stages->>'review' IS NULL OR (d->>'review_evidence_id') IS DISTINCT FROM (stages->>'review')
       THEN RETURN false; END IF;
    required:=ARRAY['Candidate','Gate','Review'];
  ELSIF s='pr' THEN
    IF jsonb_typeof(d->'pr') IS DISTINCT FROM 'string' OR length(d->>'pr')=0
       OR stages->>'run' IS NULL OR (d->>'source_evidence_id') IS DISTINCT FROM (stages->>'run')
       THEN RETURN false; END IF;
    SELECT document INTO run_doc FROM runtime.api_evidence_records
      WHERE tenant_id=t AND project_id=p AND id=stages->>'run';
    IF NOT FOUND OR jsonb_typeof(run_doc->'gates') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
    IF jsonb_array_length(run_doc->'gates')=0 OR EXISTS (
        SELECT 1 FROM jsonb_array_elements(run_doc->'gates') g WHERE g->>'result' IS DISTINCT FROM 'PASS')
        THEN RETURN false; END IF;
    required:=ARRAY['Candidate','Gate','Review','PR'];
  ELSE RETURN false;
  END IF;
  RETURN NOT EXISTS (SELECT 1 FROM unnest(required) r(stage) WHERE NOT EXISTS (
    SELECT 1 FROM runtime.api_evidence_links l
      WHERE l.tenant_id=t AND l.project_id=p AND l.evidence_id=e AND l.stage=r.stage));
END $$;

CREATE OR REPLACE FUNCTION runtime.check_mission_version() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE prior runtime.api_mission_versions%ROWTYPE; k text; eid text; d jsonb; target text;
BEGIN
  IF jsonb_typeof(NEW.document->'evidence_ids') IS DISTINCT FROM 'array'
     OR jsonb_typeof(NEW.document->'stages') IS DISTINCT FROM 'object'
     OR NOT (NEW.document->'stages' ?& ARRAY['generate','review','run','pr'])
     OR (NEW.document->'stages')-ARRAY['generate','review','run','pr'] <> '{}'::jsonb THEN
    RAISE EXCEPTION 'invalid mission snapshot' USING ERRCODE='check_violation';
  END IF;
  SELECT * INTO prior FROM runtime.api_mission_versions WHERE tenant_id=NEW.tenant_id
    AND project_id=NEW.project_id AND mission_id=NEW.mission_id ORDER BY version DESC LIMIT 1;
  IF FOUND THEN
    IF NEW.version<>prior.version+1 THEN
      RAISE EXCEPTION 'mission version conflict' USING ERRCODE='check_violation'; END IF;
    FOREACH k IN ARRAY ARRAY['goal','repo_ref','target_paths','risk','confirmed','created_at'] LOOP
      IF (NEW.document->k) IS DISTINCT FROM (prior.document->k) THEN
        RAISE EXCEPTION 'mission input is immutable' USING ERRCODE='check_violation'; END IF;
    END LOOP;
    IF NOT ((NEW.document->'evidence_ids') @> (prior.document->'evidence_ids')) THEN
      RAISE EXCEPTION 'mission evidence cannot be removed' USING ERRCODE='check_violation'; END IF;
    IF (NEW.document->>'state') IS DISTINCT FROM (prior.document->>'state') AND NOT (
       (prior.document->>'state',NEW.document->>'state') IN
        (('CREATED','GENERATED'),('GENERATED','REVIEWED'),('REVIEWED','RAN'),('RAN','PR_OPENED'))
       OR (prior.document->>'state' IN ('CREATED','GENERATED','REVIEWED','RAN')
           AND NEW.document->>'state' IN ('CANCELLED','FAILED'))) THEN
      RAISE EXCEPTION 'illegal mission transition' USING ERRCODE='check_violation'; END IF;
    FOREACH k IN ARRAY ARRAY['generate','review','run','pr'] LOOP
      IF prior.document->'stages'->>k IS NOT NULL
         AND (NEW.document->'stages'->>k) IS DISTINCT FROM (prior.document->'stages'->>k) THEN
        RAISE EXCEPTION 'mission stage is immutable' USING ERRCODE='check_violation'; END IF;
    END LOOP;
  ELSIF NEW.version<>1 OR NEW.document->>'state' IS DISTINCT FROM 'CREATED'
        OR NEW.document->'evidence_ids'<>'[]'::jsonb
        OR NEW.document->'stages'<>'{"generate":null,"review":null,"run":null,"pr":null}'::jsonb THEN
    RAISE EXCEPTION 'mission must start empty and created' USING ERRCODE='check_violation';
  END IF;
  FOR eid IN SELECT jsonb_array_elements_text(NEW.document->'evidence_ids') LOOP
    SELECT document INTO d FROM runtime.api_evidence_records
      WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=eid;
    IF NOT FOUND THEN RAISE EXCEPTION 'mission evidence missing' USING ERRCODE='check_violation'; END IF;
    IF d->>'mission_id' IS DISTINCT FROM NEW.mission_id AND (
        d->>'mission_id' IS NOT NULL OR d->>'kind' IS DISTINCT FROM 'provider_call' OR NOT EXISTS (
        SELECT 1 FROM runtime.api_evidence_records parent
          WHERE parent.tenant_id=NEW.tenant_id AND parent.project_id=NEW.project_id
            AND parent.document->>'mission_id'=NEW.mission_id
            AND jsonb_typeof(parent.document->'review')='object'
            AND runtime.mission_review_calls_valid(NEW.tenant_id,NEW.project_id,NEW.mission_id,parent.document)
            AND (parent.document->'provider_evidence_ids') @> jsonb_build_array(eid))) THEN
      RAISE EXCEPTION 'mission evidence ownership differs' USING ERRCODE='check_violation'; END IF;
  END LOOP;
  FOREACH k IN ARRAY ARRAY['generate','review','run','pr'] LOOP
    eid:=NEW.document->'stages'->>k;
    IF eid IS NOT NULL AND (jsonb_typeof(NEW.document->'stages'->k)<>'string'
        OR NOT (NEW.document->'evidence_ids' ? eid)
        OR NOT runtime.mission_stage_valid(NEW.tenant_id,NEW.project_id,NEW.mission_id,k,eid,NEW.document->'stages')) THEN
      RAISE EXCEPTION 'mission stage evidence differs' USING ERRCODE='check_violation'; END IF;
    IF k='review' AND eid IS NOT NULL AND EXISTS (
        SELECT 1 FROM runtime.api_evidence_records parent
          CROSS JOIN LATERAL jsonb_array_elements_text(coalesce(parent.document->'provider_evidence_ids','[]'::jsonb)) refs(call_id)
          WHERE parent.tenant_id=NEW.tenant_id AND parent.project_id=NEW.project_id AND parent.id=eid
            AND NOT ((NEW.document->'evidence_ids') ? refs.call_id)) THEN
      RAISE EXCEPTION 'mission review requires call evidence' USING ERRCODE='check_violation'; END IF;
  END LOOP;
  IF (NEW.document->'stages'->>'review' IS NOT NULL AND NEW.document->'stages'->>'generate' IS NULL)
     OR (NEW.document->'stages'->>'run' IS NOT NULL AND NEW.document->'stages'->>'review' IS NULL)
     OR (NEW.document->'stages'->>'pr' IS NOT NULL AND NEW.document->'stages'->>'run' IS NULL) THEN
    RAISE EXCEPTION 'mission stage order differs' USING ERRCODE='check_violation'; END IF;
  target:=CASE NEW.document->>'state' WHEN 'GENERATED' THEN 'generate' WHEN 'REVIEWED' THEN 'review'
    WHEN 'RAN' THEN 'run' WHEN 'PR_OPENED' THEN 'pr' END;
  IF target IS NOT NULL AND NEW.document->'stages'->>target IS NULL THEN
    RAISE EXCEPTION 'mission state needs server evidence' USING ERRCODE='check_violation'; END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS mission_version_valid ON runtime.api_mission_versions;
CREATE TRIGGER mission_version_valid BEFORE INSERT ON runtime.api_mission_versions
  FOR EACH ROW EXECUTE FUNCTION runtime.check_mission_version();
DO $$ DECLARE tbl text; BEGIN
  FOREACH tbl IN ARRAY ARRAY['api_missions','api_mission_versions'] LOOP
    EXECUTE format('ALTER TABLE runtime.%I ENABLE ROW LEVEL SECURITY',tbl);
    EXECUTE format('ALTER TABLE runtime.%I FORCE ROW LEVEL SECURITY',tbl);
    EXECUTE format('DROP POLICY IF EXISTS mission_scope ON runtime.%I',tbl);
    EXECUTE format('CREATE POLICY mission_scope ON runtime.%I USING (tenant_id=core.current_tenant() AND project_id=ANY(core.current_projects())) WITH CHECK (tenant_id=core.current_tenant() AND project_id=ANY(core.current_projects()))',tbl);
    EXECUTE format('DROP TRIGGER IF EXISTS mission_immutable ON runtime.%I',tbl);
    EXECUTE format('CREATE TRIGGER mission_immutable BEFORE UPDATE OR DELETE ON runtime.%I FOR EACH ROW EXECUTE FUNCTION runtime.reject_binding_mutation()',tbl);
    EXECUTE format('REVOKE ALL ON runtime.%I FROM PUBLIC',tbl);
    EXECUTE format('GRANT SELECT,INSERT ON runtime.%I TO core_app',tbl);
  END LOOP;
END $$;
COMMIT;
