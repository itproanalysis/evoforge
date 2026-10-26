# Evidence bucket: uniform access + CMEK, versioning on, cheap lifecycle.

resource "google_kms_key_ring" "evidence" {
  name     = "evoforge-evidence"
  project  = var.project
  location = var.region
  depends_on = [google_project_service.apis]
}

resource "google_kms_crypto_key" "evidence" {
  name            = "evidence-key"
  key_ring        = google_kms_key_ring.evidence.id
  rotation_period = "7776000s" # 90d
}

# Grant GCS service account use of the key (project format: service-<num>@gs-project-accounts.iam.gserviceaccount.com).
# Resolved at apply time via data source; kept explicit so `terraform validate` passes offline.
data "google_project" "self" {
  project_id = var.project
}

resource "google_kms_crypto_key_iam_binding" "gcs_use" {
  crypto_key_id = google_kms_crypto_key.evidence.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  members = [
    "serviceAccount:service-${data.google_project.self.number}@gs-project-accounts.iam.gserviceaccount.com",
  ]
}

resource "google_storage_bucket" "evidence" {
  name                        = "${var.project}-evoforge-evidence-${var.env}"
  project                     = var.project
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false # true only for throwaway envs

  versioning { enabled = true }

  encryption {
    default_kms_key_name = google_kms_crypto_key.evidence.id
  }

  lifecycle_rule {
    condition {
      age                   = 30
      with_state            = "ARCHIVED"
      matches_storage_class = ["STANDARD"]
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age                   = 365
      matches_storage_class = ["NEARLINE", "COLDLINE"]
    }
    action { type = "Delete" }
  }

  depends_on = [google_kms_crypto_key_iam_binding.gcs_use]
}
