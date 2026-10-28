# EvoForge evolution roadmap — a code service that proves it gets better

2026-10-28. Owner priority: Muse Spark 1 > Claude 2 > Codex 3. Work rows live on the board (`docs/COORDINATION.md` §6).

## What is new here

Code agents today ask to be trusted. EvoForge's position is the opposite: **nothing is claimed without a measurement
or a proof**. Two things no one else ships together:

1. **It evolves its own way of working and shows the measured learning curve.** Harness changes (prompts, diff
   application, retry feedback, memory) are adopted only when they beat the current champion on a sealed evaluation
   with non-overlapping confidence intervals, and every adoption is a row on `/performance`.
2. **Every result carries a proof anyone can check.** Gate verdicts, evidence chain and diff digest are signed by the
   server (Ed25519); the public key is published; a PR links its certificate.

## Where it stands (measured, 2026-10-28)

| Measurement | Result | Note |
|---|---|---|
| Production X_SINGLE, sealed v0 (`m_045caf7c2f1e`) | 2/12 = 16.7% (Wilson 4.7–44.8%) | v0 goals omit required behaviour (`EVAL_V1_GOALS.md`) |
| Local, sealed v1 goals, strict diff apply | 5/12 | 7 misses: diffs rejected on hunk header counts |
| Local, same Builder outputs, hunk counts recomputed | 12/12 (Wilson 75.8–100%) | single local run, not an official number |

Lesson: most of the gap was the harness and the task specs, not the model. That is exactly the kind of improvement
the evolution loop has to find and prove by itself.

## Milestones (each has an exit test)

| # | Milestone | Work | Exit (measured) |
|---|---|---|---|
| M1 | **Honest measurement** | T24 async eval jobs, T26 hunk recount, T25 strong-oracle prompts, sealed v1 data (done) + v1 loader, W4 usage-derived baseline cost, W9 failure reasons | Production X_SINGLE and PIPELINE on v1 with Wilson intervals and usage-derived cost on `/performance` |
| M2 | **Self-evolving harness (champion/challenger)** | Harness variants run on sealed v1 as eval jobs; adopt only when challenger Wilson lo > champion hi; adoption history on `/performance`. A second sealed suite (v2, additive, never used for tuning) guards against overfitting to v1 | At least one adopted variant whose win also holds on v2 |
| M3 | **Proof-carrying results** | T27 Ed25519 certificates + `/v1/proof/key`; `/verify/[id]` shows signed/unsigned honestly; PR body links the certificate | A live PR whose certificate verifies offline with the published key; an edited certificate fails |
| M4 | **Autonomous maintenance** | Evolution autopilot (de481a8/f4de75d) on real repos as background jobs with the T27 budget cap; evolutions, memory and leaderboard persisted in PostgreSQL; WVI recorded from merged PRs | Verified PRs merged on a real repo with zero reverts, every one with a valid certificate |

## Rules for claims

- A number on any page comes from a stored measurement or the ledger, or the page says "not measured".
- "Improved" means non-overlapping 95% intervals on the same suite version and model. Otherwise "no clear difference".
- A capability is described only after its exit test has passed in production.
