# Secret Manager shells only — no values in tf. Values set via gcloud (see README_DEPLOY.md).

resource "google_secret_manager_secret" "model_api_key" {
  secret_id = "MODEL_API_KEY"
  project   = var.project
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "github_token" {
  secret_id = "GITHUB_TOKEN"
  project   = var.project
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "db_url" {
  secret_id = "DB_URL"
  project   = var.project
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

# Cloud Run runtime service account (least privilege; secrets granted below).
resource "google_service_account" "run" {
  account_id   = "evoforge-run-${var.env}"
  project      = var.project
  display_name = "EvoForge Cloud Run (${var.env})"
}

resource "google_secret_manager_secret_iam_member" "run_model_key" {
  project   = var.project
  secret_id = google_secret_manager_secret.model_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.run.email}"
}

resource "google_secret_manager_secret_iam_member" "run_db_url" {
  project   = var.project
  secret_id = google_secret_manager_secret.db_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.run.email}"
}

resource "google_secret_manager_secret_iam_member" "run_github" {
  project   = var.project
  secret_id = google_secret_manager_secret.github_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.run.email}"
}
