import type { MeasurementRecord } from "./api";

export interface TimelinePoint {
  measurement_id: string;
  kind: string;
  suite_version: string;
  harness_version: string;
  created_at: number;
  pass_rate: number;
  lo: number;
  hi: number;
  passed: number;
  n: number;
  cost_cents: number;
  evidence_id: string;
}

export interface HarnessChange {
  index: number;
  from: string;
  to: string;
}

export interface FamilyCell {
  measurement_id: string;
  passed: number;
  n: number;
}

export interface FamilyRow {
  family: string;
  cells: FamilyCell[];
}

export interface TimelineSegment {
  suite_version: string;
  model: string;
  points: TimelinePoint[];
  harnessChanges: HarnessChange[];
  families: FamilyRow[];
}

export interface Timeline {
  segments: TimelineSegment[];
}

export type TimelineVerdictKind = "improved" | "no_clear_difference" | "worse";

export interface TimelinePointLike {
  pass_rate: number;
  lo: number;
  hi: number;
}

export interface TimelineComparisonResult {
  verdict: TimelineVerdictKind;
  deltaPp: number;
  baseId?: string;
  currId?: string;
}

function rateOf(p: TimelinePointLike): number {
  const v = (p as { pass_rate?: unknown }).pass_rate;
  return typeof v === "number" && !Number.isNaN(v) ? v : 0;
}

/** Pure Wilson-interval comparison, same rule as the API: improved only
 *  when intervals do not overlap. Delta is in percentage points. */
export function compareTimelinePoints(
  base: TimelinePointLike,
  curr: TimelinePointLike,
): { verdict: TimelineVerdictKind; deltaPp: number } {
  const deltaPp = 100 * (rateOf(curr) - rateOf(base));
  if (curr.lo > base.hi) {
    return { verdict: "improved", deltaPp };
  }
  if (curr.hi < base.lo) {
    return { verdict: "worse", deltaPp };
  }
  return { verdict: "no_clear_difference", deltaPp };
}

/** Alias kept for discoverability; same pure interval rule. */
export const compareIntervals = compareTimelinePoints;

/** Measured verdict for one segment header.
 *  Prefers latest X_SINGLE vs latest PIPELINE; otherwise compares the
 *  latest X_SINGLE points of the earliest vs latest harness versions.
 *  Returns null when no comparable pair exists. */
export function segmentVerdict(
  seg: TimelineSegment | null | undefined,
): TimelineComparisonResult | null {
  if (!seg || !Array.isArray(seg.points) || seg.points.length < 2) {
    return null;
  }
  const xs = seg.points.filter((p) => p.kind === "X_SINGLE");
  const pipes = seg.points.filter((p) => p.kind === "PIPELINE");
  let base: TimelinePoint | undefined;
  let curr: TimelinePoint | undefined;
  if (xs.length >= 1 && pipes.length >= 1) {
    base = xs[xs.length - 1];
    curr = pipes[pipes.length - 1];
  } else if (xs.length >= 2) {
    const order: string[] = [];
    const latestByHarness = new Map<string, TimelinePoint>();
    for (const p of xs) {
      if (!order.includes(p.harness_version)) {
        order.push(p.harness_version);
      }
      latestByHarness.set(p.harness_version, p);
    }
    if (order.length < 2) {
      return null;
    }
    base = latestByHarness.get(order[0]);
    curr = latestByHarness.get(order[order.length - 1]);
    if (!base || !curr) {
      return null;
    }
  } else {
    return null;
  }
  const { verdict, deltaPp } = compareTimelinePoints(base, curr);
  return {
    verdict,
    deltaPp,
    baseId: base.measurement_id,
    currId: curr.measurement_id,
  };
}

/** Aliases kept for discoverability. */
export const getSegmentVerdict = segmentVerdict;
export const segmentComparison = segmentVerdict;

export function buildTimeline(history: MeasurementRecord[]): Timeline {
  if (!Array.isArray(history) || history.length === 0) {
    return { segments: [] };
  }
  const sorted = [...history].sort((a, b) => a.created_at - b.created_at);
  const segments: TimelineSegment[] = [];
  // Keep per-record family maps aligned with sorted order so families
  // can be built per segment after grouping.
  const familyByRecord: Array<Record<string, { n: number; passed: number }>> = [];

  for (let i = 0; i < sorted.length; i += 1) {
    const r = sorted[i];
    familyByRecord.push(r.per_family ?? {});
    const point: TimelinePoint = {
      measurement_id: r.measurement_id,
      kind: r.kind,
      suite_version: r.suite_version,
      harness_version: r.harness_version,
      created_at: r.created_at,
      pass_rate: r.pass_rate,
      lo: r.wilson95 ? r.wilson95[0] : r.pass_rate,
      hi: r.wilson95 ? r.wilson95[1] : r.pass_rate,
      passed: r.passed,
      n: r.n,
      cost_cents: r.cost_cents,
      evidence_id: r.evidence_id,
    };
    const last = segments[segments.length - 1];
    if (
      last &&
      last.suite_version === r.suite_version &&
      last.model === r.model
    ) {
      last.points.push(point);
    } else {
      segments.push({
        suite_version: r.suite_version,
        model: r.model,
        points: [point],
        harnessChanges: [],
        families: [],
      });
    }
  }

  // Fill harnessChanges + families per segment. Track global sorted index.
  let cursor = 0;
  for (const seg of segments) {
    const start = cursor;
    const end = start + seg.points.length;
    for (let i = 1; i < seg.points.length; i += 1) {
      const prev = seg.points[i - 1];
      const cur = seg.points[i];
      if (cur.harness_version !== prev.harness_version) {
        seg.harnessChanges.push({
          index: i,
          from: prev.harness_version,
          to: cur.harness_version,
        });
      }
    }
    const names = new Set<string>();
    for (let k = start; k < end; k += 1) {
      const pf = familyByRecord[k] ?? {};
      for (const key of Object.keys(pf)) {
        names.add(key);
      }
    }
    const ordered = [...names].sort();
    seg.families = ordered.map((family) => ({
      family,
      cells: seg.points.map((p, j) => {
        const entry = (familyByRecord[start + j] ?? {})[family];
        if (entry) {
          return {
            measurement_id: p.measurement_id,
            passed: entry.passed,
            n: entry.n,
          };
        }
        return { measurement_id: p.measurement_id, passed: 0, n: 0 };
      }),
    }));
    cursor = end;
  }

  return { segments };
}
