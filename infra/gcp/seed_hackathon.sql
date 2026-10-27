-- EvoForge hackathon seed (NOT a contract change): tenant + project + Meta allowlist.
-- Apply AFTER core_DRAFT + context_plane + migrations 001-010, with ON_ERROR_STOP.
-- UUIDs mirror EVO_TENANT_ID / EVO_PROJECT_ID env on the API service.

INSERT INTO core.tenants (tenant_id, name, plan)
VALUES ('b0d28fa8-1323-4f13-bed5-e1ce1b649b40', 'evoforge-hackathon', 'TEAM')
ON CONFLICT (tenant_id) DO NOTHING;

INSERT INTO core.projects (tenant_id, project_id, name)
VALUES ('b0d28fa8-1323-4f13-bed5-e1ce1b649b40', 'd46af903-5555-461b-91f1-9ce94fc336b9', 'hackathon-default')
ON CONFLICT (tenant_id, project_id) DO NOTHING;

INSERT INTO core.provider_allowlist (tenant_id, project_id, provider, model_glob, data_consent_at, consented_by)
VALUES ('b0d28fa8-1323-4f13-bed5-e1ce1b649b40', 'd46af903-5555-461b-91f1-9ce94fc336b9', 'meta', 'muse-*', now(), 'b0d28fa8-1323-4f13-bed5-e1ce1b649b40')
ON CONFLICT (tenant_id, project_id, provider, model_glob) DO NOTHING;
