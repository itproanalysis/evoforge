# v3.8 Evolution Arena (R1–R5) → execution plan (2026-10-29)

Source: owner-supplied *EvoForge v3.8 — Evolution Arena & EvoCore Integrated Improvement Plan*. Product line:
**EvoForge — AI That Evolves How AI Builds.** The protagonist is *evolution you can see*: one goal, an app that changes
round by round (R1–R5), every round leaving a snapshot you can replay, EvoForge and a single AI side by side.
Read with `docs/NORTH_STAR.md` and `docs/V36_EXECUTION_PLAN.md` (its rules still bind). Keys/Opus lane stay at submission.

## Rules added by v3.8 (binding)

1. **A round is a checkpoint where the app really changed and was measured** — not a count of agent calls.
2. **Snapshot or it did not happen.** Each round × side stores source hash, cumulative held-out score, rendered preview,
   cost, time and status. `READY` only when every test so far passes; `UNVERIFIED` when the code changed but some fail;
   `FAILED` when nothing applicable was produced. A failed round is never filled with another round's or the other
   side's result.
3. **Cumulative scoring.** Round n is scored on R1..Rn tests, so a regression in an earlier feature shows.
4. **Replay is read-only.** Viewing R1–R5 never calls a model and never adds cost.
5. **Product evolution ≠ harness evolution.** R1→R5 shows the app improving inside one run; claiming EvoForge itself got
   better needs transfer to new tasks (later, P1). Do not mix the two in copy.
6. **Same contract both sides:** same base, same round goals, same tests, allowances printed (manifest).
7. Recorded runs are labelled `Recorded run`; a one-sided run is never advertised as a comparison.

## Map

| v3.8 item | What exists / who | Status |
|---|---|---|
| Round app + tests (P0-A data) | **Claude** `evals/rounds_v1/mission_board.json` (`claude/rounds-v1` `d4c2e4e`): Mission Board, R0 + 5 rounds (Initial Build → Feature Growth → UX Refinement → Robustness → Verified Release), 3 held-out tests per round, cumulative; every round-n test fails on round n-1 code, all pass on round n reference | **done** |
| Round engine + snapshots + replay API (P0-A/B, SNAP-01..05/07, ARENA-01/02) | **Muse T51** (`muse/round34`): `POST/GET /v1/evolution/runs`, `GET /v1/evolution/apps`, two lanes, critic feedback by default, immutable per-round snapshots, manifest | building |
| Single-task Arena + manifest + preview | T44 + T48 + T49 (release 10) | done, gating |
| Arena without held-out signal | **Muse T50** (`muse/round33`) | building |
| R1–R5 Replay UI: scrubber, both sides' `SandboxedPreview`, First↔Latest, Auto Replay (no network), status/cost/score per round, manifest strip | **Muse T52** after T51 (Builder), **agy** polish / 16:9 recording mode | next |
| Mission Control D3: left rail (Mission, Arena, Evolution, Evidence, Projects, Settings), AI panel, large live preview, fixed command bar with `RECEIVED → VALIDATED → QUEUED → APPLIED/REJECTED/CANCELLED` | agy cockpit (W26) + Muse T46/CMD-01 | open |
| Candidate code out of the API container (SEC-02; preview + scoring) | **Codex** | open — blocks public/BYOK |
| Per-org isolation, BYOK, GitHub (P0-C) | Codex B1 (W25); BYOK at submission | in progress / deferred |
| EvoCore LAB (strategy mutation, Pareto archive, promotion, transfer) | P1 — after P0-A/B ship | later |

## Proof plan for "evolution"

- **In-run (shown now):** verified rounds per side, cumulative held-out pass, cost and time per round, R1↔R5 preview.
- **Across runs (P1):** arms A single model, B naive parallel, C 5-agent without EvoCore, D EvoCore; claim only what
  non-overlapping intervals support, on held-out apps not used for tuning.

## Production log

- **2026-10-29 release 11, first R1-R5 run `job_479c85e3e326` (critic feedback):** EvoForge READY R1, R2, then FAILED
  R3-R5 (6/15 cumulative); single AI FAILED every round (its diffs never applied under strict hunk counts; 0/15).
  Cost 110c vs 31c, 645 s vs 191 s. Root cause of the EvoForge stall: the Builder spent 7998 of its 8000 output tokens
  on reasoning and was cut off, so every R3+ attempt returned an empty diff. Fix: production `MODEL_MAX_TOKENS=32000`
  (API revision `evoforge-api-00027`, also in `deploy_prod.sh`; both lanes share it); the same R3 call then finished at
  6950 tokens and passed R1-R3 9/9 locally. Empty-diff events now carry the Builder's reason (`claude/output-budget`).
- **Run 2 `job_a1bb968d838a` (32k budget, release 11):** EvoForge UNVERIFIED every round at 2/3, 5/6, 8/9, 11/12,
  14/15; single READY R1-R2 then FAILED (strict apply). The one test EvoForge kept missing checked "preview shows >= 3
  tasks" which the R1 goal did not state — a Critic data defect; goal fixed (`b43473f`), other rounds re-audited.
- **Run 3 `job_b9fbd6da2e3f` (release 12, critic feedback):** EvoForge **READY 5/5 (15/15)**, single READY 4/5
  (R5 diff did not apply). Cost 204c vs 52c, 912 s vs 200 s; cost per verified round 41c vs 13c — EvoForge was more
  reliable here but ~4x more expensive. Cause of the cost: an R1 Critic test the R2 redesign legitimately breaks kept
  every retry of R2-R5 failing (T53 side effect). Fix in progress: Muse T57 retires such stale tests.
- Three runs, one app: no significance claim yet (T55 `/v1/evolution/stats` will report the intervals).
- **Run 4 `job_b17e57611e71` (release 13b, Scoreboard app, critic feedback, strict single):** EvoForge READY 5/5
  (15/15, attempts 1/2/2/3/2 — T57 stopped the 3-attempt burn), single READY 2/5 (R3 and R5 diffs did not apply, R4
  regressed). Cost 146c vs 38c, 625 s vs 150 s.
- **Stats after 4 runs (`/v1/evolution/stats`, all runs incl. the two before the fixes):** EvoForge 12/20 verified
  rounds [0.39, 0.78], single 8/20 [0.22, 0.61] — **not significant**. Since the fixes (runs 3-4): 10/10 vs 6/10, still
  overlapping intervals. Next: more runs, and the equal-tools mode (T60) so the single AI gets the same patch tolerance.
- **Equal-tools runs (release 14, `single_apply=tolerant`):** Mission Board `job_ad1a590f78f7` both 5/5 (115c vs
  44c); Scoreboard `job_cbcf4ae84fef` both 5/5 (154c vs 35c; the EvoForge lane reported "critic 0/N" on every
  attempt — a Critic suite that cannot run in the stdlib-only sandbox burnt all retries; fixed in `claude/critic-robust`
  `8a97853`).
- **Sealed v3, equal tools (harness /2, 32k budget):** X_SINGLE `m_2237cf978add` **48/48** (152c); PIPELINE with Critic
  feedback `m_3035d3cb1682` **48/48** (304c).

### What the evidence now says (2026-10-29 evening)

1. With tolerant patch application and a 32k output budget, Muse Spark 1.3 solves every sealed task and both
   evolution apps in one shot. **Our current suites are saturated**: they cannot show an orchestration advantage.
2. The large measured gains (v2 single shot 22/36 -> 35/36, R3+ stalls fixed, stale-Critic and sandbox-Critic waste
   removed) came from **EvoForge changing how it builds** — harness, output budget, Critic handling — each found from
   production evidence and verified. That is the claim the data supports: *AI that evolves how AI builds*.
3. "EvoForge beats a single AI under equal tools" is **not shown yet**. Next: sealed v5 with tasks a single shot
   actually fails (calibrated in production before use), then equal-tools comparisons on it.
- **Sealed v5 (12 rule-dense tasks, release 15):** X_SINGLE /2 `m_d475978dabed` 9/12 [0.47, 0.91] 115c; X_SINGLE /3
  `m_f43769eae727` 10/12 [0.55, 0.95] 140c; **PIPELINE /3 + Critic feedback (no held-out signal)** `m_34a9a98e50bb`
  **12/12** [0.76, 1.00] 278c, 13 attempts. First hard-suite result where EvoForge beats an equal-tools single shot
  (12/12 vs 10/12) and where the harness change /2 -> /3 helps the single shot (9 -> 10). Intervals still overlap
  (n = 12); repeats running to reach n = 36.
- **v5 repeats (equal tools, harness /3):** run 2 single 12/12 (133c) vs EvoForge 12/12 (238c, 12 attempts); run 3
  single 9/12 (144c) vs EvoForge 11/12 (324c, 14 attempts). **Pooled n = 36: single 31/36 [0.71, 0.94], EvoForge
  35/36 [0.86, 0.995]** — EvoForge ahead in every run, intervals still overlap (not significant); paired, at least 4
  tasks favour EvoForge and none the single AI (exact McNemar p ~ 0.125 if b = 4, c = 0). Cost 840c vs 417c (2.0x).
  Honest claim today: on hard tasks EvoForge is more reliable at about twice the model cost; significance needs more
  paired runs.

### Release 18 — production outage fix (2026-10-30, external review items 1 and 3)
- **Cause:** every DB transaction opened its own PostgreSQL connection, and every list endpoint read ids and then each
  document in its own transaction (N+1). With a few thousand records, dashboard/performance/outcomes/arena/evolution
  took over 40–90 s (502 at the proxy), connection slots ran out (release 17 crashed at startup), and open live-update
  streams each held one of the API's 40 worker threads for 25 s, so requests queued until Cloud Run answered 429.
- **Fix (release 18, API 00034 / Runner 00023 / Web 00032):** per-process connection pool (`EVO_PG_POOL_SIZE=10`),
  one-query `postgres_state.scan()` for all hot lists and the ledger replay, async SSE, 100 worker threads.
- **Measured in production (same 9 endpoints):** before — dashboard 11 s, performance/outcomes/arena/evolution runs/
  stats all timed out at 90 s, missions 9 s; after — 0.2–1.9 s each. Burst of 80 concurrent GETs with 10 open streams:
  80/80 HTTP 200, no 429; p50 6.5 s, p95 10.9 s on one 1-vCPU instance (next lever: 2 vCPU).
- **Evidence chain:** each record links only the stages known when it was written, so the run record of the mission
  behind PR #7 showed PR empty. `/v1/evidence/<id>` now also returns `mission_chain` (stages merged over the mission's
  records): ObjectiveVersion→PR filled, Outcome empty because the PR is not merged (opened PR ≠ verified improvement).
- **Claim fixed:** the proof page said "code never leaves the server" while `/v1/evidence` returns the candidate patch
  and the Builder's visible tests (both also in the public PR). Held-out tests are hash-only. Wording now says exactly
  that.
- **Mobile (375 px):** Arena 573→375, Lab 637→385 (release 18); Verify 474 and Replay 512 fixed in release 19.
- **Prompt Arena in production after the fix:** bakery landing page, round 1 tie 3/3 vs 3/3 (single 6¢, EvoForge 13¢,
  judge 13¢); follow-up "add a footer with hours and contact" round 2 tie 6/6 vs 6/6 (single 4¢, EvoForge 11¢,
  judge 10¢; 3 acceptance tests inherited + 3 new). Easy prompts do not separate the lanes; rule-dense prompts next.
- **Rule-dense prompt Arenas (release 18–20, production):** shipping-cost calculator: tie 3/3 vs 3/3 (single 13¢;
  EvoForge 37¢, 2 attempts; judge 15¢). Password meter: 0/5 vs 0/5 (release 18; single 13¢, EvoForge 40¢, judge 18¢)
  and again 0/3 vs 0/3 after T73 (release 20; single 13¢, EvoForge 40¢, judge 22¢) — EvoForge's own Critic passed 4/4.
  Diagnosis: a fresh judge suite for the same prompt passes 3/3 on BOTH production candidates, locally and through the
  Runner path; so scoring works and the production judge's suite was unsatisfiable or wrong (the judge is the same
  model and nothing checks its tests). Honest reading: no prompt-Arena result yet separates the lanes; ties and
  0–0 are not wins. Next (T76): the judge also writes a reference solution and only tests that pass on it and fail on
  the empty template count; a suite the reference cannot pass is reported as "judge suite invalid", never as a tie.
- **Releases 19–20:** English default + home explanation + plain words (T71, Muse), mobile layout (menu bar above
  content; all 11 checked pages exactly 375 px wide in production, en and ko), acceptance interface for both lanes
  (T73, Muse). T72 (second Meta model as Critic, env-only) is reviewed and waits for the owner's key and prices.

### Sealed v5 Arena in production — equal tools (release 22, 2026-10-30)
- **Harness finding first:** the sealed Arena's single lane used strict hunk counts while EvoForge recounts. In a first
  v5 run (release 21) the single lane lost SV5-AO-02 only because its patch failed that rule; with equal tools the same
  task is a 3/3 tie. That run was stopped after 2 tasks and is not counted below. `/v1/arena` now takes
  `single_apply="tolerant"` (the Arena page sends it); the manifest records `apply`/harness and an equal-tools note.
- **12 matches, equal tools, Critic feedback only (no held-out signal to EvoForge):** EvoForge solved 12/12 tasks,
  single 9/12; paired: EvoForge 3 wins, single 0, ties 9. Hidden tests 36/36 vs 27/36. Model cost 264¢ vs 135¢ (2.0×).
  - Wins: SV5-AO-01 (single returned an empty patch after 28¢ of output), SV5-PM-01 (both first patches failed to
    apply; EvoForge's retry fixed it), SV5-SS-01 (single's patch malformed; EvoForge's first attempt applied).
- **Honest reading:** task level n = 12 — Wilson 95% [0.76, 1.00] vs [0.47, 0.91] overlap; a 3–0 paired split is not
  significant (two-sided sign test p = 0.25). Test-level intervals do not overlap ([0.90, 1.00] vs [0.59, 0.86]) but the
  three tests of a task fail together, so that view overstates the evidence. Consistent with the pooled equal-tools
  eval (31/36 vs 35/36): EvoForge is more reliable on hard tasks at about twice the model cost; ties dominate when the
  single call works.
- **Scoreboard caveat:** `/v1/arena/summary` totals still include earlier strict-harness matches (T79, in progress,
  adds an equal-tools block shown first).
- **Prompt Arena with the judge reference (release 23, T76):** the password-meter prompt that scored 0/5 and 0/3 for
  both sides earlier now runs on a checked suite — judge wrote 6 tests, all 6 passed on the judge's reference build
  (0 dropped) — and both sides pass 6/6: tie (single 10¢, EvoForge 43¢, judge 33¢ incl. the reference build). The
  earlier 0–0 results measured the judge, not the lanes. Equal-tools scoreboard after release 23: 18 scored, EvoForge
  3 / single 0 / ties 15.

### Releases 25–26 — workspace canvas, sharing, per-round missions, public runs (2026-10-30)
- **Release 25:** Codex's owner-requested canvas redesign merged and browser-reviewed by the release captain (desktop
  ko/en, 375 px: no overflow, previews, code view, More menu). Fixes on review: the cost label no longer says
  "estimate" (T19 honesty gate), and the Measurements sheet compares both sides (hidden tests 57/65 vs 48/65 at the
  time, wins/ties, "not statistically significant yet (p = 0.25)") instead of EvoForge alone.
- **Release 26:** T82 share links (`/share/<id>`, plain-language labels after a production review), T84 per-round
  missions in one chained job + public daily limit (20 runs/day, `GET /v1/arena/limits`, 429 over the limit), T85 input
  with rounds R1–R5, five challenges whose every mission is checkable through `render(state)`, Continue / New run
  toggle. Owner decision 2026-10-30: anyone may start runs within the daily limit (replaces operator-only start).
- **Production check:** a 2-round plan (bakery page → add prices) ran as one job: round 1 tie 3/3 vs 3/3 (single 2¢,
  EvoForge 8¢, judge 7¢), round 2 continued from round 1 on 6 tests (3 inherited + 3 new), tie 6/6 vs 6/6 (2¢ / 6¢,
  judge 10¢); the plan reserved both runs at start (2 of 20).

### Cloud review 2026-10-30 — statistics on one fair basis; a second v5 run (no deploy yet; release 27 awaits the owner)
- **One basis:** headline numbers count only fair comparisons — equal tools AND no held-out signal to EvoForge.
  Excluded and counted (production): 3 strict-harness matches — 2 of them EvoForge "wins", one only from the strict
  patch rule — and 1 older oracle-feedback match. The review's "6-0-19, p = 0.031" mixed those in; we do not claim it.
- **Second v5 run, same conditions (12 matches):** all 12 ties — both sides 11/12 (both failed SV5-AO-01). Model cost
  EvoForge 347¢, single 132¢. More data did not separate them this time.
- **Fair total after it (33 matches):** EvoForge 3 wins, single 0, ties 30; tasks solved 30 vs 27; cost 822¢ vs 333¢
  → EvoForge solved 3 more tasks at 163¢ extra per extra task; sign test p = 0.25 (not significant).
- **Replay (paired per round, 30 pairs):** EvoForge alone verified 6 rounds, single alone 2, both 16, neither 6;
  p = 0.29. The Replay disclosure wrongly said EvoForge saw failing held-out test names; every run used Critic
  feedback. Corrected when served (flagged), and new runs store the right sentence.
- **Performance pooled:** v5 harness /3, single 31/36 vs EvoForge (Critic feedback) 35/36, intervals overlap; v3
  saturated (48/48 both) — a harder suite is needed to separate them.

### Wrap-up 2026-10-30 evening — merged PRs, a fresh PR, public repositories
- **Outcome:** the owner merged evoforge-target PR #7 (`8dbb8f56`); `POST /v1/outcomes` recorded it VALIDATED →
  validated improvements 0 → 1. PR #8 (CI, README, median demo mission) merged; the target's CI passes on `main`.
- **D14 checked on a new PR:** mission `msn_f93c2cb43d98` (median, even length) → PR #9: word-boundary title, one
  descriptive commit per file, trailing newlines, verify link, target CI passes. Left open for the live demo.
- **Public:** source https://github.com/itproanalysis/evoforge (the submission branch only; full-history secret scan
  clean) and https://github.com/itproanalysis/evoforge-target.
- **Open gap, not deployed:** recording an outcome does not link the evidence chain's Outcome stage, so the Evidence
  page shows it empty. Fix + test on `release/2026-10-30-28` (680b7289); its full gate did not finish.
- **Release 28 (deployed the same night):** source `2d7787ee` = Outcome-stage link (680b7289) + Codex's PromptBar
  caption fix (f5b06c6a) + Codex's PR-URL-string fix (3757a949, API part). Cloud Build gate 1328 passed / 65 skipped;
  local PostgreSQL subset 197 passed. Revisions API 00048-pkb, Web 00046-mdk, Runner 00037-mzt. PR #7's outcome was
  repaired once → Outcome event `ev_138160a46fca`; certificate `cert_fdb4cf3cf564` still verifies offline.
