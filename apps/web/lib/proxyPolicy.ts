const EXACT_ALLOW = new Set([
  "/v1/commands/generate",
  "/v1/objectives",
  "/v1/candidates/review",
  "/v1/gates/evaluate",
  "/v1/runs",
  "/v1/pr/create",
  "/v1/ledger",
  "/v1/ledger/reconcile",
  "/v1/missions",
  "/v1/feedback",
  "/v1/dashboard",
  "/v1/outcomes",
  "/v1/performance",
  "/v1/participants",
  "/v1/eval/suites",
  "/v1/eval/baseline",
  "/v1/eval/pipeline",
  "/v1/evolution",
  "/v1/evolution/apps",
  "/v1/evolution/runs",
  "/v1/proof/key",
  "/v1/leaderboard",
  "/v1/memory",
  "/v1/eval/jobs",
  "/v1/eval/abtest",
  "/v1/eval/decisions",
  "/v1/arena",
  "/v1/stream",
  "/v1/mcp",
]);

const SEGMENT_RE = /^[A-Za-z0-9._~-]+$/;
const CONTROL_RE = /[\x00-\x1f\x7f]/;

export function resolveApiPath(segments: string[]): string | null {
  if (!Array.isArray(segments) || segments.length === 0) return null;
  for (const seg of segments) {
    if (typeof seg !== "string") return null;
    if (seg.length === 0) return null;
    if (seg === "." || seg === "..") return null;
    if (seg.includes("/") || seg.includes("\\") || seg.includes("%")) return null;
    if (CONTROL_RE.test(seg)) return null;
    if (!SEGMENT_RE.test(seg)) return null;
  }
  const apiPath = `/${segments.join("/")}`;
  if (apiPath === "/v1/kernel" || apiPath.startsWith("/v1/kernel/")) return null;
  if (EXACT_ALLOW.has(apiPath)) return apiPath;
  if (
    segments.length === 3 &&
    segments[0] === "v1" &&
    (segments[1] === "evidence" || segments[1] === "events")
  ) {
    return apiPath;
  }
  if (segments.length === 3 && segments[0] === "v1" && segments[1] === "commands") {
    return apiPath;
  }
  if (
    segments.length === 4 &&
    segments[0] === "v1" &&
    segments[1] === "commands" &&
    segments[3] === "advance"
  ) {
    return apiPath;
  }
  if (segments.length === 3 && segments[0] === "v1" && segments[1] === "missions") {
    return apiPath;
  }
  if (segments.length === 2 && segments[0] === "v1" && segments[1] === "evolution") {
    return apiPath;
  }
  if (
    segments.length === 3 && segments[0] === "v1" &&
    (segments[1] === "evolution" || segments[1] === "proof")
  ) {
    return apiPath;
  }
  if (
    segments.length === 4 && segments[0] === "v1" &&
    segments[1] === "proof" && segments[2] === "cert"
  ) {
    return apiPath;
  }
  if (
    segments.length === 4 && segments[0] === "v1" && segments[1] === "evolution" &&
    (segments[3] === "step" || segments[3] === "run" ||
     segments[3] === "cancel" || segments[3] === "promote")
  ) {
    return apiPath;
  }
  if (
    segments.length === 4 && segments[0] === "v1" &&
    segments[1] === "evolution" && segments[2] === "runs"
  ) {
    return apiPath;
  }
  if (
    segments.length === 4 &&
    segments[0] === "v1" &&
    segments[1] === "eval" &&
    segments[2] === "jobs"
  ) {
    return apiPath;
  }
  if (
    segments.length === 2 &&
    segments[0] === "v1" &&
    segments[1] === "arena"
  ) {
    return apiPath;
  }
  if (
    segments.length === 3 &&
    segments[0] === "v1" &&
    segments[1] === "arena"
  ) {
    return apiPath;
  }
  if (
    segments.length === 4 &&
    segments[0] === "v1" &&
    segments[1] === "missions" &&
    (segments[3] === "advance" || segments[3] === "cancel")
  ) {
    return apiPath;
  }
  if (
    segments.length === 4 &&
    segments[0] === "v1" &&
    segments[1] === "feedback" &&
    segments[3] === "promote"
  ) {
    return apiPath;
  }
  return null;
}
