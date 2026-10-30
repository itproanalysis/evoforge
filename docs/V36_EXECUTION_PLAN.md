# v3.6 feedback → execution plan (2026-10-29)

Source: owner-supplied assessment *EvoForge v3.6 — Current Assessment and Product Transformation Feedback* (read-only
review of the live site). Its verdict: the verification backend is real, but the product people see does not yet show
(1) the result evolving on screen, (2) the AIs working as a team, (3) a fair comparison with a single AI, or (4) a
self-service path for outside users. This file maps every P0 in that review to work that exists or is assigned.
**Read `docs/NORTH_STAR.md` first; this is its v3.6 addendum.** Owner rule still applies: keys and the Opus lane come
at submission time, so B2/B3 wait. Everything else below is now.

## Product rules from v3.6 (binding for all agents)

1. **Results over chatter.** The largest area of every screen is the thing being built (diff, tests, rendered preview),
   not agent messages. No decorative agent animations: every handoff, state or badge comes from a recorded event.
2. **RECEIVED ≠ APPLIED.** A command or goal is acknowledged at once, but "done/implemented/PASS" appears only after a
   build and held-out tests confirm it. A failed build keeps the last good preview and says `LATEST BUILD FAILED`.
3. **Opened PR ≠ verified improvement.** WVI counts a PR only after merge + a VALIDATED outcome (AT-20).
4. **Cost labels say what they measure.** Model API usage, Runner compute and platform fees are separate; a number
   that is only model usage is never called "total cost". BYOK spend is never shown as an EvoForge charge.
5. **Fair comparison, failures shown.** Both Arena lanes get the same task spec, base tree, tests and deadline; every
   allowance difference (attempts, feedback source, harness) is printed on screen. A lost or tied arena is shown as is.
6. **No 10× claim** until a matched-condition experiment shows it (see "Proof experiments" below). Presets and demos
   never display invented wins, prices or PASS states (W27).
7. **Live / Replay / Edited** are labelled. An edited video names the run id it was cut from.

## P0 map

| v3.6 ID | What | Status / owner | Done when |
|---|---|---|---|
| ENG-02 | PR_OPENED vs WVI=0 explained | **Claude, done** `claude/v36-wvi-honesty` `83befd7`: dashboard returns `prs_awaiting_validation`, the WVI rule and `spend_basis`; Mission Control shows the tile, the rule and "Model API spend (provider usage)" | AT-20; release 9 |
| COMP-01 | Two-lane Arena | **done** T44 engine (Muse) + agy split-screen UI, both in release 8 | production arena run recorded |
| COMP-02 | Fair-comparison manifest (spec hash, held-out hash, base tree, lane allowances, cost basis, disclosure) | **done** Muse T48 `f5b276f` (Critic fix: no inherited lane tree), UI rendering of the manifest → agy/Codex W27 after T48 | AT-17, AT-18: both hashes and every allowance visible on the Arena page |
| COMP-02b | EvoForge lane without the held-out oracle | **done** Muse T47 `a384a93` (`feedback="critic"`: retries see only spec-first Critic tests; held-out only judges) → arena lane option next | Arena can run both lanes with no held-out signal; v3 measured both ways |
| UX-01 | Mission Control: left tabs, AI panel, large implementation panel, fixed bottom input | agy cockpit (W26) exists; **Muse T46** wires it to real missions + SSE (T40) | typed goal → ACK → live stage events → diff/tests in one screen |
| CMD-01 | Command fast lane: `POST /v1/missions/{id}/commands` (idempotent, ACK vs APPLIED) | **Muse T50** (after T48) | AT-06: same command 3× → one task, one charge |
| ENG-01 | Agent presence from real events (role, current task, waiting/blocked reason, last evidence) | **Muse T49** (`GET /v1/agents/presence` from mission/eval/arena events) | AT-12/13 states; no state without an event |
| UX-02 | Versioned live preview | **A4**: sealed v4 visual suite **done** (Claude `f37409a`: 12 UI tasks, `render()` → XHTML/SVG, held-out DOM tests, `preview()` per task). **done** Muse T49 `d956805`: Arena on v3/v4, per-lane preview run in an isolated subprocess (no secrets, 10 s, 64 KB), `SandboxedPreview` = `iframe sandbox="" srcDoc` | AT-09/AT-10 on a visual task |
| SAAS-01 / SEC-01 | Workspace + tenant isolation | **Codex B1 / W25** (session registry, migration 013) | AT-01, AT-02 with live-PG tests |
| **SEC-02** | **Candidate code must not run in the API container.** Pipeline scoring, Arena lanes and T49 previews execute Builder output locally in the API service, which holds secrets and can reach the GCP metadata server (service-account token) and `/proc/<ppid>/environ`. Acceptable only while every candidate comes from our own model on sealed tasks. | **done in code** — Muse T68 `fd1c8694` (ownership exception, Claude reviewed): with EVO_RUNNER_URL set, all candidate and model-written code (pipeline, Arena, evolution, previews, judge filtering) runs through `runner_client.run_files` -> Runner `/run` (+ failures, preview_module); fail closed, no local fallback. Production check after release 17. Still open: block metadata egress on the Runner (network policy) | blocked public/BYOK until shipped |
| SAAS-02 | GitHub App + BYOK self-onboarding | **deferred to submission** (owner) | — |

Phase 0 item from the review, *anonymous visitors can see missions and spend*: today the public site shows the operator's
own project (our proofs). That stays public on purpose, but it must be labelled as the operator's public evidence, and
every visitor session (B1) must start empty. Claude labels it in release 9; Codex B1 enforces it.

## Proof experiments (Claude owns the protocol, Muse/Codex run code)

v3.6 asks the right question: is it the *orchestration* that wins, or just more calls? We already have A (single shot,
22/36) and the EvoForge pipeline (36/36, with held-out feedback = upper bound). Add on sealed v3 (48 tasks, 12 hard):

- **A** single shot, strict apply (harness /1).
- **B** single shot, tolerant apply (harness /2) — isolates the harness.
- **C** best-of-3 independent samples, no feedback — same call budget as the pipeline, no orchestration.
- **D** EvoForge pipeline, Critic feedback (T47), no held-out signal.
- **D⁺** EvoForge pipeline, held-out failing-test names (current upper bound, labelled as such).

EvoForge's orchestration claim holds only if **D beats C** with non-overlapping Wilson 95% intervals at equal call
budget; cost per passed task is reported for every arm. Results go to `/performance` whatever they are.

## Acceptance tests that gate any public "try it" launch

AT-01, AT-02, AT-03, AT-10, AT-17, AT-18 and AT-20 from the review. Until they pass, outside users see the operator's
public evidence and recorded Arena runs only, labelled as such.

## Releases

Release 10 = release 9 + T48 + T49 (gating). Arena page wiring of manifest + previews → agy/Codex W27 next.

### Release 9 (2026-10-29)

`release/2026-10-29-9` = release 8 + T40 SSE + T41 MCP + sealed v3 + sealed v4 + T47 + ENG-02. Gates running; deploy
from `C:\evo_forge_rel9` when green. Then measure on production: v3 A/B/D/D⁺ and the first visual Arena (v4).
