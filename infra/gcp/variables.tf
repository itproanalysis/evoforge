variable "project" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  default     = "asia-northeast3"
  description = "Seoul region (default, cost + latency)"
}

variable "env" {
  type        = string
  default     = "hackathon"
  description = "Environment label used in resource names/tags"
}

variable "db_tier" {
  type        = string
  default     = "db-g1-small"
  description = "Cloud SQL tier. db-g1-small is cheapest shared-core for hackathon; use db-custom-2-7680+ in prod."
}

variable "api_image" {
  type        = string
  default     = ""
  description = "Full Artifact Registry path for API image (set via Cloud Build substitution). Empty = not yet built."
}

variable "web_image" {
  type        = string
  default     = ""
  description = "Full Artifact Registry path for WEB image (set via Cloud Build substitution). Empty = not yet built."
}
