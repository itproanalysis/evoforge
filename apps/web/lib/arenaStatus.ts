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
