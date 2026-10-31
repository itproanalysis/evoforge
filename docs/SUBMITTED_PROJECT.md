# EvoForge — public fields as submitted

Submission ID: `e6c69e57-1455-48aa-9333-566c8922e3d3`

Track: Indie Developer Track · Push the Frontier

## Team Name

EvoForge

## Project Description

EvoForge is a coding workspace that turns AI-written changes into results developers can inspect and verify. It addresses a practical problem: plausible code and a confident agent conversation are not evidence that a change works.

Muse Spark 1.3 is the principal Builder. GPT-6.1 Sol and Gemini 4 Argon provide independent implementation plans; Claude Opus 5.5 is the specification-first Critic. A separate Runner executes tests, PostgreSQL preserves scoped state and cost reservations, and Ed25519 certificates make recorded result bytes checkable. The workspace shows EvoForge and a single Spark call side by side, with model costs and disclosed allowances. Judges can try the server-funded defaults without entering API keys.

Live product: https://evoforge-web-230852112787.asia-northeast3.run.app/en
Recorded four-model run: https://evoforge-web-230852112787.asia-northeast3.run.app/en/share/job_306819b0b688
Verify: https://evoforge-web-230852112787.asia-northeast3.run.app/en/verify/job_306819b0b688

The recorded run passed 13/13 hidden checks in both lanes: a tie, not a superiority claim. Model API usage was 10 cents for EvoForge, 3 cents for the single call and 13 cents for the shared Judge; Runner compute is excluded. Separately, an earlier same-model, single-attempt experiment improved Spark from 22/36 to 35/36 tasks by changing only the patch harness, with non-overlapping 95% Wilson intervals. Historical measurements are not presented as results of the new four-model configuration.

Hackathon contributions include the deployed workspace, model orchestration, execution and evaluation paths, durable evidence and signed-proof workflow. Earlier design documents are background, not claimed as newly written implementation. The video is an edited, narrated walkthrough of recorded production evidence, not a live screen recording. Current limits: one shared project and a 20-run site-wide daily quota. Signatures authenticate certificate bytes; adversarial verifier hardening remains unfinished.

## Public GitHub Repository

https://github.com/itproanalysis/evoforge

## 3-Minute Demo Video

https://github.com/itproanalysis/evoforge/releases/download/submission-evidence-2026-10-31/EvoForge_Evidence_Walkthrough.mp4

## Describe your use of Meta products to build the submitted project

Muse Spark 1.3 through Meta Model API is the principal Builder in EvoForge and the model used in the single-call comparison lane. The service turns its output into patches, applies them against a base tree, evaluates the resulting code with a remote Runner, and records usage-derived integer-cent model costs.

We used real Spark runs to diagnose and improve the patch harness, then re-measured the change on sealed tasks. In a controlled repeated experiment, Spark improved from 22/36 to 35/36 tasks when only the harness changed; both runs used 96 cents of model API usage and the 95% Wilson intervals did not overlap. This is a measured harness improvement, not a universal model ranking.

The current owner-approved collaboration adds GPT/Gemini implementation planning and an independent Claude Opus Critic while preserving Spark as the implementation model. We do not claim to use Muse Wonder, Muse Image, Muse Code or Meta open-weight models in the deployed default path.

## Why are Meta's models important to your solution?

Muse Spark is the implementation engine, not a decorative integration. Its real code outputs expose the failure modes EvoForge is designed to measure: patch applicability, correctness, regressions and the cost of repeated attempts. Keeping Spark as the principal Builder and the single-call comparison model lets us distinguish a harness improvement from changing the underlying model.

The project demonstrates how to build a verifiable workflow around Spark: preserve the original specification, separate implementation advice from independent tests, execute code outside the API service, account for model usage, and publish inspectable result certificates. The measured same-Spark harness gain is our strongest quantitative result; the new four-model run demonstrates operation, not statistical superiority.
