# Design studio refresh — 2026-10-30

Owner request: organize the crowded C: drive and replace the dated web appearance.
The web change starts from release 23 (`44e5ec9e`), preserving the current
workspace, comparison, operator controls, proof links and English/Korean routes.

## Changes

- Persistent desktop navigation, consistent line icons, current-page breadcrumb,
  quiet charcoal surfaces, warm green accent, larger type and more space.
- The home opens with a concise product introduction and four API-bound metrics:
  validated improvements, scored equal-tools comparisons, that cohort's
  EvoForge held-out result, and registered participants. Missing values stay `—`;
  zero remains zero; truncated participant lists use `+`. Registered is not online.
- Existing full comparison measurements and their cost labels remain in an
  expandable detail panel. The AI panel, two implementation previews, per-lane
  scores, actual run status and fixed input remain connected to the same APIs.
- Mobile navigation includes Escape, focus containment and focus return. The
  fixed input leaves bottom clearance, scrolls at small heights and respects the
  safe area. Reduced-motion and visible keyboard focus are supported.
- The locale prefix is stripped for both Korean and English current-page state.
  No authentication, provider, API, spend guard or model default changes.

The flow diagram describes the product's stages. It never claims an agent is
running; the status below it derives only from the selected actual run.

## Validation

`node scripts/check-studio-render.mjs` renders actual React components in both
languages, checks missing/zero/partial data, measured values, real running vs
recorded state, localized navigation and the real home empty state. It performs
no network/model calls. `--write-preview` produces a static empty-state HTML
review with the compiled CSS, explicitly labelled as a local design review.

The existing first-screen, scoreboard, navigation, Replay and dashboard regression
set passed 44 checks. Initial failures exposed removed layout-level Replay links
and locale-prefix wiring; restored actual navigation resolves them without
changing Critic tests. TypeScript passed. Final clean build result is recorded
in the follow-up validation manifest.

Local browser control is disabled in Work settings. Browser screenshot/layout,
hydration and 375px interaction validation remain unverified; SSR and CSS media
queries alone are not proof of pixel-correct responsive behavior. No production
deployment is claimed. Release captain reviews this web ownership exception and
integrates it through the normal clean release flow.

## Folder organization

98 clean Git worktrees were relocated using `git worktree move`, preserving
their HEAD and branch. Root-level registered worktrees fell from 125 to 27.
Dirty worktrees, recent unmerged work, the primary repository/runtime and latest
release worktrees were preserved. Five Git move refusals were left untouched.
The local manifest and restoration tool live at:

- `C:/Projects/EvoForge/README.md`
- `C:/Projects/EvoForge/organization/relocation-manifest.json`
- `C:/Projects/EvoForge/organization/WORKTREE_INDEX.md`
- `C:/Projects/EvoForge/organization/restore-worktrees.ps1`

No data or branches were deleted. Existing documents may reference old absolute
paths; use the manifest or `git worktree list` to resolve their new locations.
Unrelated services, personal files and operating-system folders were preserved.

## Final validation record

Code source `a889c893`: 49 SSR assertions, 44 existing regressions, Arena
presentation checks, TypeScript and clean Next production build all passed.
`docs/validation/2026-10-30-design-studio.json` records source and raw log hashes.
A cp949 console-print error occurred after the build returned exit 0; the raw
UTF-8 build log is intact. Static empty-state review is served on loopback
`http://127.0.0.1:47839` (HTTP 200, no scripts/model/API actions). This is not a
production deployment or a screenshot-verified live-data browser session.
