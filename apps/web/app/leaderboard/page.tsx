"use client";
import { useEffect, useState } from "react";
import { type LeaderEntry, type MemoryPattern, getLeaderboard, getMemory } from "../../lib/api";

const card: React.CSSProperties = {
  background: "#141b2d", border: "1px solid #263048",
  borderRadius: 10, padding: 14, marginTop: 16,
};

export default function LeaderboardPage() {
  const [leaders, setLeaders] = useState<LeaderEntry[]>([]);
  const [patterns, setPatterns] = useState<MemoryPattern[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    getLeaderboard().then((r) => setLeaders(r.leaders ?? [])).catch((e) => setErr(String(e)));
    getMemory().then((r) => setPatterns(r.patterns ?? [])).catch((e) => setErr(String(e)));
  }, []);

  return (
    <main style={{ maxWidth: 1080, margin: "0 auto", padding: 24, color: "#e8edf5", background: "#0b0e14", minHeight: "100vh" }}>
      <nav style={{ display: "flex", gap: 12, fontSize: 13 }}>
        <a href="/">Mission Control</a><a href="/evolution">Autopilot</a><a href="/evidence">Evidence</a>
        <a href="/leaderboard"><strong>Leaderboard</strong></a>
      </nav>
      <h1>Trust leaderboard</h1>
      <p style={{ color: "#8b93a7" }}>Ranked by verified fixes with proof links — prestige is earned, never claimed.</p>
      {err && <p style={{ color: "#f87171" }}>{err}</p>}
      <div style={card}>
        <h3>Verified wins ({leaders.length})</h3>
        {leaders.length === 0 && <p style={{ color: "#8b93a7" }}>No converged evolutions yet.</p>}
        {leaders.map((l, i) => (
          <div key={l.evolution_id} style={{ borderTop: "1px solid #263048", padding: "8px 0", fontSize: 13 }}>
            <strong>#{i + 1}</strong> {l.goal.slice(0, 90)} · score {l.best_score.toFixed(1)} · {l.generations_used} gen
            {l.proof_evidence_id ? <span> · <a href={`/verify/${l.proof_evidence_id}`}>proof</a></span> : null}
          </div>
        ))}
      </div>
      <div style={card}>
        <h3>Factory memory ({patterns.length} patterns — digests only, no code)</h3>
        {patterns.map((p) => (
          <div key={p.pattern_id} style={{ fontSize: 12, color: "#8b93a7", marginTop: 4 }}>
            {p.pattern_id.slice(0, 12)} · {(p.keywords ?? []).slice(0, 8).join(", ")} · fitness {p.fitness_score.toFixed(1)}
            {p.proof_evidence_id ? <span> · <a href={`/verify/${p.proof_evidence_id}`}>proof</a></span> : null}
          </div>
        ))}
      </div>
    </main>
  );
}
