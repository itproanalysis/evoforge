import { headers } from "next/headers";
import type { ArenaDoc } from "./api";

// Server-side read of one arena match for link previews (page metadata and the share image). It goes
// through this site's own public proxy, so it needs no credentials of its own and sees exactly what a
// visitor would. Any failure returns null and the preview falls back to a generic card.
export async function fetchArenaForPreview(id: string): Promise<ArenaDoc | null> {
  try {
    const h = await headers();
    const host = h.get("x-forwarded-host") ?? h.get("host");
    if (!host) return null;
    const proto = h.get("x-forwarded-proto") ?? (/^(localhost|127\.0\.0\.1)(:|$)/.test(host) ? "http" : "https");
    const r = await fetch(`${proto}://${host}/api/evoforge/v1/arena/${encodeURIComponent(id)}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
    });
    if (!r.ok) return null;
    const doc = (await r.json()) as ArenaDoc;
    return doc && typeof doc === "object" && doc.arena_id === id ? doc : null;
  } catch {
    return null;
  }
}

export function laneScore(doc: ArenaDoc | null, side: "evoforge" | "single"): { passed: number; n: number } | null {
  const h = doc?.lanes?.[side]?.heldout;
  return h && Number.isInteger(h.passed) && Number.isInteger(h.n) && h.n > 0 ? { passed: h.passed, n: h.n } : null;
}
