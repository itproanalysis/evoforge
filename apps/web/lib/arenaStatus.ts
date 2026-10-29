import type { ArenaDoc, ArenaLane } from "./api";

export function laneView(lane: ArenaLane | null | undefined) {
  const status = lane?.status ?? "pending";
  const complete = status === "succeeded";
  const passed = lane?.heldout?.passed;
  const n = lane?.heldout?.n;
  const inconclusive = lane?.outcome === "verification_inconclusive";
  const attempted = complete && Number.isInteger(lane?.attempts) && (lane?.attempts as number) > 0;
  const scoredOutcome = lane?.outcome === "passed" || lane?.outcome === "heldout_failed";
  const hasScore = attempted && scoredOutcome && !inconclusive && Number.isInteger(passed) && Number.isInteger(n)
    && (n as number) > 0 && (passed as number) >= 0 && (passed as number) <= (n as number);
  const rawCostState = lane?.cost_status;
  const knownState = rawCostState === "pending" || rawCostState === "incomplete" || rawCostState === "estimated" || rawCostState === "usage_reported";
  const contradictory = (rawCostState === "usage_reported" && lane?.usage_missing === true)
    || (rawCostState === "estimated" && lane?.usage_missing === false);
  const costState = contradictory || (rawCostState != null && !knownState) ? "unavailable"
    : status === "failed" || rawCostState === "incomplete" ? "incomplete"
      : !complete || rawCostState === "pending" ? "pending"
        : rawCostState === "estimated" || lane?.usage_missing === true ? "estimated"
          : rawCostState === "usage_reported" ? "usage_reported" : "legacy";
  const hasCost = attempted && (costState === "estimated" || costState === "usage_reported" || costState === "legacy")
    && Number.isInteger(lane?.cost_cents) && (lane?.cost_cents as number) >= 0;
  return {
    status,
    score: hasScore ? `${passed}/${n}` : null,
    cost: hasCost ? lane!.cost_cents : null,
    costState,
    attempts: complete && Number.isInteger(lane?.attempts) ? lane!.attempts : null,
    outcome: complete && inconclusive ? "verification_inconclusive" : attempted ? lane!.outcome : null,
    result: hasScore ? ((passed as number) === n ? "passed" : "not_passed") : null,
    error: status === "failed" && typeof lane?.error === "string" ? lane.error : null,
  };
}

export function costLabel(state: string): string {
  switch (state) {
    case "pending": return "비용 집계 대기";
    case "incomplete": return "비용 일부 미확인";
    case "estimated": return "예약 상한 추정 비용";
    case "usage_reported": return "사용량 기준 비용";
    case "legacy": return "서버 비용 집계 · 출처 미확인";
    default: return "비용 출처 불일치 또는 미확인";
  }
}

export function arenaVerdict(arena: ArenaDoc | null | undefined) {
  if (arena?.status !== "succeeded" || !laneView(arena.lanes?.single).score || !laneView(arena.lanes?.evoforge).score) return null;
  const winner = arena.verdict?.winner;
  return winner === "single" || winner === "evoforge" || winner === "tie" ? arena.verdict : null;
}

export function arenaCost(arena: ArenaDoc | null | undefined) {
  const single = laneView(arena?.lanes?.single).cost;
  const evo = laneView(arena?.lanes?.evoforge).cost;
  return single === null || evo === null ? null : single + evo;
}

function shortHash(value: unknown): string | null {
  if (typeof value !== "string" || value.length === 0) return null;
  const hex = value.startsWith("sha256:") ? value.slice("sha256:".length) : value;
  if (hex.length === 0) return null;
  return hex.slice(0, 12);
}

function manifestLane(lane: unknown) {
  const rec = (lane ?? {}) as Record<string, unknown>;
  const harness = typeof rec.harness === "string" ? rec.harness : null;
  const attempts = Number.isInteger(rec.max_attempts) ? (rec.max_attempts as number) : null;
  const feedback = typeof rec.feedback === "string" ? rec.feedback : null;
  return { harness, attempts, feedback };
}

export function manifestView(doc: ArenaDoc | null | undefined) {
  const manifest = (doc as { manifest?: unknown } | null | undefined)?.manifest as Record<string, unknown> | null | undefined;
  if (manifest == null || typeof manifest !== "object") return null;
  const lanes = (manifest.lanes ?? {}) as Record<string, unknown>;
  const evoforge = manifestLane(lanes.evoforge);
  const single = manifestLane(lanes.single);
  const disclosure = typeof manifest.disclosure === "string" ? manifest.disclosure : null;
  return {
    spec: shortHash(manifest.task_spec_hash),
    heldout: shortHash(manifest.heldout_hash),
    baseTree: shortHash(manifest.base_tree_sha),
    single,
    evoforge,
    upperBound: evoforge.feedback === "heldout_failing_test_names",
    disclosure,
  };
}

export type PreviewSource = "pending" | "candidate" | "base" | "none";

export function previewView(lane: ArenaLane | null | undefined): { html: string | null; source: PreviewSource; error: string | null } {
  if (lane?.status !== "succeeded") return { html: null, source: "pending", error: null };
  const rec = lane as unknown as Record<string, unknown>;
  const source = rec.preview_source;
  const html = rec.preview_html;
  if ((source === "candidate" || source === "base") && typeof html === "string") {
    return { html, source, error: null };
  }
  const error = typeof rec.preview_error === "string" ? (rec.preview_error as string) : null;
  return { html: null, source: "none", error };
}

export interface PromptArenaView {
  prompt: string;
  acceptanceCount: number;
  dropped: number;
  scorable: boolean | null;
  judgeCost: string;
  judge: string;
  winner: "evoforge" | "single" | "tie" | null;
}

export function promptArenaView(doc: ArenaDoc | null | undefined): PromptArenaView | null {
  const rec = (doc ?? {}) as unknown as Record<string, unknown>;
  if (rec.mode !== "prompt") return null;
  const prompt = typeof rec.prompt === "string" ? (rec.prompt as string) : "";
  const manifest = (rec.manifest ?? {}) as Record<string, unknown>;
  const acceptanceCount = Number.isInteger(manifest.acceptance_count) ? (manifest.acceptance_count as number) : 0;
  const dropped = Number.isInteger(manifest.acceptance_dropped) ? (manifest.acceptance_dropped as number) : 0;
  const finished = doc?.status === "succeeded" || doc?.status === "failed";
  const rawWinner = (doc?.verdict as { winner?: unknown } | undefined)?.winner;
  const scorable = !finished ? null : acceptanceCount >= 3 && rawWinner !== "unscorable";
  const judgeCents = (doc as unknown as Record<string, unknown>)?.judge_cost_cents;
  const judgeCost = Number.isInteger(judgeCents) && (judgeCents as number) >= 0 ? `${judgeCents}¢` : "—";
  const judge = typeof manifest.judge === "string" ? (manifest.judge as string) : "";
  const winner = finished && scorable === true
    && (rawWinner === "evoforge" || rawWinner === "single" || rawWinner === "tie")
    ? rawWinner : null;
  return { prompt, acceptanceCount, dropped, scorable, judgeCost, judge, winner };
}
