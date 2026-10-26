# Artifact Registry + Cloud Run services. Scale-to-zero for minimal cost.
# NOTE (demo): invoker = public (allUsers). Lock down post-hackathon (remove
# the IAM bindings, front with IAP / LB + auth).

resource "google_artifact_registry_repository" "images" {
  project       = var.project
  location      = var.region
  repository_id = "evoforge"
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

resource "google_cloud_run_v2_service" "api" {
  name     = "evoforge-api"
  project  = var.project
  location = var.region

  template {
    service_account = google_service_account.run.email
    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }

    vpc_access {
      connector = google_vpc_access_connector.serverless.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      # Set via Cloud Build substitution (default :latest placeholder).
      image = var.api_image != "" ? var.api_image : "${var.region}-docker.pkg.dev/${var.project}/evoforge/api:latest"

      ports { container_port = 8080 }

      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }

      env {
        name  = "MODEL_API_BASE"
        value = "https://api.meta.ai/v1"
      }
      env {
        name  = "MODEL_BUILDER"
        value = "muse-spark-1.3"
      }
      env {
        name  = "MODEL_CRITIC"
        value = "muse-spark-1.3"
      }
      env {
        name = "MODEL_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.model_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_url.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_service" "web" {
  name     = "evoforge-web"
  project  = var.project
  location = var.region

  template {
    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }

    containers {
      image = var.web_image != "" ? var.web_image : "${var.region}-docker.pkg.dev/${var.project}/evoforge/web:latest"

      ports { container_port = 3000 }

      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }

      env {
        name  = "NEXT_PUBLIC_API_BASE"
        value = google_cloud_run_v2_service.api.uri
      }
      env {
        name  = "PORT"
        value = "3000"
      }
    }

    max_instance_request_concurrency = 80
  }

  depends_on = [google_project_service.apis]
}

# Public invoker for demo only.
resource "google_cloud_run_v2_service_iam_member" "api_public" {
  project  = var.project
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "web_public" {
  project  = var.project
  location = var.region
  name     = google_cloud_run_v2_service.web.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "api_uri" {
  value = google_cloud_run_v2_service.api.uri
}

output "web_uri" {
  value = google_cloud_run_v2_service.web.uri
}
