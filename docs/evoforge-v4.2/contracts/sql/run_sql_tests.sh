#!/usr/bin/env bash
# Usage: PGHOST=... PGUSER=<superuser> ./run_sql_tests.sh   (creates and drops a throwaway database)
set -euo pipefail
DB="evoforge_test_$$"
cd "$(dirname "$0")"
ROLES="ctx_owner, ctx_gateway, ctx_security, core_owner, core_app"
psql -q -c "DROP ROLE IF EXISTS $ROLES" >/dev/null 2>&1 || true
psql -v ON_ERROR_STOP=1 -q -c "CREATE DATABASE $DB"
trap 'psql -q -c "DROP DATABASE IF EXISTS $DB" >/dev/null; psql -q -c "DROP ROLE IF EXISTS $ROLES" >/dev/null 2>&1 || true' EXIT
psql -v ON_ERROR_STOP=1 -q -t -A -d "$DB" -f roles_TEST_ONLY.sql \
  -f context_plane_DRAFT.sql -f context_plane_tests.sql \
  -f core_DRAFT.sql -f core_tests.sql 2>&1 | sed -E "s/^psql:[^ ]+ NOTICE:  //" | grep -v "^$"
