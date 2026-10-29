# Canvas rebuild - 2026-10-30

Owner: remove about 80% of the text and rebuild beyond the existing dashboard.

References (principles, not copied brand assets):
- Linear, consistent controls and quiet navigation: https://linear.app/changelog/2026-03-12-ui-refresh
- Linear layout hierarchy: https://linear.app/now/how-we-redesigned-the-linear-ui
- Figma, canvas-focused toolbar: https://help.figma.com/hc/en-us/articles/360041064174-Access-design-tools-from-the-toolbar

The home now uses `CanvasWorkspace`: two output surfaces, a small run selector,
Preview/Changes/Tests views, comparison toggle, compact command input and an icon
rail. Activity, participants, measurements, conditions and operator controls open
on demand in a native modal sheet. No promotional masthead, metrics wall or agent
cards appear by default. Existing operator controls remain available, not deleted.

The picker uses actual saved run documents and retains newly completed jobs.
Pending new jobs clear an older run's result until the new matching document is
loaded. Preview source, cost provenance, base output, unconfirmed and failed
states keep the existing conservative mappers. Auth, backend, model defaults,
operator gating, spend confirmation and reservation/receipt paths are unchanged.

Default/empty Korean desktop SSR text: **409 -> 79 non-whitespace characters,
80.7% reduction** against source `333d88d9`. Includes placeholders; excludes
hidden/mobile-only/assistive labels, closed disclosures and dialogs, and generated
artifact text. The script and HTML hashes make this repeatable. This is not a
claim that every page, generated output or browser viewport has 80.7% less text.

`check-canvas-density.py` requires the saved before HTML in .local/design-review.
`check-studio-render.mjs` checks actual English/Korean components, pending and
finished costs, scoped previews, waiting state and closed sheet by default.
Two Builder source-wiring checks now follow the extracted canvas and accept
native details/summary disclosures; independent Critic tests are unchanged.

The local review still uses eight saved public GET responses, labelled as a
review/saved record with timestamp on hover. It allows no live API requests or
model execution; operator controls are off. Browser control is disabled, so
screenshots, real input, mobile layout and hydration remain UNVERIFIED. Source,
logs and final validation results are recorded in the follow-up manifest.
Not deployed; release captain integrates through the existing clean gates.

The compact read-only cue remains visible when operator controls are off; this
adds four Korean characters while keeping the requested 80 percent reduction.
