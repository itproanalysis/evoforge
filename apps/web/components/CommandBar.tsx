"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  getEvolutionRun,
  listEvolutionApps,
  startEvolutionRun,
  type EvolutionAppSummary,
} from "../lib/api";
import { commandState } from "../lib/roundReplay";

type Props = {
  onStarted?: (runId: string) => void;
};

const STATE_KEY: Record<string, string> = {
  RECEIVED: "state-received",
  QUEUED: "state-queued",
  RUNNING: "state-running",
  APPLIED: "state-applied",
  REJECTED: "state-rejected",
  FAILED: "state-failed",
};

export function CommandBar({ onStarted }: Props) {
  const t = useTranslations("replay");
  const [apps, setApps] = useState<EvolutionAppSummary[]>([]);
  const [appId, setAppId] = useState<string>("");
  const [feedback, setFeedback] = useState<string>("critic");
  const [httpStatus, setHttpStatus] = useState<number | null>(null);
  const [runStatus, setRunStatus] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await listEvolutionApps();
        if (cancelled) return;
        const list = Array.isArray(res.apps) ? res.apps : [];
        setApps(list);
        if (list.length > 0) setAppId(list[0].app_id);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "failed to list apps");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const doc = await getEvolutionRun(runId);
        if (cancelled) return;
        setRunStatus(typeof doc.status === "string" ? doc.status : null);
      } catch {
        // keep the last known command state while polling
      }
    };
    void poll();
    const id = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [runId]);

  const cmd = commandState(httpStatus, runStatus);
  // Live runs spend the operator's model credits: only the operator build shows Start (public visitors see recorded runs).
  const operator = process.env.NEXT_PUBLIC_EVO_OPERATOR_CONTROLS === "1";

  const onStart = async () => {
    if (!appId || busy || !operator) return;
    if (typeof window !== "undefined" && !window.confirm(t("cost-warning"))) return;
    setBusy(true);
    setError(null);
    setHttpStatus(null);
    setRunStatus(null);
    try {
      const res = await startEvolutionRun(appId, feedback);
      setHttpStatus(res.status);
      const body =
        res.body && typeof res.body === "object"
          ? (res.body as { run_id?: unknown; status?: unknown })
          : null;
      const newId = typeof body?.run_id === "string" ? body.run_id : null;
      const st = typeof body?.status === "string" ? body.status : null;
      if (res.status === 202 && newId) {
        setRunId(newId);
        setRunStatus(st);
        onStarted?.(newId);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to start run");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="studio-command-bar">
      <div className="flex items-center gap-3 flex-wrap">
        <label className="text-xs flex items-center gap-1.5">
          {t("app-label")}
          <select
            value={appId}
            onChange={(e) => setAppId(e.target.value)}
            className="px-2 py-1 rounded text-xs border border-border bg-background-secondary cursor-pointer"
            aria-label={t("app-label")}
          >
            {apps.map((a) => (
              <option key={a.app_id} value={a.app_id}>
                {a.app_id}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs flex items-center gap-1.5">
          {t("feedback-label")}
          <select
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            className="px-2 py-1 rounded text-xs border border-border bg-background-secondary cursor-pointer"
            aria-label={t("feedback-label")}
          >
            <option value="critic">{t("feedback-critic")}</option>
            <option value="heldout">{t("feedback-heldout")} (upper bound)</option>
          </select>
        </label>
        <button
          type="button"
          onClick={onStart}
          disabled={busy || !appId || !operator}
          title={operator ? undefined : t("operator-only")}
          className="px-3.5 py-1.5 text-xs font-semibold text-white bg-accent-blue hover:bg-[#1b64da] disabled:bg-background-tertiary disabled:text-text-tertiary disabled:cursor-not-allowed cursor-pointer"
        >
          {t("start")}
        </button>
        <span
          className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border border-border bg-background-secondary"
          data-command-state={cmd.state}
        >
          {t(STATE_KEY[cmd.state] ?? "state-received")}
          {cmd.reason ? ` · ${cmd.reason}` : ""}
        </span>
        {error && <span style={{ color: "#f04452", fontSize: 12 }}>{error}</span>}
      </div>
      <p className="mt-1 text-xs text-text-secondary">{t("cost-warning")}</p>
      {!operator && <p className="mt-1 text-xs text-text-secondary">{t("operator-only")}</p>}
    </div>
  );
}

export default CommandBar;
