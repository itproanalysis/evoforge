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

echo "== build (tests gate the images)"
"$GCLOUD" builds submit --project "$PROJECT" --config infra/gcp/cloudbuild.prod.yaml \
  --substitutions "_REGION=${REGION},_TAG=${TAG}" .

echo "== runner: no secrets, no roles, private, one job per instance"
"$GCLOUD" run deploy evoforge-runner --project "$PROJECT" --region "$REGION" --image "${REG}/runner:${TAG}" \
  --service-account "$(SA runner)" --no-allow-unauthenticated --port 8081 \
  --cpu 2 --memory 2Gi --concurrency 1 --min-instances 0 --max-instances 3 --timeout 900 --quiet

echo "== api: private; only the web SA may invoke; Meta key + GitHub token from Secret Manager"
# max-instances 1 until the request path is on Cloud SQL (in-memory evidence/ledger must stay on one instance).
"$GCLOUD" run deploy evoforge-api --project "$PROJECT" --region "$REGION" --image "${REG}/api:${TAG}" \
  --service-account "$(SA api)" --no-allow-unauthenticated --port 8080 \
  --cpu 1 --memory 1Gi --min-instances 1 --max-instances 1 --timeout 900 \
  --set-secrets "MODEL_API_KEY=MODEL_API_KEY:latest,GITHUB_TOKEN=GITHUB_TOKEN:latest" \
  --set-env-vars "^@^MODEL_API_BASE=https://api.meta.ai/v1@MODEL_BUILDER=muse-spark-1.3@MODEL_CRITIC=muse-spark-1.3@GITHUB_REPO=${GITHUB_REPO}@EVO_REQUIRE_ID_TOKEN=1@EVO_API_URL=${API_URL}@EVO_WEB_SERVICE_ACCOUNT=$(SA web)@EVO_RUNNER_URL=${RUNNER_URL}@EVO_RUNNER_AUDIENCE=${RUNNER_URL}@EVO_ALLOW_LOCAL_REPOS=0@EVO_WEB_ORIGINS=" \
  --quiet

echo "== web: public origin, app-level owner login; calls the API server-side with its ID token"
"$GCLOUD" run deploy evoforge-web --project "$PROJECT" --region "$REGION" --image "${REG}/web:${TAG}" \
  --service-account "$(SA web)" --allow-unauthenticated --port 3000 \
  --cpu 1 --memory 512Mi --min-instances 0 --max-instances 3 \
  --set-secrets "EVO_SESSION_SECRET=EVO_SESSION_SECRET:latest,EVO_OWNER_PASSWORD_HASH=EVO_OWNER_PASSWORD_HASH:latest" \
  --set-env-vars "EVO_API_BASE=${API_URL},EVO_OWNER_USER=${OWNER_USER}" --quiet

echo "== invoker bindings (least privilege)"
"$GCLOUD" run services add-iam-policy-binding evoforge-api --project "$PROJECT" --region "$REGION" \
  --member "serviceAccount:$(SA web)" --role roles/run.invoker --quiet >/dev/null
"$GCLOUD" run services add-iam-policy-binding evoforge-runner --project "$PROJECT" --region "$REGION" \
  --member "serviceAccount:$(SA api)" --role roles/run.invoker --quiet >/dev/null

echo "== done"
"$GCLOUD" run services list --project "$PROJECT" --region "$REGION" --format "table(metadata.name,status.url)"
