# VPC + Serverless VPC Access for Cloud Run -> Cloud SQL (private IP).
# NOTE: for direct private peering, google_service_networking_connection requires
# a pre-reserved /16 (here /20 minimal). This is the standard minimal setup.

resource "google_compute_network" "vpc" {
  name                    = "evoforge-vpc"
  project                 = var.project
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

resource "google_compute_subnetwork" "subnet" {
  name          = "evoforge-subnet"
  project       = var.project
  region        = var.region
  network       = google_compute_network.vpc.id
  ip_cidr_range = "10.10.0.0/24"
}

resource "google_compute_global_address" "private_ip_alloc" {
  name          = "evoforge-sql-peering-range"
  project       = var.project
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 20
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "peering" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_alloc.name]
  depends_on              = [google_project_service.apis]
}

resource "google_vpc_access_connector" "serverless" {
  name           = "evoforge-conn"
  project        = var.project
  region         = var.region
  network        = google_compute_network.vpc.name
  ip_cidr_range  = "10.8.0.0/28"
  min_throughput = 200
  max_throughput = 300
  depends_on     = [google_project_service.apis]
}
