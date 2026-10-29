// Pure round-replay helpers. No UI framework, no network calls, no module
// loading: this file is intentionally self-contained so it can be compiled
// and loaded standalone.
export type EvolutionSnapStatus = "READY" | "UNVERIFIED" | "FAILED" | "PENDING";

export interface EvolutionSnap {
  status: EvolutionSnapStatus;
  verified?: boolean;
  heldout?: { passed: number; n: number } | null;
  cost_cents?: number | null;
  elapsed_ms?: number | null;
  source_sha?: string | null;
  preview_html?: string | null;
  preview_error?: string | null;
  diff?: string | null;
  events?: unknown[] | null;
}

export interface EvolutionRound {
  index: number;
  name?: string;
  goal?: string;
  sides: { evoforge: EvolutionSnap; single: EvolutionSnap };
}

export interface EvolutionRun {
  run_id: string;
  app_id?: string;
  title?: string;
  status?: string;
  manifest?: {
    app_id?: string;
    rounds?: number;
    cost_basis?: string;
    runner_cost?: string;
    disclosure?: string;
    lanes?: unknown;
  };
  rounds?: EvolutionRound[];
  totals?: {
    evoforge?: { cost_cents?: number | null; elapsed_ms?: number | null; verified_rounds?: number | null };
    single?: { cost_cents?: number | null; elapsed_ms?: number | null; verified_rounds?: number | null };
  };
}

export type ReplaySideKey = "evoforge" | "single";

export const REPLAY_SIDES: ReplaySideKey[] = ["evoforge", "single"];

const KNOWN_STATUSES: EvolutionSnapStatus[] = ["READY", "UNVERIFIED", "FAILED", "PENDING"];

function snapStatus(snap: EvolutionSnap | null | undefined): EvolutionSnapStatus {
  const s = (snap as { status?: unknown } | null | undefined)?.status;
  return typeof s === "string" && (KNOWN_STATUSES as string[]).includes(s)
    ? (s as EvolutionSnapStatus)
    : "PENDING";
}

function snapOf(
  run: EvolutionRun | null | undefined,
  roundIndex: number,
  side: ReplaySideKey,
): EvolutionSnap | null {
  const rounds = (run as { rounds?: unknown } | null | undefined)?.rounds;
  if (!Array.isArray(rounds)) return null;
  for (const r of rounds) {
    if (r && typeof r === "object" && (r as { index?: unknown }).index === roundIndex) {
      const sides = (r as { sides?: unknown }).sides;
      if (sides && typeof sides === "object") {
        const snap = (sides as Record<string, unknown>)[side];
        return snap && typeof snap === "object" ? (snap as EvolutionSnap) : null;
      }
      return null;
    }
  }
  return null;
}

export interface RoundSideView {
  status: EvolutionSnapStatus;
  verified: boolean;
  score: string;
  cost: string;
  previewHtml: string | null;
}

export interface RoundView {
  index: number;
  name: string;
  sides: Record<ReplaySideKey, RoundSideView>;
}

function sideView(snap: EvolutionSnap | null): RoundSideView {
  const status = snapStatus(snap);
  const verified = status === "READY";
  let score = "—";
  if (status !== "PENDING") {
    const heldout = (snap as { heldout?: unknown } | null)?.heldout;
    if (heldout && typeof heldout === "object") {
      const passed = (heldout as { passed?: unknown }).passed;
      const n = (heldout as { n?: unknown }).n;
      if (typeof passed === "number" && Number.isFinite(passed) && typeof n === "number" && Number.isFinite(n)) {
        score = `${passed}/${n}`;
      }
    }
  }
  let cost = "—";
  if (status !== "PENDING") {
    const cents = (snap as { cost_cents?: unknown } | null)?.cost_cents;
    if (typeof cents === "number" && Number.isFinite(cents)) {
      cost = `${cents}¢`;
    }
  }
  let previewHtml: string | null = null;
  if (status !== "PENDING") {
    const html = (snap as { preview_html?: unknown } | null)?.preview_html;
    if (typeof html === "string" && html.length > 0) {
      previewHtml = html;
    }
  }
  return { status, verified, score, cost, previewHtml };
}

/** View of one round, or null when that round index is absent from the run. */
export function roundView(run: EvolutionRun | null | undefined, index: number): RoundView | null {
  const rounds = (run as { rounds?: unknown } | null | undefined)?.rounds;
  if (!Array.isArray(rounds)) return null;
  let found: {
    index?: unknown;
    name?: unknown;
  } | null = null;
  for (const r of rounds) {
    if (r && typeof r === "object" && (r as { index?: unknown }).index === index) {
      found = r as { index?: unknown; name?: unknown };
      break;
    }
  }
  if (!found) return null;
  const name = typeof found.name === "string" && found.name ? found.name : `R${index}`;
  return {
    index,
    name,
    sides: {
      evoforge: sideView(snapOf(run, index, "evoforge")),
      single: sideView(snapOf(run, index, "single")),
    },
  };
}

/** Highest round index where neither side is PENDING; 0 when there is none. */
export function latestCommonRound(run: EvolutionRun | null | undefined): number {
  const rounds = (run as { rounds?: unknown } | null | undefined)?.rounds;
  if (!Array.isArray(rounds) || rounds.length === 0) return 0;
  let best = 0;
  let seen = false;
  for (const r of rounds) {
    if (!r || typeof r !== "object") continue;
    const idx = (r as { index?: unknown }).index;
    if (typeof idx !== "number" || !Number.isFinite(idx)) continue;
    const sides = (r as { sides?: unknown }).sides;
    const evo = sides && typeof sides === "object"
      ? snapStatus((sides as Record<string, unknown>).evoforge as EvolutionSnap | null)
      : "PENDING";
    const single = sides && typeof sides === "object"
      ? snapStatus((sides as Record<string, unknown>).single as EvolutionSnap | null)
      : "PENDING";
    if (evo !== "PENDING" && single !== "PENDING") {
      if (!seen || idx > best) {
        best = idx;
        seen = true;
      }
    }
  }
  return seen ? best : 0;
}

/** First-to-latest scrubber range. */
export function firstLatest(run: EvolutionRun | null | undefined): [number, number] {
  return [1, latestCommonRound(run)];
}

/** Next round index, or null when it does not exist (replay stops, no wrap). */
export function nextRound(i: number, run: EvolutionRun | null | undefined): number | null {
  const rounds = (run as { rounds?: unknown } | null | undefined)?.rounds;
  if (!Array.isArray(rounds)) return null;
  const want = i + 1;
  for (const r of rounds) {
    if (r && typeof r === "object" && (r as { index?: unknown }).index === want) {
      return want;
    }
  }
  return null;
}

export interface ReplayTotalsSide {
  cost: string;
  verified: string;
  elapsed: number;
}

export type ReplayTotals = Record<ReplaySideKey, ReplayTotalsSide>;

/** Totals strip view: cost as "N¢", verified as "k/R" with R = manifest.rounds. */
export function totalsView(run: EvolutionRun | null | undefined): ReplayTotals {
  const manifest = (run as { manifest?: unknown } | null | undefined)?.manifest;
  const rounds = (run as { rounds?: unknown } | null | undefined)?.rounds;
  const roundCount = Array.isArray(rounds) ? rounds.length : 0;
  let total = 0;
  if (manifest && typeof manifest === "object") {
    const mr = (manifest as { rounds?: unknown }).rounds;
    if (typeof mr === "number" && Number.isFinite(mr)) total = mr;
    else total = roundCount;
  } else {
    total = roundCount;
  }
  const totals = (run as { totals?: unknown } | null | undefined)?.totals;
  const one = (side: ReplaySideKey): ReplayTotalsSide => {
    const lane =
      totals && typeof totals === "object"
        ? ((totals as Record<string, unknown>)[side] as
            | { cost_cents?: unknown; elapsed_ms?: unknown; verified_rounds?: unknown }
            | null
            | undefined)
        : null;
    const cents = lane?.cost_cents;
    const cost = typeof cents === "number" && Number.isFinite(cents) ? `${cents}¢` : "—";
    const vr = lane?.verified_rounds;
    const k = typeof vr === "number" && Number.isFinite(vr) ? vr : 0;
    const ms = lane?.elapsed_ms;
    const elapsed = typeof ms === "number" && Number.isFinite(ms) ? ms : 0;
    return { cost, verified: `${k}/${total}`, elapsed };
  };
  return { evoforge: one("evoforge"), single: one("single") };
}

export type AgentRole = "builder" | "critic" | "runner" | "gate";

export type AgentRowState = "active" | "done" | "idle";

export interface AgentRow {
  role: AgentRole;
  state: AgentRowState;
  message: string | null;
}

export type CommandStateName = "RECEIVED" | "QUEUED" | "RUNNING" | "APPLIED" | "REJECTED" | "FAILED";

export interface CommandState {
  state: CommandStateName;
  reason: string | null;
}

const AGENT_ROLES: AgentRole[] = ["builder", "critic", "runner", "gate"];

interface PanelEvent {
  seq: number;
  role: string;
  message: string;
  order: number;
}

function collectSideEvents(
  run: EvolutionRun | null | undefined,
  side: ReplaySideKey,
): PanelEvent[] {
  const out: PanelEvent[] = [];
  const rounds = (run as { rounds?: unknown } | null | undefined)?.rounds;
  if (!Array.isArray(rounds)) return out;
  let order = 0;
  for (const r of rounds) {
    if (!r || typeof r !== "object") continue;
    const sides = (r as { sides?: unknown }).sides;
    if (!sides || typeof sides !== "object") continue;
    const snap = (sides as Record<string, unknown>)[side];
    if (!snap || typeof snap !== "object") continue;
    const events = (snap as { events?: unknown }).events;
    if (!Array.isArray(events)) continue;
    for (const e of events) {
      if (!e || typeof e !== "object") continue;
      const seq = (e as { seq?: unknown }).seq;
      if (typeof seq !== "number" || !Number.isFinite(seq)) continue;
      const role = (e as { role?: unknown }).role;
      if (typeof role !== "string" || !role) continue;
      const raw = (e as { message?: unknown }).message;
      const message = typeof raw === "string" ? raw : raw === null || raw === undefined ? "" : String(raw);
      out.push({ seq, role, message, order });
      order += 1;
    }
  }
  return out;
}

/** Latest live-agent view for one side: one row per role, newest role live. */
export function agentPanel(run: EvolutionRun | null | undefined, side: ReplaySideKey): AgentRow[] {
  const all = collectSideEvents(run, side);
  let newest: PanelEvent | null = null;
  for (const e of all) {
    if (
      newest === null ||
      e.seq > newest.seq ||
      (e.seq === newest.seq && e.order > newest.order)
    ) {
      newest = e;
    }
  }
  const live = (run as { status?: unknown } | null | undefined)?.status === "running";
  return AGENT_ROLES.map((role) => {
    let best: PanelEvent | null = null;
    for (const e of all) {
      if (e.role !== role) continue;
      if (
        best === null ||
        e.seq > best.seq ||
        (e.seq === best.seq && e.order > best.order)
      ) {
        best = e;
      }
    }
    if (best === null) return { role, state: "idle" as AgentRowState, message: null };
    const isNewest = newest !== null && best.order === newest.order;
    return { role, state: live && isNewest ? "active" : "done", message: best.message };
  });
}

/** RECEIVED is not APPLIED: map send status + polled run status to one badge. */
export function commandState(
  httpStatus: number | null,
  runStatus: string | null,
): CommandState {
  if (httpStatus === null || httpStatus === undefined) {
    return { state: "RECEIVED", reason: null };
  }
  if (httpStatus === 409) return { state: "REJECTED", reason: "busy" };
  if (httpStatus === 402) return { state: "REJECTED", reason: "budget" };
  if (httpStatus === 422) return { state: "REJECTED", reason: "invalid" };
  if (httpStatus !== 202) return { state: "REJECTED", reason: "error" };
  if (runStatus === "running") return { state: "RUNNING", reason: null };
  if (runStatus === "succeeded") return { state: "APPLIED", reason: null };
  if (runStatus === "failed") return { state: "FAILED", reason: null };
  return { state: "QUEUED", reason: null };
}

export type EvolutionStatsComparison = "evoforge_better" | "single_better" | "not_significant";

export interface EvolutionStatsSide {
  rounds: number;
  verified: number;
  wilson95: [number, number];
  cost_cents: number;
  cost_per_verified_cents: number | null;
}

export interface EvolutionStats {
  runs: number;
  comparison: EvolutionStatsComparison;
  method: string;
  by_side: Record<ReplaySideKey, EvolutionStatsSide>;
}

export interface StatsSideView {
  verified: string;
  rate: string;
  interval: string;
  costPerVerified: string;
}

export interface StatsView {
  runs: number;
  verdict: string;
  evoforge: StatsSideView;
  single: StatsSideView;
}

const EM_DASH_PLACEHOLDER = "—";

function statsSideView(side: EvolutionStatsSide | null | undefined): StatsSideView {
  const raw = (side && typeof side === "object" ? side : null) as {
    rounds?: unknown;
    verified?: unknown;
    wilson95?: unknown;
    cost_per_verified_cents?: unknown;
  } | null;
  const n = typeof raw?.rounds === "number" && Number.isFinite(raw.rounds) ? raw.rounds : 0;
  const k = typeof raw?.verified === "number" && Number.isFinite(raw.verified) ? raw.verified : 0;
  const verified = `${k}/${n}`;
  const rate = n === 0 ? EM_DASH_PLACEHOLDER : `${Math.round((100 * k) / n)}%`;
  let interval = EM_DASH_PLACEHOLDER;
  if (n !== 0) {
    const w = raw?.wilson95;
    if (
      Array.isArray(w) &&
      w.length >= 2 &&
      typeof w[0] === "number" &&
      Number.isFinite(w[0]) &&
      typeof w[1] === "number" &&
      Number.isFinite(w[1])
    ) {
      interval = `${Math.round((w[0] as number) * 100)}–${Math.round((w[1] as number) * 100)}%`;
    }
  }
  const cpv = raw?.cost_per_verified_cents;
  const costPerVerified =
    typeof cpv === "number" && Number.isFinite(cpv) ? `${cpv}¢` : EM_DASH_PLACEHOLDER;
  return { verified, rate, interval, costPerVerified };
}

/** Stats panel view: verdict is the server's comparison, never computed here. */
export function statsView(stats: EvolutionStats | null | undefined): StatsView | null {
  if (stats === null || stats === undefined) return null;
  if (typeof stats !== "object") return null;
  const s = stats as {
    runs?: unknown;
    comparison?: unknown;
    by_side?: unknown;
  };
  const runs = typeof s.runs === "number" && Number.isFinite(s.runs) ? s.runs : 0;
  const verdict = typeof s.comparison === "string" ? s.comparison : "not_significant";
  const bySide =
    s.by_side && typeof s.by_side === "object"
      ? (s.by_side as Record<string, EvolutionStatsSide | null | undefined>)
      : null;
  return {
    runs,
    verdict,
    evoforge: statsSideView(bySide?.evoforge),
    single: statsSideView(bySide?.single),
  };
}
