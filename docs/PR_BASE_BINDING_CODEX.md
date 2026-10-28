# Public PR base binding handoff

The isolated `codex/pr-base-binding` change passes the immutable base returned
by the server Runner to `github.create_pr(expected_base_sha=...)` and rejects
missing, non-SHA or mutable bases before any GitHub request. The helper checks
that the target branch still points to the verified commit and reads the diff
and generated test file contents at that commit. A moved target returns 409.

This change does not complete canonical candidate, approval, billing, or live
deployment integration. It does not change the merge authorization path.

Two promoted test fixtures require owner review before integration. The T17
fake GitHub response used `basesha` while its mock Runner reported 40 `b`
characters. The T18 fake used `basesha` while its Runner executes a real Git
fixture. The isolated worktree contains uncommitted fixture corrections: T17
uses its Runner's existing SHA, and T18 uses the real fixture Git HEAD. Existing
success, conflict, content and held-out secrecy assertions remain intact.
The 33 focused tests passed with both corrections. The pre-correction failures
and focused runs are in `C:/evo_forge/.local/validation-pr-*-codex.log`.
Do not integrate the code without resolving and committing these owner-managed
fixture corrections and rerunning the required suite against the final tree.

The isolated tree with both fixture corrections passed the real local
PostgreSQL kernel suite (169 tests), frozen SQL/package validation, and web
`npm ci`, TypeScript check and production build. Logs are under
`C:/evo_forge/.local/validation-pr-*-codex.log`; the PostgreSQL kernel log is
`C:/evo_forge_codex_pr/.local/validation-kernel.log`.
The complete API suite passed 667 tests with one skipped on this same worktree,
including the two uncommitted fixture corrections; this does not establish a
green suite for the commit alone until those owner-managed changes are included.

The main checkout's pre-existing modified Runner and Critic test files were
not touched or included in this isolated validation.
