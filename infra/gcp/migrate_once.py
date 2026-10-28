"""One-shot Cloud SQL provisioner (run by the release captain, not CI).

Order: roles -> contract files verbatim -> service migrations in order ->
hackathon seed. Each file runs in its own transaction (ON_ERROR_STOP
semantics); NOTHING is edited. Root password comes from env SQLROOT_PW.
Secrets never print.
"""

import glob
import os
import sys

import psycopg

HOST = os.environ.get("PGHOST", "34.158.214.106")
PORT = int(os.environ.get("PGPORT", "5432"))
SSLMODE = os.environ.get("PGSSLMODE", "require")
DB = "evoforge"

FILES = [
    "docs/evoforge-v4.2/contracts/sql/core_DRAFT.sql",
    "docs/evoforge-v4.2/contracts/sql/context_plane_DRAFT.sql",
    *(sorted(glob.glob("services/api/migrations/[0-9]*.sql"))),
    "infra/gcp/seed_hackathon.sql",
]

# Only the files from the documented initial provisioning incident may be
# acknowledged by its recovery procedure. Never derive this from the glob.
LEGACY_RECOVERY_FILES = frozenset([
    "docs/evoforge-v4.2/contracts/sql/core_DRAFT.sql",
    "docs/evoforge-v4.2/contracts/sql/context_plane_DRAFT.sql",
    "services/api/migrations/001_receipt_documents.sql",
    "services/api/migrations/002_builder_call_bindings.sql",
    "services/api/migrations/003_api_evidence.sql",
    "services/api/migrations/004_api_commands.sql",
    "services/api/migrations/005_runner_candidates.sql",
    "services/api/migrations/006_api_missions.sql",
    "services/api/migrations/007_tenant_credit_holds.sql",
    "services/api/migrations/008_builder_candidates.sql",
    "services/api/migrations/009_usage_release_guards.sql",
    "services/api/migrations/010_candidate_pr_evidence.sql",
])

BOOTSTRAP = """
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'core_owner') THEN
    CREATE ROLE core_owner NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'core_app') THEN
    CREATE ROLE core_app NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ctx_owner') THEN
    CREATE ROLE ctx_owner NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ctx_gateway') THEN
    CREATE ROLE ctx_gateway NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ctx_security') THEN
    CREATE ROLE ctx_security NOLOGIN;
  END IF;
END $$;
GRANT core_app TO evoforge;
GRANT ctx_gateway TO evoforge;
GRANT ctx_security TO evoforge;
-- Cloud SQL superuser is not a full superuser: membership is required to
-- assume the contract owner roles used by *_DRAFT.sql (SET LOCAL ROLE).
GRANT core_owner TO postgres;
GRANT ctx_owner TO postgres;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE TABLE IF NOT EXISTS ops.applied_files (
  path text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);
"""


def run(connstr: str, sql: str, label: str, setup: str = "") -> None:
    with psycopg.connect(connstr, sslmode=SSLMODE, connect_timeout=30) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            if setup:
                cur.execute(setup)
            cur.execute(sql)
        conn.commit()
    print("applied:", label, flush=True)


def _already_applied(root: str, path: str) -> bool:
    try:
        with psycopg.connect(root, sslmode=SSLMODE, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM ops.applied_files WHERE path = %s", (path,))
                return cur.fetchone() is not None
    except Exception:
        raise RuntimeError("migration ledger unavailable") from None


def _mark_applied(root: str, path: str) -> None:
    with psycopg.connect(root, sslmode=SSLMODE, connect_timeout=30) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("INSERT INTO ops.applied_files (path) VALUES (%s) ON CONFLICT DO NOTHING", (path,))
        conn.commit()


def _recover_initial_provisioning(root: str) -> None:
    """Record only operator-verified files from the known initial incident."""
    with psycopg.connect(root, sslmode=SSLMODE, connect_timeout=30) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            for path in FILES:
                if path.replace("\\", "/") in LEGACY_RECOVERY_FILES:
                    cur.execute("INSERT INTO ops.applied_files (path) VALUES (%s) ON CONFLICT DO NOTHING", (path,))
        conn.commit()


def _check_marker(root: str, path: str) -> None:
    """Detect the known future-migration false marker without changing state."""
    if path.replace("\\", "/") != "services/api/migrations/011_performance_measurements.sql":
        return
    with psycopg.connect(root, sslmode=SSLMODE, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('runtime.performance_measurements') IS NOT NULL")
            row = cur.fetchone()
            if not row or row[0] is not True:
                raise RuntimeError("migration 011 is marked applied but its table is missing; operator reconciliation required")


def main() -> int:
    root_pw = os.environ.get("SQLROOT_PW", "")
    if not root_pw:
        print("SQLROOT_PW missing", flush=True)
        return 2
    root = f"postgresql://postgres:{root_pw}@{HOST}:{PORT}/{DB}"
    app_pw = os.environ.get("SQLAPP_PW", "")
    if not app_pw:
        print("SQLAPP_PW missing (needed for smoke check)", flush=True)
        return 2
    app = f"postgresql://evoforge:{app_pw}@{HOST}:{PORT}/{DB}"
    # bootstrap roles as superuser
    run(root, BOOTSTRAP, "roles+grants")
    # This is an operator assertion, not a conclusion from table existence.
    # Enable only after verifying that the initial provisioning incident really
    # committed every listed file; 011 and later are always handled normally.
    if os.environ.get("EVO_RECOVER_INITIAL_PROVISIONING") == "1":
        _recover_initial_provisioning(root)
        print("recovery: operator-verified initial files recorded", flush=True)
    for f in FILES:
        if _already_applied(root, f):
            _check_marker(root, f)
            print("skip (applied):", f, flush=True)
            continue
        sql = open(f, encoding="utf-8").read()
        if f.endswith("seed_hackathon.sql"):
            # Forced RLS applies even to owners: seed as the app role with
            # tenant/project session scope (policy: current_tenant()).
            setup = (
                "SET LOCAL ROLE core_app; "
                "SET LOCAL app.tenant_id = 'b0d28fa8-1323-4f13-bed5-e1ce1b649b40'; "
                "SET LOCAL app.project_ids = 'd46af903-5555-461b-91f1-9ce94fc336b9';"
            )
            run(app, sql, f, setup)
        else:
            run(root, sql, f)
        _mark_applied(root, f)
    # smoke check as the app user
    with psycopg.connect(app, sslmode=SSLMODE, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE core_app")
            cur.execute("SET LOCAL app.tenant_id = 'b0d28fa8-1323-4f13-bed5-e1ce1b649b40'")
            cur.execute("SET LOCAL app.project_ids = 'd46af903-5555-461b-91f1-9ce94fc336b9'")
            cur.execute("SELECT count(*) FROM core.projects")
            print("app smoke: core.projects =", cur.fetchone()[0], flush=True)
            cur.execute("SELECT count(*) FROM core.provider_allowlist")
            print("app smoke: allowlist =", cur.fetchone()[0], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
