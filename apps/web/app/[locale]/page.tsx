"use client";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  API_BASE,
  type DashboardSnapshot,
  type LedgerSnapshot,
  type MissionDetail,
  type MissionState,
  type MissionSummary,
  type Outcome,
  type PerformanceSnapshot,
  getDashboard,
  getLedger,
  getMission,
  getPerformance,
  getParticipants,
  listMissions,
  listOutcomes,
  postMission,
  postMissionAdvance,
  postMissionCancel,
  postOutcome,
} from "../../lib/api";
import { Button, Input, Card, Badge } from "../../components/ui";
import { Error as ErrorComponent } from "../../components/ui/Error";
import { getErrorMessageKey } from "../../lib/apiErrors";
import { comparisonProvenance, provenance, viewProvenance } from "../../lib/performanceProvenance";

const TERMINAL: MissionState[] = ["PR_OPENED", "CANCELLED", "FAILED"];
const CHAIN: MissionState[] = ["GENERATED", "REVIEWED", "RAN", "PR_OPENED"];
const PIPELINE_STEPS: MissionState[] = [
  "CREATED",
  "GENERATED",
  "REVIEWED",
  "RAN",
  "PR_OPENED",
];

function round1(val: number): number {
  return Math.round(val * 10) / 10;
}

function formatRate(rate: number | null | undefined): string {
  return typeof rate === "number" && Number.isFinite(rate) ? `${round1(rate * 100)}%` : "—";
}

export default function MissionControl() {
  const t = useTranslations("mission-control");
  const tErrors = useTranslations("errors");

  const [goal, setGoal] = useState("");
  const [repoRef, setRepoRef] = useState("HEAD");
  const [busy, setBusy] = useState(false);
  const [recordingOutcome, setRecordingOutcome] = useState(false);
  const [mergedSha, setMergedSha] = useState("");
  const [outcomePrUrl, setOutcomePrUrl] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [autoPoll, setAutoPoll] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<string>("");
  const [syncError, setSyncError] = useState(false);
  const [err, setErr] = useState("");
  const [mission, setMission] = useState<MissionDetail | null>(null);
  const [missions, setMissions] = useState<MissionSummary[]>([]);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const [dashboard, setDashboard] = useState<DashboardSnapshot | null>(null);
  const [ledger, setLedger] = useState<LedgerSnapshot | null>(null);
  const [perf, setPerf] = useState<PerformanceSnapshot | null>(null);
  const [participants, setParticipants] = useState<Awaited<ReturnType<typeof getParticipants>> | null>(null);
  const stopRef = useRef(false);
  const selectedIdRef = useRef<string | null>(null);
  const refreshingRef = useRef(false);

  const refreshState = async (missionId: string | null) => {
    if (refreshingRef.current) return;
    refreshingRef.current = true;
    setSyncing(true);
    const targetId = missionId ?? selectedIdRef.current;
    try {
      const [dash, books, performance, history, recent, people] = await Promise.allSettled([
        getDashboard(), getLedger(), getPerformance(), listOutcomes(), listMissions(), getParticipants(),
      ]);
      if (dash.status === "fulfilled") setDashboard(dash.value);
      if (books.status === "fulfilled") setLedger(books.value);
      if (performance.status === "fulfilled") setPerf(performance.value);
      if (history.status === "fulfilled") setOutcomes(history.value.outcomes ?? []);
      if (people.status === "fulfilled") setParticipants(people.value);
      else setParticipants(null);
      const list = recent.status === "fulfilled" ? recent.value.missions ?? [] : [];
      if (recent.status === "fulfilled") setMissions(list);
      let failed = [dash, books, performance, history, recent].some((r) => r.status === "rejected");
      const idToLoad = targetId || (list.length > 0 ? list[0].mission_id : null);
      if (idToLoad && selectedIdRef.current === targetId) {
        selectedIdRef.current = idToLoad;
        try {
          const detail = await getMission(idToLoad);
          if (selectedIdRef.current === idToLoad) setMission(detail);
        } catch {
          failed = true;
        }
      }
      setSyncError(failed);
      if (!failed) setLastUpdated(new Date().toLocaleTimeString());
    } finally {
      refreshingRef.current = false;
      setSyncing(false);
    }
  };

  useEffect(() => {
    void refreshState(null);
  }, []);

  useEffect(() => {
    const isRunning = mission && !TERMINAL.includes(mission.state);
    if (!autoPoll) return;
    const intervalMs = isRunning ? 2000 : 5000;
    const id = setInterval(() => {
      void refreshState(selectedIdRef.current);
    }, intervalMs);
    return () => clearInterval(id);
  }, [mission?.mission_id, mission?.state, autoPoll]);

  const fmtCents = (n: number | null | undefined) =>
    typeof n === "number" ? `${n}¢` : "—";

  const metrics: { k: string; v: string }[] = dashboard
    ? [
        ...Object.entries(dashboard.missions_by_state).map(([s, n]) => ({
          k: `${t("metrics.missions-prefix")}${s}`,
          v: String(n),
        })),
        { k: t("metrics.active-missions"), v: String(dashboard.active_missions) },
        {
          k: t("metrics.validated-wvi"),
          v: String(dashboard.validated_improvements ?? 0),
        },
        { k: t("metrics.blocked-merges"), v: String(dashboard.blocked_merges) },
        { k: t("metrics.spent"), v: fmtCents(dashboard.spent_cents) },
        { k: t("metrics.reserved"), v: fmtCents(dashboard.reserved_cents) },
        { k: t("metrics.unknown-holds"), v: String(dashboard.unknown_holds) },
      ]
    : [];

  const unknownCount =
    ledger && Array.isArray(ledger.unknown_reservations)
      ? ledger.unknown_reservations.length
      : null;

  const selectMission = async (missionId: string) => {
    selectedIdRef.current = missionId;
    setMission(null);
    setOutcomePrUrl("");
    try {
      const m = await getMission(missionId);
      if (selectedIdRef.current === missionId) {
        setMission(m);
        setOutcomePrUrl(m.pr_url ?? "");
      }
    } catch { setSyncError(true); }
  };

  const openInLab = (m: MissionDetail) => {
    try {
      localStorage.setItem("evoforge.goal", JSON.stringify(m.goal));
      localStorage.setItem("evoforge.repo_ref", m.repo_ref || "HEAD");
      localStorage.setItem(
        "evoforge.review_evidence_id",
        m.review_evidence_id || ""
      );
      localStorage.setItem("evoforge.run_evidence_id", m.run_evidence_id || "");
    } catch {}
    if (typeof window !== "undefined") {
      window.location.href = "/lab";
    }
  };

  const handleRecordOutcome = async () => {
    if (!mission || !mergedSha.trim() || recordingOutcome) return;
    setRecordingOutcome(true);
    setErr("");
    try {
      await postOutcome(
        mission.mission_id,
        mergedSha.trim(),
        outcomePrUrl.trim() || mission.pr_url || ""
      );
      setMergedSha("");
      await refreshState(mission.mission_id);
    } catch (e) {
      const errorKey = getErrorMessageKey(e);
      setErr(tErrors(errorKey as any));
    } finally {
      setRecordingOutcome(false);
    }
  };

  const runMission = async () => {
    if (busy || !goal.trim()) return;
    setBusy(true);
    stopRef.current = false;
    setErr("");
    setMission(null);
    try {
      const created = await postMission(goal, repoRef || "HEAD");
      selectedIdRef.current = created.mission_id;
      let current = await getMission(created.mission_id);
      setMission(current);
      await refreshState(current.mission_id);
      for (const to of CHAIN) {
        if (stopRef.current) break;
        await postMissionAdvance(current.mission_id, to);
        current = await getMission(current.mission_id);
        setMission(current);
        await refreshState(current.mission_id);
        if (TERMINAL.includes(current.state)) break;
      }
    } catch (e) {
      const errorKey = getErrorMessageKey(e);
      setErr(tErrors(errorKey as any));
    } finally {
      setBusy(false);
      await refreshState(selectedIdRef.current);
    }
  };

  const stopMission = async () => {
    if (!mission || TERMINAL.includes(mission.state)) return;
    stopRef.current = true;
    try {
      await postMissionCancel(mission.mission_id);
    } catch (e) {
      const errorKey = getErrorMessageKey(e);
      setErr(tErrors(errorKey as any));
    } finally {
      await refreshState(mission.mission_id);
    }
  };

  const active = mission && !TERMINAL.includes(mission.state);
  const currentStepIdx = mission ? PIPELINE_STEPS.indexOf(mission.state) : -1;

  return (
    <main>
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="my-1 text-2xl font-bold">{t("heading")}</h1>
          <p className="text-text-secondary text-sm mt-0">
            {t("description")} · {API_BASE}/v1/missions
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-background-secondary border border-border text-text-secondary">
            <span
              className={`w-2 h-2 rounded-full ${
                syncing || syncError ? "bg-accent-amber" : "bg-accent-green"
              }`}
            />
            {syncError ? t("sync-error") : syncing ? t("syncing") : !autoPoll ? t("sync-paused") : t("live-status")}
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
            {autoPoll ? t("auto-poll-on") : t("auto-poll-off")}
          </button>
          <Button
            onClick={() => void refreshState(selectedIdRef.current)}
            variant="secondary"
            disabled={syncing}
          >
            {t("refresh-now")}
          </Button>
        </div>
      </div>

      {syncError && <p role="alert" className="text-sm text-accent-amber mt-3">{t("sync-error-detail")}</p>}

      <section className="flex gap-3 flex-wrap mt-4">
        {metrics.map((m) => (
          <Card key={m.k} className="min-w-[140px] flex-1">
            <div className="text-xs text-text-secondary">{m.k}</div>
            <div className="text-2xl font-bold mt-1">{m.v}</div>
          </Card>
        ))}
      </section>

      <Card className="mt-4">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="text-xs text-text-secondary">
            {t("performance-heading")}
          </div>
          <a href="/performance" className="text-xs text-accent-cyan hover:underline">
            {t("performance-link")}
          </a>
        </div>
        <div className="text-sm mt-2 flex flex-wrap gap-4">
          <div>
            <span className="text-text-secondary">X_SINGLE: </span>
            {perf?.baseline?.status === "measured" ? (
              <code>
                {perf.baseline.passed ?? perf.baseline.record?.passed}/
                {perf.baseline.n ?? perf.baseline.record?.n} (
                {formatRate(perf.baseline.pass_rate ?? perf.baseline.record?.pass_rate)})
              </code>
            ) : (
              <span>{t(perf ? "not-measured" : "performance-unavailable")}</span>
            )}
            {perf?.baseline?.status === "measured" && <span className="text-text-secondary"> · {t(`provenance.${viewProvenance(perf.baseline)}` as any)}</span>}
          </div>
          <div>
            <span className="text-text-secondary">PIPELINE: </span>
            {perf?.pipeline?.status === "measured" ? (
              <code>
                {perf.pipeline.passed ?? perf.pipeline.record?.passed}/
                {perf.pipeline.n ?? perf.pipeline.record?.n} (
                {formatRate(perf.pipeline.pass_rate ?? perf.pipeline.record?.pass_rate)})
              </code>
            ) : (
              <span>{t(perf ? "not-measured" : "performance-unavailable")}</span>
            )}
            {perf?.pipeline?.status === "measured" && <span className="text-text-secondary"> · {t(`provenance.${viewProvenance(perf.pipeline)}` as any)}</span>}
          </div>
          <div>
            {perf &&
            perf.comparison.status === "measured" &&
            perf.comparison.verdict ? (
              <>
                {t("comparison")}: <span>{t(`verdicts.${perf.comparison.verdict}` as any)}</span>{" "}
                {typeof perf.comparison.delta_pp === "number"
                  ? `Δ${round1(perf.comparison.delta_pp)}%p`
                  : ""}
                <span className="text-text-secondary"> · {t(`provenance.${comparisonProvenance(perf.baseline, perf.pipeline)}` as any)}</span>
              </>
            ) : (
              <span className="text-text-secondary">{t(perf ? "comparison-empty" : "performance-unavailable")}</span>
            )}
          </div>
          {perf?.production ? (
            <div className="text-text-secondary">
              runs=<code>{perf.production.runs}</code> pass=
              <code>{perf.production.gate_pass}</code> fail=
              <code>{perf.production.gate_fail}</code> inconclusive=
              <code>{perf.production.gate_inconclusive}</code>
            </div>
          ) : null}
        </div>
      </Card>

      <Card className="mt-4">
        <h2 className="text-base font-semibold m-0">{t("participants-heading")}</h2>
        {!participants || participants.status !== "available" ? (
          <p className="text-sm text-text-secondary mb-0">{t("participants-unavailable")}</p>
        ) : participants.participants.length === 0 ? (
          <p className="text-sm text-text-secondary mb-0">{t("participants-empty")}</p>
        ) : (
          <div className="grid gap-2 mt-3">
            {participants.participants.map((person) => (
              <div key={person.agent_id} className="p-2.5 rounded-lg border border-border text-sm">
                <div className="font-semibold">{person.agent_id} · {person.kind}</div>
                <div className="text-text-secondary">{t("participant-roles")}: {person.roles.map((value) => t.has(`participant-values.${value}` as any) ? t(`participant-values.${value}` as any) : value).join(", ") || "—"}</div>
                <div className="text-text-secondary">{t("participant-states")}: {[person.join_state, person.connection_state, person.execution_state, person.credential_state].map((value) => t.has(`participant-values.${value}` as any) ? t(`participant-values.${value}` as any) : value).join(" · ")}</div>
              </div>
            ))}
            {participants.has_more && <p className="text-sm text-text-secondary">{t("participants-more")}</p>}
          </div>
        )}
      </Card>

      <Card className="mt-4">
        <h2 className="text-base font-semibold m-0">{t("measurement-history")}</h2>
        {!perf ? (
          <p className="text-sm text-text-secondary">{t("history-unavailable")}</p>
        ) : !perf.history?.length ? (
          <p className="text-sm text-text-secondary">{t("history-empty")}</p>
        ) : (
          <div className="grid gap-2 mt-3">
            {[...perf.history].sort((a, b) => b.created_at - a.created_at).map((entry) => (
              <div key={entry.measurement_id} className="flex flex-wrap justify-between gap-2 p-2.5 rounded-lg border border-border text-sm">
                <span>{entry.kind} · {entry.model} · {entry.suite_version} · {t(`provenance.${provenance(entry.provider_stub)}` as any)}</span>
                <span>{entry.passed}/{entry.n} · {formatRate(entry.pass_rate)} · {new Date(entry.created_at * 1000).toLocaleString()}</span>
                {entry.evidence_id && <a href={`/evidence?id=${encodeURIComponent(entry.evidence_id)}`} className="text-accent-cyan hover:underline">{t("evidence-label")}</a>}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="mt-4">
        <div className="text-xs text-text-secondary mb-2">{t("objective-label")}</div>
        <div className="flex gap-2 flex-wrap">
          <Input
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder={t("objective-placeholder")}
            className="flex-[2_1_320px]"
          />
          <Input
            value={repoRef}
            onChange={(e) => setRepoRef(e.target.value)}
            placeholder={t("repo-ref-label")}
            title={t("repo-ref-label")}
            className="flex-[1_1_120px]"
          />
          <Button
            onClick={runMission}
            disabled={busy || !goal.trim()}
            loading={busy}
            variant="primary"
          >
            {busy ? t("running-mission") : t("run-mission")}
          </Button>
          {active && (
            <Button onClick={stopMission} variant="danger">
              {t("stop-mission")}
            </Button>
          )}
        </div>
        {err && (
          <div className="mt-3">
            <ErrorComponent message={err} />
          </div>
        )}
      </Card>

      {mission && (
        <Card className="mt-4">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="text-xs text-text-secondary">
              {t("selected-mission-heading")} · {t("mission-id")}:{" "}
              <code>{mission.mission_id}</code> · repo_ref:{" "}
              <code>{mission.repo_ref}</code> · risk: <code>{mission.risk}</code>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => openInLab(mission)}
                className="text-xs text-accent-cyan hover:underline bg-transparent border-0 cursor-pointer p-0"
              >
                {t("open-in-lab")}
              </button>
              <a
                href={`/evidence?id=${encodeURIComponent(
                  mission.evidence_ids[mission.evidence_ids.length - 1] ??
                    mission.mission_id
                )}`}
                className="text-xs text-text-link hover:underline"
              >
                {t("evidence-link")}
              </a>
            </div>
          </div>

          <div className="mt-2 flex items-center gap-2 flex-wrap">
            <Badge state={mission.state as MissionState}>
              {t(`states.${mission.state}` as any)}
            </Badge>
            <span className="text-sm font-medium text-text-primary">
              {mission.goal}
            </span>
          </div>

          <div className="flex gap-1.5 flex-wrap mt-3">
            {PIPELINE_STEPS.map((step, idx) => {
              const done = currentStepIdx >= idx;
              const isCurrent = mission.state === step;
              return (
                <span
                  key={step}
                  className={`text-xs px-2.5 py-1 rounded border ${
                    isCurrent
                      ? "bg-accent-blue text-white border-accent-blue font-bold"
                      : done
                      ? "bg-background-elevated text-accent-green border-border"
                      : "bg-background-primary text-text-secondary border-border opacity-60"
                  }`}
                >
                  {idx + 1}. {step}
                </span>
              );
            })}
            {(mission.state === "FAILED" || mission.state === "CANCELLED") && (
              <span className="text-xs px-2.5 py-1 rounded border bg-accent-red text-white border-accent-red font-bold">
                {mission.state}
              </span>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-3 text-xs">
            {[
              { label: "Generate", eid: mission.generate_evidence_id },
              { label: "Review", eid: mission.review_evidence_id },
              { label: "Server Run", eid: mission.run_evidence_id },
              { label: "Pull Request", eid: mission.pr_evidence_id },
            ].map((st) => (
              <div
                key={st.label}
                className="flex items-center justify-between bg-background-elevated border border-border rounded px-2.5 py-1.5"
              >
                <span className="text-text-secondary">{st.label}:</span>
                {st.eid ? (
                  <a
                    href={`/evidence?id=${encodeURIComponent(st.eid)}`}
                    className="text-accent-cyan hover:underline font-mono"
                  >
                    {st.eid}
                  </a>
                ) : (
                  <span className="text-text-secondary">—</span>
                )}
              </div>
            ))}
          </div>

          {mission.pr_url && (
            <div className="mt-3 text-sm">
              PR:{" "}
              <a
                href={mission.pr_url}
                target="_blank"
                rel="noreferrer"
                className="text-accent-green hover:underline font-mono"
              >
                {mission.pr_url}
              </a>
            </div>
          )}

          <div className="text-xs text-text-secondary mt-2">
            {t("evidence-label")}:{" "}
            {mission.evidence_ids.length ? (
              <span className="inline-flex flex-wrap gap-1.5">
                {mission.evidence_ids.map((eid) => (
                  <a
                    key={eid}
                    href={`/evidence?id=${encodeURIComponent(eid)}`}
                    className="text-text-link hover:underline font-mono"
                  >
                    {eid}
                  </a>
                ))}
              </span>
            ) : (
              "—"
            )}
          </div>

          {mission.state === "PR_OPENED" && (
            <div className="mt-4 pt-3 border-t border-border">
              <div className="text-xs text-text-secondary mb-2">
                {t("record-outcome-heading")}
              </div>
              <div className="flex gap-2 flex-wrap">
                <Input
                  value={mergedSha}
                  onChange={(e) => setMergedSha(e.target.value)}
                  placeholder={t("merged-sha-placeholder")}
                  className="flex-[1_1_220px]"
                />
                <Input
                  value={outcomePrUrl}
                  onChange={(e) => setOutcomePrUrl(e.target.value)}
                  placeholder={mission.pr_url || t("pr-url-placeholder")}
                  className="flex-[1_1_240px]"
                />
                <Button
                  onClick={handleRecordOutcome}
                  disabled={recordingOutcome || !mergedSha.trim()}
                  loading={recordingOutcome}
                  variant="primary"
                >
                  {recordingOutcome
                    ? t("recording-outcome")
                    : t("record-outcome-button")}
                </Button>
              </div>
            </div>
          )}
        </Card>
      )}

      <Card className="mt-4">
        <div className="text-xs text-text-secondary mb-2">
          {t("recent-missions-heading")} ({missions.length})
        </div>
        {missions.length === 0 ? (
          <div className="text-sm text-text-secondary">
            {t("recent-missions-empty")}
          </div>
        ) : (
          <div className="grid gap-2">
            {missions.map((m) => {
              const isSel = mission?.mission_id === m.mission_id;
              return (
                <div
                  key={m.mission_id}
                  onClick={() => void selectMission(m.mission_id)}
                  className={`flex items-center justify-between flex-wrap gap-2 p-2.5 rounded-lg border cursor-pointer transition-colors ${
                    isSel
                      ? "bg-background-elevated border-accent-blue"
                      : "bg-background-primary border-border hover:border-border-secondary"
                  }`}
                >
                  <div className="flex items-center gap-2 flex-wrap min-w-0">
                    <Badge state={m.state as MissionState}>
                      {t(`states.${m.state}` as any)}
                    </Badge>
                    <code className="text-xs text-text-tertiary">
                      {m.mission_id}
                    </code>
                    <span className="text-sm text-text-primary truncate max-w-[420px]">
                      {m.goal}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-text-secondary">
                    <span>
                      {t("evidence-label")}: {m.evidence_ids.length}
                    </span>
                    {m.updated_at ? (
                      <span>
                        {new Date(m.updated_at * 1000).toLocaleTimeString()}
                      </span>
                    ) : null}
                    <span className="text-accent-cyan font-semibold">
                      {isSel ? t("inspecting") : t("inspect-mission")}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <Card className="mt-4">
        <div className="text-xs text-text-secondary mb-2">
          {t("outcomes-heading")} ({outcomes.length})
        </div>
        {outcomes.length === 0 ? (
          <div className="text-sm text-text-secondary">
            {t("outcomes-empty")}
          </div>
        ) : (
          <div className="grid gap-2">
            {outcomes.map((o, idx) => (
              <div
                key={`${o.mission_id}-${o.merged_sha}-${idx}`}
                className="flex items-center justify-between flex-wrap gap-2 p-2.5 rounded-lg border border-border bg-background-primary text-xs"
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="px-2 py-0.5 rounded-full bg-accent-green text-background-primary font-bold">
                    {o.outcome_status} (w={o.weight})
                  </span>
                  <code>{o.mission_id}</code>
                  <span className="text-text-secondary">
                    sha: <code>{o.merged_sha.slice(0, 12)}</code>
                  </span>
                  {o.pr_url ? (
                    <a
                      href={o.pr_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-accent-cyan hover:underline"
                    >
                      {o.pr_url}
                    </a>
                  ) : null}
                </div>
                <div className="flex items-center gap-2">
                  {o.evidence_id ? (
                    <a
                      href={`/evidence?id=${encodeURIComponent(o.evidence_id)}`}
                      className="text-text-link hover:underline font-mono"
                    >
                      {o.evidence_id}
                    </a>
                  ) : null}
                  {o.recorded_at ? (
                    <span className="text-text-secondary">
                      {new Date(o.recorded_at * 1000).toLocaleTimeString()}
                    </span>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="mt-4">
        <div className="text-xs text-text-secondary">{t("ledger.heading")}</div>
        <div className="text-sm mt-1">
          {ledger ? (
            <>
              {t("ledger.spent-cents")}=<code>{ledger.spent_cents}</code>{" "}
              {t("ledger.reserved-cents")}=<code>{ledger.reserved_cents}</code>{" "}
              {t("ledger.unknown-reservations")}=<code>{unknownCount}</code>
              {ledger.unknown_reservations.length > 0 ? (
                <span className="text-xs text-accent-amber ml-2">
                  ({ledger.unknown_reservations.join(", ")})
                </span>
              ) : null}
            </>
          ) : (
            "—"
          )}
        </div>
      </Card>
    </main>
  );
}
