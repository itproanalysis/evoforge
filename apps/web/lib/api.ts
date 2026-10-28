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
  prs_awaiting_validation?: number;
  wvi_rule?: string;
  spend_basis?: string;
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

export type EvalJobKind = "X_SINGLE" | "PIPELINE";

export type EvalJobStatus = "queued" | "running" | "succeeded" | "failed";

export interface EvalJob {
  job_id: string;
  kind: EvalJobKind;
  status: EvalJobStatus;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  result: Record<string, unknown> | null;
  error: string | null;
}

export function startEvalJob(kind: EvalJobKind, family?: string) {
  return req<{ job_id: string; kind: EvalJobKind; status: EvalJobStatus; created_at: number }>(
    "/v1/eval/jobs",
    {
      method: "POST",
      body: JSON.stringify(family ? { kind, family } : { kind }),
    },
  );
}

export function getEvalJob(id: string) {
  return req<EvalJob>(`/v1/eval/jobs/${encodeURIComponent(id)}`);
}

export function listEvalJobs() {
  return req<{ jobs: EvalJob[] }>("/v1/eval/jobs");
}

export interface DecisionMeasurement {
  passed: number;
  n: number;
  pass_rate: number;
  wilson95: [number, number];
  [key: string]: unknown;
}

export type DecisionVerdict = "improved" | "no_clear_difference" | "worse";

export type AdoptionDecision = "adopt" | "keep";

export interface Decision {
  decision_id?: string;
  created_at: number;
  suite_version: string;
  kind: string;
  model?: string;
  family?: string | null;
  champion: string;
  challenger: string;
  champion_measurement: DecisionMeasurement;
  challenger_measurement: DecisionMeasurement;
  verdict: DecisionVerdict;
  decision: AdoptionDecision;
  reason: string;
  [key: string]: unknown;
}

export interface AbTestBody {
  suite_version: string;
  kind: string;
  family?: string;
  champion: string;
  challenger: string;
}

export function startAbTest(body: AbTestBody) {
  return req<{ job_id: string; kind: string; status: EvalJobStatus; created_at: number }>(
    "/v1/eval/abtest",
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function listDecisions() {
  return req<{ decisions: Decision[] }>("/v1/eval/decisions");
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
  run_active?: boolean;
  run_error?: string | null;
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
  signed?: boolean | null;
  algorithm?: string | null;
  public_key?: string | null;
  verify?: { ok: boolean; reason: string };
}

export function startEvolution(goal: string, repo_ref = "HEAD", max_generations = 3, population = 2, use_memory = true, source_repo = "") {
  return req<EvolutionPublic & { evidence_id?: string }>("/v1/evolution/start", {
    method: "POST",
    body: JSON.stringify({ goal, repo_ref, max_generations, population, use_memory, source_repo }),
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
  return req<{ evolution_id: string; status: string; run_active: boolean; run_error?: string | null }>(
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

export function getProofKey() {
  return req<{ algorithm: string; public_key: string }>(`/v1/proof/key`);
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

export type FeedbackKind = "bug" | "missed_case" | "praise" | "other";

export interface FeedbackItem {
  feedback_id: string;
  mission_id: string;
  kind: FeedbackKind;
  text: string;
  created_at: number;
  promoted_mission_id: string | null;
}

export function postFeedback(mission_id: string, kind: FeedbackKind, text: string) {
  return req<FeedbackItem>("/v1/feedback", {
    method: "POST",
    body: JSON.stringify({ mission_id, kind, text }),
  });
}

export function listFeedback() {
  return req<{ feedback: FeedbackItem[] }>("/v1/feedback");
}

export function promoteFeedback(feedback_id: string) {
  return req<{ mission_id: string; feedback_id: string }>(
    `/v1/feedback/${encodeURIComponent(feedback_id)}/promote`,
    { method: "POST" },
  );
}


export interface ArenaEvent {
  seq: number;
  ts: number;
  role: "builder" | "critic" | "runner" | "gate" | "system";
  message: string;
}

export interface ArenaLane {
  status: "running" | "succeeded" | "failed";
  attempts: number;
  heldout: { passed: number; n: number };
  outcome: "passed" | "empty_diff" | "apply_failed" | "heldout_failed" | "verification_inconclusive";
  cost_cents: number;
  elapsed_ms: number;
  diff: string;
  events: ArenaEvent[];
  failing_tests?: string[];
  error?: string | null;
}

export interface ArenaDoc {
  arena_id: string;
  status: "running" | "succeeded" | "failed";
  suite_version: "v1" | "v2";
  task_id: string;
  model: string;
  goal: string;
  created_at: number;
  started_at?: number | null;
  finished_at?: number | null;
  lanes: {
    single: ArenaLane;
    evoforge: ArenaLane;
  };
  verdict: {
    winner: "evoforge" | "single" | "tie" | "inconclusive";
    reason: string;
  };
  error?: string | null;
}

export function postArena(task_id: string, suite_version: "v1" | "v2" = "v2", model: string = "muse-spark-1.3") {
  return req<{ arena_id: string; status: string }>("/v1/arena", {
    method: "POST",
    body: JSON.stringify({ task_id, suite_version, model }),
  });
}

export function getArena(arena_id: string) {
  return req<ArenaDoc>(`/v1/arena/${encodeURIComponent(arena_id)}`);
}

export function listArenas() {
  return req<{ arenas: ArenaDoc[] }>("/v1/arena");
}

// --- R1-R5 round replay (recorded evolution runs) ---

export type EvolutionSnapStatus = "READY" | "UNVERIFIED" | "FAILED" | "PENDING";

export interface EvolutionSnap {
  status: EvolutionSnapStatus;
  verified?: boolean;
  heldout?: { passed: number; n: number } | null;
  cost_cents?: number | null;
  elapsed_ms?: number | null;
  source_sha?: string | null;
  preview_html?: string | null;
  preview_error?: string | null;
  diff?: string | null;
  events?: unknown[] | null;
  [key: string]: unknown;
}

export interface EvolutionRound {
  index: number;
  name?: string;
  goal?: string;
  sides: { evoforge: EvolutionSnap; single: EvolutionSnap };
}

export interface EvolutionRunManifest {
  app_id?: string;
  rounds?: number;
  cost_basis?: string;
  runner_cost?: string;
  disclosure?: string;
  lanes?: unknown;
  [key: string]: unknown;
}

export interface EvolutionRunLaneTotals {
  cost_cents?: number | null;
  elapsed_ms?: number | null;
  verified_rounds?: number | null;
  [key: string]: unknown;
}

export interface EvolutionRun {
  run_id: string;
  app_id?: string;
  title?: string;
  status?: string;
  manifest?: EvolutionRunManifest;
  rounds?: EvolutionRound[];
  totals?: { evoforge?: EvolutionRunLaneTotals; single?: EvolutionRunLaneTotals };
  [key: string]: unknown;
}

export interface EvolutionRunSummary {
  run_id: string;
  app_id?: string;
  title?: string;
  status?: string;
  [key: string]: unknown;
}

export function listEvolutionRuns() {
  return req<{ runs: EvolutionRunSummary[] }>("/v1/evolution/runs");
}

export function getEvolutionRun(id: string) {
  return req<EvolutionRun>(`/v1/evolution/runs/${encodeURIComponent(id)}`);
}
