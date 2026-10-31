# EvoForge north star — owner's direction (2026-10-29)

**Owner update 2026-10-31:** Judges must not enter API keys. The owner explicitly
selected GPT, Gemini and Claude in the default collaboration path, using
server-managed platform credentials. Muse Spark 1.3 remains principal Builder;
GPT-6.1 Sol and Gemini 4 Argon supply independent implementation advice;
Claude Opus 5.5 is the independent spec-first Critic. This supersedes the old
same-Spark Critic/BYOK-first judging default below. Keep the single lane a
single Spark call, label the comparison as multi-model system vs single model,
show actual costs, preserve public limits and never silently substitute models.
This does not approve an unrestricted external BYOK launch or final submission.

> One screen, two lanes: the same task goes to **EvoForge** (left) and to a **single AI** (right). You watch both work in
> real time, then see who actually passed the hidden tests and what each cost. Anyone can run it with their own API key,
> in their own isolated session. Today is the preparation stage for AIs collaborating at a level that surprises people.

## What the owner asked for

1. **Split-screen demo.** Left EvoForge, right a single AI (e.g. Opus). Left visibly produces the better result; the
   cost of each side is shown at the top.
2. **Workspace page.** Far left: feature tabs. Main area: left = status of each AI (Builder, Critic, Runner, gates,
   evolution), right = what is being built (code, diff, tests, live preview), bottom = input. You type a goal and watch
   the result evolve live.
3. **External users run it with their own API key.**
4. **Per-user isolated sessions** — EvoForge becomes an external service.
5. This is the preparation stage for remarkable multi-AI collaboration.

## Design decisions (Claude, as release/critic agent; owner may override)

- **The split screen is a product feature ("Arena"), not a video edit.** The demo is a screen recording of the Arena
  page, so every number on screen is live.
- **Fair, honest comparison.** Both lanes get the same task and the same context, and both are scored by the same
  sealed held-out tests that neither lane sees. The single-AI lane is what a chat gives you: one response, applied as is
  (strict `git apply` semantics, harness /1). The EvoForge lane uses its pipeline (harness /2, Critic, up to 3 attempts
  with failing-test feedback). Costs are provider usage per lane. Production already measured this gap on sealed v2:
  single attempt 22/36 vs EvoForge pipeline 36/36.
- **Right lane model.** Default: the same model single-shot (isolates what EvoForge adds). With a user-supplied
  Anthropic key, the right lane can be Claude (e.g. Opus) — a system-vs-model comparison, labelled as such.
- **Sessions without accounts first.** A visitor enters an API key; the server creates an isolated session
  (opaque `__Host-` cookie) mapped to its own tenant/project in PostgreSQL (row-level security already scopes every
  runtime table). Keys live only in server memory for the session lifetime, encrypted at rest in memory, never logged,
  never returned, never written to the database. Each session has a hard spend cap and rate limit. Accounts/OAuth can
  come later.
- **Visible results.** Add sealed "visual" tasks whose output is a small HTML/SVG page, scored by held-out DOM tests and
  rendered side by side in a sandboxed preview (`iframe sandbox`, `srcdoc`, strict CSP) so the evolution is something
  you see, not only a number.

## Phases and acceptance

| Phase | What | Owner | Done when |
|---|---|---|---|
| A1 | **Arena engine** (`POST /v1/arena`, two lanes run concurrently as one job, held-out scoring for both, usage cost per lane, per-lane event log) | Muse T44 (Builder), Claude (Critic) | sealed T44 green; production arena on a v2 task shows EvoForge pass + single-shot fail with costs |
| A2 | **Arena split-screen UI** (left EvoForge / right single AI, cost header, per-lane timeline, diff and test results, verdict) | Muse T45, agy polish | recording the page gives the demo video |
| A3 | **Workspace shell** (left feature tabs; AI status / implementation / input layout; live via SSE T40) | Muse T46, agy | a goal typed at the bottom streams live progress on both panels |
| A4 | **Visual sealed suite + sandboxed preview** (HTML/SVG tasks, DOM held-out tests, side-by-side render) | Claude (suite, Critic-owned), Muse (preview) | arena on a visual task renders both outputs; scores come from held-out tests |
| B1 | **Per-session tenancy** (session → tenant/project in PG, creation, expiry, RLS checks, deletion) | Codex | two sessions cannot read each other's missions, evidence, measurements, ledger |
| B2 | **BYOK key vault + provider adapters** (Meta, Anthropic), per-session caps, rate limits, key redaction tests | Muse (API), Codex (vault), Claude (security review) | keys never appear in logs, DB, responses; spend cap enforced per session |
| B3 | **External launch hardening** (abuse limits, ToS/consent text, cost display, incident switch) | Claude + owner | owner approves public access |

Order: A1 → A2 (demo-ready) in parallel with B1; then A3/A4; then B2/B3. Nothing in B is opened to the public until B3.

**Owner update (2026-10-29):** API keys and the Claude/Opus lane come **last, at submission/demo time**. Until then the right
lane is the same model single-shot, and the work is to make EvoForge itself much stronger (A1–A4, B1, reliability,
verification depth, multi-AI collaboration). B2/B3 wait.

**v3.6 addendum (2026-10-29):** the owner's v3.6 assessment is mapped to work in `docs/V36_EXECUTION_PLAN.md` — product
rules (results over chatter, RECEIVED ≠ APPLIED, opened PR ≠ WVI, honest cost labels, fair Arena manifest, no 10× claim
without a matched experiment) and the P0 owners. Read it before picking UI, Arena or metrics work.

**v3.8 addendum (2026-10-29):** *EvoForge — AI That Evolves How AI Builds.* The signature screen is the **Evolution
Arena**: one app evolves R1→R5, each round leaves a replayable snapshot (preview, cumulative tests, cost, status) for
EvoForge and a single AI side by side. Plan, rules and owners: `docs/V38_EVOLUTION_ARENA_PLAN.md`.
