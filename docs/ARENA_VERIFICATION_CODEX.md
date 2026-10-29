# Arena verification and cost provenance

Review candidate on `codex/sealed-scoring-r8`, based on release-8 `096b49b`.
Includes the earlier local Runner evidence and import-time exit refinements.
The release owner integrates it; no release worktree or production was changed.

## Behavior

- Baseline, pipeline and Arena lanes apply the existing candidate screen before
  applying or executing the candidate diff. A flagged candidate is unconfirmed,
  not a successful task or an assertion failure. The screen is conservative and
  incomplete; it is not an independent observer or an isolation boundary.
- Arena scoring retains genuine partial assertion results, but rejects malformed
  counts, nonzero-success exit inconsistencies and a failed integrity flag.
- A failed/unconfirmed lane cannot award its opponent a victory or a tie.
  The comparison returns `verdict.winner = inconclusive` instead.
- Model usage settlement remains intact even when verification is inconclusive.
- `usage_missing` and `cost_status` preserve cost provenance: `pending`,
  `incomplete`, `estimated` (reservation upper bound), or `usage_reported`
  (token usage priced by the configured rate). These are model API costs, not
  confirmed provider invoices or total Runner/build/platform costs.

`arena.py` ownership exception: the new Muse T44 scorer duplicated the counts-only
logic, so the same verification fix is applied here on an isolated branch.
Existing shared WIP is preserved. The model remains `muse-spark-1.3`.

## Checks

- 73 focused checks passed; two slow orchestration tests deselected. Includes a
  real partial-failure pytest subprocess and a FastAPI asynchronous job/read
  contract check. Provider/lane fixtures do not prove live model quality.
  Log: `.local/validation-arena-consistency.log`.
- Existing sealed T44 HTTP cases plus Runner report regressions: 16 passed,
  one upstream deprecation warning, 422.48s. Log:
  `.local/validation-arena-existing-http.log`.
- Frozen package validation and final release gates are recorded separately.
  No live paid evaluation, deployment, or public launch is claimed.

## v3.8 mapping and remaining work

Supports evidence-based snapshots, failed/inconclusive rounds, and honest cost
labels (SNAP-05, ARENA-02/04). This does not implement the R1–R5 snapshot engine,
capture storage, independent remote execution, or replay itself. Those remain
the owners' P0-A work in `V38_EVOLUTION_ARENA_PLAN.md`. Keys and recording stay
at submission time. The current static screen can be bypassed; SEC-02 and the
independent observer remain necessary before public execution.
