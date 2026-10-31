import type { ArenaDoc } from "./api";

export function shareComparison(doc: ArenaDoc | null | undefined): {
  kind: 'multi_model' | 'same_builder' | 'unconfirmed'; model: string | null;
} {
  const manifest = doc?.manifest;
  if (manifest?.comparison_scope === 'multi_model_system_vs_single_model' ||
      manifest?.collaboration?.profile === 'collaborative') {
    return {kind: 'multi_model', model: null};
  }
  const single = manifest?.lanes?.single?.model;
  const evoforge = manifest?.lanes?.evoforge?.model;
  if (typeof single === 'string' && single && typeof evoforge === 'string' && evoforge) {
    return single === evoforge ? {kind: 'same_builder', model: single} : {kind: 'unconfirmed', model: null};
  }
  // Historical records have the common Builder model at the document root.
  return typeof doc?.model === 'string' && doc.model
    ? {kind: 'same_builder', model: doc.model}
    : {kind: 'unconfirmed', model: null};
}

export function shareUrl(origin: string, locale: string, arenaId: string): string {
  const base = (origin ?? "").replace(/\/+$/, "");
  const prefix = locale === "ko" ? "/ko" : "";
  return `${base}${prefix}/share/${encodeURIComponent(arenaId)}`;
}

function oneLine(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim().slice(0, 120);
}

export function shareText(doc: ArenaDoc | null | undefined, locale: string): string {
  const ko = locale === "ko";
  const rec = (doc ?? {}) as unknown as Record<string, unknown>;
  const rawPrompt = (rec.prompt as string | undefined) || (rec.goal as string | undefined)
    || (rec.task_id as string | undefined) || (rec.arena_id as string | undefined) || "";
  const short = oneLine(rawPrompt);
  const status = rec.status as string | undefined;
  const finished = status === "succeeded" || status === "failed";
  if (!finished) {
    return ko ? `${short} · 아직 실행 중 · 점수 없음` : `${short} · still running · no score yet`;
  }
  const lanes = (rec.lanes ?? {}) as Record<string, Record<string, unknown>>;
  const evo = (lanes.evoforge ?? {}) as Record<string, unknown>;
  const single = (lanes.single ?? {}) as Record<string, unknown>;
  const evoHeld = (evo.heldout ?? {}) as Record<string, unknown>;
  const singleHeld = (single.heldout ?? {}) as Record<string, unknown>;
  const evoScore = Number.isInteger(evoHeld.passed) && Number.isInteger(evoHeld.n)
    ? `${evoHeld.passed}/${evoHeld.n}` : "—";
  const singleScore = Number.isInteger(singleHeld.passed) && Number.isInteger(singleHeld.n)
    ? `${singleHeld.passed}/${singleHeld.n}` : "—";
  const evoCost = Number.isInteger(evo.cost_cents) ? `${evo.cost_cents}¢` : "—";
  const singleCost = Number.isInteger(single.cost_cents) ? `${single.cost_cents}¢` : "—";
  const singleLabel = ko ? "단일" : "single";
  const verdict = (rec.verdict ?? {}) as Record<string, unknown>;
  const winner = typeof verdict.winner === "string" ? verdict.winner : "";
  const reason = typeof verdict.reason === "string" ? verdict.reason : "";
  const verdictPart = winner && reason ? `${winner}: ${reason}` : winner;
  const parts = [
    short,
    `EvoForge ${evoScore}`,
    `${singleLabel} ${singleScore}`,
    `EvoForge ${evoCost}`,
    `${singleLabel} ${singleCost}`,
  ];
  if (verdictPart) parts.push(oneLine(verdictPart));
  return parts.join(ko ? " · " : " · ");
}
