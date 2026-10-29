"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  getEvolutionRun,
  listEvolutionRuns,
  type EvolutionRunSummary,
} from "../../../lib/api";
import { RoundReplay } from "../../../components/RoundReplay";
import { watchReplaySelection, type ReplaySelection } from "../../../lib/replaySelection";
import { AgentPanel } from "../../../components/AgentPanel";
import { CommandBar } from "../../../components/CommandBar";
import { EvolutionStats } from "../../../components/EvolutionStats";
import { StrategiesPanel } from "../../../components/StrategiesPanel";

export default function ReplayPage() {
  const t = useTranslations("replay");
  const tCommon = useTranslations("common");
  const [runs, setRuns] = useState<EvolutionRunSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selection, setSelection] = useState<ReplaySelection | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState(false);
  const [listAttempt, setListAttempt] = useState(0);
  const [loadAttempt, setLoadAttempt] = useState(0);
  // Hide the prior run immediately, even before the selection effect runs.
  const current = selection?.runId === selectedId ? selection : null;
  const selected = current?.status === "ready" ? current.run : null;

  useEffect(() => {
    let cancelled = false;
    setListLoading(true);
    setListError(false);
    (async () => {
      try {
        const res = await listEvolutionRuns();
        if (cancelled) return;
        const list = Array.isArray(res.runs) ? res.runs : [];
        setRuns(list);
        setSelectedId((id) => list.some((run) => run.run_id === id) ? id : list[0]?.run_id ?? null);
      } catch {
        if (!cancelled) setListError(true);
      } finally {
        if (!cancelled) setListLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [listAttempt]);

  useEffect(() => {
    if (!selectedId) {
      setSelection(null);
      return;
    }
    return watchReplaySelection(selectedId, getEvolutionRun, setSelection);
  }, [selectedId, loadAttempt]);

  // A run started from the command bar: reload the list (it will include the new run) and select it.
  const handleStarted = (runId: string) => {
    setSelectedId(runId);
    setListAttempt((n) => n + 1);
  };

  return (
    <div>
      <h1>{t("title")}</h1>
      <EvolutionStats />
      <StrategiesPanel />
      {listError && <p role="alert" style={{ color: "#f87171" }}>
        {t("load-failed")} <button type="button" onClick={() => setListAttempt((n) => n + 1)}>{t("retry")}</button>
      </p>}
      {listLoading ? <p role="status">{tCommon("loading")}</p> : !listError && runs.length === 0 ? (
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
            {current?.status === "error" && <p role="alert" style={{ color: "#f87171" }}>
              {t("load-failed")} <button type="button" onClick={() => setLoadAttempt((n) => n + 1)}>{t("retry")}</button>
            </p>}
            {current?.status === "ready" && current.refreshError !== undefined && <p role="alert" style={{ color: "#fbbf24" }}>
              {t("refresh-failed")} <button type="button" onClick={() => setLoadAttempt((n) => n + 1)}>{t("retry")}</button>
            </p>}
            {selected ? (
              <>
                <RoundReplay key={selected.run_id} run={selected} />
                <AgentPanel run={selected} />
              </>
            ) : selectedId && current?.status !== "error" ? (
              <p role="status" style={{ color: "#8b93a7" }}>{tCommon("loading")}</p>
            ) : null}
          </div>
        </div>
      )}
      <CommandBar onStarted={handleStarted} />
    </div>
  );
}
