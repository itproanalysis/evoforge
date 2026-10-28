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

export interface BestHarnessPoint {
  harness_version: string;
  passed: number;
  n: number;
  pass_rate: number;
  lo: number;
  hi: number;
  measurement_id?: string;
}

export interface BestHarnessComparison {
  suite_version: string;
  model: string;
  from: BestHarnessPoint;
  to: BestHarnessPoint;
  verdict: TimelineVerdictKind;
  delta_pp: number;
  /** camelCase alias of delta_pp. */
  deltaPp: number;
  /** Newest PIPELINE point of the same suite/model, or null when absent. */
  pipeline: BestHarnessPoint | null;
  /** Aliases of pipeline. */
  pipeline_point: BestHarnessPoint | null;
  pipelinePoint: BestHarnessPoint | null;
}

function pointOfRecord(r: MeasurementRecord): BestHarnessPoint {
  const w = (r as { wilson95?: unknown }).wilson95;
  const lo =
    Array.isArray(w) && typeof w[0] === "number" && Number.isFinite(w[0])
      ? (w[0] as number)
      : r.pass_rate;
  const hi =
    Array.isArray(w) && typeof w[1] === "number" && Number.isFinite(w[1])
      ? (w[1] as number)
      : r.pass_rate;
  return {
    harness_version: r.harness_version,
    passed: r.passed,
    n: r.n,
    pass_rate: r.pass_rate,
    lo,
    hi,
    measurement_id: r.measurement_id,
  };
}

/** Pure harness comparison for the home proof card.
 *  Picks the newest (by max created_at) suite+model group whose X_SINGLE
 *  measurements span at least two harness versions, compares the newest
 *  X_SINGLE record of the earliest harness (from) with the newest X_SINGLE
 *  record of the latest harness (to) using the Wilson-interval rule
 *  (improved only when to.lo > from.hi, worse only when to.hi < from.lo),
 *  and attaches the newest PIPELINE point of that group when present.
 *  Never invents numbers; lo/hi are the records' wilson95. Returns null
 *  when no comparable pair exists. */
export function bestHarnessComparison(
  history: MeasurementRecord[] | null | undefined,
): BestHarnessComparison | null {
  if (!Array.isArray(history) || history.length === 0) {
    return null;
  }
  interface Group {
    suite_version: string;
    model: string;
    records: MeasurementRecord[];
  }
  const groups = new Map<string, Group>();
  for (const r of history) {
    if (!r || typeof r !== "object") continue;
    const suite = (r as { suite_version?: unknown }).suite_version;
    const model = (r as { model?: unknown }).model;
    if (typeof suite !== "string" || !suite) continue;
    if (typeof model !== "string" || !model) continue;
    const key = `${suite}||${model}`;
    const g = groups.get(key);
    if (g) {
      g.records.push(r);
    } else {
      groups.set(key, { suite_version: suite, model, records: [r] });
    }
  }
  let best: Group | null = null;
  let bestTs = -Infinity;
  for (const g of groups.values()) {
    const xs = g.records.filter((r) => r.kind === "X_SINGLE");
    const harnessSet = new Set<string>();
    for (const r of xs) {
      if (typeof r.harness_version === "string" && r.harness_version) {
        harnessSet.add(r.harness_version);
      }
    }
    if (harnessSet.size < 2) continue;
    let maxTs = -Infinity;
    for (const r of g.records) {
      const t = typeof r.created_at === "number" ? r.created_at : -Infinity;
      if (t > maxTs) maxTs = t;
    }
    if (
      maxTs > bestTs ||
      (maxTs === bestTs &&
        best !== null &&
        g.suite_version > best.suite_version)
    ) {
      best = g;
      bestTs = maxTs;
    }
  }
  if (!best) {
    return null;
  }
  const xs = best.records.filter((r) => r.kind === "X_SINGLE");
  const latestByHarness = new Map<string, MeasurementRecord>();
  const ordered = [...xs].sort((a, b) => {
    const ta = typeof a.created_at === "number" ? a.created_at : 0;
    const tb = typeof b.created_at === "number" ? b.created_at : 0;
    return ta - tb;
  });
  for (const r of ordered) {
    if (typeof r.harness_version !== "string" || !r.harness_version) continue;
    latestByHarness.set(r.harness_version, r);
  }
  if (latestByHarness.size < 2) {
    return null;
  }
  const entries = [...latestByHarness.entries()].sort((a, b) => {
    const ta = typeof a[1].created_at === "number" ? a[1].created_at : 0;
    const tb = typeof b[1].created_at === "number" ? b[1].created_at : 0;
    return ta - tb;
  });
  const fromRec = entries[0][1];
  const toRec = entries[entries.length - 1][1];
  if (!fromRec || !toRec) {
    return null;
  }
  const from = pointOfRecord(fromRec);
  const to = pointOfRecord(toRec);
  const { verdict, deltaPp } = compareTimelinePoints(from, to);
  const delta_pp = 100 * (to.pass_rate - from.pass_rate);
  void deltaPp;
  const pipes = best.records.filter((r) => r.kind === "PIPELINE");
  let pipeline: BestHarnessPoint | null = null;
  if (pipes.length > 0) {
    let newest = pipes[0];
    let newestTs =
      typeof newest.created_at === "number" ? newest.created_at : -Infinity;
    for (let i = 1; i < pipes.length; i += 1) {
      const t =
        typeof pipes[i].created_at === "number"
          ? (pipes[i].created_at as number)
          : -Infinity;
      if (t > newestTs) {
        newest = pipes[i];
        newestTs = t;
      }
    }
    pipeline = pointOfRecord(newest);
  }
  return {
    suite_version: best.suite_version,
    model: best.model,
    from,
    to,
    verdict,
    delta_pp,
    deltaPp: delta_pp,
    pipeline,
    pipeline_point: pipeline,
    pipelinePoint: pipeline,
  };
}

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
