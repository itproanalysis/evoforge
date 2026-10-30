"use client";
import React from "react";
import { useTranslations } from "next-intl";
import {
  buildTimeline,
  segmentVerdict,
  type Timeline,
  type TimelineSegment,
} from "../lib/evolutionTimeline";
import type { MeasurementRecord } from "../lib/api";

export interface EvolutionTimelineProps {
  timeline?: Timeline;
  data?: Timeline;
  segments?: TimelineSegment[];
  history?: MeasurementRecord[];
  className?: string;
}

const FALLBACK: Record<string, string> = {
  "timeline.not-comparable": "Not comparable \u2014 different suite or model",
  "timeline.empty": "No measurements yet. Run a baseline or pipeline measurement to start the timeline.",
  "timeline.legend-x-single": "Single AI baseline",
  "timeline.legend-pipeline": "EvoForge pipeline",
  "timeline.families-heading": "Per-family results",
  "timeline.harness": "harness {version}",
  "timeline.verdict-improved": "Improvement confirmed ({delta})",
  "timeline.verdict-unclear": "Unclear difference (intervals overlap, {delta})",
  "timeline.verdict-worse": "Worse ({delta})",
};

function formatDate(createdAt: number): string {
  try {
    const d = new Date(createdAt * 1000);
    if (Number.isNaN(d.getTime())) return String(createdAt);
    return d.toISOString().slice(5, 16).replace("T", " ");
  } catch {
    return String(createdAt);
  }
}

function shortHarness(version: string): string {
  const i = version.lastIndexOf("/");
  return i >= 0 ? version.slice(i) : version;
}

function formatDeltaPp(v: number): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%p`;
}

function clamp01(v: number): number {
  if (typeof v !== "number" || Number.isNaN(v)) return 0;
  return Math.min(1, Math.max(0, v));
}

function colorForKind(kind: string): string {
  if (kind === "PIPELINE") return "#12a66e";
  if (kind === "X_SINGLE") return "#3182f6";
  return "#8b5cf6";
}

function SegmentPanel({
  seg,
  notComparableLabel,
  legendX,
  legendPipe,
  harnessLabel,
  familiesHeading,
  formatVerdict,
}: {
  seg: TimelineSegment;
  notComparableLabel: string;
  legendX: string;
  legendPipe: string;
  harnessLabel: (version: string) => string;
  familiesHeading: string;
  formatVerdict: (c: { verdict: string; deltaPp: number }) => string;
}) {
  void notComparableLabel;
  const LEFT = 48;
  const RIGHT = 14;
  const TOP = 20;
  const BOTTOM = 36;
  const CHART_H = 180;
  const VB_W = 640;
  const VB_H = TOP + CHART_H + BOTTOM;
  const n = seg.points.length;
  const innerW = VB_W - LEFT - RIGHT;
  const height = VB_H;
  const y = (v: number) => TOP + CHART_H * (1 - clamp01(v));
  const x = (i: number) => (n <= 1 ? LEFT + innerW / 2 : LEFT + (innerW * i) / Math.max(1, n - 1));
  const hxFor = (index: number) =>
    n <= 1 ? LEFT : LEFT + (innerW * (index - 0.5)) / Math.max(1, n - 1);
  const gridVals = [0, 25, 50, 75, 100];

  const byKind = new Map<string, Array<{ i: number; px: number; py: number }>>();
  seg.points.forEach((p, i) => {
    const px = x(i);
    const py = y(p.pass_rate);
    const arr = byKind.get(p.kind) ?? [];
    arr.push({ i, px, py });
    byKind.set(p.kind, arr);
  });

  const comparison = segmentVerdict(seg);
  const verdictText = comparison ? formatVerdict(comparison) : null;

  return (
    <section
      data-testid="evolution-segment"
      data-suite={seg.suite_version}
      data-model={seg.model}
      className="border border-border rounded-card bg-background-primary p-3 min-w-0"
      style={{ maxWidth: "100%" }}
    >
      <h3 className="text-sm font-semibold text-text-primary break-words">
        {seg.suite_version} · {seg.model}
      </h3>
      {verdictText ? (
        <p data-testid="evolution-verdict" className="text-xs text-text-secondary mt-1 break-words">
          {verdictText}
        </p>
      ) : null}
      <div className="flex items-center gap-4 mt-1 text-xs text-text-secondary flex-wrap">
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block w-2.5 h-2.5 rounded-full"
            style={{ backgroundColor: colorForKind("X_SINGLE") }}
          />
          {legendX}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block w-2.5 h-2.5 rounded-full"
            style={{ backgroundColor: colorForKind("PIPELINE") }}
          />
          {legendPipe}
        </span>
      </div>

      <div className="w-full max-w-full mt-2" style={{ maxWidth: "100%" }}>
        <svg
          role="img"
          aria-label={`${seg.suite_version} ${seg.model}`}
          width="100%"
          height={height}
          viewBox={`0 0 ${VB_W} ${height}`}
          preserveAspectRatio="xMidYMid meet"
          className="block w-full h-auto"
          style={{ width: "100%", height: "auto", maxWidth: "100%" }}
        >
          <style>{`@keyframes evo-grow{from{opacity:0;transform:scale(0.6)}to{opacity:1;transform:scale(1)}}.evo-anim{animation:evo-grow 400ms ease-out;transform-box:fill-box;transform-origin:center}@media (prefers-reduced-motion:reduce){.evo-anim{animation:none !important}}`}</style>
          {gridVals.map((g) => {
            const gv = g / 100;
            const gy = y(gv);
            return (
              <g key={g}>
                <line
                  x1={LEFT}
                  x2={VB_W - RIGHT}
                  y1={gy}
                  y2={gy}
                  stroke="#e5e8eb"
                  strokeWidth={1}
                  opacity={0.9}
                />
                <text x={LEFT - 6} y={gy + 4} textAnchor="end" fontSize={10} fill="#8b95a1">
                  {g}%
                </text>
              </g>
            );
          })}
          {seg.harnessChanges.map((hc) => {
            const hx = hxFor(hc.index);
            const nearRight = hx > VB_W - RIGHT - 48;
            const anchor = nearRight ? "end" : "start";
            const tx = nearRight ? hx - 4 : hx + 4;
            return (
              <g key={`${hc.index}-${hc.to}`}>
                <title>{harnessLabel(hc.to)}</title>
                <line
                  x1={hx}
                  x2={hx}
                  y1={TOP}
                  y2={TOP + CHART_H}
                  stroke="#e88400"
                  strokeWidth={1.5}
                  strokeDasharray="4 4"
                  opacity={0.9}
                />
                <text x={tx} y={TOP + 2} fontSize={10} fill="#e88400" textAnchor={anchor}>
                  {shortHarness(hc.to)}
                </text>
              </g>
            );
          })}
          {[...byKind.entries()].map(([kind, pts]) => {
            if (pts.length < 2) return null;
            const d = pts.map((p) => `${p.px},${p.py}`).join(" ");
            return (
              <polyline
                key={kind}
                points={d}
                fill="none"
                stroke={colorForKind(kind)}
                strokeWidth={1.5}
                opacity={0.55}
              />
            );
          })}
          {seg.points.map((p, i) => {
            const px = x(i);
            const c = colorForKind(p.kind);
            const date = formatDate(p.created_at);
            const title =
              `${p.kind} ${p.passed}/${p.n} ${(p.pass_rate * 100).toFixed(1)}% ` +
              `[${(p.lo * 100).toFixed(1)}\u2013${(p.hi * 100).toFixed(1)}%] ` +
              `harness ${p.harness_version} ${date}`;
            return (
              <g key={p.measurement_id}>
                <a href={`/verify/${encodeURIComponent(p.evidence_id)}`} aria-label={title}>
                  <title>{title}</title>
                  <line
                    x1={px}
                    x2={px}
                    y1={y(p.hi)}
                    y2={y(p.lo)}
                    stroke={c}
                    strokeWidth={3}
                    strokeLinecap="round"
                    opacity={0.9}
                    className="evo-anim motion-reduce:animate-none"
                  />
                  <circle
                    cx={px}
                    cy={y(p.pass_rate)}
                    r={6}
                    fill={c}
                    stroke="#ffffff"
                    strokeWidth={2}
                    className="evo-anim motion-reduce:animate-none"
                  />
                </a>
                <text
                  x={px}
                  y={TOP + CHART_H + 18}
                  textAnchor="middle"
                  fontSize={10}
                  fill="#8b95a1"
                >
                  {date}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {seg.families.length > 0 ? (
        <div className="mt-3 min-w-0" style={{ maxWidth: "100%" }}>
          <div className="text-xs text-text-secondary mb-1">{familiesHeading}</div>
          <div className="overflow-x-auto max-w-full" style={{ maxWidth: "100%" }}>
            <table
              className="border-collapse text-xs"
              style={{ minWidth: Math.max(280, 120 + 72 * n), maxWidth: "none" }}
            >
              <thead>
                <tr>
                  <th className="text-left font-medium text-text-secondary p-1 min-w-[90px]">
                    <span className="sr-only">family</span>
                  </th>
                  {seg.points.map((p) => (
                    <th
                      key={p.measurement_id}
                      className="font-medium text-text-secondary p-1 text-center min-w-[64px]"
                      scope="col"
                    >
                      {formatDate(p.created_at)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {seg.families.map((row) => (
                  <tr key={row.family}>
                    <th
                      scope="row"
                      title={row.family}
                      className="text-left font-medium text-text-primary p-1 whitespace-nowrap truncate min-w-[90px] max-w-[140px]"
                    >
                      {row.family}
                    </th>
                    {row.cells.map((cell) => {
                      const empty = cell.n === 0;
                      const rate = empty ? 0 : cell.passed / cell.n;
                      return (
                        <td
                          key={cell.measurement_id}
                          className="p-1 text-center border border-border"
                          title={empty ? `${row.family}: no data` : `${row.family} ${cell.passed}/${cell.n}`}
                          style={
                            empty
                              ? {
                                  background:
                                    "repeating-linear-gradient(45deg, #f2f4f6, #f2f4f6 4px, #e5e8eb 4px, #e5e8eb 8px)",
                                  color: "#8b95a1",
                                }
                              : {
                                  backgroundColor: `rgba(18, 166, 110, ${(0.12 + 0.68 * clamp01(rate)).toFixed(3)})`,
                                  color: 0.12 + 0.68 * clamp01(rate) >= 0.5 ? "#ffffff" : "#191f28",
                                }
                          }
                        >
                          {cell.passed}/{cell.n}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </section>
  );
}

export function EvolutionTimeline(props: EvolutionTimelineProps) {
  let tr: ((key: string, vars?: Record<string, string | number>) => string) | null = null;
  try {
    const t = useTranslations("performance");
    tr = (key: string, vars?: Record<string, string | number>) => {
      const short = key.startsWith("performance.") ? key.slice("performance.".length) : key;
      const bare = short.startsWith("timeline.") ? short : `timeline.${short}`;
      try {
        return (t as (k: string, v?: Record<string, string | number>) => string)(bare as never, vars as never);
      } catch {
        const fb = FALLBACK[key] ?? FALLBACK[`performance.${bare}`] ?? FALLBACK[bare];
        if (fb && vars) {
          return Object.entries(vars).reduce(
            (s, [k, v]) => s.replace(`{${k}}`, String(v)),
            fb,
          );
        }
        return fb ?? bare;
      }
    };
  } catch {
    tr = null;
  }
  const translate = (key: string, vars?: Record<string, string | number>): string => {
    if (tr) return tr(key, vars);
    const fb = FALLBACK[key] ?? key;
    if (vars) {
      return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, String(v)), fb);
    }
    return fb;
  };

  const timeline: Timeline = React.useMemo(() => {
    if (props.timeline) return props.timeline;
    if (props.data) return props.data;
    if (props.segments) return { segments: props.segments };
    if (props.history) return buildTimeline(props.history);
    return { segments: [] };
  }, [props.timeline, props.data, props.segments, props.history]);

  const emptyText = translate("timeline.empty");
  const dividerText = translate("timeline.not-comparable");
  const legendX = translate("timeline.legend-x-single");
  const legendPipe = translate("timeline.legend-pipeline");
  const familiesHeading = translate("timeline.families-heading");
  const harnessLabel = (version: string) => translate("timeline.harness", { version });
  const formatVerdict = (c: { verdict: string; deltaPp: number }): string => {
    const delta = formatDeltaPp(c.deltaPp);
    if (c.verdict === "improved") return translate("timeline.verdict-improved", { delta });
    if (c.verdict === "worse") return translate("timeline.verdict-worse", { delta });
    return translate("timeline.verdict-unclear", { delta });
  };

  if (!timeline || timeline.segments.length === 0) {
    return (
      <div className={props.className ?? ""} style={{ maxWidth: "100%" }}>
        <p className="text-sm text-text-secondary">{emptyText}</p>
      </div>
    );
  }

  return (
    <div className={props.className ?? ""} style={{ maxWidth: "100%" }}>
      {timeline.segments.map((seg, si) => (
        <React.Fragment key={`${seg.suite_version}__${seg.model}__${si}`}>
          {si > 0 ? (
            <div
              role="separator"
              aria-label={dividerText}
              className="flex items-center gap-2 my-3 text-xs text-text-secondary"
            >
              <span className="flex-1 border-t border-dashed border-border" />
              <span className="px-2 py-0.5 rounded-full border border-border bg-background-primary whitespace-nowrap">
                {dividerText}
              </span>
              <span className="flex-1 border-t border-dashed border-border" />
            </div>
          ) : null}
          <SegmentPanel
            seg={seg}
            notComparableLabel={dividerText}
            legendX={legendX}
            legendPipe={legendPipe}
            harnessLabel={harnessLabel}
            familiesHeading={familiesHeading}
            formatVerdict={formatVerdict}
          />
        </React.Fragment>
      ))}
    </div>
  );
}

export default EvolutionTimeline;
