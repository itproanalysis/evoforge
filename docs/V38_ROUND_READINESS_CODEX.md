# v3.8 round readiness corrections

Review branch: `codex/sealed-scoring-r8`. It now includes release-11 `e426e56`
and the completed Arena UI status/cost fixes; all integration happens in this
personal worktree. Release worktrees and shared unfinished files are preserved.

Source: the owner's *EvoForge v3.8 Evolution Arena & EvoCore Integrated
Improvement Plan*, and `V38_EVOLUTION_ARENA_PLAN.md` / `V36_EXECUTION_PLAN.md`.
The priority is P0-A: an actual application evolving through recorded rounds.
Keys, the Opus lane and recording remain deferred to submission.

## Implemented corrections (SNAP-05 and readiness prerequisites)

- Round scoring uses the same count/exit/report consistency check as Arena.
  A contradictory report cannot produce a verified round.
- Cumulative or round-only scoring uncertainty reaches orchestration as an
  explicit verification failure; it is not discarded when threads join.
- READY requires a nonempty rendered preview with its matching SHA-256 and
  no render error, as well as passing cumulative tests.
- A failed round keeps its own input files for subsequent recovery but has
  no candidate preview. It does not relabel the prior preview as this round.
- The existing candidate screen runs before round patch application.
- The T51 Builder self-check now requires the failed checkpoint's preview
  to be empty with an error. The independent Critic acceptance tests and the
  frozen v4.2 contracts are unchanged.

Ownership exception: `evolution_rounds.py` and the one Builder self-check
assertion implement these latest owner requirements on a personal integration
branch. No other agent's in-progress file is committed.

## Validation and limits

90 focused regressions passed (two slow orchestration cases deselected),
including positive/negative round readiness, failed-round preview separation,
actual pytest partial-failure handling and the Arena HTTP contract. Log:
`.local/validation-round-readiness.log`.

Existing T50/T51 HTTP scenarios: 9 passed in 305.14s, including five verified
rounds, a failed round with recovery, immutable/read-only replay, and Critic
feedback. Log: `.local/validation-rounds-existing-http.log`.

T51 Builder checks: 4 passed after tightening the failed-preview assertion.
The additional HTTP-to-TypeScript status contract initially exposed two old
fixture assumptions (empty base files, then inherited pending cost status).
Both fixtures were corrected for the real manifest/cost contract; the final
HTTP-to-UI check passed. Log: `.local/validation-arena-status-http-final.log`.

Clean npm ci, TypeScript, Arena presentation checks and production build passed
in this integration worktree. Logs: `.local/validation-web-*.log`.
Full API/PG release gates are still required. Deterministic provider fixtures
do not establish live model quality or a deployed R1–R5 experience.

Browser integration remains UNVERIFIED: custom local environment setup was
rejected by automatic approval review (`blocked by policy`, no further reason
supplied). Standard Next startup succeeded but its authenticated navigation
repeated a login redirect. No authentication was bypassed, no credentials were
requested, and no rendered screenshot or browser E2E completion is claimed.

## Still partial in the full v3.8 contract

Rendered HTML plus its digest is not a screenshot capture, a separately
versioned build, or a complete four-part immutable Snapshot Manifest.
Those capture/build/evidence/accounting artifacts, remote execution (SEC-02),
org isolation, cancellation and production browser E2E remain separate work.
This patch must not be described as completing SNAP-01..07 or public launch.
