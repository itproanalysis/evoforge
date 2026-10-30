# EvoForge — 3-minute demo script (recording guide)

Production: https://evoforge-web-230852112787.asia-northeast3.run.app (English by default, Korean under `/ko`).
Record at 1440x900 or larger; every number below is live on the site and in `docs/V38_EVOLUTION_ARENA_PLAN.md`.
Say only what the screen shows. No "10x" claims, no claims of significance.

| Time | Screen | Say (about) |
|---|---|---|
| 0:00–0:20 | Home `/` — the workspace canvas: EvoForge and the single call side by side (Screen view), then open **Measurements** (top right) | "Same request, same Meta model, same tools: EvoForge on the left, one AI call on the right. Measurements: hidden tests EvoForge vs single, wins and ties, and whether that is significant yet." |
| 0:20–0:55 | `/arena` — scoreboard card (equal-tools line first), then the sealed v5 list | "On 12 hard, rule-dense tasks with equal tools, EvoForge solved all 12, the single call 9 — three wins, no losses, nine ties — at about twice the model cost. With n = 12 that is not yet statistically significant, and we say so." |
| 0:55–1:30 | Open the SV5-PM-01 match: both lanes, events, fairness manifest | "Here both first patches failed to apply. The single call has no second chance. EvoForge's Critic wrote its own tests from the spec — it never sees the hidden tests — and the retry passed all of them. The manifest shows equal tools, the task and test hashes, and the costs." |
| 1:30–2:05 | Home input → **New run** → pick the **Challenge** "Bakery site": rounds 1–4 fill in; start; the AI status and outputs update live; open the finished round's **Share** link (`/share/<id>`) | "Anyone can try it — a different mission per round, each round continuing from its own code, within a daily limit. Hidden tests are written and checked against a reference before either side runs. One click shares the result, scores and costs included." (Pre-record the run if it would exceed the time; the recorded match plays from the run picker.) |
| 2:05–2:35 | `/replay` presentation mode (`?present=1&run=<id>`) — rounds R1→R5 | "Apps also evolve over rounds; every round is an immutable snapshot with its score and cost, replayed without calling a model." |
| 2:35–2:55 | `/verify/ev_0b8f99df27e9` — signed certificate, mission chain ObjectiveVersion → PR | "Results are signed with Ed25519 and can be checked offline. An opened PR is not counted as an improvement until it is merged and validated." |
| 2:55–3:00 | Back to home | "AI that measures — and evolves — how AI builds." |

## Before recording
- `GET /v1/arena/limits` — runs left today (one round = one run; 20 per day). A 4-round challenge needs 4.
- `GET /v1/arena/summary` — confirm the equal-tools block (v5: 12 scored, EvoForge 3 / single 0 / ties 9).
- Do not deploy while recording (a deploy restarts the API and kills a running match).
- If the second Meta model is switched on for the Critic (T72), mention it on the manifest (`critic_model`, `critic_provider`).

## Honest limits to keep in the narration
- Prompt-Arena matches so far are ties or unscorable; no prompt-Arena win is claimed.
- Costs are model API usage only (Runner compute not included).
- One tenant, operator-started paid runs; visitors see recorded runs.

---

## Option B — the verified-PR and self-improvement story (previous script, 2026-10-29)
Use these beats instead of 2:05–2:55 if the PR proof matters more than the replay.

### 0:20–1:05 — A verified change, end to end
1. New mission on `itproanalysis/evoforge-target`: "add div(a, b), ValueError on b == 0".
2. GENERATED: Muse Spark Builder patch + its tests.
3. REVIEWED: an independent Muse Spark Critic wrote sealed tests from the spec before seeing the patch.
4. RAN: the separate Runner executes visible + held-out tests → gates GH_INTEGRITY / GC_COMPOSITION / G2_REQUIRED.
5. PR_OPENED: the GitHub PR body carries the signed proof — certificate id, Ed25519 key fingerprint, signature, and a
   `/verify/<id>` link.
Say: "If any gate is unsure, there is no PR. We have had a live mission with every test passing blocked because one
test was a tautology."

### 1:05–1:35 — Anyone can check it
Open `/verify/<id>`: "Ed25519 signed", key matches `GET /v1/proof/key`. Edit one field of the certificate JSON →
verification fails. "A URL instead of a chat transcript."

### 1:35–2:30 — It gets better, and proves it
Open `/performance`.
- Timeline on sealed v2 (36 tasks, held-out never shown to the Builder): harness /1 21/36 (42.2–72.9%) → harness /2
  35/36 (85.8–99.5%), pipeline 36/36 at ≈2.4¢ per solved task.
- "Improved — the intervals don't overlap." Point at the harness marker on the chart.
- Adoption history: champion /1 vs challenger /2 → **Adopted**. "The service ran the A/B itself and only adopts on
  non-overlapping 95% intervals."
- One honest beat: "On our first 12-task suite the same gain was *not* significant, and the page said so. So we built a
  bigger sealed suite."

### 2:30–2:50 — Built the same way
"Muse Spark built this service's own features against sealed tests from an independent Critic: eval jobs, the diff
recount that produced this jump, signed proofs, the timeline you just saw."

