// Same-origin API access via the Next.js proxy route.
// The browser never calls the API directly and no API base URL is exposed
// to the client at runtime.
export const API_BASE = "/api/evoforge";

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
  sealed_tests?: Array<{ kind?: string; code_sha256?: string; code_len?: number } | string>;
  sealed_count?: number;
  sealed_tests_count?: number;
  sealed_kinds?: string[];
  review?: { result: string; findings?: unknown[] };
  stub?: boolean;
  model?: string;
  evidence_id?: string;
  provider_evidence_ids?: string[];
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

export interface SealedTest {
  kind: string;
  code_sha256: string;
  code_len: number;
}

export interface SuiteResult {
  pass: number;
  n: number;
  timed_out: boolean;
  exit_code: number | null;
}

export interface RunResponse {
  gates: GateVerdict[];
  run: { base: string; visible: SuiteResult; heldout: SuiteResult; heldout_kinds: string[] };
  evidence_id: string;
}

export function postRun(
  source_repo: string,
  base_sha: string,
  diff: string,
  tests: string[],
  review_evidence_id: string,
) {
  return req<RunResponse>("/v1/runs", {
    method: "POST",
    body: JSON.stringify({ source_repo, base_sha, diff, tests: tests.map((code) => ({ code })), review_evidence_id }),
  });
}

// The server opens a PR only from its own stored, all-PASS evidence of a server run.
export function postCreatePR(evidence_id: string, title: string, body = "", base = "main") {
  return req<PRResponse>("/v1/pr/create", {
    method: "POST",
    body: JSON.stringify({ evidence_id, title, body, base }),
  });
}

export function getLedger() {
  return req<LedgerSnapshot>("/v1/ledger");
}

export type MissionState =
  | "CREATED"
  | "GENERATED"
  | "REVIEWED"
  | "RAN"
  | "PR_OPENED"
  | "CANCELLED"
  | "FAILED";

export interface MissionSummary {
  mission_id: string;
  state: MissionState;
  goal: string;
  updated_at: number;
  evidence_ids: string[];
}

export interface MissionDetail extends MissionSummary {
  repo_ref: string;
  target_paths: string[] | null;
  risk: string;
  created_at: number;
  generate_evidence_id: string | null;
  review_evidence_id: string | null;
  run_evidence_id: string | null;
  pr_evidence_id: string | null;
  pr_url: string | null;
}

export interface DashboardSnapshot {
  missions_by_state: Record<string, number>;
  active_missions: number;
  blocked_merges: number;
  spent_cents: number;
  reserved_cents: number;
  unknown_holds: number;
}

export function postMission(goal: string, repo_ref = "HEAD", risk = "LOW") {
  return req<{ mission_id: string; state: MissionState; evidence_id: string }>(
    "/v1/missions",
    { method: "POST", body: JSON.stringify({ goal, repo_ref, risk }) },
  );
}

export function postMissionAdvance(mission_id: string, to: MissionState) {
  return req<{ mission_id: string; state: MissionState; evidence_id?: string }>(
    `/v1/missions/${encodeURIComponent(mission_id)}/advance`,
    { method: "POST", body: JSON.stringify({ to }) },
  );
}

export function postMissionCancel(mission_id: string) {
  return req<{ mission_id: string; state: MissionState }>(
    `/v1/missions/${encodeURIComponent(mission_id)}/cancel`,
    { method: "POST" },
  );
}

export function getMission(mission_id: string) {
  return req<MissionDetail>(`/v1/missions/${encodeURIComponent(mission_id)}`);
}

export function listMissions() {
  return req<{ missions: MissionSummary[] }>("/v1/missions");
}

export function getDashboard() {
  return req<DashboardSnapshot>("/v1/dashboard");
}

export interface LedgerSnapshot {
  project: string;
  spent_cents: number;
  reserved_cents: number;
  overruns: unknown[];
  unknown_reservations: string[];
}

export function getEvidence(id: string) {
  return req<EvidenceChain | Record<string, unknown>>(
    `/v1/evidence/${encodeURIComponent(id)}`,
  );
}

export interface ChainEvent {
  id: string;
  stage: string;
  kind: string;
  evidence_id: string;
  summary: Record<string, unknown>;
}

export function getEvent(event_id: string) {
  return req<ChainEvent>(`/v1/events/${encodeURIComponent(event_id)}`);
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
