"use client";
import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  API_BASE,
  getEvalJob,
  getEvalSuites,
  getPerformance,
  listEvalJobs,
  startEvalJob,
  type EvalJob,
  type EvalSuite,
  type MeasurementView,
  type PerformanceSnapshot,
} from "../../../lib/api";
import {
  comparisonProvenance,
  provenance,
  viewProvenance,
} from "../../../lib/performanceProvenance";
import { buildTimeline } from "../../../lib/evolutionTimeline";
import { EvolutionTimeline } from "../../../components/EvolutionTimeline";
import { Button, Card } from "../../../components/ui";

function fmtPct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

function fmtInterval(iv: [number, number] | undefined): string {
  if (!iv || iv.length !== 2) return "—";
  return `${(iv[0] * 100).toFixed(1)}–${(iv[1] * 100).toFixed(1)}%`;
}

function fmtCents(n: number | null | undefined): string {
  return typeof n === "number" ? `${n}¢` : "—";
}

function fmtDelta(pp: number | null): string {
  if (typeof pp !== "number") return "—";
  return `${pp > 0 ? "+" : ""}${pp.toFixed(1)}%p`;
}

type Translate = ReturnType<typeof useTranslations>;

function MeasureCard({
  t,
  title,
  kind,
  view,
  costPerSolved,
  evidenceHref,
}: {
  t: Translate;
  title: string;
  kind: string;
  view: MeasurementView | null;
  costPerSolved: number | null;
  evidenceHref: (id: string) => string;
}) {
  if (!view) {
    return (
      <Card className="flex-[1_1_220px] min-w-0">
        <div className="text-xs text-text-secondary">{title}</div>
        <div className="text-2xl font-bold mt-1">—</div>
        <div className="text-xs text-text-secondary mt-1">{t("loading")}</div>
      </Card>
    );
  }
  if (view.status !== "measured") {
    return (
      <Card className="flex-[1_1_220px] min-w-0">
        <div className="text-xs text-text-secondary">{title}</div>
        <div className="text-base font-bold mt-1">{t("not-measured")}</div>
        <div className="text-sm text-text-secondary mt-1">
          {view.reason || t("kind-not-measured", { kind })}
        </div>
      </Card>
    );
  }
  const rec = view.record;
  const rate = typeof view.pass_rate === "number" ? view.pass_rate : (rec?.pass_rate ?? 0);
  const evId = view.evidence_id ?? rec?.evidence_id;
  return (
    <Card className="flex-[1_1_220px] min-w-0">
      <div className="text-xs text-text-secondary">{title}</div>
      <div className="text-2xl font-bold mt-1">{fmtPct(rate)}</div>
      <div className="text-xs text-text-secondary">
        {t(`provenance.${viewProvenance(view)}` as any)}
      </div>
      <div className="text-sm text-text-secondary mt-1">
        {view.passed ?? rec?.passed} / {view.n ?? rec?.n} · {t("interval")}{" "}
        {fmtInterval(view.wilson95 ?? rec?.wilson95)}
      </div>
      <div className="text-sm mt-1">
        {t("cost-per-solved")}: {fmtCents(costPerSolved)} · {t("total-cost")}:{" "}
        {fmtCents(view.cost_cents ?? rec?.cost_cents)}
      </div>
      <div className="text-xs text-text-secondary mt-1">
        {view.suite_version ?? rec?.suite_version} · {view.model ?? rec?.model} ·{" "}
        {view.harness_version ?? rec?.harness_version}
      </div>
      {evId ? (
        <div className="text-xs mt-1.5">
          {t("evidence")}:{" "}
          <a href={evidenceHref(evId)} className="text-accent-cyan hover:underline">
            <code>{evId}</code> →
          </a>
        </div>
      ) : null}
    </Card>
  );
}

export default function PerformancePage() {
  const t = useTranslations("performance");
  const locale = useLocale();
  const prefix = locale === "ko" ? "" : `/${locale}`;
  const evidenceHref = (id: string) => `${prefix}/evidence?id=${encodeURIComponent(id)}`;

  const [perf, setPerf] = useState<PerformanceSnapshot | null>(null);
  const [suites, setSuites] = useState<EvalSuite[]>([]);
  const [suiteVersion, setSuiteVersion] = useState<string>("v0");
  const [busy, setBusy] = useState<"baseline" | "pipeline" | null>(null);
  const [job, setJob] = useState<EvalJob | null>(null);
  const [jobError, setJobError] = useState("");
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState(false);
  const [autoPoll, setAutoPoll] = useState(true);
  const [lastUpdated, setLastUpdated] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const refreshingRef = useRef(false);

  const refresh = async () => {
    if (refreshingRef.current) return;
    refreshingRef.current = true;
    setSyncing(true);
    try {
      setPerf(await getPerformance());
      setSyncError(false);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch {
      // Keep the last good snapshot visible but never claim it is fresh.
      setSyncError(true);
    } finally {
      refreshingRef.current = false;
      setLoading(false);
      setSyncing(false);
    }
  };

  useEffect(() => {
    void refresh();
    getEvalSuites()
      .then((out) => {
        setSuites(out.suites ?? []);
        if (out.suite_version) setSuiteVersion(out.suite_version);
      })
      .catch(() => {});
    listEvalJobs()
      .then((out) => {
        const active = (out.jobs ?? []).find(
          (j) => j.status === "queued" || j.status === "running",
        );
        if (active) setJob(active);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!autoPoll && busy === null) return;
    const id = setInterval(() => {
      void refresh();
    }, busy !== null ? 3000 : 5000);
    return () => clearInterval(id);
  }, [autoPoll, busy]);

  const jobActive = job !== null && (job.status === "queued" || job.status === "running");

  useEffect(() => {
    if (!jobActive || !job) return;
    const id = setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => clearInterval(id);
  }, [jobActive, job?.job_id]);

  useEffect(() => {
    if (!job || (job.status !== "queued" && job.status !== "running")) return;
    const jobId = job.job_id;
    const id = setInterval(() => {
      void (async () => {
        try {
          const cur = await getEvalJob(jobId);
          setJob(cur);
          if (cur.status === "succeeded") {
            setJobError("");
            await refresh();
          } else if (cur.status === "failed") {
            setJobError(cur.error ?? "");
          }
        } catch {
          // Keep polling; a transient fetch failure must not drop the job.
        }
      })();
    }, 5000);
    return () => clearInterval(id);
  }, [job?.job_id, job?.status]);

  const runMeasure = async (kind: "baseline" | "pipeline") => {
    if (busy || jobActive) return;
    setBusy(kind);
    setErr("");
    setJobError("");
    try {
      const started = await startEvalJob(kind === "baseline" ? "X_SINGLE" : "PIPELINE");
      const cur = await getEvalJob(started.job_id);
      setJob(cur);
    } catch (e) {
      try {
        const listed = await listEvalJobs();
        const active = (listed.jobs ?? []).find(
          (j) => j.status === "queued" || j.status === "running",
        );
        if (active) {
          setJob(active);
          return;
        }
      } catch {
        // Fall through to the start error below.
      }
      const msg = e instanceof Error ? e.message : String(e);
      setErr(msg.includes("402") ? t(`budget-${kind}` as any, { detail: msg }) : msg);
    } finally {
      setBusy(null);
    }
  };

  const families = new Map<
    string,
    {
      suite?: EvalSuite;
      base?: { n: number; passed: number };
      pipe?: { n: number; passed: number };
    }
  >();
  for (const s of suites) families.set(s.family, { suite: s });
  const baseFam = perf?.baseline.record?.per_family ?? perf?.baseline.per_family;
  const pipeFam = perf?.pipeline.record?.per_family ?? perf?.pipeline.per_family;
  if (baseFam) {
    for (const [fam, v] of Object.entries(baseFam)) {
      families.set(fam, { ...(families.get(fam) ?? {}), base: v });
    }
  }
  if (pipeFam) {
    for (const [fam, v] of Object.entries(pipeFam)) {
      families.set(fam, { ...(families.get(fam) ?? {}), pipe: v });
    }
  }

  const history = perf?.history ?? [];
  const prod = perf?.production ?? null;
  const measured = perf?.comparison.status === "measured";
  const verdictKey =
    measured && perf?.comparison.verdict ? perf.comparison.verdict : "none";
  const attempts =
    perf?.pipeline.record?.attempts_total ?? perf?.pipeline.attempts_total;

  return (
    <main className="w-full">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="my-1 text-2xl font-bold">{t("heading")}</h1>
          <p className="text-text-secondary text-sm mt-0">
            GET {API_BASE}/v1/performance · {t("subtitle")}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-background-secondary border border-border text-text-secondary">
            <span
              className={`w-2 h-2 rounded-full ${
                syncing || syncError ? "bg-accent-amber" : "bg-accent-green"
              }`}
            />
            {syncError ? t("sync-error") : syncing ? t("syncing") : t("live")}
            {lastUpdated ? ` · ${t("last-updated")}: ${lastUpdated}` : ""}
          </span>
          <button
            onClick={() => setAutoPoll((v) => !v)}
            className={`px-2.5 py-1 rounded text-xs border transition-colors cursor-pointer ${
              autoPoll
                ? "bg-accent-blue text-white border-accent-blue"
                : "bg-background-secondary text-text-secondary border-border"
            }`}
          >
            {autoPoll ? t("auto-on") : t("auto-off")}
          </button>
          <Button onClick={() => void refresh()} variant="secondary" disabled={syncing}>
            {t("refresh")}
          </Button>
        </div>
      </div>

      <Card className="mt-4">
        <div className="text-xs text-text-secondary">{t("timeline.heading")}</div>
        {loading && !perf ? (
          <div className="text-sm text-text-secondary mt-1">{t("loading")}</div>
        ) : history.length === 0 ? (
          <div className="text-sm text-text-secondary mt-1">{t("timeline.empty")}</div>
        ) : (
          <div className="mt-2">
            <EvolutionTimeline timeline={buildTimeline(history)} />
          </div>
        )}
      </Card>

      <section className="flex gap-3 flex-wrap mt-4">
        <MeasureCard
          t={t}
          title={t("baseline-title")}
          kind="X_SINGLE"
          view={perf?.baseline ?? null}
          costPerSolved={perf?.cost_per_solved_cents.baseline ?? null}
          evidenceHref={evidenceHref}
        />
        <MeasureCard
          t={t}
          title={t("pipeline-title")}
          kind="PIPELINE"
          view={perf?.pipeline ?? null}
          costPerSolved={perf?.cost_per_solved_cents.pipeline ?? null}
          evidenceHref={evidenceHref}
        />
        <Card className="flex-[1_1_220px] min-w-0">
          <div className="text-xs text-text-secondary">{t("verdict-title")}</div>
          {loading && !perf ? (
            <div className="text-sm text-text-secondary mt-2">{t("loading")}</div>
          ) : measured && perf ? (
            <>
              <div className="text-2xl font-bold mt-1">
                {t(`verdicts.${verdictKey}` as any)}
              </div>
              <div className="text-xs text-text-secondary">
                {t(`provenance.${comparisonProvenance(perf.baseline, perf.pipeline)}` as any)}
              </div>
              <div className="text-sm text-text-secondary mt-1">
                {t("delta")} {fmtDelta(perf.comparison.delta_pp)} · verdict=
                {perf.comparison.verdict}
              </div>
            </>
          ) : (
            <>
              <div className="text-base font-bold mt-1">{t("not-measured")}</div>
              <div className="text-sm text-text-secondary mt-1">
                {perf?.comparison.reason || t("no-comparison")}
              </div>
            </>
          )}
        </Card>
      </section>

      <Card className="mt-4">
        <div className="text-xs text-text-secondary">{t("run-heading")}</div>
        <div className="flex gap-2 mt-2 flex-wrap">
          <Button
            onClick={() => void runMeasure("baseline")}
            disabled={busy !== null || jobActive}
            loading={busy === "baseline" || (jobActive && job?.kind === "X_SINGLE")}
            variant="primary"
          >
            {busy === "baseline" || (jobActive && job?.kind === "X_SINGLE") ? t("measuring") : t("run-baseline")}
          </Button>
          <Button
            onClick={() => void runMeasure("pipeline")}
            disabled={busy !== null || jobActive}
            loading={busy === "pipeline" || (jobActive && job?.kind === "PIPELINE")}
            variant="primary"
          >
            {busy === "pipeline" || (jobActive && job?.kind === "PIPELINE") ? t("measuring") : t("run-pipeline")}
          </Button>
        </div>
        {job ? (
          <div className="text-sm text-text-secondary mt-2 break-words">
            <div>
              {t("jobs.title")}: <code>{job.job_id}</code> · {t("jobs.status")}:{" "}
              {t(`jobs.${job.status}` as any)}
            </div>
            <div>
              {t("jobs.elapsed")}:{" "}
              {Math.max(0, Math.round(((job.finished_at ?? nowMs / 1000) - job.created_at) * 10) / 10)}s
            </div>
            {job.status === "failed" && (jobError || job.error) ? (
              <p role="alert" className="text-accent-red text-sm mt-1 break-words">
                {t("jobs.error")}: {jobError || job.error}
              </p>
            ) : null}
          </div>
        ) : null}
        {err ? (
          <p role="alert" className="text-accent-red text-sm mt-2 break-words">
            {t("error-prefix")}
            {err}
          </p>
        ) : null}
        {loading ? <p className="text-sm text-text-secondary">{t("loading")}</p> : null}
      </Card>

      <Card className="mt-4">
        <div className="text-xs text-text-secondary">
          {t("families-heading", { version: suiteVersion })}
        </div>
        {loading && !perf ? (
          <div className="text-sm text-text-secondary mt-1">{t("loading")}</div>
        ) : !baseFam && !pipeFam ? (
          <div className="text-sm text-text-secondary mt-1">
            {t("not-measured-short")} — {perf?.comparison.reason || t("families-empty")}
          </div>
        ) : null}
        {families.size > 0 ? (
          <div className="grid gap-2 mt-2">
            {[...families.entries()].map(([fam, v]) => (
              <div
                key={fam}
                className="border border-border rounded-lg p-2.5 bg-background-primary text-sm break-words"
              >
                <div className="flex justify-between flex-wrap gap-1.5">
                  <strong>{fam}</strong>
                  {v.suite ? (
                    <span className="text-xs text-text-secondary">
                      tasks={v.suite.task_count} · kinds: {v.suite.heldout_kinds.join(", ")}
                    </span>
                  ) : null}
                </div>
                <div className="text-text-secondary mt-1">
                  X_SINGLE: {v.base ? `${v.base.passed}/${v.base.n}` : "not_measured"} ·{" "}
                  PIPELINE: {v.pipe ? `${v.pipe.passed}/${v.pipe.n}` : "not_measured"}
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </Card>

      <Card className="mt-4">
        <div className="text-xs text-text-secondary">{t("history-heading")}</div>
        {loading && !perf ? (
          <div className="text-sm text-text-secondary mt-1">{t("loading")}</div>
        ) : history.length === 0 ? (
          <div className="text-sm text-text-secondary mt-1">
            {t("not-measured-short")} — {t("history-empty")}
          </div>
        ) : (
          <div className="grid gap-2 mt-2">
            {history.map((m) => {
              const pct = m.n > 0 ? Math.max(0, Math.min(100, (m.passed / m.n) * 100)) : 0;
              return (
                <div
                  key={m.measurement_id}
                  className="border border-border rounded-lg p-2.5 bg-background-primary text-sm min-w-0 break-words"
                >
                  <div className="flex justify-between flex-wrap gap-1.5">
                    <div>
                      <code>{m.kind}</code> {m.passed}/{m.n} ({fmtPct(m.pass_rate)}) ·{" "}
                      {fmtCents(m.cost_cents)}
                    </div>
                    {m.evidence_id ? (
                      <a
                        href={evidenceHref(m.evidence_id)}
                        className="text-accent-cyan text-xs hover:underline"
                      >
                        <code>{m.evidence_id}</code> →
                      </a>
                    ) : null}
                  </div>
                  <div className="h-2 rounded bg-border mt-1.5 w-full">
                    <div className="h-2 rounded bg-accent-green" style={{ width: `${pct}%` }} />
                  </div>
                  <div className="text-xs text-text-secondary mt-1">
                    {m.measurement_id} · {m.suite_version} · {m.model} ·{" "}
                    {t(`provenance.${provenance(m.provider_stub)}` as any)} ·{" "}
                    {new Date(m.created_at * 1000).toLocaleString()}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <Card className="mt-4">
        <div className="text-xs text-text-secondary">{t("production-heading")}</div>
        {loading && !perf ? (
          <div className="text-sm text-text-secondary mt-1">{t("loading")}</div>
        ) : !prod ? (
          <div className="text-sm text-text-secondary mt-1">
            {t("not-measured-short")} — {t("production-empty")}
          </div>
        ) : (
          <div className="text-sm mt-1 break-words">
            runs=<code>{prod.runs}</code> gate_pass=<code>{prod.gate_pass}</code>{" "}
            gate_fail=<code>{prod.gate_fail}</code> gate_inconclusive=
            <code>{prod.gate_inconclusive}</code> heldout=
            <code>
              {typeof prod.heldout_pass_rate_pct === "number"
                ? `${prod.heldout_pass_rate_pct.toFixed(1)}%`
                : "—"}
            </code>
            <div className="text-xs text-text-secondary mt-1">{prod.sample_note}</div>
          </div>
        )}
      </Card>

      <Card className="mt-4">
        <div className="text-xs text-text-secondary">{t("how-heading")}</div>
        <ul className="text-sm pl-5 mt-2 mb-0 list-disc break-words">
          <li>
            {t("how-suite", {
              suite:
                perf?.baseline.record?.suite_version ??
                perf?.pipeline.record?.suite_version ??
                suiteVersion,
            })}
            {suites.length > 0
              ? ` (${t("how-families", { families: suites.map((s) => s.family).join(", ") })})`
              : null}
          </li>
          <li>
            {t("how-n-model", {
              n:
                perf?.baseline.record?.n ??
                perf?.baseline.n ??
                perf?.pipeline.record?.n ??
                perf?.pipeline.n ??
                "—",
              model:
                perf?.baseline.record?.model ??
                perf?.pipeline.record?.model ??
                "muse-spark-1.3",
            })}
          </li>
          <li>
            {t("how-attempts")}
            {typeof attempts === "number" ? ` (${t("how-attempts-latest", { count: attempts })})` : null}
          </li>
          <li>{t("how-wilson")}</li>
          <li>{t("how-budget")}</li>
          <li>{t("how-storage", { storage: perf?.storage ?? "—" })}</li>
        </ul>
      </Card>
    </main>
  );
}
