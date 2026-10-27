# Remote state: all applies (local or Cloud Build) share this bucket.
# Create once: gsutil mb -p var.project -l asia-northeast3 gs://evoforge-prod-4ff3-tfstate
terraform {
  backend "gcs" {
    bucket = "evoforge-prod-4ff3-tfstate"
    prefix = "evoforge/hackathon"
  }
}
