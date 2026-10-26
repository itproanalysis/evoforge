"use client";
import { useState } from "react";
import {
  API_BASE,
  type Candidate,
  type GateVerdict,
  postGenerate,
} from "../lib/api";

const card: React.CSSProperties = {
  background: "#141b2d",
  border: "1px solid #263048",
  borderRadius: 10,
  padding: 14,
  minWidth: 140,
  flex: "1 1 140px",
};

const label: React.CSSProperties = { fontSize: 12, color: "#8b96ad" };
const value: React.CSSProperties = {
  fontSize: 22,
  fontWeight: 700,
  marginTop: 4,
};

function gateColor(r: string) {
  if (r === "PASS") return "#22c55e";
  if (r === "FAIL") return "#ef4444";
  return "#f59e0b";
}

export default function MissionControl() {
  const [goal, setGoal] = useState("Fix flaky login retry");
  const [repoSha, setRepoSha] = useState("HEAD");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [commandId, setCommandId] = useState("");
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [gates, setGates] = useState<GateVerdict[]>([]);
  const [reserved, setReserved] = useState<number | null>(null);
  const [evidence, setEvidence] = useState<{ repo_sha: string; model: string } | null>(null);
  const [runs, setRuns] = useState(0);

  // Demo dashboard metrics (live API has no snapshot endpoint yet).
  const inconclusive = gates.some((g) => g.result === "INCONCLUSIVE");
  const failed = gates.filter((g) => g.result === "FAIL").length;
  const metrics = [
    { k: "Running seats", v: String(runs > 0 ? 1 : 0) },
    { k: "Waiting for human", v: inconclusive ? "1" : "0" },
    { k: "Active tasks", v: String(runs) },
    { k: "WVI", v: gates.length ? `${gates.filter((g) => g.result === "PASS").length}/${gates.length}` : "—" },
    { k: "Blocked merges", v: String(failed + (inconclusive ? 1 : 0)) },
    {
      k: "Spent (est.)",
      v: reserved == null ? "—" : `~${reserved}¢`,
      sub: "provider_billed 없음 → 추정치",
    },
    { k: "Bottleneck", v: inconclusive ? "human review" : failed ? "gate FAIL" : "—" },
  ];

  const run = async () => {
    setLoading(true);
    setErr("");
    try {
      const out = await postGenerate(goal, repoSha);
      setCommandId(out.command_id);
      setCandidate(out.candidate);
      setGates(out.gates ?? []);
      setReserved(out.budget_reserved_cents ?? null);
      setEvidence(out.evidence ?? null);
      setRuns((n) => n + 1);
      try {
        localStorage.setItem("evoforge.candidate", JSON.stringify(out.candidate));
        localStorage.setItem("evoforge.gates", JSON.stringify(out.gates ?? []));
        localStorage.setItem("evoforge.goal", JSON.stringify(goal));
      } catch {}
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main>
      <h1 style={{ margin: "4px 0 4px" }}>Mission Control</h1>
      <p style={{ color: "#8b96ad", fontSize: 13, marginTop: 0 }}>
        POST {API_BASE}/v1/commands/generate · Indie-track hackathon slice
      </p>
      <section style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        {metrics.map((m) => (
          <div key={m.k} style={card}>
            <div style={label}>{m.k}</div>
            <div style={value}>{m.v}</div>
            {m.sub ? <div style={{ ...label, marginTop: 4 }}>{m.sub}</div> : null}
          </div>
        ))}
      </section>

      <section style={{ ...card, marginTop: 16 }}>
        <div style={label}>Goal</div>
        <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
          <input
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            style={{ flex: "2 1 320px", padding: 8, borderRadius: 6, border: "1px solid #33405c", background: "#0b0e14", color: "#e8edf5" }}
          />
          <input
            value={repoSha}
            onChange={(e) => setRepoSha(e.target.value)}
            title="repo_sha"
            style={{ flex: "1 1 120px", padding: 8, borderRadius: 6, border: "1px solid #33405c", background: "#0b0e14", color: "#e8edf5" }}
          />
          <button
            onClick={run}
            disabled={loading || !goal.trim()}
            style={{ padding: "8px 16px", borderRadius: 6, background: "#2563eb", color: "#fff", border: 0, cursor: "pointer" }}
          >
            {loading ? "Generating…" : "Generate candidate"}
          </button>
        </div>
        {err ? <p style={{ color: "#ef4444" }}>Error: {err}</p> : null}
      </section>

      {commandId ? (
        <section style={{ ...card, marginTop: 16 }}>
          <div style={label}>command_id: {commandId}</div>
          {evidence ? (
            <div style={{ fontSize: 13, marginTop: 4 }}>
              evidence repo_sha=<code>{evidence.repo_sha}</code> model=<code>{evidence.model}</code>
            </div>
          ) : null}
          <h3>Gates</h3>
          {gates.length === 0 ? <p>no gates returned</p> : null}
          <ul style={{ listStyle: "none", padding: 0, display: "grid", gap: 8 }}>
            {gates.map((g, i) => (
              <li
                key={`${g.gate}-${i}`}
                style={{ border: "1px solid #263048", borderRadius: 8, padding: 10, background: "#0f1524" }}
              >
                <span
                  style={{
                    display: "inline-block",
                    padding: "2px 10px",
                    borderRadius: 20,
                    fontSize: 12,
                    fontWeight: 700,
                    color: "#0b0e14",
                    background: gateColor(g.result),
                    marginRight: 8,
                  }}
                >
                  {g.result}
                </span>
                <strong>{g.gate}</strong>
                {g.reason ? <div style={{ fontSize: 13, color: "#aeb9cf", marginTop: 4 }}>{g.reason}</div> : null}
              </li>
            ))}
          </ul>
          {inconclusive ? (
            <p style={{ color: "#f59e0b" }} title="예외 승인 필요">
              INCONCLUSIVE 게이트가 있어 머지가 차단됩니다 (예외 승인 필요).
            </p>
          ) : null}
          {candidate ? (
            <p>
              <a href="/lab" style={{ color: "#7db4ff" }}>
                Open in Improvement Lab →
              </a>{" "}
              <a href="/evidence" style={{ color: "#7db4ff", marginLeft: 12 }}>
                Evidence Timeline →
              </a>
            </p>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}
