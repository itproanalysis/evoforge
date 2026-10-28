import type { EvidenceLink, GateVerdict } from "./api";

export type EvidenceGraphStatus = "done" | "blocked" | "missing";

export interface EvidenceGraphNode {
  stage: string;
  label: string;
  status: EvidenceGraphStatus;
  detail: string;
  href: string | null;
}

export interface EvidenceGraphEdge {
  from: string;
  to: string;
}

export interface EvidenceGraph {
  nodes: EvidenceGraphNode[];
  edges: EvidenceGraphEdge[];
}

export interface EvidenceChainInput {
  stage: string;
  event_id: string | null;
}

export interface EvidenceGateInput {
  gate: string;
  result: string;
  reason?: string;
}

function gateDetail(gates: EvidenceGateInput[]): string {
  return gates
    .map((g) => {
      const reason =
        typeof g.reason === "string" && g.reason ? ` (${g.reason})` : "";
      return `${g.gate}: ${g.result}${reason}`;
    })
    .join(", ");
}

export function buildEvidenceGraph(
  chain: EvidenceChainInput[] | null | undefined,
  gates: EvidenceGateInput[] | null | undefined,
): EvidenceGraph {
  if (!Array.isArray(chain) || chain.length === 0) {
    return { nodes: [], edges: [] };
  }
  const gateList = Array.isArray(gates) ? gates : [];
  const nodes: EvidenceGraphNode[] = chain.map((link) => {
    const stage = String(link.stage);
    const eventId =
      typeof link.event_id === "string" && link.event_id
        ? link.event_id
        : null;
    const href = eventId ? `/evidence?id=${encodeURIComponent(eventId)}` : null;
    if (eventId === null) {
      return {
        stage,
        label: stage,
        status: "missing",
        detail: "",
        href: null,
      };
    }
    if (stage === "Gate") {
      const failing = gateList.filter((g) => g.result !== "PASS");
      if (failing.length > 0) {
        return {
          stage,
          label: stage,
          status: "blocked",
          detail: gateDetail(failing),
          href,
        };
      }
      return {
        stage,
        label: stage,
        status: "done",
        detail: gateList.length > 0 ? gateDetail(gateList) : eventId,
        href,
      };
    }
    return {
      stage,
      label: stage,
      status: "done",
      detail: eventId,
      href,
    };
  });
  const edges: EvidenceGraphEdge[] = [];
  for (let i = 0; i < chain.length - 1; i += 1) {
    edges.push({
      from: String(chain[i].stage),
      to: String(chain[i + 1].stage),
    });
  }
  return { nodes, edges };
}

export default buildEvidenceGraph;
