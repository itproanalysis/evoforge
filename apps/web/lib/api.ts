export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8080";

export type GateResult = "PASS" | "FAIL" | "INCONCLUSIVE";

export interface GateVerdict {
  gate: string;
  result: GateResult;
  reason?: string;
}

export interface Candidate {
  id?: string;
  diff: string;
  tests: string[];
  goal?: string;
}

export interface GenerateResponse {
  command_id: string;
  candidate: Candidate;
  gates: GateVerdict[];
  budget_reserved_cents: number;
  evidence: { repo_sha: string; model: string };
}

export interface ReviewResponse {
  sealed_tests?: Array<{ code: string } | string>;
  review?: { result: string; findings?: unknown[] };
  stub?: boolean;
  model?: string;
  evidence_id?: string;
  raw?: unknown;
}

export interface PRResponse {
  pr?: { html_url?: string; number?: number };
  evidence_id?: string;
  source_evidence_id?: string;
  raw?: unknown;
}

export interface EvaluateResponse {
  gates: GateVerdict[];
  evidence_id: string;
}

export interface RunStats {
  heldout_kinds: string[];
  vis_pass: number;
  vis_n: number;
  held_pass: number;
  held_n: number;
}

export interface EvidenceLink {
  stage: string;
  event_id: string | null;
}

export interface EvidenceChain {
  id: string;
  chain: EvidenceLink[];
  raw?: unknown;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`${r.status} ${path}: ${text.slice(0, 200)}`);
  }
  return (await r.json()) as T;
}

export function postGenerate(goal: string, repo_sha = "HEAD", risk = "LOW") {
  return req<GenerateResponse>("/v1/commands/generate", {
    method: "POST",
    body: JSON.stringify({ goal, repo_sha, risk }),
  });
}

export function postReview(goal_contract: string, diff: string, ci = "") {
  return req<ReviewResponse>("/v1/candidates/review", {
    method: "POST",
    body: JSON.stringify({ goal_contract, diff, ci }),
  });
}

export function postEvaluate(diff: string, tests: string[], stats: RunStats) {
  return req<EvaluateResponse>("/v1/gates/evaluate", {
    method: "POST",
    body: JSON.stringify({ diff, tests: tests.map((code) => ({ code })), ...stats }),
  });
}

// The server opens a PR only from its own stored, all-PASS gate evaluation.
export function postCreatePR(evidence_id: string, title: string, body = "", base = "main") {
  return req<PRResponse>("/v1/pr/create", {
    method: "POST",
    body: JSON.stringify({ evidence_id, title, body, base }),
  });
}

export function getEvidence(id: string) {
  return req<EvidenceChain | Record<string, unknown>>(
    `/v1/evidence/${encodeURIComponent(id)}`,
  );
}

export const EVIDENCE_STAGES = [
  "ObjectiveVersion",
  "Task",
  "Candidate",
  "Gate",
  "Review",
  "PR",
  "Outcome",
] as const;
