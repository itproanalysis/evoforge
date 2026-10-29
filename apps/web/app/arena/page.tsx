"use client";

import { useEffect, useState } from "react";
import { getArena, listArenas, postArena, type ArenaDoc } from "../../lib/api";
import { laneView, arenaVerdict, costLabel } from "../../lib/arenaStatus";

const card: React.CSSProperties = {
  background: "#141b2d",
  border: "1px solid #263048",
  borderRadius: 10,
  padding: 16,
  marginTop: 16,
};

export default function ArenaRootPage() {
  const [arenas, setArenas] = useState<ArenaDoc[]>([]);
  const [selected, setSelected] = useState<ArenaDoc | null>(null);

  useEffect(() => {
    listArenas().then((res) => {
      if (res && res.arenas) {
        setArenas(res.arenas);
        if (res.arenas.length > 0) setSelected(res.arenas[0]);
      }
    }).catch(console.warn);
  }, []);

  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: 24, color: "#e8edf5", background: "#0b0e14", minHeight: "100vh" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #263048", paddingBottom: 16 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: "bold", margin: 0 }}>⚔️ EvoForge Arena (Live)</h1>
          <p style={{ fontSize: 13, color: "#8b93a7", margin: "4px 0 0 0" }}>Two lanes on the same sealed benchmark task: EvoForge vs Single AI</p>
        </div>
        <nav style={{ display: "flex", gap: 12, fontSize: 13 }}>
          <a href="/" style={{ color: "#8b93a7" }}>Mission Control</a>
          <a href="/arena" style={{ color: "#10b981", fontWeight: "bold" }}>Arena</a>
          <a href="/performance" style={{ color: "#8b93a7" }}>Performance</a>
          <a href="/evolution" style={{ color: "#8b93a7" }}>Autopilot</a>
        </nav>
      </header>

      {selected && (
        <div style={{ marginTop: 20 }}>
          <div style={card}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontSize: 13, fontWeight: "bold", color: "#10b981" }}>Task: {selected.task_id} ({selected.suite_version})</span>
              <span style={{ fontSize: 12, color: "#8b93a7" }}>Verdict: <strong>{arenaVerdict(selected)?.winner ?? (selected.verdict?.winner === "inconclusive" ? "verification inconclusive" : "pending")}</strong></span>
            </div>
            <p style={{ fontSize: 14, marginTop: 8 }}>{selected.goal}</p>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 16 }}>
            <div style={{ ...card, borderColor: "#10b981" }}>
              <h3 style={{ color: "#10b981", marginTop: 0 }}>EvoForge Pipeline (Harness /2)</h3>
              <p style={{ fontSize: 13 }}>Status: <strong>{selected.lanes?.evoforge?.status}</strong></p>
              <p style={{ fontSize: 13 }}>Heldout: <strong>{laneView(selected.lanes?.evoforge).score ?? "pending / unverified"}</strong></p>
              <p style={{ fontSize: 13 }}>{costLabel(laneView(selected.lanes?.evoforge).costState)}: <strong>{laneView(selected.lanes?.evoforge).cost === null ? "—" : `${laneView(selected.lanes?.evoforge).cost}¢`}</strong> · Attempts: <strong>{laneView(selected.lanes?.evoforge).attempts ?? "—"}</strong></p>
              {laneView(selected.lanes?.evoforge).status === "failed" && <p>Failed: {laneView(selected.lanes?.evoforge).error || "reason unavailable"}</p>}
              <pre style={{ background: "#06090e", padding: 12, borderRadius: 6, fontSize: 11, overflowX: "auto", maxHeight: 200, color: "#a7f3d0" }}>
                {selected.lanes?.evoforge?.diff || "// No patch"}
              </pre>
            </div>

            <div style={{ ...card, borderColor: "#3b82f6" }}>
              <h3 style={{ color: "#60a5fa", marginTop: 0 }}>Single AI (Harness /1, 1 attempt)</h3>
              <p style={{ fontSize: 13 }}>Status: <strong>{selected.lanes?.single?.status}</strong></p>
              <p style={{ fontSize: 13 }}>Heldout: <strong>{laneView(selected.lanes?.single).score ?? "pending / unverified"}</strong></p>
              <p style={{ fontSize: 13 }}>{costLabel(laneView(selected.lanes?.single).costState)}: <strong>{laneView(selected.lanes?.single).cost === null ? "—" : `${laneView(selected.lanes?.single).cost}¢`}</strong> · Attempts: <strong>{laneView(selected.lanes?.single).attempts ?? "—"}</strong></p>
              {laneView(selected.lanes?.single).status === "failed" && <p>Failed: {laneView(selected.lanes?.single).error || "reason unavailable"}</p>}
              <pre style={{ background: "#06090e", padding: 12, borderRadius: 6, fontSize: 11, overflowX: "auto", maxHeight: 200, color: "#93c5fd" }}>
                {selected.lanes?.single?.diff || "// No patch"}
              </pre>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
