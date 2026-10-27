"""One-shot Cloud SQL provisioner (run by the release captain, not CI).

Order: roles -> contract files verbatim -> service migrations 001-010 ->
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
        return False


def _mark_applied(root: str, path: str) -> None:
    with psycopg.connect(root, sslmode=SSLMODE, connect_timeout=30) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("INSERT INTO ops.applied_files (path) VALUES (%s) ON CONFLICT DO NOTHING", (path,))
        conn.commit()


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
    # Recovery from the first provisioning run (2026-10-28): contract files +
    # migrations 001-010 all committed (each printed "applied"); only the seed
    # failed (forced RLS). If core.tenants exists, those files are done.
    try:
        with psycopg.connect(root, sslmode=SSLMODE, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM core.tenants LIMIT 1")
                contracts_done = True
    except Exception:
        contracts_done = False
    if contracts_done:
        with psycopg.connect(root, sslmode=SSLMODE, connect_timeout=30) as conn:
            conn.autocommit = False
            with conn.cursor() as cur:
                for f in FILES:
                    if not f.endswith("seed_hackathon.sql"):
                        cur.execute(
                            "INSERT INTO ops.applied_files (path) VALUES (%s) ON CONFLICT DO NOTHING",
                            (f,))
            conn.commit()
        print("recovery: contracts+migrations already applied", flush=True)
    for f in FILES:
        if _already_applied(root, f):
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
