"use client";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  getEvalJob,
  listDecisions,
  startAbTest,
  type Decision,
} from "../lib/api";
import { Button, Card } from "./ui";

const HARNESS_OPTIONS = ["api-sealed-eval/1", "api-sealed-eval/2"];
const SUITE_OPTIONS = ["v0", "v1", "v2"];
const KIND_OPTIONS = ["X_SINGLE", "PIPELINE"];

function shortHarness(version: string): string {
  const i = version.lastIndexOf("/");
  return i >= 0 ? version.slice(i) : version;
}

function clamp01(v: number): number {
  if (typeof v !== "number" || Number.isNaN(v)) return 0;
  return Math.min(1, Math.max(0, v));
}

function fmtPct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

function fmtInterval(iv: [number, number] | undefined): string {
  if (!iv || iv.length !== 2) return "—";
  return `${(iv[0] * 100).toFixed(1)}–${(iv[1] * 100).toFixed(1)}%`;
}

function IntervalBar({
  lo,
  hi,
  rate,
  color,
  label,
}: {
  lo: number;
  hi: number;
  rate: number;
  color: string;
  label: string;
}) {
  const left = clamp01(lo) * 100;
  const width = Math.max(0, clamp01(hi) - clamp01(lo)) * 100;
  const dot = clamp01(rate) * 100;
  return (
    <div className="flex items-center gap-1.5 min-w-0">
      <span className="text-xs text-text-secondary shrink-0 w-14 truncate" title={label}>
        {label}
      </span>
      <div
        role="img"
        aria-label={`${label} ${fmtPct(rate)} [${fmtInterval([lo, hi])}]`}
        className="relative flex-1 h-2 rounded bg-border min-w-0"
      >
        <div
          className="absolute top-0 h-2 rounded"
          style={{ left: `${left}%`, width: `${width}%`, backgroundColor: color }}
        />
        <div
          className="absolute rounded-full border border-background-primary"
          style={{
            left: `calc(${dot}% - 3px)`,
            top: "-2px",
            width: "8px",
            height: "8px",
            backgroundColor: color,
          }}
        />
      </div>
    </div>
  );
}

export function AdoptionHistory() {
  const t = useTranslations("performance");
  const [decisions, setDecisions] = useState<Decision[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [suite, setSuite] = useState("v2");
  const [kind, setKind] = useState("X_SINGLE");
  const [champion, setChampion] = useState(HARNESS_OPTIONS[0]);
  const [challenger, setChallenger] = useState(HARNESS_OPTIONS[1]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = async () => {
    try {
      const out = await listDecisions();
      setDecisions(out.decisions ?? []);
      setLoadError("");
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const jobActive = jobId !== null;

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    setJobId(null);
    setJobStatus("");
    setSubmitting(false);
  };

  const pollJob = (id: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(() => {
      void (async () => {
        try {
          const cur = await getEvalJob(id);
          setJobStatus(cur.status);
          if (cur.status === "succeeded") {
            stopPolling();
            setFormError("");
            await refresh();
          } else if (cur.status === "failed") {
            stopPolling();
            setFormError(cur.error ?? t("adoption.job-failed"));
          }
        } catch (e) {
          // Keep polling on transient failures.
        }
      })();
    }, 5000);
  };

  const submit = async () => {
    if (submitting || jobActive) return;
    setSubmitting(true);
    setFormError("");
    try {
      const started = await startAbTest({ suite_version: suite, kind, champion, challenger });
      setJobId(started.job_id);
      setJobStatus(started.status);
      try {
        const cur = await getEvalJob(started.job_id);
        setJobStatus(cur.status);
        if (cur.status === "succeeded") {
          stopPolling();
          await refresh();
          return;
        }
        if (cur.status === "failed") {
          stopPolling();
          setFormError(cur.error ?? t("adoption.job-failed"));
          return;
        }
      } catch {
        // Fall through to polling.
      }
      pollJob(started.job_id);
    } catch (e) {
      setSubmitting(false);
      setFormError(e instanceof Error ? e.message : String(e));
    }
  };

  const sorted = [...(decisions ?? [])].sort((a, b) => b.created_at - a.created_at);

  return (
    <Card className="mt-4 w-full max-w-full min-w-0">
      <div className="text-xs text-text-secondary">{t("adoption.heading")}</div>
      <form
        className="flex gap-2 flex-wrap mt-2 min-w-0"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label className="flex flex-col gap-1 text-xs text-text-secondary min-w-0 flex-[1_1_140px]">
          {t("adoption.suite-label")}
          <select
            aria-label={t("adoption.suite-label")}
            value={suite}
            onChange={(e) => setSuite(e.target.value)}
            disabled={submitting || jobActive}
            className="px-2 py-1.5 rounded border border-border bg-background-primary text-text-primary text-sm min-w-0 w-full"
          >
            {SUITE_OPTIONS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-secondary min-w-0 flex-[1_1_140px]">
          {t("adoption.kind-label")}
          <select
            aria-label={t("adoption.kind-label")}
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            disabled={submitting || jobActive}
            className="px-2 py-1.5 rounded border border-border bg-background-primary text-text-primary text-sm min-w-0 w-full"
          >
            {KIND_OPTIONS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-secondary min-w-0 flex-[1_1_140px]">
          {t("adoption.champion-label")}
          <select
            aria-label={t("adoption.champion-label")}
            value={champion}
            onChange={(e) => setChampion(e.target.value)}
            disabled={submitting || jobActive}
            className="px-2 py-1.5 rounded border border-border bg-background-primary text-text-primary text-sm min-w-0 w-full"
          >
            {HARNESS_OPTIONS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-secondary min-w-0 flex-[1_1_140px]">
          {t("adoption.challenger-label")}
          <select
            aria-label={t("adoption.challenger-label")}
            value={challenger}
            onChange={(e) => setChallenger(e.target.value)}
            disabled={submitting || jobActive}
            className="px-2 py-1.5 rounded border border-border bg-background-primary text-text-primary text-sm min-w-0 w-full"
          >
            {HARNESS_OPTIONS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-end min-w-0">
          <Button
            type="submit"
            variant="primary"
            size="sm"
            disabled={submitting || jobActive}
            loading={submitting || jobActive}
          >
            {submitting || jobActive ? t("adoption.running") : t("adoption.run")}
          </Button>
        </div>
      </form>
      {jobActive ? (
        <div className="text-xs text-text-secondary mt-1.5 break-words">
          {t("adoption.job-status")}: <code>{jobId}</code>
          {jobStatus ? ` · ${jobStatus}` : ""}
        </div>
      ) : null}
      {formError ? (
        <p role="alert" className="text-accent-red text-sm mt-1.5 break-words">
          {t("error-prefix")}
          {formError}
        </p>
      ) : null}
      <div className="mt-3 min-w-0">
        {decisions === null ? (
          <div className="text-sm text-text-secondary">{t("loading")}</div>
        ) : loadError && sorted.length === 0 ? (
          <p role="alert" className="text-accent-red text-sm break-words">
            {t("error-prefix")}
            {loadError}
          </p>
        ) : sorted.length === 0 ? (
          <div className="text-sm text-text-secondary">{t("adoption.empty")}</div>
        ) : (
          <div className="grid gap-2 min-w-0">
            {sorted.map((d, i) => {
              const champ = d.champion_measurement;
              const chall = d.challenger_measurement;
              const adopted = d.decision === "adopt";
              const key = String(
                (d.decision_id as string | undefined) ?? `${d.created_at}-${d.champion}-${d.challenger}-${i}`,
              );
              return (
                <div
                  key={key}
                  data-testid="adoption-row"
                  className="border border-border rounded-lg p-2.5 bg-background-primary text-sm min-w-0 break-words w-full max-w-full"
                >
                  <div className="flex justify-between items-start gap-2 flex-wrap min-w-0">
                    <div className="text-xs text-text-secondary min-w-0">
                      {new Date(d.created_at * 1000).toLocaleString()} · {d.suite_version} · {d.kind}
                    </div>
                    <span
                      data-testid={adopted ? "adoption-badge-adopt" : "adoption-badge-keep"}
                      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold shrink-0 ${
                        adopted
                          ? "bg-accent-green text-white"
                          : "bg-background-secondary border border-border text-text-secondary"
                      }`}
                    >
                      {adopted ? t("adoption.adopted") : t("adoption.kept")}
                    </span>
                  </div>
                  <div className="text-sm font-semibold mt-1 break-words">
                    {shortHarness(d.champion)} → {shortHarness(d.challenger)}
                    <span className="text-xs font-normal text-text-secondary ml-1.5">
                      {d.champion} → {d.challenger}
                    </span>
                  </div>
                  <div className="grid gap-1.5 mt-2 min-w-0">
                    <div className="min-w-0">
                      <div className="text-xs text-text-secondary break-words">
                        {shortHarness(d.champion)} · {fmtPct(champ.pass_rate)} · {champ.passed}/{champ.n} ·{" "}
                        {t("interval")} {fmtInterval(champ.wilson95)}
                      </div>
                      <IntervalBar
                        lo={champ.wilson95?.[0] ?? 0}
                        hi={champ.wilson95?.[1] ?? 0}
                        rate={champ.pass_rate}
                        color="#38bdf8"
                        label={shortHarness(d.champion)}
                      />
                    </div>
                    <div className="min-w-0">
                      <div className="text-xs text-text-secondary break-words">
                        {shortHarness(d.challenger)} · {fmtPct(chall.pass_rate)} · {chall.passed}/{chall.n}{" "}
                        · {t("interval")} {fmtInterval(chall.wilson95)}
                      </div>
                      <IntervalBar
                        lo={chall.wilson95?.[0] ?? 0}
                        hi={chall.wilson95?.[1] ?? 0}
                        rate={chall.pass_rate}
                        color="#22c55e"
                        label={shortHarness(d.challenger)}
                      />
                    </div>
                  </div>
                  <div className="text-xs text-text-secondary mt-1.5 break-words">
                    {t(`verdicts.${d.verdict}` as never)} · verdict={d.verdict} · decision={d.decision}
                    {d.reason ? ` · ${d.reason}` : ""}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Card>
  );
}

export default AdoptionHistory;
