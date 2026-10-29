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

The existing T50/T51 HTTP scenarios are running in
`.local/validation-rounds-existing-http.log`; final web/release gates are
recorded separately. These fixtures use deterministic provider responses.
They do not establish live model quality or a deployed R1–R5 experience.

## Still partial in the full v3.8 contract

Rendered HTML plus its digest is not a screenshot capture, a separately
versioned build, or a complete four-part immutable Snapshot Manifest.
Those capture/build/evidence/accounting artifacts, remote execution (SEC-02),
org isolation, cancellation and production browser E2E remain separate work.
This patch must not be described as completing SNAP-01..07 or public launch.
