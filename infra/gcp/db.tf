# Cloud SQL Postgres 15, private IP only. Minimal cost for hackathon.
# Migrations (docs/evoforge-v4.2/contracts/sql/core_DRAFT.sql +
# context_plane_DRAFT.sql) are applied via Cloud Build (psql step in
# infra/gcp/cloudbuild.yaml) — no CHECK/trigger changes per contract freeze.

resource "random_password" "db" {
  length  = 24
  special = false
}

resource "google_sql_database_instance" "pg" {
  name             = "evoforge-pg-${var.env}"
  project          = var.project
  region           = var.region
  database_version = "POSTGRES_15"

  settings {
    tier              = var.db_tier
    edition           = "ENTERPRISE"
    availability_type = "ZONAL" # REGIONAL in prod
    disk_size         = 10
    disk_type         = "PD_SSD"

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = false # enable in prod
    }

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
    }

    database_flags {
      name  = "max_connections"
      value = "100"
    }
    database_flags {
      name  = "log_min_duration_statement"
      value = "1000"
    }
  }

  deletion_protection = false # true in prod
  depends_on          = [google_service_networking_connection.peering]
}

resource "google_sql_database" "db" {
  name     = "evoforge"
  project  = var.project
  instance = google_sql_database_instance.pg.name
}

resource "google_sql_user" "app" {
  name     = "evoforge"
  project  = var.project
  instance = google_sql_database_instance.pg.name
  password = random_password.db.result
}

output "db_connection_name" {
  value       = google_sql_database_instance.pg.connection_name
  description = "Cloud SQL connection name for Cloud Run connector / Cloud Build migrate step"
}

output "db_private_ip" {
  value = google_sql_database_instance.pg.private_ip_address
}
