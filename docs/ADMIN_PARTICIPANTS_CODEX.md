# Project participant view

`GET /v1/participants` reports only agents tied to the configured project by
an existing task lease holder, candidate author, or reviewer row. Roles are
`lease_holder`, `builder`, and `reviewer`; lease holder does not assert that the
lease is still active. Agent kind and the four separate recorded states are
returned without inventing names or claiming a person is active. Tenant agents
with no project-linked evidence are not included. A 1,000-row cap has an
explicit `has_more` flag. Memory mode reports unavailable; PostgreSQL failures
return 503 rather than an empty success.

The UI proxy must explicitly allow this path. Deployment needs a clean release
worktree and updated API and web services. This branch does not deploy.
Real PostgreSQL tests check project isolation, role derivation and HTTP output;
full API validation passed 667 with two skipped. The other worktree's modified
Runner and promoted test were not included. Provider identities, human names,
other chats and their status are not synthesized from process information.
