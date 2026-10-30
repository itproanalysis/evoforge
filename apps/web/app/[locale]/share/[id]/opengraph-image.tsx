import { ImageResponse } from "next/og";
import { fetchArenaForPreview, laneScore } from "../../../../lib/serverArena";

// The picture a chat app or social post shows for a shared result: the verdict, both hidden-test
// scores as bars and the costs, read from the stored match. Text stays in Latin script because the
// bundled image font has no Korean glyphs; a prompt in another script is left out rather than garbled.
export const alt = "EvoForge match result";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const VERDICT: Record<string, string> = {
  evoforge: "EvoForge wins",
  single: "Single AI call wins",
  tie: "Tie",
  inconclusive: "Needs another check",
  unscorable: "Not scorable",
};

export default async function Image({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const doc = await fetchArenaForPreview(id);
  const evo = laneScore(doc, "evoforge");
  const single = laneScore(doc, "single");
  const winner = doc?.verdict?.winner ?? "";
  const headline = VERDICT[winner] ?? "Same model, two builds, hidden tests decide";
  const rawPrompt = (doc?.prompt || doc?.goal || "").replace(/\s+/g, " ").trim();
  const prompt = /^[\x20-\x7E]*$/.test(rawPrompt) ? (rawPrompt.length > 110 ? `${rawPrompt.slice(0, 107)}...` : rawPrompt) : "";
  const cost = (side: "evoforge" | "single") => {
    const c = doc?.lanes?.[side]?.cost_cents;
    return Number.isInteger(c) ? `${c} cents` : "";
  };
  const lane = (label: string, s: { passed: number; n: number } | null, color: string, track: string, costText: string) => (
    <div style={{ display: "flex", flexDirection: "column", width: "100%", marginTop: 28 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
        <span style={{ fontSize: 30, fontWeight: 700, color: "#333d4b" }}>{label}</span>
        <span style={{ display: "flex", alignItems: "flex-end", gap: 16 }}>
          <span style={{ fontSize: 22, color: "#8b95a1" }}>{costText}</span>
          <span style={{ fontSize: 56, fontWeight: 800, color }}>{s ? `${s.passed}/${s.n}` : "-"}</span>
        </span>
      </div>
      <div style={{ display: "flex", marginTop: 10, height: 18, borderRadius: 9, background: track, width: "100%" }}>
        <div style={{ display: "flex", height: 18, borderRadius: 9, background: color, width: `${s ? Math.round((100 * s.passed) / s.n) : 0}%` }} />
      </div>
    </div>
  );
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", padding: 48, background: "#f2f4f6" }}>
        <div style={{ display: "flex", flexDirection: "column", width: "100%", height: "100%", padding: "48px 56px", background: "#ffffff", borderRadius: 40 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 26, fontWeight: 800, color: "#191f28" }}>EvoForge</span>
            <span style={{ fontSize: 20, fontWeight: 700, color: "#1b64da", background: "#e8f3ff", padding: "8px 18px", borderRadius: 999 }}>Hidden tests decide · signed result</span>
          </div>
          <div style={{ display: "flex", marginTop: 28, height: 76, alignItems: "center", fontSize: 60, fontWeight: 800, letterSpacing: -2, color: winner === "evoforge" ? "#0a8a5a" : winner === "single" ? "#1b64da" : "#191f28" }}>{headline}</div>
          {prompt ? <div style={{ display: "flex", marginTop: 12, fontSize: 26, lineHeight: 1.35, color: "#6b7684" }}>{prompt}</div> : null}
          {lane("EvoForge", evo, "#12a66e", "#e8f8f1", cost("evoforge"))}
          {lane("Single AI call", single, "#3182f6", "#eaf2fe", cost("single"))}
        </div>
      </div>
    ),
    size,
  );
}
