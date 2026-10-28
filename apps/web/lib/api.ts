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
  validated_improvements: number;
  validated_mission_ids: string[];
  spent_cents: number;
  reserved_cents: number;
  unknown_holds: number;
}

export interface Outcome {
  mission_id: string;
  goal?: string;
  pr_url: string;
  merged_sha: string;
  outcome_status: string;
  weight: number;
  run_evidence_id: string | null;
  pr_evidence_id: string | null;
  recorded_at: number;
  evidence_id?: string;
}

export function postOutcome(mission_id: string, merged_sha: string, pr_url = "") {
  return req<Outcome>("/v1/outcomes", {
    method: "POST",
    body: JSON.stringify({ mission_id, merged_sha, pr_url }),
  });
}

export function listOutcomes() {
  return req<{ outcomes: Outcome[] }>("/v1/outcomes");
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

export interface EvalSuite {
  family: string;
  task_count: number;
  heldout_kinds: string[];
}

export interface EvalSuitesResponse {
  suite_version: string;
  suites: EvalSuite[];
}

export interface XSingle {
  pass_rate: number;
  n: number;
  cost_cents: number;
}

export function getEvalSuites() {
  return req<EvalSuitesResponse>("/v1/eval/suites");
}

export interface MeasurementRecord {
  provider_stub?: boolean;
  measurement_id: string;
  kind: string;
  suite_version: string;
  model: string;
  harness_version: string;
  n: number;
  passed: number;
  pass_rate: number;
  wilson95: [number, number];
  cost_cents: number;
  created_at: number;
  per_family: Record<string, { n: number; passed: number }>;
  evidence_id: string;
  attempts_total?: number;
  usage_missing?: boolean;
}

export interface MeasurementView {
  provider_stub?: boolean;
  status: "measured" | "not_measured";
  reason: string;
  record: MeasurementRecord | null;
  kind?: string;
  measurement_id?: string;
  suite_version?: string;
  model?: string;
  harness_version?: string;
  n?: number;
  passed?: number;
  pass_rate?: number;
  wilson95?: [number, number];
  cost_cents?: number;
  created_at?: number;
  per_family?: Record<string, { n: number; passed: number }>;
  evidence_id?: string;
  attempts_total?: number;
  usage_missing?: boolean;
}

export interface PerformanceComparison {
  status: "measured" | "not_measured";
  reason: string;
  delta_pp: number | null;
  verdict: "improved" | "no_clear_difference" | "worse" | null;
}

export interface ProductionStats {
  runs: number;
  gate_pass: number;
  gate_fail: number;
  gate_inconclusive: number;
  heldout_pass_rate_pct: number | null;
  sample_note: string;
}

export interface PerformanceSnapshot {
  baseline: MeasurementView;
  pipeline: MeasurementView;
  comparison: PerformanceComparison;
  cost_per_solved_cents: { baseline: number | null; pipeline: number | null };
  history: MeasurementRecord[];
  production: ProductionStats;
  storage: string;
}

export interface BaselineResponse {
  baseline_id: string;
  evidence_id: string;
  measurement_id: string;
  measurement: MeasurementRecord;
  suite_version: string;
  model: string;
}

export interface PipelineResponse {
  pipeline_id: string;
  evidence_id: string;
  measurement_id: string;
  measurement: MeasurementRecord;
  suite_version: string;
  model: string;
}

export function getPerformance() {
  return req<PerformanceSnapshot>("/v1/performance");
}

export interface Participant {
  agent_id: string;
  kind: string;
  roles: string[];
  join_state: string;
  connection_state: string;
  execution_state: string;
  credential_state: string;
}

export function getParticipants() {
  return req<{status: "available" | "unavailable"; participants: Participant[]; has_more?: boolean}>("/v1/participants");
}

export function runBaseline(suite_version = "v0", model = "muse-spark-1.3") {
  return req<BaselineResponse>("/v1/eval/baseline", {
    method: "POST",
    body: JSON.stringify({ suite_version, model }),
  });
}

export function runPipeline(suite_version = "v0", model = "muse-spark-1.3") {
  return req<PipelineResponse>("/v1/eval/pipeline", {
    method: "POST",
    body: JSON.stringify({ suite_version, model }),
  });
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

// --- Autonomous Evolution (Autopilot) + Proof Certificates ---

export interface EvolutionCandidate {
  generate_evidence_id?: string | null;
  review_evidence_id?: string | null;
  run_evidence_id?: string | null;
  gates?: GateVerdict[];
  fitness?: { score: number; all_pass: boolean; gates_pass: number; gates_total: number };
  review_result?: string | null;
  diff_chars?: number;
  diff_sha256?: string;
  candidate_error?: string | null;
}

export interface EvolutionGeneration {
  index: number;
  converged: boolean;
  at: number;
  candidates: EvolutionCandidate[];
  winner_run_evidence_id?: string | null;
}

export interface EvolutionPublic {
  evolution_id: string;
  goal: string;
  repo_ref: string;
  status: "RUNNING" | "CONVERGED" | "EXHAUSTED" | "CANCELLED";
  max_generations: number;
  population: number;
  generations: EvolutionGeneration[];
  best: {
    generation?: number;
    run_evidence_id?: string | null;
    fitness?: { score: number; all_pass: boolean };
    gates?: GateVerdict[];
    review_result?: string | null;
  } | null;
  created_at: number;
  updated_at: number;
}

export interface ProofCertificate {
  certificate_id: string;
  evidence_id: string;
  issued_at: number;
  verdict: "VERIFIED" | "NOT_VERIFIED";
  gates: GateVerdict[];
  chain: EvidenceLink[];
  diff_sha256: string;
  sealed_kinds: string[];
  sealed_count: number;
  model: string;
  signature: string;
  verify?: { ok: boolean; reason: string };
}

export function startEvolution(goal: string, repo_ref = "HEAD", max_generations = 3, population = 2, use_memory = true) {
  return req<EvolutionPublic & { evidence_id?: string }>("/v1/evolution/start", {
    method: "POST",
    body: JSON.stringify({ goal, repo_ref, max_generations, population, use_memory }),
  });
}

export function listEvolutions() {
  return req<{ evolutions: EvolutionPublic[] }>("/v1/evolution");
}

export function getEvolution(evolution_id: string) {
  return req<EvolutionPublic>(`/v1/evolution/${encodeURIComponent(evolution_id)}`);
}

export function stepEvolution(evolution_id: string) {
  return req<{ evolution_id: string; status: string; generation: number; converged: boolean; winner: EvolutionCandidate }>(
    `/v1/evolution/${encodeURIComponent(evolution_id)}/step`,
    { method: "POST" },
  );
}

export function runEvolution(evolution_id: string) {
  return req<{ evolution_id: string; status: string; generations_ran: number; best: EvolutionPublic["best"] }>(
    `/v1/evolution/${encodeURIComponent(evolution_id)}/run`,
    { method: "POST" },
  );
}

export function promoteEvolution(evolution_id: string) {
  return req<PRResponse>(`/v1/evolution/${encodeURIComponent(evolution_id)}/promote`, {
    method: "POST",
  });
}

export function getProof(evidence_id: string) {
  return req<ProofCertificate>(`/v1/proof/${encodeURIComponent(evidence_id)}`);
}

export interface LeaderEntry {
  evolution_id: string;
  goal: string;
  generations_used: number;
  best_score: number;
  proof_evidence_id: string | null;
  proof_path: string | null;
}

export interface MemoryPattern {
  pattern_id: string;
  evolution_id: string;
  keywords: string[];
  fitness_score: number;
  proof_evidence_id: string | null;
  proof_path: string | null;
  at: number;
}

export function getLeaderboard() {
  return req<{ leaders: LeaderEntry[]; count: number }>("/v1/leaderboard");
}

export function getMemory() {
  return req<{ patterns: MemoryPattern[]; count: number }>("/v1/memory");
}
