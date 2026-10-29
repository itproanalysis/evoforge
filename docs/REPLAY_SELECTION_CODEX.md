# Replay selection and refresh correctness

The Replay page retained the previous run while loading a newly selected one.
Its async interval could also write a late old-run response after selection
changed. A highlighted history item could therefore disagree with the preview.

The page now binds its state to the selected run ID and hides mismatched state
before effects execute. Cleanup invalidates the prior request's results and
timer. The loader rejects a response whose run ID differs from the request.
Polling is scheduled after each GET settles, only while that same run is
running, so slow requests do not overlap. Completed recorded runs do not poll.

Loading, empty, initial failure and stale refresh are separate states. Failed
refreshes may retain the last confirmed result for the SAME run, with an
explicit warning and retry. Failures cannot display another run's preview.
The messages are available in Korean and English; raw error bodies are not
rendered. All calls remain the existing read-only Evolution GET endpoints.

## Checks

- `scripts/check-replay-selection.mjs`: delayed old/new responses, mismatched
  IDs, initial errors, serialized polling, failed refresh/recovery, completed
  runs and cleanup passed with controlled promises/timers.
- Actual FastAPI Evolution GET payloads were passed to that TypeScript loader;
  late responses retained the selected run and manifest. Model calls are
  explicitly forbidden in the contract test.
- The HTTP contract plus independent T52 acceptance and Builder checks:
  14 passed, one upstream deprecation warning. Log:
  `.local/validation-replay-selection.log`.
- One Builder source-wiring assertion now reads the extracted loader's polling
  settings rather than requiring their literal text in the page. Its behavior
  is exercised by the new runtime tests; independent Critic tests are unchanged.
- TypeScript passed; final production build is recorded separately.

This is an isolated Web ownership exception on the Codex integration branch.
It does not establish authenticated Replay browser E2E, live model quality,
artifact capture, production deployment or public-service readiness.
