"use client";
import React from "react";
import { useTranslations } from "next-intl";
import { buildEvidenceGraph } from "../lib/evidenceGraph";
import type {
  EvidenceGraph as EvidenceGraphData,
  EvidenceGraphEdge,
  EvidenceGraphNode,
} from "../lib/evidenceGraph";
import type { EvidenceLink, GateVerdict } from "../lib/api";

export interface EvidenceGraphProps {
  graph?: EvidenceGraphData;
  data?: EvidenceGraphData;
  nodes?: EvidenceGraphNode[];
  edges?: EvidenceGraphEdge[];
  chain?: EvidenceLink[];
  gates?: GateVerdict[];
  className?: string;
}

const FALLBACK: Record<string, string> = {
  "graph.heading": "Evidence chain",
  "graph.done": "Done",
  "graph.blocked": "Blocked",
  "graph.missing": "Missing",
  "graph.legend-done": "Done",
  "graph.legend-blocked": "Blocked",
  "graph.legend-missing": "Missing",
  "graph.empty": "No evidence chain yet.",
};

/* Theme tokens (see tailwind.config.ts):
   done -> accent.green #22c55e, blocked -> accent.red #ef4444,
   missing -> text.secondary #8b96ad (dashed). */
const COLORS: Record<string, { stroke: string; fill: string }> = {
  done: { stroke: "#22c55e", fill: "#10241a" },
  blocked: { stroke: "#ef4444", fill: "#2a1215" },
  missing: { stroke: "#8b96ad", fill: "#141b2d" },
};

const NODE_W = 148;
const NODE_H = 56;
const GAP_X = 28;
const GAP_Y = 44;
const PAD = 16;
/* Layout wraps to two rows at narrow widths (375px and below / <= 640px). */
const WRAP_BREAKPOINT = 640;
const NARROW_WIDTH = 375;

function shortStatus(
  status: string,
  t: (key: string) => string,
): string {
  if (status === "done") return t("graph.done");
  if (status === "blocked") return t("graph.blocked");
  return t("graph.missing");
}

export function EvidenceGraph(props: EvidenceGraphProps) {
  let tr: ((key: string) => string) | null = null;
  try {
    const t = useTranslations("evidence");
    tr = (key: string) => {
      try {
        return (t as (k: string) => string)(key as never);
      } catch {
        return FALLBACK[key] ?? key;
      }
    };
  } catch {
    tr = null;
  }
  const translate = (key: string): string => {
    if (tr) return tr(key);
    return FALLBACK[key] ?? key;
  };

  const graph: EvidenceGraphData = React.useMemo(() => {
    if (props.graph) return props.graph;
    if (props.data) return props.data;
    if (props.nodes || props.edges) {
      return { nodes: props.nodes ?? [], edges: props.edges ?? [] };
    }
    if (props.chain) {
      return buildEvidenceGraph(
        props.chain as { stage: string; event_id: string | null }[],
        (props.gates ?? []) as { gate: string; result: string }[],
      );
    }
    return { nodes: [], edges: [] };
  }, [props.graph, props.data, props.nodes, props.edges, props.chain, props.gates]);

  const nodes = graph.nodes ?? [];
  const edges = graph.edges ?? [];

  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const [measured, setMeasured] = React.useState(0);
  React.useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      const w = el.clientWidth || el.getBoundingClientRect().width || 0;
      setMeasured(w);
    };
    update();
    let ro: ResizeObserver | null = null;
    try {
      if (typeof ResizeObserver !== "undefined") {
        ro = new ResizeObserver(() => update());
        ro.observe(el);
      }
    } catch {
      ro = null;
    }
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("resize", update);
      if (ro) ro.disconnect();
    };
  }, []);

  const effectiveWidth =
    measured > 0
      ? measured
      : typeof window !== "undefined" && window.innerWidth > 0
        ? window.innerWidth
        : 0;
  // Left-to-right flow; wraps to two rows at 375px (narrow <= WRAP_BREAKPOINT).
  const narrow =
    effectiveWidth > 0
      ? effectiveWidth <= WRAP_BREAKPOINT || effectiveWidth <= NARROW_WIDTH + 265
      : false;
  void NARROW_WIDTH;
  const cols = nodes.length === 0 ? 0 : narrow ? Math.ceil(nodes.length / 2) : nodes.length;
  const rows = nodes.length === 0 ? 0 : Math.ceil(nodes.length / Math.max(1, cols));

  const pos = (index: number): { x: number; y: number } => {
    const c = cols > 0 ? cols : nodes.length;
    const col = c > 0 ? index % c : index;
    const row = c > 0 ? Math.floor(index / c) : 0;
    return {
      x: PAD + col * (NODE_W + GAP_X),
      y: PAD + row * (NODE_H + GAP_Y),
    };
  };

  const indexByStage = new Map<string, number>();
  nodes.forEach((n, i) => {
    if (!indexByStage.has(n.stage)) indexByStage.set(n.stage, i);
  });

  const vbW =
    nodes.length === 0
      ? 0
      : PAD * 2 + Math.min(nodes.length, Math.max(1, cols)) * NODE_W +
        (Math.min(nodes.length, Math.max(1, cols)) - 1) * GAP_X;
  const vbH = nodes.length === 0 ? 0 : PAD * 2 + rows * NODE_H + (rows - 1) * GAP_Y;

  if (nodes.length === 0) {
    return (
      <div
        ref={containerRef}
        data-testid="evidence-graph"
        className={props.className ?? ""}
        style={{ maxWidth: "100%" }}
      >
        <p className="text-sm text-text-secondary">{translate("graph.empty")}</p>
      </div>
    );
  }

  const edgeLines = edges
    .map((e, i) => {
      const a = indexByStage.get(e.from);
      const b = indexByStage.get(e.to);
      if (a === undefined || b === undefined) return null;
      const pa = pos(a);
      const pb = pos(b);
      const sameRow = Math.floor(a / Math.max(1, cols)) === Math.floor(b / Math.max(1, cols));
      let x1: number;
      let y1: number;
      let x2: number;
      let y2: number;
      if (sameRow) {
        x1 = pa.x + NODE_W;
        y1 = pa.y + NODE_H / 2;
        x2 = pb.x;
        y2 = pb.y + NODE_H / 2;
      } else {
        x1 = pa.x + NODE_W / 2;
        y1 = pa.y + NODE_H;
        x2 = pb.x + NODE_W / 2;
        y2 = pb.y;
      }
      return { e, i, x1, y1, x2, y2 };
    })
    .filter(Boolean) as Array<{ e: EvidenceGraphEdge; i: number; x1: number; y1: number; x2: number; y2: number }>;

  const heading = translate("graph.heading");
  const legendDone = translate("graph.legend-done");
  const legendBlocked = translate("graph.legend-blocked");
  const legendMissing = translate("graph.legend-missing");

  return (
    <div
      ref={containerRef}
      data-testid="evidence-graph"
      className={props.className ?? ""}
      style={{ maxWidth: "100%" }}
    >
      <p className="text-sm font-semibold text-text-primary mb-2">{heading}</p>
      <div className="w-full max-w-full overflow-x-auto" style={{ maxWidth: "100%" }}>
        <svg
          role="img"
          aria-label={heading}
          width="100%"
          height={vbH}
          viewBox={`0 0 ${vbW} ${vbH}`}
          preserveAspectRatio="xMidYMid meet"
          className="block w-full h-auto"
          style={{ width: "100%", height: "auto", maxWidth: "100%" }}
          data-narrow={narrow ? "two-rows" : "one-row"}
        >
          <style>{`@keyframes ev-edge-reveal{from{stroke-dashoffset:24;opacity:0}to{stroke-dashoffset:0;opacity:1}}.ev-edge-anim{stroke-dasharray:6 4;animation:ev-edge-reveal 500ms ease-out}@media (prefers-reduced-motion:reduce){.ev-edge-anim{animation:none !important}}@media (max-width: 375px){.ev-node-text{font-size:11px}}`}</style>
          <defs>
            <marker
              id="ev-arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 9 5 L 0 9 z" fill="#8b96ad" />
            </marker>
          </defs>
          {edgeLines.map(({ e, i, x1, y1, x2, y2 }) => (
            <line
              key={`${e.from}-${e.to}-${i}`}
              data-testid="evidence-edge"
              x1={x1}
              y1={y1}
              x2={x2 === x1 ? x2 : x2 - 3}
              y2={y2}
              stroke="#8b96ad"
              strokeWidth={1.5}
              markerEnd="url(#ev-arrow)"
              className="ev-edge-anim motion-reduce:animate-none"
            >
              <title>{`${e.from} → ${e.to}`}</title>
            </line>
          ))}
          {nodes.map((n, i) => {
            const p = pos(i);
            const c = COLORS[n.status] ?? COLORS.missing;
            const statusText = shortStatus(n.status, translate);
            const titleText = n.detail
              ? `${n.label} — ${statusText}: ${n.detail}`
              : `${n.label} — ${statusText}`;
            const ariaLabel = n.href ? `${titleText} (${n.href})` : titleText;
            const rect = (
              <>
                <rect
                  x={p.x}
                  y={p.y}
                  width={NODE_W}
                  height={NODE_H}
                  rx={8}
                  fill={c.fill}
                  stroke={c.stroke}
                  strokeWidth={n.status === "missing" ? 1.5 : 2}
                  strokeDasharray={n.status === "missing" ? "6 4" : undefined}
                />
                <text
                  x={p.x + NODE_W / 2}
                  y={p.y + 22}
                  textAnchor="middle"
                  fontSize={12}
                  fontWeight={600}
                  fill="#e8edf5"
                  className="ev-node-text"
                >
                  {n.label}
                </text>
                <text
                  x={p.x + NODE_W / 2}
                  y={p.y + 40}
                  textAnchor="middle"
                  fontSize={11}
                  fill={c.stroke}
                  className="ev-node-text"
                >
                  {statusText}
                </text>
              </>
            );
            return (
              <g key={`${n.stage}-${i}`} data-testid="evidence-node">
                <title>{titleText}</title>
                {n.href ? (
                  <a href={n.href} aria-label={ariaLabel}>
                    <title>{titleText}</title>
                    {rect}
                  </a>
                ) : (
                  <g aria-label={ariaLabel}>{rect}</g>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <div
        data-testid="evidence-legend"
        className="flex items-center gap-4 mt-2 text-xs text-text-secondary flex-wrap"
      >
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block w-3 h-3 rounded"
            style={{ backgroundColor: COLORS.done.stroke }}
          />
          {legendDone}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block w-3 h-3 rounded"
            style={{ backgroundColor: COLORS.blocked.stroke }}
          />
          {legendBlocked}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block w-3 h-3 rounded border border-dashed"
            style={{ borderColor: COLORS.missing.stroke }}
          />
          {legendMissing}
        </span>
      </div>
    </div>
  );
}

export default EvidenceGraph;
