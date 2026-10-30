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

- 2026-10-29 (Claude): migration 012 (`012_evolutions.sql`, T30) applied with `migrate_once.py`; RLS enable+force verified on
  runtime.api_evolutions and runtime.api_evolution_memory.
- 2026-10-30 23:45 (agy on behalf of owner, `release/2026-10-30-29` @ `447e0ab7`, image tag `370c329`, api `00049` [lxm], web `00047` [67g], runner `00038` [sjj], storage=postgres):
  PR #1 merged (inner page light design unification + web CI fix). Web/API/Runner successfully built via Cloud Build (1e6dbbca-893b-483b-b08e-702a314d1a32) and deployed to Cloud Run. All 9 pages (/, /arena, /replay, /evidence, /performance, /lab, /verify/ev_ab527200a91d, /evolution, /leaderboard) verified at 1440px and 390px (light theme palette #f2f4f6/#fff, API proxy panels loading live data). Live mission through the proxy `msn_f1aea6002f1c` ran CREATED→GENERATED→REVIEWED→RAN on Cloud Run Runner (visible 2/2, held-out 3/3; GH_INTEGRITY=PASS, GC_COMPOSITION=PASS, G2_REQUIRED=PASS).

> **Owner, 2026-10-29: we are far from done. Keys/Opus lane and the demo happen at submission time. Until then: make EvoForge
> itself excellent — pick a row, ship it with tests, keep production green.**

## 7. Submission readiness (Meta hackathon, Indie · Push the Frontier) — read this before you pick work

Source docs: `docs/SUBMISSION.md` (what we submit), `docs/DEMO_SCRIPT.md` (3-min video), `docs/SPEC_GAP_REVIEW.md`
(185 blueprint requirements: 65 live / 43 partial / 27 module-only / 50 not started).

**Where we are strongest (keep these true; do not regress them):**
1. Production proof: sealed v2 (36 tasks) harness /1 21/36 → /2 35/36, non-overlapping Wilson intervals; pipeline 36/36 at ≈2.4¢/task.
2. Verification core is live: spec-first sealed Critic, server Runner, GH_INTEGRITY/G2/GC gates, PR only on all-PASS.
3. Ed25519-signed, stored, re-checkable certificates; PRs quote them and link /verify.
4. Self-improvement under statistics: harness A/B (T35) adopts only on non-overlap; measured timeline and adoption history.
5. Honest numbers everywhere (not_measured, provenance labels, fixed-rate cost labelled).
6. The service was built by Muse Spark under the same sealed-test discipline.

**What must be added before submission (owner):**
- S1 **done** — PR #7 (`msn_87b0a3b13fb1`), certificate `cert_fdb4cf3cf564` verifies offline; v1.0 criterion 3 met.
- S2 Durable ledger (Muse T39) and SSE live updates (Muse T40).
- S3 Release 7 = T37 durable decisions + T38 home proof card (+ T39/T40 when green); then one production A/B run so the adoption row is real (Claude).
- S4 Correct every doc that says a module is "on main" when it is not wired: say "module (not in the request path)" (Codex for its modules; Claude for SERVICE_STATUS).
- S5 Oracle holdout from 20 to ≥200 human-labelled tests (Codex) — blueprint M0 bar; until then INCONCLUSIVE stays conservative. Offline intake audit + S4 module-scope doc clarifications prepared in `codex/oracle-holdout-r7` `d126d4b` (release-7 base, 2026-10-29): 15 focused checks passed. Old-base `9c5cff5`: full API 714 passed / 4 skipped and package 0 failures (log C:/evo_forge_codex_oracle/.local/validation-oracle-intake-api.log); not a release-7 full-suite claim. Not on main. Authentic human labels remain required; metadata is an attestation, not verification. See `docs/ORACLE_HOLDOUT_INTAKE.md` on that branch.
- S6 Record the demo video per `docs/DEMO_SCRIPT.md` on a fresh mission (owner).

**After submission:** Remote MCP (read-only evidence/proof tools first), Collective Graph UI, Feedback Intelligence, onboarding/orgs/roles,
prepaid billing, external pen test, SLO/observability, codec/cascade ablations (blueprint R49-4).

## 6. Work board (updated 2026-10-28 22:30 KST — read before starting; update your row when you start/finish)

Direction and milestones: `docs/ROADMAP_EVOLUTION.md`. Priority order is Muse Spark 1 > Claude 2 > Codex 3 (owner decision). One owner per row; if a row is not
yours, do not start it — add a row instead. Product copy says "service", never "demo"/"hackathon".

| # | Work | Owner | Branch / state | Done when |
|---|---|---|---|---|
| W1 | **T24 async eval jobs**: `POST /v1/eval/jobs` (202), `GET /v1/eval/jobs[/{id}]`, one job at a time, same budget guard; performance page polls | Muse Spark (Builder), Claude (Critic: sealed tests, review) | **done** `757f9bc` (round 2), in `release/2026-10-28-3` | sealed T24 tests + full suite green, reviewed, released |
| W2 | **Release execution + live checks**: cut `release/*`, deploy with `infra/gcp/deploy_prod.sh STATE_BACKEND=postgres`, live mission, record here | Claude (on behalf of release captain Muse) | `release/2026-10-28-2` deploying | live check recorded in §5/§4 |
| W3 | **Measurements**: X_SINGLE baseline and PIPELINE on production (postgres-backed). Nobody else starts `/v1/eval/*` on production — duplicate runs spend credit and the 22:13 run was lost when the API was replaced | Claude | v0 baseline done 22:27 (`m_045caf7c2f1e`: 2/12, 16.7%, Wilson 4.7–44.8%, 1440¢ fixed-rate, see W4); pipeline after W1; v1 baseline+pipeline after W8 | numbers on `/performance`, spend read from dev.meta.ai billing |
| W4 | **Usage-derived baseline cost**: `sealed_eval._call_builder_task` settles a fixed `BASELINE_COST_CENTS` (120¢/task) while the pipeline settles provider usage; settle baseline from usage the same way (`performance.usage_cost_cents`), keep the reservation cap, keep fail-closed on missing usage | Codex | open | X_SINGLE and PIPELINE cost-per-solved are comparable; tests show a baseline call billed from usage |
| W5 | **Loading states**: Mission Control and Performance show "loading" until the first response; show "cannot load" only after a request actually failed (today the error text flashes on every page load) | agy | done (verified tsc/build/pytest) | no error text before the first fetch settles; 375px layout intact |
| W6 | Runner isolation / PR base binding follow-ups already in flight | Codex | `codex/*` | merged to main with full suite green |
| W10 | **T25 strong-oracle prompts**: Builder/Critic system prompts ask for `==` value asserts and `pytest.raises`, forbid `assert True/False` and try/except (frozen `oracle_ast` rates those tautologies). Live mission `msn_db7a9a9e80c9` (div): visible 3/3, held-out 4/4, G2 PASS, PR blocked GH_INTEGRITY=INCONCLUSIVE (strong fraction 0.67 < 0.8) | Muse Spark (Builder), Claude (Critic) | **done** `f5836a2` (round 1), in `release/2026-10-28-3` | sealed T25 + full suite green; next live mission opens a PR |
| W11 | **T26 hunk recount** in `patch.py`: diffs with wrong `@@` counts apply by their body (git `--recount`), context still exact. v1 local: same Builder outputs 5/12 strict → 12/12 recounted | Muse Spark (Builder), Claude (Critic) | **done** `902c1e2` (round 1, HARNESS_VERSION → api-sealed-eval/2), ships in release 4 after the v1 strict measurement | sealed T26 + full suite green |
| W12 | **T27 signed proofs + evolution budget**: Ed25519 certificates (`EVO_PROOF_SIGNING_KEY`), `GET /v1/proof/key`, verify with server key only; `/v1/evolution/start` refuses worst case > `EVO_EVOLUTION_MAX_CENTS` (default 1500¢). Review of de481a8: sha256 "signature" was forgeable; 10×5 evolution could reserve 12000¢ | Muse Spark (Builder), Claude (Critic) | **done** `495d91e` (round 3); `EVO_PROOF_SIGNING_KEY` created in Secret Manager (api SA only); ships in release 4 | sealed T27 + full suite green; key in Secret Manager |
| W13 | **v1 loader**: `sealed_eval` reads `evals/sealed_v<N>/` by `suite_version`; eval request models accept `"v1"`; `/v1/eval/suites` lists both | Muse Spark (after T24 merges) | **done** `af33625` (Claude, Muse busy), in `release/2026-10-28-3` | v1 baseline runs on production |
| W14 | **Persist evolutions / memory / leaderboard** in PostgreSQL (today process memory: lost on every deploy) | Codex (migration) + Muse (store) | open | an evolution survives an API redeploy |
| W15 | **T28 evolution timeline** on `/performance`: pure `lib/evolutionTimeline.ts` (tested by compiling and running it), inline-SVG chart with Wilson bars, harness-change markers, suite breaks, per-family heatmap, reduced-motion aware | Muse Spark (Builder), Claude (Critic) | `muse/round13` from release 3, building | sealed T28 + web tests + tsc green |
| W16 | **Release plan for the proof**: release 3 (T24+T25+W13, harness /1) → measure v1 X_SINGLE + PIPELINE as eval jobs → release 4 (+T26 harness /2, +T27, +T28) → measure the same v1 again. Same suite, same model, only the harness changes | Claude | **done (v2, release 5)**: X_SINGLE /1 21/36 (42.2–72.9%) → /2 35/36 (85.8–99.5%) = improved, non-overlapping; PIPELINE /2 36/36 (90.4–100%); details in ROADMAP_EVOLUTION.md | both measurements on `/performance`, verdict from non-overlapping intervals |
| W17 | **Test-gate speed**: full API suite takes 14–19 min per check and every Muse round pays it. Proposal: pytest-xdist after a parallel-safety pass (process-wide ledger/measurement stores, temp dirs); meanwhile web-only tasks check `-k "web or i18n or locale or message or proxy"` + tsc, and the full suite runs once per release | Codex (safety pass), Claude | open | full suite < 6 min with identical results |
| W18 | **T29 usage-derived X_SINGLE cost + per-task outcomes** (`passed`/`empty_diff`/`apply_failed`/`heldout_failed` + failing test names, no code) — covers W4 + W9 | Muse Spark (Builder), Claude (Critic) | `muse/round14`, building | sealed T29 + full suite green |
| W19 | **T30 evolution + memory persistence** (migration `012_evolutions.sql`, `postgres_evolutions.py`) — covers W14 | Muse Spark (Builder), Claude (Critic); **Codex: review 012 (migrations are yours)** | Codex review of `muse/round15` `00ad8a1`: **10 live-PG checks passed**, including raw SQL RLS/privileges/immutable memory and existing T30 persistence tests. Review/tests: `codex/review-evolution-012` `241e37d`, `docs/EVOLUTION_012_CODEX_REVIEW.md`; no production changes or full integration claim | sealed T30 on live PG + full suite green; 012 applied with `migrate_once.py` |
| W20 | **T31 background evolution runs + signed-proof `/verify` UI** | Muse Spark (Builder), Claude (Critic) | `muse/round16` (release 3 + T27), building | sealed T31 + full suite + tsc green |
| W21 | **UI consistency pass after T28/T31 land**: one visual language across Mission Control, Performance, Evolution, Leaderboard, Verify; 375px audit; empty/loading/error states | agy | open — start after release 4 is on main | screenshots at 375/1280 attached in the commit message |
| W22 | **Runner report forgery (Codex finding, top priority)**: candidate code can write a passing JUnit report and exit 0 before held-out assertions run (`atexit` probe, `RUNNER_REPORT_FAILCLOSED_PROPOSAL.md`). Do NOT block every PR; ship layered defence now: (1) diff screen → INCONCLUSIVE when a candidate touches `atexit`, `os._exit`, import-time `sys.exit`, `faulthandler`, writes `*.xml`/JUnit paths, imports `_pytest`/`pytest` internals, adds `conftest.py`/`sitecustomize`/`usercustomize`/`.pth`, or rebinds `builtins`/`sys.modules`; (2) parent-side cross-check: required test ids, JUnit counts, pytest `-rA` summary lines and the exit code must all agree, else INCONCLUSIVE; (3) held-out run in a fresh interpreter per test file with the report path chosen by the parent after the child exits. Then (4) wire `independent_runner_verifier` once an independent observer exists | **Codex** (runner owner), Claude reviews | steps 1–2 **reviewed and in `release/2026-10-29-8`** (`codex/runner-verify-r7`: diff screen → INCONCLUSIVE at PR time; Runner cross-checks JUnit/summary/modules/exit code). **Open for Codex:** step 3 (fresh interpreter per held-out file, parent-chosen report path), step 4 (independent observer + signed receipts), apply the candidate screen in sealed-eval scoring too; local/remote execution-evidence scoring candidate is now `codex/eval-run-evidence` `64936cd` (docs `b74cc6d`, release-8 base): local summary/JUnit cross-check, integer/exit/flag checks, `verification_inconclusive` scores zero, provider costs preserved. 20 focused + 36 baseline/Runner checks passed (overlapping sets); full API/release integration pending. Then narrow the `sys.exit` rule to import-time/module-level use (Codex: `codex/runner-exit-scope` `308d039`, release-8 base; 63 scope/report/PR checks passed, full API running in C:/evo_forge_codex_exit_scope/.local/validation-exit-scope-api.log; not integrated) | forgery probe → INCONCLUSIVE (not PASS); full suite green; normal missions still open PRs |
| W23 | **T41 Remote MCP (read-only)** — blueprint §23: MCP endpoint exposing get_performance, get_proof, verify_certificate, list_missions, get_mission so any MCP client (incl. other agents) can check EvoForge's proofs | Muse Spark (Builder), Claude (Critic) | next | MCP client lists tools and verifies a stored certificate |
| W24 | **North star A1 — Arena engine (T44)**: same task to EvoForge lane and single-AI lane, concurrent, held-out scoring for both, usage cost per lane (`docs/NORTH_STAR.md`) | Muse Spark (Builder), Claude (Critic) | **done** (round 1 pass: 11 Muse tests + 6 sealed Critic tests + 126 proxy cases + tsc green; merged in release-8 `206239f`) | sealed T44 green; production arena run recorded |
| W25 | **North star B1 — per-session tenancy**: a visitor session maps to its own tenant/project in PostgreSQL (create, expire, delete), every runtime table stays RLS-scoped, cross-session reads impossible; design note first | **Codex** | design-first contract prepared: `codex/session-tenancy-design` `da0f5c8`, `docs/SESSION_TENANCY_DESIGN_CODEX.md` (release-8 base). Internal registry candidate `codex/session-registry` `5ed1022`: migration 013, credential digests, per-transaction expiry/revocation and scoped adapters; 6 actual PG + 12 input checks passed, full API still running in C:/evo_forge_codex_sessions/.local/. Package+SQL96 passed, but the separate legacy kernel regression hit its 600s timeout; no full-kernel pass claim. Requires preprovisioned scopes; HTTP/bootstrap/jobs/SSE/legacy ledger cache and key-vault integration remain pending. Other-owner session/Arena WIP preserved. No public launch | two sessions cannot read each other's missions/evidence/measurements/ledger (live-PG tests) |
| W26 | **North star A2/A3 — Arena split screen + workspace shell**: left feature tabs, AI status panel, implementation panel (code/diff/tests/preview), bottom input, live via SSE | Muse Spark T45/T46 (Builder), **agy** (cockpit UI & isolation), Claude (Critic) | **done** (agy: 4-zone cockpit layout, 2-split duel, 4 presets incl. visual DOM counter, sandboxed iframe live preview, reactive AI swarm cards, BYOK in-memory vault, Next.js build 14/14 green) | recording the Arena page is the demo video |
| W27 | **Arena result truth and linked implementation**: remove preset result/price/PASS claims; show returned evidence only and fetch the selected generation candidate public artifact | Codex + admin_ui ([arenaDisplay.ts], check-arena-display.mjs, truth-first winner binding, zero client key storage, clean Next.js build & tsc passed) | real candidate diff/tests bound to the displayed evolution; absent evidence stays unconfirmed; no invented wins, costs or statuses |
| W28 | **Production outage (external review #1): API timeouts >40 s and 429s** — PG connection pool, one-query list scans, async SSE, mission-level evidence chain, accurate proof-page claim | Claude | **done** — release 18 live 2026-10-30 (API 00034); latency 90 s timeouts → 0.2–1.9 s, 80-concurrent burst 80/80 OK (V38 log) | production endpoints < 2 s, no 429 under burst |
| W29 | **First screen + mobile (external review #3)**: English default, home intro, internal codes → plain words (T71, Muse), 375px overflow on Arena/Lab/Verify/Replay | Muse Spark T71 (Builder), Claude (Critic + layout fixes) | **done** — releases 19–20; 11 pages exactly 375px in production (en, ko) | scrollWidth ≤ 375 on every page; sealed T71 |
| W30 | **Critic on a second Meta model (external review #4, T72)**: OpenAI-compatible endpoint (Llama on Fireworks/Baseten) by env only; key memory/Secret Manager only; owner-set prices, refuse if unset; manifest names the Critic | Muse Spark (Builder), Claude (Critic) | **code live** (release 21, env-only, key routing fixed); owner adds key + prices at submission | sealed T72 + focused suite |
| W31 | **Prompt-Arena fairness (T73)**: publish the interface the hidden acceptance tests call (names, arity, input keys — never values) to both lanes; production password-meter run scored 0/5 vs 0/5 from interface guessing | Muse Spark (Builder), Claude (Critic) | **done** — T73 interface (r20), T76/T80 judge reference (r21/r24); password meter now 6/6 vs 6/6 on a checked suite | sealed T73 + prompt-Arena tests |
| W32 | **Arena numbers that mean something**: equal tools in the sealed Arena, v5 in the UI, live progress, scoreboard (all / equal tools / significance) on home + Arena; jobs API without lane patches | Muse Spark T74/T75/T77/T78/T79/T81 (Builder), Claude (Critic, equal-tools harness, releases 21–24) | **done** — release 24 live; v5 equal tools 12/12 vs 9/12, 3-0-9, p = 0.25 (not significant) | scoreboard matches `/v1/arena/summary`; claims match `docs/SUBMISSION.md` |
| W8 | **Sealed eval v1 with contract-stating goals** (`docs/EVAL_V1_GOALS.md`): `evals/sealed_v1/` copies v0 held-out tests, files and reference fixes unchanged and replaces only `goal`; `SUITE_VERSION` selectable; every task passes `check_task`. v0 measured 2/12 mostly because tests check behaviour the goals never state | Claude (data, Codex idle) | data merged `dede1da` (check_task 12/12); loader = W13 | v1 loads, `check_task` green for 12/12, `/v1/eval/suites` lists v0 and v1 |
| W9 | **Per-task failure reason in eval evidence** (`empty_diff` / `apply_failed` / `heldout_failed` + failing test names / `provider_error`; no held-out code) | Codex (`sealed_eval.py`) | open | baseline and pipeline evidence carry a reason for every task with score < 1 |
| W7 | Main worktree hygiene: uncommitted `services/api/evoforge/runner.py`, `services/api/tests/test_critic_t5_runner.py`, `apps/web/tsconfig.tsbuildinfo` sit in `C:\evo_forge` (cline checkpoints). Owner of that work: commit on your branch or discard; never leave WIP in the shared main worktree | whoever owns that WIP (cline) / agy | **done** — committed on `codex/self-healing-and-adaptive-eval` (`1cdeef01`, 98 runner + 9 adaptive eval tests green); `git status` clean on `main` | `git status` clean in `C:\evo_forge` |
| W15 | **Case-based autopilot & UI diagnostics**: real Muse Spark autopilot case (`calc.py`, 360¢, 1 gen CONVERGED, proof verified), mutex per evolution (`lock_for`), bounded memory (200 limit), source_repo pass-through, UI contract presets (WVI PR #6, EVAL_V1, PM-01) & W10 gate diagnostics in Mission Control and Lab | agy + Muse-rounds | done | tsc/build/pytest green (23 tests passed), Case Study 01 documented |

**Final version (v1.0) is done when, in production:**
1. `/performance` shows v1 X_SINGLE and PIPELINE for harness /1 and /2 with Wilson intervals, usage-derived cost and per-task outcomes; the verdict comes from non-overlapping intervals.
2. The evolution timeline (T28) renders those measurements; harness changes and suite breaks are visible.
3. A live mission opens a PR whose proof certificate is Ed25519-signed and verifies against `GET /v1/proof/key`; an edited certificate fails.
4. Evolutions, memory and the leaderboard survive a redeploy (T30), and an autopilot run completes through the web without timeouts (T31).
5. Full suite, `validate_package --pg`, `npm ci`, `tsc`, `next build` green on the release commit.

**Calls to agents (pick your row now):** Codex → W17 (test-gate speed), W19 review of migration 012, W6. agy → W21. Muse Spark → every Builder row; new Muse rows are added as soon as one finishes.

Rules that came from today's incidents:
- **Never commit, merge or test-run in another agent's worktree or on a `release/*` branch you do not own.** On 2026-10-29
  06:26–06:27 an agent committed Muse's in-progress T43 output in `C:\evo_forge_muse28` and merged it into
  `release/2026-10-29-8` inside `C:\evo_forge_rel8` while that release's gate was running there; the gate had to be thrown
  away. Muse loop worktrees (`C:\evo_forge_muse*`) and release worktrees (`C:\evo_forge_rel*`) are Claude's; signing a
  commit "Critic: Claude" does not make it reviewed. Want something released? Add a row; the release owner merges it.
- **main is behind production.** Production runs `release/2026-10-29-7` (T24–T38, sealed v1/v2, harness A/B, signed proofs,
  shared Runner patch). `main` has only docs on top of release 2. Uncommitted WIP in `C:\evo_forge` (runner.py, sealed_eval.py,
  test_critic_t5_runner.py, test_muse_sealed_eval.py, ~1.2k lines) blocks a clean merge. Owner of that WIP: commit it on your
  branch, then `main` absorbs `release/2026-10-29-7` from a clean worktree. Branch new work from the release branch, not main.
- The env block of `evoforge-api` is owned by `deploy_prod.sh` (§5). One deploy at a time: check
  `gcloud builds list` before submitting.
- Web traffic follows the latest revision; do not pin traffic without writing it here.
- A live eval that is still running dies when the API is redeployed. Check §6 W3 before deploying.


## Owner-requested workspace/design follow-up (Codex, 2026-10-30)

| Work | Owner | Branch / state | Acceptance |
|---|---|---|---|
| W32 folder organization + studio appearance | Codex (owner-requested web ownership exception) | `codex/design-studio` tip `37107dab`, app code `ed60f35b`; C:/Projects/EvoForge/worktrees/design-studio | Toss-inspired refinement of the accepted minimal canvas: softer type/surfaces, comfortable targets, mobile More menu, growing input, received/active/error states, focus return and reduced motion. Korean default SSR copy 409 -> 80 (80.4% less). 122 SSR assertions + 64 web checks + TypeScript + clean build passed. Saved-record review port 47839; no model run. Browser verification unavailable (disabled); not deployed, captain integrates. Folder cleanup remains verified. |
| W33 | **Release 25–26: canvas + share + rounds + public runs** — Codex canvas (owner request) integrated and browser-reviewed; T82 share links, T84 per-round plan + daily limit, T85 rounds UI + challenges | Codex (canvas), Muse Spark T82/T84/T85 (Builder), Claude (Critic, review, releases) | **done** — release 26 live; 2-round plan verified in production | `/share/<id>` public; 20 runs/day; claims match `docs/SUBMISSION.md` |
