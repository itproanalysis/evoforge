# Canvas interaction refinement - 2026-10-30

Owner: make the accepted minimal canvas more comfortable, intuitive and polished,
using Toss as a reference. This is an owner-requested web ownership exception.

Primary references, principles only (no brand assets or third-party libraries):
- https://toss.tech/article/8-writing-principles-of-toss - concise, predictable,
  conversational copy; remove words that do not help the next action.
- https://toss.tech/article/interaction - consistent, purposeful interaction.

The same output-first canvas now uses a quieter cloud surface, readable slate
type, a blue action accent and softer output/input shapes. Controls have more
room, the view selector has a short sliding selection, and the native inspector
enters gently. Reduced-motion users get no animation or press scaling.

On mobile, people and history stay direct; measurements and settings share a
native More menu. Its summary, navigation targets and inspector close have 44px
targets. Escape closes the menu; closing an inspector restores its opener's
focus. The textarea grows with input, with a 16px mobile font. Operator and spend
confirmation guards are preserved.

New feedback distinguishes received requests from active jobs, adds a concise
read-retry on polling failure, and shows a small success check only when the
existing evidence mapper reports passed. Recorded runs include the real date
when valid; malformed/out-of-range dates cannot crash the picker. There is no
invented progress, participant, cost or winner.

Default/empty Korean desktop SSR copy remains within the owner's budget:
409 -> 80 non-whitespace characters (80.4% less). This includes placeholders,
excludes generated artifacts/hidden labels/closed disclosures, and is not a
browser pixel or all-page measurement. The full criteria are in the prior
CANVAS_REDESIGN_CODEX.md and the new validation manifest.

No backend, authentication, provider default, frozen contract or candidate HTML
was changed. The local review uses saved public GET records and disables writes.
Browser control is disabled: mobile rendering, real input, focus behavior and
hydration still need browser review. Not deployed; release captain integrates
the candidate through normal gates. Validation evidence is recorded separately.

Final evidence: app source ed60f35b passed 122 actual-component SSR assertions,
64 existing web regressions, TypeScript and a clean Next production build. The
local review bundle/read boundary passed; HTML and script returned 200, and the
model-action POST route returned 404. Logs and artifact hashes are saved in
docs/validation/2026-10-30-toss-refinement.json. The browser limits above still
apply; these checks do not establish visual polish in a running browser.
