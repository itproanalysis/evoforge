# AGENTS.md — EvoForge build coordination (all agents, human or AI)

Read `docs/COORDINATION.md` before touching shared paths. The short version:

1. **Never commit another agent's files.** Stage only paths you own (`git add <path>`, never `git add -A`).
2. **Never submit a Cloud Build from a dirty tree.** Deploys go only from the
   pristine `release/*` worktree (see COORDINATION.md). A build from a live
   workdir captures other agents' half-written files and fails or ships WIP.
3. **Module ownership is exclusive** (table in COORDINATION.md). If you must
   touch another module, leave the tree green and note it in your commit msg.
4. **CI gates are the law:** `validate_package --pg`, `pytest services/api -q`
   (450+ tests), `tsc --noEmit` + `npm ci` in `apps/web`. Do not weaken them.
5. Money is integer cents. No LiteLLM. No BYOK UI. No secrets in repo or logs.
