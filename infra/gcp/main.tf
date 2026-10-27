# Provider defaults (versions pinned in versions.tf).
provider "google" {
  project = var.project
  region  = var.region
}
