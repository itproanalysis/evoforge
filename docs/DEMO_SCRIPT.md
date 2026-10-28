# EvoForge demo video script (3 min, Indie track)

Target: show a machine that produces VERIFIED PRs, not claims. All numbers below
are measured live; re-run before recording and update IDs.

## 0:00–0:20 — Problem (20s)
"AI coding tools are fast in the session, but teams can't tell what actually
improved. EvoForge turns agent work into verified PRs or blocks it with evidence."

Show: Mission Control (https://evoforge-web-230852112787.asia-northeast3.run.app).

## 0:20–1:10 — PASS chain (50s)
1. New mission: goal "fix sub() …", repo `itproanalysis/evoforge-target`, target `calc.py`.
2. Advance GENERATED → Builder patch (Muse Spark 1.3, real call, usage tokens shown).
3. REVIEWED → Critic: 3 sealed tests (negative/boundary/compositional), PASS with findings.
4. RAN → hygiene sandbox: visible 3/3, held-out 3/3 → GH_INTEGRITY/GC_COMPOSITION/G2 PASS.
5. PR_OPENED → real GitHub PR. Merge it in the browser.
6. Outcomes: VALIDATED. Dashboard WVI 1, spent/unknown-holds.

Reference (re-run to refresh): PR #6 https://github.com/itproanalysis/evoforge-target/pull/6.

## 1:10–2:00 — FAIL chain (50s)
Mission "webhook 403": Critic FAIL (unwired endpoint) + held-out 0/3 → gap +1.000
→ GH_INTEGRITY FAIL → PR button disabled ("예외 승인 필요"). "Bad code is blocked
with reasons, not vibes."

## 2:00–2:40 — Measurement (40s)
- Sealed v0 catalogue: `GET /v1/eval/suites` (hashes only, code never leaves server).
- X_SINGLE baseline `bl_a42d827d2917`: n=12, pass 2/12 (0.167), cost 1440¢,
  hygiene 7/7 clean. "Single-shot한계가 정직한 분모. Mission 체인이 분자다."

## 2:40–3:00 — Architecture (20s)
Next.js (same-origin proxy) → FastAPI private-IAM → Meta Model API (muse-spark-1.3)
+ GitHub + Cloud SQL PG (RLS, integer cents, no LiteLLM, no BYOK). End card: URLs.

## Recording checklist
- [ ] Fresh mission run on recording day (IDs change after deploys pre-SQL; post-SQL they persist)
- [ ] Ledger spent + dashboard on screen
- [ ] No secrets on screen (proxy uses server identity; keys never in browser)
- [ ] Captions: EN primary, KO secondary
