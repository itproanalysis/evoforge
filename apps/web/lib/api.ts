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
  candidate_id?: string;
  verdict: GateResult | string;
  sealed_tests?: string[];
  reason?: string;
  raw?: unknown;
}

export interface PRResponse {
  pr_url?: string;
  pr_id?: string;
  blocked?: boolean;
  reason?: string;
  raw?: unknown;
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

export function postReview(candidate_id: string, gates: GateVerdict[]) {
  return req<ReviewResponse>("/v1/candidates/review", {
    method: "POST",
    body: JSON.stringify({ candidate_id, gates }),
  });
}

export function postCreatePR(candidate_id: string) {
  return req<PRResponse>("/v1/pr/create", {
    method: "POST",
    body: JSON.stringify({ candidate_id }),
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
