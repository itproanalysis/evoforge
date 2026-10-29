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
- 2026-10-28 22:31 (Claude, `release/2026-10-28-2` @ `8dd8b41`, api `00017` 17 env, web `00017`, storage=postgres):
  live mission through the proxy `msn_db7a9a9e80c9` CREATED→GENERATED→REVIEWED→RAN on the Cloud Run Runner
  (visible 3/3, held-out 4/4); PR correctly refused by GH_INTEGRITY=INCONCLUSIVE (weak Builder test, W10).
  Note: missions/outcomes created on api `00015` (memory backend), including PR #6's WVI, are not in postgres.

## 6. Work board (updated 2026-10-28 22:30 KST — read before starting; update your row when you start/finish)

Direction and milestones: `docs/ROADMAP_EVOLUTION.md`. Priority order is Muse Spark 1 > Claude 2 > Codex 3 (owner decision). One owner per row; if a row is not
yours, do not start it — add a row instead. Product copy says "service", never "demo"/"hackathon".

| # | Work | Owner | Branch / state | Done when |
|---|---|---|---|---|
| W1 | **T24 async eval jobs**: `POST /v1/eval/jobs` (202), `GET /v1/eval/jobs[/{id}]`, one job at a time, same budget guard; performance page polls | Muse Spark (Builder), Claude (Critic: sealed tests, review) | `muse/round9`, building | sealed T24 tests + full suite green, reviewed, released |
| W2 | **Release execution + live checks**: cut `release/*`, deploy with `infra/gcp/deploy_prod.sh STATE_BACKEND=postgres`, live mission, record here | Claude (on behalf of release captain Muse) | `release/2026-10-28-2` deploying | live check recorded in §5/§4 |
| W3 | **Measurements**: X_SINGLE baseline and PIPELINE on production (postgres-backed). Nobody else starts `/v1/eval/*` on production — duplicate runs spend credit and the 22:13 run was lost when the API was replaced | Claude | v0 baseline done 22:27 (`m_045caf7c2f1e`: 2/12, 16.7%, Wilson 4.7–44.8%, 1440¢ fixed-rate, see W4); pipeline after W1; v1 baseline+pipeline after W8 | numbers on `/performance`, spend read from dev.meta.ai billing |
| W4 | **Usage-derived baseline cost**: `sealed_eval._call_builder_task` settles a fixed `BASELINE_COST_CENTS` (120¢/task) while the pipeline settles provider usage; settle baseline from usage the same way (`performance.usage_cost_cents`), keep the reservation cap, keep fail-closed on missing usage | Codex | open | X_SINGLE and PIPELINE cost-per-solved are comparable; tests show a baseline call billed from usage |
| W5 | **Loading states**: Mission Control and Performance show "loading" until the first response; show "cannot load" only after a request actually failed (today the error text flashes on every page load) | agy | done (verified tsc/build/pytest) | no error text before the first fetch settles; 375px layout intact |
| W6 | Runner isolation / PR base binding follow-ups already in flight | Codex | `codex/*` | merged to main with full suite green |
| W10 | **T25 strong-oracle prompts**: Builder/Critic system prompts ask for `==` value asserts and `pytest.raises`, forbid `assert True/False` and try/except (frozen `oracle_ast` rates those tautologies). Live mission `msn_db7a9a9e80c9` (div): visible 3/3, held-out 4/4, G2 PASS, PR blocked GH_INTEGRITY=INCONCLUSIVE (strong fraction 0.67 < 0.8) | Muse Spark (Builder), Claude (Critic) | `muse/round10`, building | sealed T25 + full suite green; next live mission opens a PR |
| W11 | **T26 hunk recount** in `patch.py`: diffs with wrong `@@` counts apply by their body (git `--recount`), context still exact. v1 local: same Builder outputs 5/12 strict → 12/12 recounted | Muse Spark (Builder), Claude (Critic) | `muse/round11`, building | sealed T26 + full suite green |
| W12 | **T27 signed proofs + evolution budget**: Ed25519 certificates (`EVO_PROOF_SIGNING_KEY`), `GET /v1/proof/key`, verify with server key only; `/v1/evolution/start` refuses worst case > `EVO_EVOLUTION_MAX_CENTS` (default 1500¢). Review of de481a8: sha256 "signature" was forgeable; 10×5 evolution could reserve 12000¢ | Muse Spark (Builder), Claude (Critic) | `muse/round12`, building | sealed T27 + full suite green; key in Secret Manager |
| W13 | **v1 loader**: `sealed_eval` reads `evals/sealed_v<N>/` by `suite_version`; eval request models accept `"v1"`; `/v1/eval/suites` lists both | Muse Spark (after T24 merges) | open | v1 baseline runs on production |
| W14 | **Persist evolutions / memory / leaderboard** in PostgreSQL (today process memory: lost on every deploy) | Codex (migration) + Muse (store) | open | an evolution survives an API redeploy |
| W8 | **Sealed eval v1 with contract-stating goals** (`docs/EVAL_V1_GOALS.md`): `evals/sealed_v1/` copies v0 held-out tests, files and reference fixes unchanged and replaces only `goal`; `SUITE_VERSION` selectable; every task passes `check_task`. v0 measured 2/12 mostly because tests check behaviour the goals never state | Claude (data, Codex idle) | data merged `dede1da` (check_task 12/12); loader = W13 | v1 loads, `check_task` green for 12/12, `/v1/eval/suites` lists v0 and v1 |
| W9 | **Per-task failure reason in eval evidence** (`empty_diff` / `apply_failed` / `heldout_failed` + failing test names / `provider_error`; no held-out code) | Codex (`sealed_eval.py`) | open | baseline and pipeline evidence carry a reason for every task with score < 1 |
| W7 | Main worktree hygiene: uncommitted `services/api/evoforge/runner.py`, `services/api/tests/test_critic_t5_runner.py`, `apps/web/tsconfig.tsbuildinfo` sit in `C:\evo_forge` (cline checkpoints). Owner of that work: commit on your branch or discard; never leave WIP in the shared main worktree | whoever owns that WIP (cline) | open | `git status` clean in `C:\evo_forge` |
| W15 | **Case-based autopilot & UI diagnostics**: real Muse Spark autopilot case (`calc.py`, 360¢, 1 gen CONVERGED, proof verified), mutex per evolution (`lock_for`), bounded memory (200 limit), source_repo pass-through, UI contract presets (WVI PR #6, EVAL_V1, PM-01) & W10 gate diagnostics in Mission Control and Lab | agy + Muse-rounds | done | tsc/build/pytest green (23 tests passed), Case Study 01 documented |

Rules that came from today's incidents:
- The env block of `evoforge-api` is owned by `deploy_prod.sh` (§5). One deploy at a time: check
  `gcloud builds list` before submitting.
- Web traffic follows the latest revision; do not pin traffic without writing it here.
- A live eval that is still running dies when the API is redeployed. Check §6 W3 before deploying.


## Codex owner-requested design refresh (2026-10-30)

| Work | Owner | Branch / state | Acceptance |
|---|---|---|---|
| W32 workspace organization and studio design | Codex (web ownership exception requested by the owner) | `codex/design-studio`, based on release 23; C:/Projects/EvoForge/worktrees/design-studio | 98 clean worktrees relocated with HEAD/branch preserved; existing web regressions + actual-component SSR, TypeScript and clean build; browser screenshot review remains pending because local browser control is disabled; release captain integrates/deploys |
