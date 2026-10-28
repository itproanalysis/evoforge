"use client";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  type EvolutionPublic,
  getEvolution,
  listEvolutions,
  promoteEvolution,
  runEvolution,
  startEvolution,
  stepEvolution,
} from "../../../lib/api";
import { Button, Input, Card } from "../../../components/ui";
import { getErrorMessageKey } from "../../../lib/apiErrors";

function fitnessBar(score: number) {
  const pct = Math.max(0, Math.min(130, score));
  return (
    <div style={{ background: "#0b0e14", borderRadius: 6, height: 8, minWidth: 120 }}>
      <div
        style={{
          width: `${Math.min(100, (pct / 130) * 100)}%`,
          height: 8,
          borderRadius: 6,
          background: score >= 100 ? "#34d399" : score >= 30 ? "#fbbf24" : "#f87171",
        }}
      />
    </div>
  );
}

export default function Evolution() {
  const t = useTranslations("evolution");
  const tErrors = useTranslations("errors");
  const [goal, setGoal] = useState("");
  const [repo, setRepo] = useState("");
  const [maxGen, setMaxGen] = useState(3);
  const [pop, setPop] = useState(2);
  const [useMem, setUseMem] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [evos, setEvos] = useState<EvolutionPublic[]>([]);
  const [selected, setSelected] = useState<EvolutionPublic | null>(null);

  const refresh = async (id?: string) => {
    try {
      const list = await listEvolutions();
      setEvos(list.evolutions ?? []);
      const target = id ?? selected?.evolution_id ?? list.evolutions?.[0]?.evolution_id;
      if (target) setSelected(await getEvolution(target));
    } catch (e) {
      setErr(tErrors(getErrorMessageKey(e)));
    }
  };

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selected) return;
    if (!(selected.run_active || selected.status === "RUNNING")) return;
    // Poll GET /v1/evolution/{id} every 3 s while run_active or status RUNNING,
    // updating the generation timeline live.
    const id = setInterval(() => void refresh(selected.evolution_id), 3000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.evolution_id, selected?.status, selected?.run_active]);

  const act = async (kind: string, fn: () => Promise<unknown>, id?: string) => {
    setBusy(kind);
    setErr("");
    try {
      await fn();
      await refresh(id);
    } catch (e) {
      setErr(`${kind}: ${tErrors(getErrorMessageKey(e))}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <h1>{t("heading")}</h1>
      <p style={{ color: "#8b93a7" }}>{t("description")}</p>

      <Card>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <Input
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder={t("goal-placeholder")}
            style={{ flex: "2 1 260px" }}
          />
          <Input
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            placeholder={t("repo-placeholder")}
            style={{ flex: "1 1 160px" }}
          />
          <label>
            {t("max-gen")} <Input type="number" value={maxGen} min={1} max={10}
              onChange={(e) => setMaxGen(Number(e.target.value) || 3)} style={{ width: 64 }} />
          </label>
          <label>
            {t("population")} <Input type="number" value={pop} min={1} max={5}
              onChange={(e) => setPop(Number(e.target.value) || 2)} style={{ width: 64 }} />
          </label>
          <label style={{ fontSize: 13 }}>
            <input type="checkbox" checked={useMem} onChange={(e) => setUseMem(e.target.checked)} /> {t("use-memory")}
          </label>
          <Button disabled={busy !== null || !goal.trim()}
            onClick={() => void act("start", async () => {
              const r = await startEvolution(goal, "HEAD", maxGen, pop, useMem, repo.trim());
              setGoal("");
              await refresh(r.evolution_id);
            })}>
            {busy === "start" ? t("starting") : t("start")}
          </Button>
        </div>
        {err && <p style={{ color: "#f87171" }}>{err}</p>}
      </Card>

      <div style={{ display: "flex", gap: 16, marginTop: 16, flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 220px" }}>
        <Card>
          <h3>{t("runs-heading")}</h3>          {evos.length === 0 && <p style={{ color: "#8b93a7" }}>{t("empty")}</p>}
          {evos.map((e) => (
            <div key={e.evolution_id} style={{ marginBottom: 8 }}>
              <Button variant={selected?.evolution_id === e.evolution_id ? "primary" : "ghost"}
                onClick={() => void act("select", async () => setSelected(await getEvolution(e.evolution_id)), e.evolution_id)}>
                {e.evolution_id.slice(0, 12)} · {e.status}
              </Button>
            </div>
          ))}
        </Card>
        </div>

        <div style={{ flex: "3 1 420px" }}>
        <Card>
          {!selected && <p style={{ color: "#8b93a7" }}>{t("select-hint")}</p>}
          {selected && (
            <div>
              <h3>{selected.evolution_id} <span style={{ fontSize: 12, background: "#263048", padding: "2px 8px", borderRadius: 12 }}>{selected.status}</span></h3>
              <p>{selected.goal}</p>
              {selected.run_active && <p style={{ color: "#fbbf24", fontSize: 13 }}>{t("run-active")}</p>}
              {selected.run_error && <p style={{ color: "#f87171", fontSize: 13 }}>{t("run-error")}: {selected.run_error}</p>}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
                <Button disabled={busy !== null || selected.status !== "RUNNING"}
                  onClick={() => void act("step", () => stepEvolution(selected.evolution_id), selected.evolution_id)}>
                  {busy === "step" ? t("working") : t("step")}
                </Button>
                <Button disabled={busy !== null || selected.status !== "RUNNING"}
                  onClick={() => void act("run", async () => {
                    // POST /v1/evolution/{id}/run starts a background run (202);
                    // the 3 s poll above refreshes GET /v1/evolution/{id} live.
                    await runEvolution(selected.evolution_id);
                    await refresh(selected.evolution_id);
                  }, selected.evolution_id)}>
                  {busy === "run" ? t("working") : t("run-all")}
                </Button>
                <Button disabled={busy !== null || !selected.best?.run_evidence_id}
                  onClick={() => void act("promote", () => promoteEvolution(selected.evolution_id), selected.evolution_id)}>
                  {busy === "promote" ? t("working") : t("promote")}
                </Button>
                {selected.best?.run_evidence_id && (
                  <a href={`/evidence?id=${selected.best.run_evidence_id}`}>Evidence →</a>
                )}
                {selected.best?.run_evidence_id && (
                  <a href={`/verify/${selected.best.run_evidence_id}`}>{t("proof-link")}</a>
                )}
              </div>
              {selected.generations.map((g) => (
                <div key={g.index} style={{ borderTop: "1px solid #263048", paddingTop: 8, marginTop: 8 }}>
                  <strong>Gen {g.index}</strong> {g.converged ? "✅ CONVERGED" : "…"}
                  {g.candidates.map((c, i) => (
                    <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 12 }}>cand {i}</span>
                      {fitnessBar(c.fitness?.score ?? 0)}
                      <span style={{ fontSize: 12 }}>{(c.fitness?.score ?? 0).toFixed(1)} pts</span>
                      <span style={{ fontSize: 12, color: "#8b93a7" }}>
                        {(c.gates ?? []).map((gg) => `${gg.gate}=${gg.result}`).join(" ")}
                        {c.candidate_error ? ` · ${c.candidate_error.slice(0, 120)}` : ""}
                      </span>
                      {c.run_evidence_id && (
                        <a style={{ fontSize: 12 }} href={`/verify/${c.run_evidence_id}`}>proof</a>
                      )}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </Card>
        </div>
      </div>
    </div>
  );
}
