# Performance measurement persistence

When `EVO_STATE_BACKEND=postgres`, new baseline and pipeline measurements are
stored in migration 011's project-scoped, append-only table and reference the
existing stored evaluation evidence. The adapter checks the evidence's model,
suite, counts, cost, scores and provider stub flag before inserting. Memory
mode remains ephemeral. PostgreSQL errors fail closed rather than falling back
to process memory. The API reports `storage: postgres` or `storage: memory`.

`provider_stub` is retained in newly measured records. A false value is an
adapter claim, not independent verification of the model or provider billing.
Older process-memory records cannot be recovered and absent provenance must
not be inferred. Neither this change nor stored evidence proves a production
deployment, full Broker integration or real model execution.

Evaluation evidence is committed before its measurement. If insertion fails,
the request fails and the existing evidence remains; this is not an atomic
two-record transaction and may require operator investigation. Apply migration
011 using the approved deployment path before deploying this API version.
The real PostgreSQL regression checks restart via a new adapter, tenant/project
isolation, missing evidence, manipulated counts, immutable records, and the
pipeline HTTP-to-evidence-to-measurement path. PostgreSQL kernel 169 tests and
the two targeted database checks passed. The full API suite passed 665 tests
with two skipped. The web tree is identical to the separately validated
`ad46bb5` tree (npm ci, TypeScript check and production build passed).
Testing uses synthetic fixtures, never live models or provider billing.
