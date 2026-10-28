#!/usr/bin/env bash
# EvoForge production deploy (Cloud Run, asia-northeast3). Idempotent; secrets come only from Secret Manager.
#   PROJECT=evoforge-prod-4ff3 TAG=$(git rev-parse --short HEAD) bash infra/gcp/deploy_prod.sh
# Prereqs (one-time, see docs/DEPLOY_PRODUCTION.md): APIs, Artifact Registry "evoforge", service accounts
# evoforge-{web,api,runner}, secrets MODEL_API_KEY, GITHUB_TOKEN, EVO_SESSION_SECRET, EVO_OWNER_PASSWORD_HASH.
set -euo pipefail
: "${PROJECT:?set PROJECT}"
REGION="${REGION:-asia-northeast3}"
TAG="${TAG:?set TAG}"
GITHUB_REPO="${GITHUB_REPO:-itproanalysis/evoforge-target}"
OWNER_USER="${OWNER_USER:-itproanalysis}"
GCLOUD="${GCLOUD:-gcloud}"
REG="${REGION}-docker.pkg.dev/${PROJECT}/evoforge"
NUM="$("$GCLOUD" projects describe "$PROJECT" --format='value(projectNumber)')"
API_URL="https://evoforge-api-${NUM}.${REGION}.run.app"
RUNNER_URL="https://evoforge-runner-${NUM}.${REGION}.run.app"
SA() { echo "evoforge-$1@${PROJECT}.iam.gserviceaccount.com"; }

# State backend. Every deploy sets the full env (--set-env-vars replaces it), so the PostgreSQL
# settings must travel with the provider/runner settings or one deploy silently drops the other.
STATE_SECRETS=""
STATE_ENV=""
if [ "${STATE_BACKEND:-memory}" = "postgres" ]; then
  : "${TENANT_ID:?set TENANT_ID (server-owned tenant UUID) for STATE_BACKEND=postgres}"
  : "${PROJECT_UUID:?set PROJECT_UUID (server-owned project UUID) for STATE_BACKEND=postgres}"
  STATE_SECRETS=",DATABASE_URL=DB_URL:latest"
  STATE_ENV="|EVO_STATE_BACKEND=postgres|EVO_TENANT_ID=${TENANT_ID}|EVO_PROJECT_ID=${PROJECT_UUID}"
fi

if [ "${SKIP_BUILD:-0}" != "1" ]; then
  echo "== build (tests gate the images)"
  "$GCLOUD" builds submit --project "$PROJECT" --config infra/gcp/cloudbuild.prod.yaml \
    --substitutions "_REGION=${REGION},_TAG=${TAG}" .
fi

echo "== runner: no secrets, no roles, private, one job per instance"
"$GCLOUD" run deploy evoforge-runner --project "$PROJECT" --region "$REGION" --image "${REG}/runner:${TAG}" \
  --service-account "$(SA runner)" --no-allow-unauthenticated --port 8081 \
  --cpu 2 --memory 2Gi --concurrency 1 --min-instances 0 --max-instances 3 --timeout 900 --quiet

echo "== api: private; only the web SA may invoke; Meta key + GitHub token from Secret Manager"
# CPU always allocated: eval jobs (T24) run after the response returns.
# max-instances 1 until the request path is on Cloud SQL (in-memory evidence/ledger must stay on one instance).
"$GCLOUD" run deploy evoforge-api --project "$PROJECT" --region "$REGION" --image "${REG}/api:${TAG}" \
  --service-account "$(SA api)" --no-allow-unauthenticated --port 8080 \
  --cpu 1 --memory 1Gi --min-instances 1 --max-instances 1 --timeout 900 --no-cpu-throttling \
  --set-secrets "MODEL_API_KEY=MODEL_API_KEY:latest,GITHUB_TOKEN=GITHUB_TOKEN:latest${STATE_SECRETS}" \
  --set-env-vars "^|^MODEL_API_BASE=https://api.meta.ai/v1|MODEL_BUILDER=muse-spark-1.3|MODEL_CRITIC=muse-spark-1.3|GITHUB_REPO=${GITHUB_REPO}|EVO_REQUIRE_ID_TOKEN=1|EVO_API_URL=${API_URL}|EVO_WEB_SERVICE_ACCOUNT=$(SA web)|EVO_RUNNER_URL=${RUNNER_URL}|EVO_RUNNER_AUDIENCE=${RUNNER_URL}|EVO_ALLOW_LOCAL_REPOS=0|EVO_WEB_ORIGINS=${STATE_ENV}" \
  --quiet

echo "== web: public origin, owner-only without login (EVO_WEB_AUTH=none, POST rate limit); calls the API server-side with its ID token"
"$GCLOUD" run deploy evoforge-web --project "$PROJECT" --region "$REGION" --image "${REG}/web:${TAG}" \
  --service-account "$(SA web)" --allow-unauthenticated --port 3000 \
  --cpu 1 --memory 512Mi --min-instances 0 --max-instances 3 \
  --set-secrets "EVO_SESSION_SECRET=EVO_SESSION_SECRET:latest,EVO_OWNER_PASSWORD_HASH=EVO_OWNER_PASSWORD_HASH:latest" \
  --set-env-vars "EVO_API_BASE=${API_URL},EVO_OWNER_USER=${OWNER_USER},EVO_WEB_AUTH=${WEB_AUTH:-none},EVO_WEB_POST_PER_MIN=${WEB_POST_PER_MIN:-20}" --quiet

echo "== invoker bindings (least privilege)"
"$GCLOUD" run services add-iam-policy-binding evoforge-api --project "$PROJECT" --region "$REGION" \
  --member "serviceAccount:$(SA web)" --role roles/run.invoker --quiet >/dev/null
"$GCLOUD" run services add-iam-policy-binding evoforge-runner --project "$PROJECT" --region "$REGION" \
  --member "serviceAccount:$(SA api)" --role roles/run.invoker --quiet >/dev/null

echo "== done"
"$GCLOUD" run services list --project "$PROJECT" --region "$REGION" --format "table(metadata.name,status.url)"
