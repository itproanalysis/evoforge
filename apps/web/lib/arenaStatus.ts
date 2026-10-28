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
  const hasCost = attempted && Number.isInteger(lane?.cost_cents) && (lane?.cost_cents as number) >= 0;
  return {
    status,
    score: hasScore ? `${passed}/${n}` : null,
    cost: hasCost ? lane!.cost_cents : null,
    attempts: complete && Number.isInteger(lane?.attempts) ? lane!.attempts : null,
    outcome: complete && inconclusive ? "verification_inconclusive" : attempted ? lane!.outcome : null,
    result: hasScore ? ((passed as number) === n ? "passed" : "not_passed") : null,
    error: status === "failed" && typeof lane?.error === "string" ? lane.error : null,
  };
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
