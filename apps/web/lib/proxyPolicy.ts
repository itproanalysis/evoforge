const EXACT_ALLOW = new Set([
  "/v1/commands/generate",
  "/v1/objectives",
  "/v1/candidates/review",
  "/v1/gates/evaluate",
  "/v1/runs",
  "/v1/pr/create",
  "/v1/ledger",
  "/v1/ledger/reconcile",
  "/v1/eval/sandbox",
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
  return null;
}
