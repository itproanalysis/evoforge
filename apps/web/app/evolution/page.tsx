"use client";
import { useEffect, useState } from "react";
import {
  type EvolutionPublic, getEvolution, listEvolutions, promoteEvolution,
  runEvolution, startEvolution, stepEvolution,
} from "../../lib/api";

const card: React.CSSProperties = {
  background: "#141b2d", border: "1px solid #263048",
  borderRadius: 10, padding: 14, marginTop: 16,
};

export default function EvolutionPage() {
  const [goal, setGoal] = useState("");
  const [repo, setRepo] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [evos, setEvos] = useState<EvolutionPublic[]>([]);
  const [sel, setSel] = useState<EvolutionPublic | null>(null);

  const refresh = async (id?: string) => {
    const list = await listEvolutions();
    setEvos(list.evolutions ?? []);
    const target = id ?? sel?.evolution_id ?? list.evolutions?.[0]?.evolution_id;
    if (target) setSel(await getEvolution(target));
  };

  useEffect(() => { void refresh().catch((e) => setErr(String(e))); }, []);

  const act = async (kind: string, fn: () => Promise<unknown>, id?: string) => {
    setBusy(kind); setErr("");
    try { await fn(); await refresh(id); }
    catch (e) { setErr(`${kind}: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setBusy(null); }
  };

  return (
    <main style={{ maxWidth: 1080, margin: "0 auto", padding: 24, color: "#e8edf5", background: "#0b0e14", minHeight: "100vh" }}>
      <nav style={{ display: "flex", gap: 12, fontSize: 13 }}>
        <a href="/">Mission Control</a><a href="/lab">Lab</a><a href="/evidence">Evidence</a>
        <a href="/performance">Performance</a><a href="/evolution"><strong>Autopilot</strong></a>
      </nav>
      <h1>Autopilot — goal in, verified PR out</h1>
      <p style={{ color: "#8b93a7" }}>Autonomous evolution: breeds candidates, scores with the trust kernel, retries with Critic feedback.</p>
      <div style={card}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="Fix flaky login retry"
            style={{ flex: "2 1 260px", padding: 8, borderRadius: 6, background: "#0b0e14", color: "#e8edf5", border: "1px solid #33405c" }} />
          <input value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="source_repo (optional)"
            style={{ flex: "1 1 160px", padding: 8, borderRadius: 6, background: "#0b0e14", color: "#e8edf5", border: "1px solid #33405c" }} />
          <button disabled={busy !== null || !goal.trim()}
            onClick={() => void act("start", async () => {
              const r = await startEvolution(goal, "HEAD", 3, 2, true, repo.trim()); setGoal(""); await refresh(r.evolution_id);
            })}>Start evolution</button>
        </div>
        {err && <p style={{ color: "#f87171" }}>{err}</p>}
      </div>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <div style={{ ...card, flex: "1 1 200px" }}>
          <h3>Runs</h3>
          {evos.map((e) => (
            <div key={e.evolution_id} style={{ marginBottom: 6 }}>
              <button onClick={() => void act("select", async () => setSel(await getEvolution(e.evolution_id)), e.evolution_id)}>
                {e.evolution_id.slice(0, 12)} · {e.status}
              </button>
            </div>
          ))}
        </div>
        <div style={{ ...card, flex: "3 1 420px" }}>
          {!sel && <p style={{ color: "#8b93a7" }}>Start an evolution or pick a run.</p>}
          {sel && (
            <div>
              <h3>{sel.evolution_id} [{sel.status}]</h3>
              <p>{sel.goal}</p>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button disabled={busy !== null || sel.status !== "RUNNING"}
                  onClick={() => void act("step", () => stepEvolution(sel.evolution_id), sel.evolution_id)}>Step 1 gen</button>
                <button disabled={busy !== null || sel.status !== "RUNNING"}
                  onClick={() => void act("run", () => runEvolution(sel.evolution_id), sel.evolution_id)}>Run to end</button>
                <button disabled={busy !== null || !sel.best?.run_evidence_id}
                  onClick={() => void act("promote", () => promoteEvolution(sel.evolution_id), sel.evolution_id)}>Promote to PR</button>
                {sel.best?.run_evidence_id && <a href={`/verify/${sel.best.run_evidence_id}`}>Proof certificate →</a>}
              </div>
              {sel.generations.map((g) => (
                <div key={g.index} style={{ borderTop: "1px solid #263048", marginTop: 8, paddingTop: 8 }}>
                  <strong>Gen {g.index}</strong> {g.converged ? "✅" : "…"}
                  {g.candidates.map((c, i) => (
                    <div key={i} style={{ fontSize: 12, color: "#8b93a7", marginTop: 4 }}>
                      cand {i}: {((c.fitness?.score ?? 0)).toFixed(1)} pts · {(c.gates ?? []).map((gg) => `${gg.gate}=${gg.result}`).join(" ")}
                      {c.candidate_error ? ` · ${c.candidate_error.slice(0, 140)}` : ""}
                      {c.run_evidence_id ? <span> · <a href={`/verify/${c.run_evidence_id}`}>proof</a></span> : null}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
