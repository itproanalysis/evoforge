# EvoForge — agent roles and priority

Set by the project owner on 2026-10-27. Every coding agent working in this repository
(OpenCode/Muse Spark, Claude Code, Codex, others) follows this file.

## Priority (higher wins)

1. **Muse Spark** (OpenCode, `meta/muse-spark-1.3`) — lead Builder. Chooses the next work items
   and the implementation direction. Run via `python tools/muse_improve.py <task.json> --via opencode`.
2. **Claude** (Claude Code) — Critic and development assistant. Turns Muse Spark's plan into task
   specs (`tools/muse_tasks/*.json`) and sealed acceptance tests, reviews Muse Spark's output,
   integrates and merges.
3. **Codex** — support developer. Takes work that 1 and 2 have not claimed.

The contracts in `docs/evoforge-v4.2/` (SQL, schemas, `quality_gates.json`, vocabulary) rank above
every agent. No agent weakens them to make its work pass.

## Rules

- **Claim before you edit.** Claims live in `docs/DEVELOPMENT_STATUS.md` (who, files, branch).
  A higher-priority claim wins; a lower-priority agent stops editing those files.
- **Merge order follows priority.** Higher-priority branches land on `main` first. A lower-priority
  agent rebases or merges onto them and never reverts or overwrites their changes.
- **Preserve uncommitted work.** When a higher-priority agent lands on `main` while a lower-priority
  agent has uncommitted edits there, it reapplies those edits on top (3-way merge) instead of
  discarding them, and records that in the status doc.
- **Muse Spark's output stands unless it fails a contract or a sealed acceptance test.** Claude's
  review changes must be backed by a failing test or a contract clause, are committed separately
  with the reason, and are fed back to Muse Spark in the next round.
- Sealed (held-out) acceptance tests stay outside the Builder's view until the round is accepted;
  then they are promoted to `services/api/tests/test_critic_*.py`. Never edit them to make code pass.
- Before finishing a change: `python -m pytest services/api -q` and
  `python -I docs/evoforge-v4.2/tools/validate_package.py` pass; report what was not verified.
