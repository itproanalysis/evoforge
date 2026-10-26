# EvoForge — GCP Deploy (asia-northeast3, minimal cost)

No secrets in repo. Seoul region default, scale-to-zero, `db-g1-small`.

## 0) Prereqs

```bash
gcloud auth login
gcloud config set project <PROJECT_ID>
gcloud config set run/region asia-northeast3
```

## 1) Bootstrap infra (APIs, VPC, SQL, bucket, secrets shells)

```bash
cd infra/gcp
terraform init
terraform apply -var="project=<PROJECT_ID>"
```

## 2) Secrets (values only via gcloud, never tf)

```bash
printf '%s' "$MODEL_API_KEY" | gcloud secrets versions add MODEL_API_KEY --data-file=-
printf '%s' "$GITHUB_TOKEN"  | gcloud secrets versions add GITHUB_TOKEN --data-file=-

# DB_URL from Cloud SQL private IP + terraform-generated password:
PW=$(terraform output -raw 2>/dev/null; echo) # or read from google_sql_user via console
# format: postgresql://evoforge:<PW>@<PRIVATE_IP>:5432/evoforge
printf '%s' "postgresql://evoforge:<PW>@<PRIVATE_IP>:5432/evoforge" \
  | gcloud secrets versions add DB_URL --data-file=-
```

## 3) Migrations (contract freeze — verbatim, no CHECK/trigger edits)

```bash
URL=$(gcloud secrets versions access latest --secret=DB_URL)
psql "$URL" -v ON_ERROR_STOP=1 -f ../../docs/evoforge-v4.2/contracts/sql/core_DRAFT.sql
psql "$URL" -v ON_ERROR_STOP=1 -f ../../docs/evoforge-v4.2/contracts/sql/context_plane_DRAFT.sql
# (Cloud Build `migrate` step does the same against private IP.)
```

## 4) Build + deploy via Cloud Build

```bash
# from repo root C:\evo_forge (build context root for Dockerfiles)
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_ENV=hackathon,_REGION=asia-northeast3 .
```

## 5) Wire web -> api + verify

```bash
API_URL=$(terraform -chdir=infra/gcp output -raw api_uri)
WEB_URL=$(terraform -chdir=infra/gcp output -raw web_uri)
echo "API: $API_URL  WEB: $WEB_URL"
curl "$API_URL/healthz"
# web already ships with NEXT_PUBLIC_API_BASE=$API_URL baked at build time
# (run.tf also injects it as runtime env). Rebuild web if API URL changed.
```

## 6) Post-hackathon lockdown

- `terraform`: SQL `deletion_protection=true`, `availability_type=REGIONAL`,
  `db-custom-*` tier, PITR on; bucket `force_destroy=false` (already).
- Remove `google_cloud_run_v2_service_iam_member.{api,web}_public`
  (public invoker) and front with LB + IAP / authenticated invoker.
- Rotate `DB_URL` + `MODEL_API_KEY` versions; restrict
  `roles/secretmanager.secretAccessor` to prod SA only.
