"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  getEvolutionRun,
  listEvolutionRuns,
  type EvolutionRunSummary,
} from "../../../lib/api";
import { RoundReplay } from "../../../components/RoundReplay";
import { PresentationView } from "../../../components/PresentationView";
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
  const [presentRunId, setPresentRunId] = useState<string | null>(null);
  // Hide the prior run immediately, even before the selection effect runs.
  const current = selection?.runId === selectedId ? selection : null;
  const selected = current?.status === "ready" ? current.run : null;

  useEffect(() => {
    const update = () => {
      try {
        const q = new URLSearchParams(window.location.search);
        setPresentRunId(q.get("present") === "1" ? q.get("run") : null);
      } catch {
        setPresentRunId(null);
      }
    };
    update();
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);

  useEffect(() => {
    if (presentRunId) {
      setSelectedId((id) => (id === presentRunId ? id : presentRunId));
    }
  }, [presentRunId]);

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
        setSelectedId((id) => {
          try {
            const q = new URLSearchParams(window.location.search);
            const pr = q.get("present") === "1" ? q.get("run") : null;
            if (pr && list.some((run) => run.run_id === pr)) return pr;
            if (pr && id === pr) return pr;
          } catch {
            /* ignore */
          }
          return list.some((run) => run.run_id === id) ? id : list[0]?.run_id ?? null;
        });
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

  const handlePresent = (runId: string) => {
    const url = `?present=1&run=${encodeURIComponent(runId)}`;
    window.history.pushState(null, "", url);
    setPresentRunId(runId);
    setSelectedId(runId);
  };

  const handleExitPresent = () => {
    window.history.pushState(null, "", window.location.pathname);
    setPresentRunId(null);
  };

  if (presentRunId) {
    const presentRun = selected && selected.run_id === presentRunId ? selected : null;
    return (
      <div>
        {presentRun ? (
          <PresentationView run={presentRun} onExit={handleExitPresent} />
        ) : (
          <p role="status" style={{ color: "#6b7684" }}>{tCommon("loading")}</p>
        )}
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-5">{t("title")}</h1>
      <EvolutionStats />
      <StrategiesPanel />
      {listError && <p role="alert" style={{ color: "#f04452" }}>
        {t("load-failed")} <button type="button" onClick={() => setListAttempt((n) => n + 1)}>{t("retry")}</button>
      </p>}
      {listLoading ? <p role="status">{tCommon("loading")}</p> : !listError && runs.length === 0 ? (
        <p style={{ color: "#6b7684" }}>{t("empty")}</p>
      ) : (
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginTop: 20 }}>
          <div style={{ flex: "1 1 200px" }} className="studio-run-list">
            {runs.map((r) => (
              <button
                key={r.run_id}
                type="button"
                onClick={() => setSelectedId(r.run_id)}
                aria-pressed={selectedId === r.run_id}
              >
                <strong>{(r.title ?? r.run_id).slice(0, 48)}</strong>
                <span>{r.status ?? "—"}</span>
              </button>
            ))}
          </div>
          <div style={{ flex: "3 1 420px" }}>
            {current?.status === "error" && <p role="alert" style={{ color: "#f04452" }}>
              {t("load-failed")} <button type="button" onClick={() => setLoadAttempt((n) => n + 1)}>{t("retry")}</button>
            </p>}
            {current?.status === "ready" && current.refreshError !== undefined && <p role="alert" style={{ color: "#e88400" }}>
              {t("refresh-failed")} <button type="button" onClick={() => setLoadAttempt((n) => n + 1)}>{t("retry")}</button>
            </p>}
            {selected ? (
              <>
                <button type="button" className="studio-secondary-button" onClick={() => handlePresent(selected.run_id)}>
                  {t("present")}
                </button>
                <RoundReplay key={selected.run_id} run={selected} />
                <AgentPanel run={selected} />
              </>
            ) : selectedId && current?.status !== "error" ? (
              <p role="status" style={{ color: "#6b7684" }}>{tCommon("loading")}</p>
            ) : null}
          </div>
        </div>
      )}
      <CommandBar onStarted={handleStarted} />
    </div>
  );
}
