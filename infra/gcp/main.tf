variable "project" { type = string }
variable "region" { type = string default = "asia-northeast3" }

# Real service (Phase H1): Cloud Run api+web, Cloud SQL pg15, GCS evidence (CMEK), Secret Manager.
# Full resources land in D4-5; this file pins provider + naming so `terraform init` works now.
terraform {
  required_version = ">= 1.9"
  required_providers {
    google = { source = "hashicorp/google", version = ">= 5.40" }
  }
}
provider "google" { project = var.project, region = var.region }
