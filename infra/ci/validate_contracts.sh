#!/usr/bin/env bash
# Cloud Build only: disposable python:3.12-slim-bookworm container, no external DB.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends git postgresql-15
python -m pip install --no-cache-dir -r tools/requirements-validation.txt

pg_ctlcluster 15 main status >/dev/null 2>&1 || pg_ctlcluster 15 main start
trap 'pg_ctlcluster 15 main stop' EXIT
runuser -u postgres -- createuser --host=/var/run/postgresql --port=5432 --username=postgres --superuser root

# Force the isolated local test cluster, never a deployment DATABASE_URL.
export PGHOST=/var/run/postgresql PGPORT=5432 PGUSER=root PGDATABASE=postgres
python -I docs/evoforge-v4.2/tools/validate_package.py --pg
