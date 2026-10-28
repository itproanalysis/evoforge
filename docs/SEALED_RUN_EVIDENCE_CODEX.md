# Sealed evaluation execution evidence

Candidate branch: `codex/eval-run-evidence`, based on release-8 `45cffa6`.
This is a review candidate, not a deployment or a new model benchmark.

## Change

The API's local Runner now collects pytest's per-test summary and compares it
with the JUnit node IDs, module coverage, statuses and process exit code, using
the same comparison as the Runner service. The result includes
`report_integrity` rather than trusting passing JUnit counts alone.

All three sealed scoring paths (local, local with diagnostics, remote) require
integer counts at least as large as the snippet count, all tests passing, and
an integer zero exit code. The local channel check also checks module coverage.
A supplied `report_integrity` flag must be exactly
`True`. A missing remote flag remains compatible with older Runner versions;
this compatibility does not establish independently observed execution.

When local evidence channels disagree, baseline and pipeline task rows report
`verification_inconclusive` with score zero. They do not parse a contradictory
report for assertion feedback. The provider usage settlement still happens:
an unconfirmed result does not erase money already spent on the model call.

## Scope

The pytest summary and JUnit are both produced by the same child process.
Agreement is a consistency check, not an independent observer, a sandbox, or a
signed execution proof. Fresh interpreters per held-out file, the independent
observer, and the sealed candidate diff screen remain separate W22 work.
The model remains Muse Spark; no model key, live paid evaluation, production
database, frozen contract, merge authorization, or deployment was changed.

## Validation

The focused tests cover remote malformed/contradictory results, legacy flag
compatibility, local inconclusive diagnostics, actual passing and failing
pytest subprocesses, and baseline/pipeline task outcomes with usage settlement.
The provider response in the orchestration tests is deterministic; these are
regressions, not evidence of live model quality.

- Focused regressions: 20 passed in 309.44s, including actual subprocesses and
  both evaluation/settlement paths. After extracting the outcome classifier,
  its cases and the 18 non-orchestration checks passed again; raw log:
  `.local/validation-eval-evidence-final.log`.
- Frozen package validation: zero failures (without `--pg`).
- Existing Runner report checks plus the sealed baseline regression file are
  still running separately. No full API result is claimed for this branch.
- No database or web changes in this branch. Full API/PG release gates and
  integration with the current release remain required before deployment.
