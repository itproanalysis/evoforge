# EvoForge — submission (Meta Global AI Developer Hackathon · Indie · Push the Frontier)

Updated 2026-10-30 (release 26). Every number below is a stored production measurement or ledger entry; IDs are given so a judge can
re-check them.

## One line

**A code-improvement service that only ships what it can prove, and proves it is getting better.** Muse Spark writes the
patch; an independent Muse Spark Critic writes sealed tests from the spec before it sees the patch; a server-side runner
executes them; integrity gates block anything unproven; every result carries an Ed25519-signed certificate anyone can
verify. The service measures its own harness on a sealed benchmark and adopts a change only when the 95% intervals do
not overlap.

## Proof (production, muse-spark-1.3, Cloud Run + Cloud SQL)

Sealed suite v2 — 36 tasks, 6 families, held-out tests never shown to the Builder. Same suite, same model; only the
harness differs.

| Measurement | Harness | Result | Wilson 95% |
|---|---|---|---|
| X_SINGLE (one Builder attempt) | api-sealed-eval/1 — strict diff apply | 21/36 = 58.3% | 42.2–72.9% |
| X_SINGLE | api-sealed-eval/2 — hunk-count recount | **35/36 = 97.2%** | **85.8–99.5%** |
| PIPELINE (≤3 attempts, held-out failure names + assertion lines as feedback — see note) | api-sealed-eval/2 | **36/36 = 100%** | 90.4–100% |

- Verdict computed by the service: **improved** — the /2 lower bound (85.8%) is above the /1 upper bound (72.9%).
- **Replicated by the service's own A/B** (`POST /v1/eval/abtest`, decision `dec_9eccf43b2401`, both runs re-measured in one
  job): /1 22/36 (44.9–75.2%) vs /2 35/36 (85.8–99.5%) → **adopt** ("improved: lo 0.86 > hi 0.75"). Both runs now use
  provider-usage cost: 96¢ per 36 tasks (≈2.7¢ per task); the earlier 4320¢ figure was the fixed reservation rate.
- **Pipeline caveat (found in review):** retries receive the failing held-out test names and assertion lines, which can reveal
  expected values; treat the pipeline number as an upper bound. The harness proof above is single-attempt with no feedback and is
  unaffected. The Critic-feedback pipeline (T47: feedback only from the independent Critic's tests, held-out used only for the
  final score) has since shipped; the v5 results below use it.
- Pipeline cost from provider usage: **88¢ for 36 tasks (≈2.4¢ per solved task)**; every task passed on its first
  attempt.
- How we got there, honestly: the first baseline (sealed v0, 12 tasks) was 2/12. Diagnosis with the real Builder showed
  the tests checked behaviour the task goals never stated (v1 fixes the goals, tests unchanged → 7/12), and 7 of the
  remaining failures were diffs rejected only because the model miscounted `@@` hunk lengths (harness /2 → 11/12). On 12
  tasks that gain was **not** statistically clear and the service said so ("no clear difference"); v2 with 36 tasks
  separates it. See `docs/EVAL_V1_GOALS.md`, `docs/ROADMAP_EVOLUTION.md`.

## Harder tasks and equal tools (2026-10-29 evening)

The v2 gain above is a harness gain. To ask the harder question — does EvoForge beat a single AI **with the same tools**? —
we gave the single shot the same tolerant patch application (harness /2) and a 32k output budget:

- **Sealed v3 (48 tasks) is saturated:** single shot 48/48 (`m_2237cf978add`), Critic pipeline 48/48 (`m_3035d3cb1682`).
  No orchestration effect can show on it, so we said so and built a harder suite.
- **Sealed v5 (12 rule-dense tasks, calibrated against the real model first):** every single-shot miss was a large rewrite
  whose diff did not apply, not a logic error. EvoForge's response was to evolve the harness again: **api-sealed-eval/3**
  recovers a whole-file rewrite when the hunk's old side is exactly the file.

| v5, production | Passed | Wilson 95% | Model cost |
|---|---|---|---|
| Single shot, harness /2 | 9/12 | 47–91% | 115¢ |
| Single shot, harness /3 | 10/12 | 55–95% | 140¢ |
| Single shot /3, three runs pooled | 31/36 | 71–94% | 417¢ |
| **EvoForge /3 + Critic feedback (no held-out signal), three runs pooled** | **35/36** | 86–99.5% | 840¢ |

EvoForge led in every run (12–10, 12–12, 11–9) and never lost a task the single shot passed, at about **twice the model
cost**. The intervals still overlap, so we do **not** claim significance yet. IDs: `m_d475978dabed`, `m_f43769eae727`,
`m_34a9a98e50bb` and the two repeat runs on `/performance`.

**The same comparison in the Arena (2026-10-30, release 22, equal tools — both sides recount hunks; EvoForge gets
only its own Critic's tests, never a held-out signal):** EvoForge solved **12/12** v5 tasks, the single shot **9/12**;
paired 3 wins, 0 losses, 9 ties; hidden tests 36/36 vs 27/36; model cost 264¢ vs 135¢. A second run under the same
conditions was 12 ties (both 11/12). All fair Arena matches together (33): EvoForge 3 wins, 0 losses, 30 ties; solved
30 vs 27; 163¢ extra per extra task solved; sign test p = 0.25 — not significant, and the site says so. Every match is on `/arena` with its fairness manifest; the scoreboard is on the home page. We first ran
these matches with the original strict single-lane harness, saw a "win" that came only from that rule, stopped, fixed
the harness and re-ran — the strict-harness matches are not counted here.

**What EvoForge changed about how it builds today, each found from its own production evidence** (`docs/V38_EVOLUTION_ARENA_PLAN.md`):
the Builder ran out of output tokens on larger rounds (8k -> 32k); a Critic test that a later round legitimately breaks
kept burning retries (stale tests are retired); Critic tests that cannot run in the sandbox made every attempt look failed
(sandbox-runnable filter); large rewrites failed to apply (harness /3); a round goal omitted a rule its test checked (goal
fixed). That is the claim the data supports: **AI that evolves how AI builds**, with every change measured.

## Evolution Arena (v3.8) and the user-prompt Arena

- `/replay`: one app evolves R1-R5 in two lanes (EvoForge vs single AI) from the same start; every round x lane is an
  immutable snapshot (source hash, cumulative held-out score, rendered preview, cost, status READY / UNVERIFIED /
  FAILED); replay never calls a model; a 16:9 presentation mode plays a recorded run; stats with Wilson intervals; the
  EvoCore panel shows build strategies, the champion and promotion decisions (a challenger is promoted only on
  non-overlapping intervals).
- `/arena`: the user types what they want at the bottom. Before either side runs, an independent judge Critic writes
  acceptance tests from the prompt only (tests already passing on the empty template are dropped; the suite is hashed
  and never shown to either side). Both sides build from the same template with the same patch tolerance, are scored on
  that suite and shown side by side; with fewer than 3 meaningful tests the round is "unscorable" and no winner is shown.
  Follow-up requests continue each side from its own result on the cumulative suite, so a lost feature shows.

## Live verified PR with a signed proof (2026-10-29)

Mission `msn_87b0a3b13fb1` ("add div(a, b), ValueError on b == 0") ran CREATED → GENERATED → REVIEWED → RAN → PR_OPENED in
production: GH_INTEGRITY, GC_COMPOSITION and G2_REQUIRED all PASS (visible 2/2, held-out 3/3) →
[itproanalysis/evoforge-target#7](https://github.com/itproanalysis/evoforge-target/pull/7). The PR body carries certificate
`cert_fdb4cf3cf564` (Ed25519, verdict VERIFIED) and a `/verify/ev_0b8f99df27e9` link. Fetched by id and checked offline with
only `GET /v1/proof/key`, the signature is valid; changing one field makes it fail. The same goal was blocked twice before
— once by GH_INTEGRITY for a tautological Builder test, once by a Runner that still used the strict diff parser — and both
causes were fixed (strong-oracle prompts T25, shared patch module in the Runner).

**Merged and recorded (2026-10-30):** the owner merged PR #7 (merge commit `8dbb8f56`), and `POST /v1/outcomes` recorded
it as a VALIDATED outcome: the dashboard's validated improvements went from 0 to 1 (`GET /v1/outcomes` lists it). An
opened PR alone never counts. Release 28 links the evidence chain's Outcome stage when an outcome is recorded; the
PR #7 outcome, stored before that, was repaired once with the same mission and merge sha, so its chain now runs
ObjectiveVersion → … → PR → Outcome (event `ev_138160a46fca`), a repeat is refused (409), and the original certificate
`cert_fdb4cf3cf564` still verifies offline.

**A fresh PR after the PR-quality fixes:** mission `msn_f93c2cb43d98` (the target's demo bug: `stats.median` returns the
upper middle item for an even-length list) ran end to end in production (Builder 11 s, Critic review 26 s, run 7 s; all
three gates PASS, visible 2/2, held-out 3/3) →
[itproanalysis/evoforge-target#9](https://github.com/itproanalysis/evoforge-target/pull/9). Its title is cut at a word
boundary, each commit says what it does ("Update stats.py", "Add test …_1.py", "Add test …_2.py"), every file ends with
a newline, the body links `/verify/ev_ab527200a91d` (certificate `cert_bc70834c9902`, VERIFIED), and the target's own
GitHub Actions CI passes on it. PR #9 stays open so
the same demo mission can be run live.

## Why it pushes the frontier

1. **Verification is the product.** PRs open only when the server run passes the Critic's sealed tests and the
   integrity gates (GH_INTEGRITY oracle strength / held-out gap, GC_COMPOSITION, G2_REQUIRED). A live mission that passed
   every test was still blocked because a Builder test was a tautology under the frozen oracle classifier — the gate
   chose "inconclusive" over a false success.
2. **Signed, re-checkable results.** `GET /v1/proof/{evidence_id}` returns a certificate signed with Ed25519 (key in
   Secret Manager); `GET /v1/proof/key` publishes the public key; certificates are stored and retrievable by id; an
   edited certificate fails verification offline. Verified PRs quote the certificate and link `/verify/<id>`.
3. **It improves itself, under statistics.** Harness versions are selectable per measurement; `POST /v1/eval/abtest`
   runs champion vs challenger as one background job and records "adopt" only on non-overlapping intervals. The
   Performance page shows the measured timeline (intervals, harness markers, per-family heatmap) and the adoption
   history.
4. **Honest by construction.** Missing data is shown as "not measured"; X_SINGLE fixed-rate cost is labelled as such
   until usage-derived accounting ships; budgets refuse worst-case runs before any model call (402).
5. **Built by Muse Spark under the same discipline.** Tasks T24–T67 of this service (async eval jobs, hunk recount,
   signed proofs, evolution persistence, timeline UI, champion/challenger, …) were implemented by Muse Spark through
   OpenCode against sealed tests written by an independent Critic agent; out-of-scope edits were reverted
   automatically; nothing merged without the full suite passing. (T29's last piece was finished by the Critic after
   the loop stalled; the commit says so.)

## Check it yourself

```bash
WEB=https://evoforge-web-230852112787.asia-northeast3.run.app
curl -s $WEB/api/evoforge/v1/arena/summary      # all matches + equal-tools block with solved counts, Wilson 95%, sign test p
curl -s $WEB/api/evoforge/v1/arena              # every Arena match with its fairness manifest (lane events, costs)
curl -s $WEB/api/evoforge/v1/performance        # measurements, verdict, history (storage: postgres)
curl -s $WEB/api/evoforge/v1/proof/key          # Ed25519 public key
curl -s "$WEB/api/evoforge/v1/eval/suites?suite_version=v5"   # sealed suite: hashes and lengths only, never code
```

Pages (English at `/`, Korean at `/ko`): `/` is the workspace canvas — both sides' output side by side (Screen / Code /
Tests), the run picker, the input at the bottom, and Measurements (EvoForge vs single hidden tests, wins/ties and the
significance sentence) one click away; `/arena` (scoreboard, sealed v5 by default, every match with its manifest),
`/replay` (round-by-round evolution, presentation mode), `/verify/<id>` (signed certificate), `/performance`,
`/evidence`, `/lab`, `/evolution`, `/leaderboard`. Every page fits a 375 px phone.

**Try it yourself (release 26).** Anyone can start a comparison from the input at the bottom — no login — within a
daily limit of 20 runs for the whole site (`GET /v1/arena/limits`; one round = one run; a 429 tells you when it is
used up). Choose **New run**, write a different mission for each round (up to 5: round 2 continues from round 1's
code, and so on) or pick a **Challenge** (bakery site, tip calculator, password meter, to-do list, unit converter)
that fills the rounds for you. Every finished match has a public **Share** link (`/share/<id>`) with both outputs,
hidden-test scores, costs, the verdict, the fairness disclosure and its certificate id.

## Architecture

Next.js web (Cloud Run, same-origin proxy with a path allowlist) → FastAPI API (Cloud Run, private IAM: only the web
service account may invoke) → Meta Model API (`muse-spark-1.3`) for Builder and Critic, GitHub for PRs, a separate
Runner service (no secrets, no roles) for candidate execution, Cloud SQL PostgreSQL 15 with forced row-level security,
Secret Manager for every key. Integer cents ledger with reservation before every model call.

## Measured against our own 50-page blueprint

`docs/SPEC_GAP_REVIEW.md` grades all 185 blueprint requirements against the running service: **65 live, 43 partial,
27 implemented as tested modules not yet wired into the service, 50 not started.** The verification core (blueprint
§32, §35–38, §42) is live; collaboration surfaces (MCP, Folder Bridge, A2A, Collective Graph), billing and multi-tenant
onboarding are not.

## Known limits

- Single tenant, no login (owner decision); all visitors share one project and one public run history.
- The cost ledger is durable since release 9 (T39); earlier spend from before that release is not in it. Live updates use
  SSE (T40) with polling as fallback.
- Candidate code (pipeline scoring, Arena lanes, previews) runs in the secret-free Runner since release 18 (T68,
  fail closed); the Runner's metadata-server egress is still open (SEC-02 remainder) — a precondition for public or
  bring-your-own-key use.
- Prompt Arena: the judge is the same model family as the Builders; since release 21 its hidden tests are kept only if
  they pass on a judge reference build (T76), and both sides get the interface those tests call (T73). Prompt-Arena
  matches so far are ties or unscorable — no prompt-Arena win is claimed.
- Paid runs are public within one site-wide daily limit (20 runs, owner decision 2026-10-30); there is no per-user
  account or quota yet, so one visitor can use the whole day's runs.
- The oracle-strength classifier uses a 20-item human-labelled holdout; the blueprint's M0 bar is 200.
- One model in production (muse-spark-1.3). The Critic can run on a second Meta open-weight model through any
  OpenAI-compatible endpoint (T72, env-only, refuses without owner-set prices); it is switched on at submission.
- Runner reports are produced in the same process as candidate code. Our Codex agent showed a candidate can forge a passing
  JUnit report (`atexit`); layered defences (diff screen, parent-side cross-checks, fresh interpreter per held-out file)
  are being added, and an independent observer with signed receipts is the long-term boundary. Until then, verification
  holds against a model that writes ordinary code, not against an adversary that targets the harness.

## Team

Owner: itproanalysis. Builder agent: Muse Spark (via OpenCode). Critic / release agent: Claude. Supporting agents:
Codex (runner, persistence, and the owner-requested workspace canvas redesign of release 25), agy (web). Coordination rules: `AGENTS.md`, `docs/COORDINATION.md`.
