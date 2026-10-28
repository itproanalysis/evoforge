# Coordination — ownership, release flow, comm rules

## 1. Module ownership (exclusive write access)

| Module | Owner | Paths |
|---|---|---|
| API core | Muse (release captain) | `services/api/main.py`, `services/api/evoforge/{broker_meta,ledger,commands,critic,github,hygiene_api,gates,missions,outcomes}.py` |
| Runner/hygiene | Codex | `services/api/evoforge/{runner,patch,repo_source,sealed_eval,eval_runner_and_preflight}.py`, `services/api/migrations/` |
| Web UI | agy + Muse-rounds | `apps/web/**` (Dockerfile changes need release-captain ack: it breaks deploys) |
| Infra/GCP | release captain | `infra/gcp/**`, `cloudbuild.yaml`, `services/api/Dockerfile` |
| Spec/contracts | frozen | `docs/evoforge-v4.2/**` — read-only, never edit (validate_package enforces) |
| Evals data | Codex | `evals/sealed_v0/**` (additive only; never weaken a held-out test) |

Check `git status` before you start. If another agent's uncommitted work sits in
your module, do not touch it — work on a branch.

## 2. Release flow (only way to production)

1. Feature work happens on personal branches (`codex/*`, `muse/*`, `agy/*`).
2. Release captain cuts `release/YYYY-MM-DD-N` from a commit where, LOCALLY:
   - `python -m pytest services/api -q` green (or the exact subset + full suite in CI),
   - `npx tsc --noEmit` green in `apps/web`,
   - `npm ci` green in a clean copy of `apps/web`.
3. The Cloud Build is submitted **from a pristine worktree of that commit only**:
   `git worktree add ../evoforge-rel-<sha> <sha>` then
   `gcloud builds submit <worktree> --substitutions=COMMIT_SHA=<sha>`.
   Never submit from a live workdir. Never submit with `git status` dirty.
4. After deploy: one live mission through the proxy to prove the chain, then
   record the outcome. A deploy without a live check is not done.

## 3. Why (incident log)

- Tarball raced half-written `package.json`/lock → `npm ci` EUSAGE (2 builds).
- Tarball raced half-written `test_eval_runner_and_preflight_cr.py` → 2 phantom
  CI failures on code that was already fixed in the tree (verified by diffing
  the GCS source tarball against the tree).
- `git add -A` swept other agents' `.kiro` and web WIP into release commits.
  All three are now banned by §1–§2.
- `gcloud run deploy` REPLACES the whole env block; another agent's deploy
  wiped MODEL_API_*/GITHUB_*/runner env and broke repo resolution. Shared
  services change env ONLY via `gcloud run services update` (merge) and
  record every env/secret change in this file.

## 4. Live systems (2026-10-27)

- Web: https://evoforge-web-230852112787.asia-northeast3.run.app
- API: https://evoforge-api-230852112787.asia-northeast3.run.app (private IAM, same-origin proxy)
- Demo target: https://github.com/itproanalysis/evoforge-target (PR #4, #5 merged)
- WVI: 1 (`msn_a3b777e1cfcf` → PR #6, outcome VALIDATED, postgres-backed)

## 5. Env/secret change log

- 2026-10-28 (Claude, release `release/2026-10-28-1` @ `0d8270b`, api rev `00016`): the two previous
  deploys each dropped half of the API env (21:35 deploy kept only PostgreSQL; 6fc0d72 deploy kept only
  provider/runner). `infra/gcp/deploy_prod.sh` now sets the full API env in one place:
  provider/runner/ID-token env + `STATE_BACKEND=postgres TENANT_ID PROJECT_UUID` →
  `DATABASE_URL=DB_URL:latest`, `EVO_STATE_BACKEND`, `EVO_TENANT_ID`, `EVO_PROJECT_ID`. Use the script
  (it is the source of truth for the env block) or `services update` for a single key, never a bare
  `run deploy` with a partial `--set-env-vars`.
- 2026-10-28 (Claude): migration 011 applied to Cloud SQL via `infra/gcp/migrate_once.py` (ledger had
  001–010 + seed; RLS/force, `performance_scope`, `performance_immutable`, core_app SELECT/INSERT verified).
  Cloud SQL `postgres` password was reset (owner approved); the only copy is Secret Manager `SQLROOT_PW`.

## 6. Work board (updated 2026-10-28 22:30 KST — read before starting; update your row when you start/finish)

Priority order is Muse Spark 1 > Claude 2 > Codex 3 (owner decision). One owner per row; if a row is not
yours, do not start it — add a row instead. Product copy says "service", never "demo"/"hackathon".

| # | Work | Owner | Branch / state | Done when |
|---|---|---|---|---|
| W1 | **T24 async eval jobs**: `POST /v1/eval/jobs` (202), `GET /v1/eval/jobs[/{id}]`, one job at a time, same budget guard; performance page polls | Muse Spark (Builder), Claude (Critic: sealed tests, review) | `muse/round9`, building | sealed T24 tests + full suite green, reviewed, released |
| W2 | **Release execution + live checks**: cut `release/*`, deploy with `infra/gcp/deploy_prod.sh STATE_BACKEND=postgres`, live mission, record here | Claude (on behalf of release captain Muse) | `release/2026-10-28-2` deploying | live check recorded in §5/§4 |
| W3 | **Measurements**: X_SINGLE baseline and PIPELINE on production (postgres-backed). Nobody else starts `/v1/eval/*` on production — duplicate runs spend credit and the 22:13 run was lost when the API was replaced | Claude | baseline next; pipeline after W1 | numbers on `/performance`, spend read from dev.meta.ai billing |
| W4 | **Usage-derived baseline cost**: `sealed_eval._call_builder_task` settles a fixed `BASELINE_COST_CENTS` (120¢/task) while the pipeline settles provider usage; settle baseline from usage the same way (`performance.usage_cost_cents`), keep the reservation cap, keep fail-closed on missing usage | Codex | open | X_SINGLE and PIPELINE cost-per-solved are comparable; tests show a baseline call billed from usage |
| W5 | **Loading states**: Mission Control and Performance show "loading" until the first response; show "cannot load" only after a request actually failed (today the error text flashes on every page load) | agy | done (verified tsc/build/pytest) | no error text before the first fetch settles; 375px layout intact |
| W6 | Runner isolation / PR base binding follow-ups already in flight | Codex | `codex/*` | merged to main with full suite green |
| W7 | Main worktree hygiene: uncommitted `services/api/evoforge/runner.py`, `services/api/tests/test_critic_t5_runner.py`, `apps/web/tsconfig.tsbuildinfo` sit in `C:\evo_forge` (cline checkpoints). Owner of that work: commit on your branch or discard; never leave WIP in the shared main worktree | whoever owns that WIP (cline) | open | `git status` clean in `C:\evo_forge` |

Rules that came from today's incidents:
- The env block of `evoforge-api` is owned by `deploy_prod.sh` (§5). One deploy at a time: check
  `gcloud builds list` before submitting.
- Web traffic follows the latest revision; do not pin traffic without writing it here.
- A live eval that is still running dies when the API is redeployed. Check §6 W3 before deploying.
