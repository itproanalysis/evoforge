"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  getEvolutionRun,
  listEvolutionRuns,
  type EvolutionRun,
  type EvolutionRunSummary,
} from "../../../lib/api";
import { RoundReplay } from "../../../components/RoundReplay";

export default function ReplayPage() {
  const t = useTranslations("replay");
  const [runs, setRuns] = useState<EvolutionRunSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<EvolutionRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await listEvolutionRuns();
        if (cancelled) return;
        const list = Array.isArray(res.runs) ? res.runs : [];
        setRuns(list);
        if (list.length > 0) setSelectedId(list[0].run_id);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "failed to list runs");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    (async () => {
      try {
        const doc = await getEvolutionRun(selectedId);
        if (!cancelled) setSelected(doc);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "failed to load run");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  useEffect(() => {
    if (!selected || selected.status !== "running") return;
    const id = setInterval(async () => {
      try {
        const doc = await getEvolutionRun(selected.run_id);
        setSelected(doc);
      } catch {
        // keep the last snapshot while the run is still going
      }
    }, 5000);
    return () => clearInterval(id);
  }, [selected?.run_id, selected?.status]);

  return (
    <div>
      <h1>{t("title")}</h1>
      {error && <p style={{ color: "#f87171" }}>{error}</p>}
      {runs.length === 0 ? (
        <p style={{ color: "#8b93a7" }}>{t("empty")}</p>
      ) : (
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 12 }}>
          <div style={{ flex: "1 1 200px" }}>
            {runs.map((r) => (
              <div key={r.run_id} style={{ marginBottom: 8 }}>
                <button
                  type="button"
                  onClick={() => setSelectedId(r.run_id)}
                  style={{
                    fontWeight: selectedId === r.run_id ? 700 : 400,
                    cursor: "pointer",
                  }}
                >
                  {(r.title ?? r.run_id).slice(0, 48)} · {r.status ?? "—"}
                </button>
              </div>
            ))}
          </div>
          <div style={{ flex: "3 1 420px" }}>
            {selected ? (
              <RoundReplay key={selected.run_id} run={selected} />
            ) : (
              <p style={{ color: "#8b93a7" }}>{t("empty")}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
