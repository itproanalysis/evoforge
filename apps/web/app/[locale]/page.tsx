"use client";
import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  API_BASE,
  type ArenaDoc,
  type DashboardSnapshot,
  type LedgerSnapshot,
  type MissionDetail,
  type MissionState,
  type MissionSummary,
  type Outcome,
  type PerformanceSnapshot,
  type ArenaSummary,
  getArena,
  getArenaSummary,
  getDashboard,
  getEvidence,
  getLedger,
  getMission,
  getPerformance,
  getParticipants,
  listArenas,
  listMissions,
  listOutcomes,
  postMission,
  postMissionAdvance,
  postMissionCancel,
  postOutcome,
} from "../../lib/api";
import { Button, Input, Card, Badge } from "../../components/ui";
import { ProofCard } from "../../components/ProofCard";
import { FeedbackPanel } from "../../components/FeedbackPanel";
import { Error as ErrorComponent } from "../../components/ui/Error";
import { getErrorMessageKey } from "../../lib/apiErrors";
import { comparisonProvenance, provenance, viewProvenance } from "../../lib/performanceProvenance";
import {
  arenaAgentPanel,
  canFollowUp,
  previewView,
} from "../../lib/arenaStatus";
import { StudioOverview } from "../../components/StudioOverview";
import { CanvasWorkspace } from "../../components/CanvasWorkspace";
import { PromptBar } from "../../components/PromptBar";
import { WelcomeHero } from "../../components/WelcomeHero";
import { SandboxedPreview } from "../../components/SandboxedPreview";

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

const WS_SIDES: ("evoforge" | "single")[] = ["evoforge", "single"];

function pickWorkspaceArena(list: ArenaDoc[]): ArenaDoc | null {
  if (list.length === 0) return null;
  const sorted = [...list].sort(
    (a, b) => (b.created_at ?? 0) - (a.created_at ?? 0),
  );
  // First screen: the latest fair comparison EvoForge won (equal tools, no held-out signal), else the latest prompt run.
  const fairWin = sorted.find((a) => {
    const lanes = (a.manifest as { lanes?: Record<string, { apply?: string; feedback?: string }> } | undefined)?.lanes;
    return a.status === "succeeded" && a.verdict?.winner === "evoforge" && lanes?.single?.apply === "tolerant"
      && lanes?.evoforge?.feedback === "critic";
  });
  return fairWin ?? sorted.find((a) => a.mode === "prompt") ?? sorted[0];
}

export default function MissionControl() {
  const t = useTranslations("mission-control");
  const tErrors = useTranslations("errors");
  const tCommon = useTranslations("common");
  const tWorkspace = useTranslations("workspace");
  const tStudio = useTranslations("studio");
  const tArena = useTranslations("arena");
  const locale = useLocale();

  const [goal, setGoal] = useState("");
  const [repoRef, setRepoRef] = useState("HEAD");
  const [busy, setBusy] = useState(false);
  const [recordingOutcome, setRecordingOutcome] = useState(false);
  const [mergedSha, setMergedSha] = useState("");
  const [outcomePrUrl, setOutcomePrUrl] = useState("");
  const [initialLoading, setInitialLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [autoPoll, setAutoPoll] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<string>("");
  const [syncError, setSyncError] = useState(false);
  const [err, setErr] = useState("");
  const [mission, setMission] = useState<MissionDetail | null>(null);
  const [missionEvidence, setMissionEvidence] = useState<{
    gates?: Array<{ gate: string; result: string; reason?: string }>;
  } | null>(null);
  const [missions, setMissions] = useState<MissionSummary[]>([]);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const [dashboard, setDashboard] = useState<DashboardSnapshot | null>(null);
  const [ledger, setLedger] = useState<LedgerSnapshot | null>(null);
  const [perf, setPerf] = useState<PerformanceSnapshot | null>(null);
  const [participants, setParticipants] = useState<Awaited<ReturnType<typeof getParticipants>> | null>(null);
  const [workspaceArena, setWorkspaceArena] = useState<ArenaDoc | null>(null);
  const [workspaceArenas, setWorkspaceArenas] = useState<ArenaDoc[]>([]);
  const [arenaSummary, setArenaSummary] = useState<ArenaSummary | null>(null);
  const [arenaPendingId, setArenaPendingId] = useState<string | null>(null);
  const [arenaPollError, setArenaPollError] = useState(false);
  const stopRef = useRef(false);
  const selectedIdRef = useRef<string | null>(null);
  const refreshingRef = useRef(false);

  const fetchMissionEvidence = async (m: MissionDetail) => {
    const eid = m.run_evidence_id || m.generate_evidence_id;
    if (!eid) {
      setMissionEvidence(null);
      return;
    }
    try {
      const res = await getEvidence(eid);
      if (res && typeof res === "object" && "gates" in res && Array.isArray((res as any).gates)) {
        setMissionEvidence({ gates: (res as any).gates });
      } else {
        setMissionEvidence(null);
      }
    } catch {
      setMissionEvidence(null);
    }
  };

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
          if (selectedIdRef.current === idToLoad) {
            setMission(detail);
            void fetchMissionEvidence(detail);
          }
        } catch {
          failed = true;
        }
      }
      setSyncError(failed);
      if (!failed) setLastUpdated(new Date().toLocaleTimeString(locale));
    } finally {
      refreshingRef.current = false;
      setInitialLoading(false);
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

  useEffect(() => {
    if (!autoPoll) return;
    if (typeof EventSource === "undefined") return;
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/v1/stream?wait=25`);
    } catch {
      return;
    }
    // Live updates: refresh on every streamed event. The polling loop above
    // stays as the fallback when the stream errors.
    es.onmessage = () => {
      void refreshState(selectedIdRef.current);
    };
    es.onerror = () => {
      try {
        es?.close();
      } catch {}
    };
    return () => {
      try {
        es?.close();
      } catch {}
    };
  }, [autoPoll]);

  // Home workspace: latest arena (GET /v1/arena newest first; prefer a prompt
  // arena). After a PromptBar start, show the new arena here and poll it.
  useEffect(() => {
    let cancelled = false;
    void listArenas()
      .then((res) => {
        if (cancelled) return;
        const list = res && Array.isArray(res.arenas) ? res.arenas : [];
        setWorkspaceArenas(current => {
          const byId = new Map(list.map(run => [run.arena_id, run]));
          for (const run of current) byId.set(run.arena_id, run);
          return [...byId.values()].sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0));
        });
        setWorkspaceArena((cur) => cur ?? pickWorkspaceArena(list));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // Home scoreboard: measured Arena results from getArenaSummary().
  useEffect(() => {
    let cancelled = false;
    void getArenaSummary()
      .then((res) => {
        if (cancelled) return;
        if (res && typeof res === "object") {
          setArenaSummary(res);
          // The newest fair EvoForge win may be older than the 20 runs the list returns: load it directly.
          const winId = res.equal_tools?.latest_win;
          if (winId) {
            void getArena(winId).then((doc) => {
              if (!cancelled && doc?.arena_id === winId) {
                setWorkspaceArena((cur) => (cur && cur.verdict?.winner === "evoforge" && cur.status === "succeeded") || cur?.status === "running" ? cur : doc);
              }
            }).catch(() => {});
          }
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const wsTrackedId =
    arenaPendingId ??
    (workspaceArena?.status === "running" ? workspaceArena.arena_id : null);

  useEffect(() => {
    if (!wsTrackedId || arenaPollError) return;
    let active = true;
    let inFlight = false;
    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const doc = await getArena(wsTrackedId);
        if (!active) return;
        if (doc.arena_id !== wsTrackedId) throw new Error("arena id mismatch");
        setWorkspaceArena(doc);
        setWorkspaceArenas(current => [doc, ...current.filter(run => run.arena_id !== doc.arena_id)]);
        setArenaPendingId(null);
      } catch {
        if (active) setArenaPollError(true);
      } finally {
        inFlight = false;
      }
    };
    void poll();
    const id = setInterval(() => {
      void poll();
    }, 1500);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [wsTrackedId, arenaPollError]);

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
        {
          k: t("metrics.prs-awaiting"),
          v: String(dashboard.prs_awaiting_validation ?? 0),
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
    setMissionEvidence(null);
    setOutcomePrUrl("");
    try {
      const m = await getMission(missionId);
      if (selectedIdRef.current === missionId) {
        setMission(m);
        setOutcomePrUrl(m.pr_url ?? "");
        void fetchMissionEvidence(m);
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
      window.location.href = locale === "ko" ? "/ko/lab" : "/lab";
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

  const wsFollowUp = canFollowUp(workspaceArena) ? workspaceArena : null;
  const wsRunning =
    arenaPendingId !== null || workspaceArena?.status === "running";
  const displayedArena = arenaPendingId !== null && workspaceArena?.arena_id !== arenaPendingId
    ? null : workspaceArena;

  const management = <>
      <div className="studio-tools flex flex-col md:flex-row">
      <section aria-label={tWorkspace("intro")} className="studio-intro">
        <details><summary>{tStudio('guide')}</summary>
        <p className="text-sm text-text-primary mt-0 mb-2">
          {tWorkspace("intro")}
        </p>
        <ol className="list-decimal text-sm text-text-secondary mt-0 mb-0 pl-5">
          <li>{tWorkspace("intro-step-1")}</li>
          <li>{tWorkspace("intro-step-2")}</li>
          <li>{tWorkspace("intro-step-3")}</li>
        </ol>
        </details>
      </section>
      {/* Home scoreboard: measured Arena results from getArenaSummary(). */}
      <section aria-label={tWorkspace("scoreboard-heading")}>
        <details className="studio-scoreboard">
          <summary>{tWorkspace("scoreboard-heading")}</summary>
        <Card className="bg-background-secondary border border-border p-3">
          <span className="text-xs font-semibold text-text-tertiary uppercase tracking-wider block">
            {tWorkspace("scoreboard-heading")}
          </span>
          {!arenaSummary || (arenaSummary.scored ?? 0) === 0 ? (
            <p className="text-sm text-text-secondary mt-2 mb-0 break-words">
              {tWorkspace("scoreboard-empty")}
            </p>
          ) : (
            <>
              <div className="mt-2 text-xs font-semibold text-text-primary break-words">
                {tArena("summary-equal-tools")}
              </div>
              <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-secondary break-words">
                <span>
                  {tArena("summary-evoforge-wins")}:{" "}
                  <strong className="text-text-primary">{arenaSummary.equal_tools?.wins?.evoforge ?? 0}</strong>
                </span>
                <span>
                  {tArena("summary-single-wins")}:{" "}
                  <strong className="text-text-primary">{arenaSummary.equal_tools?.wins?.single ?? 0}</strong>
                </span>
                <span>
                  {tArena("summary-ties")}:{" "}
                  <strong className="text-text-primary">{arenaSummary.equal_tools?.wins?.tie ?? 0}</strong>
                </span>
                <span>
                  {tArena("summary-scored")}:{" "}
                  <strong className="text-text-primary">{arenaSummary.equal_tools?.scored ?? 0}</strong>
                </span>
              </div>
              <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-secondary break-words">
                <span>
                  {tArena("summary-heldout-evoforge")}:{" "}
                  <strong className="text-text-primary">
                    {arenaSummary.equal_tools?.heldout?.evoforge?.passed ?? 0}/{arenaSummary.equal_tools?.heldout?.evoforge?.n ?? 0}
                  </strong>
                </span>
                <span>
                  {tArena("summary-heldout-single")}:{" "}
                  <strong className="text-text-primary">
                    {arenaSummary.equal_tools?.heldout?.single?.passed ?? 0}/{arenaSummary.equal_tools?.heldout?.single?.n ?? 0}
                  </strong>
                </span>
              </div>
              <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-secondary break-words">
                <span>
                  {tArena("summary-cost-evoforge")}:{" "}
                  <strong className="text-text-primary">{arenaSummary.equal_tools?.cost_cents?.evoforge ?? 0}¢</strong>
                </span>
                <span>
                  {tArena("summary-cost-single")}:{" "}
                  <strong className="text-text-primary">{arenaSummary.equal_tools?.cost_cents?.single ?? 0}¢</strong>
                </span>
                <span>
                  {tArena("summary-cost-judge")}:{" "}
                  <strong className="text-text-primary">{arenaSummary.equal_tools?.cost_cents?.judge ?? 0}¢</strong>
                </span>
              </div>
              {(() => {
                const stats = arenaSummary.equal_tools?.stats;
                if (!stats) return null;
                const p = stats.sign_test_p;
                const pText = typeof p === "number" && Number.isFinite(p) ? String(p) : "—";
                const fmtIv = (iv: [number, number] | null | undefined) =>
                  Array.isArray(iv) ? `[${iv[0]}, ${iv[1]}]` : "—";
                const tasks = stats.tasks ?? arenaSummary.equal_tools?.scored ?? 0;
                const solvedE = stats.solved?.evoforge ?? 0;
                const solvedS = stats.solved?.single ?? 0;
                const ivE = fmtIv(stats.wilson95?.evoforge);
                const ivS = fmtIv(stats.wilson95?.single);
                const significant = typeof p === "number" && Number.isFinite(p) ? p < 0.05 : !!stats.significant;
                return (
                  <>
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-secondary break-words max-w-full">
                      <span>
                        Solved EvoForge {solvedE}/{tasks} {ivE}
                      </span>
                      <span>
                        Solved Single {solvedS}/{tasks} {ivS}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-text-secondary break-words max-w-full">
                      {significant
                        ? tArena("summary-significant", { p: pText })
                        : tArena("summary-not-significant", { p: pText })}
                    </p>
                  </>
                );
              })()}
              <div className="mt-2 text-xs font-semibold text-text-primary break-words">
                {tArena("summary-all-matches")}
              </div>
              <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-secondary break-words">
                <span>
                  {tArena("summary-evoforge-wins")}:{" "}
                  <strong className="text-text-primary">{arenaSummary.wins?.evoforge ?? 0}</strong>
                </span>
                <span>
                  {tArena("summary-single-wins")}:{" "}
                  <strong className="text-text-primary">{arenaSummary.wins?.single ?? 0}</strong>
                </span>
                <span>
                  {tArena("summary-ties")}:{" "}
                  <strong className="text-text-primary">{arenaSummary.wins?.tie ?? 0}</strong>
                </span>
                <span>
                  {tArena("summary-scored")}:{" "}
                  <strong className="text-text-primary">{arenaSummary.scored ?? 0}</strong>
                </span>
              </div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-secondary break-words">
                <span>
                  {tArena("summary-heldout-evoforge")}:{" "}
                  <strong className="text-text-primary">
                    {arenaSummary.heldout?.evoforge?.passed ?? 0}/{arenaSummary.heldout?.evoforge?.n ?? 0}
                  </strong>
                </span>
                <span>
                  {tArena("summary-heldout-single")}:{" "}
                  <strong className="text-text-primary">
                    {arenaSummary.heldout?.single?.passed ?? 0}/{arenaSummary.heldout?.single?.n ?? 0}
                  </strong>
                </span>
              </div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-secondary break-words">
                <span>
                  {tArena("summary-cost-evoforge")}:{" "}
                  <strong className="text-text-primary">{arenaSummary.cost_cents?.evoforge ?? 0}¢</strong>
                </span>
                <span>
                  {tArena("summary-cost-single")}:{" "}
                  <strong className="text-text-primary">{arenaSummary.cost_cents?.single ?? 0}¢</strong>
                </span>
                <span>
                  {tArena("summary-cost-judge")}:{" "}
                  <strong className="text-text-primary">{arenaSummary.cost_cents?.judge ?? 0}¢</strong>
                </span>
              </div>
            </>
          )}
          <div className="mt-2 text-xs break-words">
            <a
              href={`${locale === "en" ? "" : `/${locale}`}/arena`}
              className="text-accent-cyan hover:underline"
            >
              {tWorkspace("view-arena")}
            </a>
          </div>
        </Card>
        </details>
      </section>
      </div>
    <div className="canvas-management">
      <details className="mt-8" data-testid="mission-control-details">
        <summary className="cursor-pointer text-sm font-semibold text-text-primary">
          {tWorkspace("mission-control-toggle")}
        </summary>
        <div className="mt-3">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="my-1 text-2xl font-bold">{t("heading")}</h1>
          <p className="text-text-secondary text-sm mt-0">
            {t("description")}
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

      <ProofCard history={perf?.history ?? null} loading={initialLoading} />

      <section className="flex gap-3 flex-wrap mt-4">
        {metrics.length === 0 && initialLoading ? (
          <Card className="min-w-[140px] flex-1">
            <div className="text-xs text-text-secondary">{tCommon("loading")}</div>
            <div className="text-2xl font-bold mt-1">—</div>
          </Card>
        ) : (
          metrics.map((m) => (
            <Card key={m.k} className="min-w-[140px] flex-1">
              <div className="text-xs text-text-secondary">{m.k}</div>
              <div className="text-2xl font-bold mt-1">{m.v}</div>
            </Card>
          ))
        )}
      </section>
      {dashboard && (
        <p className="text-xs text-text-secondary mt-2">{t("metrics.wvi-rule")}</p>
      )}

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
            <span className="text-text-secondary">single AI baseline: </span>
            {initialLoading ? (
              <span className="text-text-secondary">{tCommon("loading")}</span>
            ) : perf?.baseline?.status === "measured" ? (
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
            <span className="text-text-secondary">EvoForge pipeline: </span>
            {initialLoading ? (
              <span className="text-text-secondary">{tCommon("loading")}</span>
            ) : perf?.pipeline?.status === "measured" ? (
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
            {initialLoading ? (
              <span className="text-text-secondary">{tCommon("loading")}</span>
            ) : perf &&
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
        {initialLoading ? (
          <p className="text-sm text-text-secondary mb-0">{tCommon("loading")}</p>
        ) : !participants || participants.status !== "available" ? (
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
        {initialLoading ? (
          <p className="text-sm text-text-secondary mb-0">{tCommon("loading")}</p>
        ) : !perf ? (
          <p className="text-sm text-text-secondary">{t("history-unavailable")}</p>
        ) : !perf.history?.length ? (
          <p className="text-sm text-text-secondary">{t("history-empty")}</p>
        ) : (
          <div className="grid gap-2 mt-3">
            {[...perf.history].sort((a, b) => b.created_at - a.created_at).map((entry) => (
              <div key={entry.measurement_id} className="flex flex-wrap justify-between gap-2 p-2.5 rounded-lg border border-border text-sm">
                <span>{entry.kind} · {entry.model} · {entry.suite_version} · {t(`provenance.${provenance(entry.provider_stub)}` as any)}</span>
                <span>{entry.passed}/{entry.n} · {formatRate(entry.pass_rate)} · {new Date(entry.created_at * 1000).toLocaleString(locale)}</span>
                {entry.evidence_id && <a href={`/evidence?id=${encodeURIComponent(entry.evidence_id)}`} className="text-accent-cyan hover:underline">{t("evidence-label")}</a>}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="mt-4">
        <div className="mb-3">
          <div className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-2">
            {t("presets-heading")}
          </div>
          <div className="flex gap-2 flex-wrap">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setGoal(
                  "should_retry(status) is True only for server errors (status >= 500). backoff(attempt) is 50 * 2**attempt ms with floor 100."
                );
              }}
            >
              {t("preset-wvi-btn")}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setGoal(
                  "pipe(items) returns each positive int doubled; non-positive ints skipped; non-int raises ValueError. Empty returns []."
                );
              }}
            >
              {t("preset-contract-btn")}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setGoal(
                  "shard(items, n) returns n lists differing by at most 1, larger first; n <= 0 raises ValueError. merge returns all."
                );
              }}
            >
              {t("preset-boundary-btn")}
            </Button>
          </div>
        </div>
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
              { label: t("stage-generate"), eid: mission.generate_evidence_id },
              { label: t("stage-review"), eid: mission.review_evidence_id },
              { label: t("stage-run"), eid: mission.run_evidence_id },
              { label: t("stage-pr"), eid: mission.pr_evidence_id },
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

          {missionEvidence && missionEvidence.gates && missionEvidence.gates.length > 0 && (
            <div className="mt-3 p-3 rounded-lg border border-border bg-background-elevated">
              <div className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-2">
                {t("gate-diagnostics-heading")}
              </div>
              <div className="flex gap-2 flex-wrap">
                {missionEvidence.gates.map((g, idx) => (
                  <span
                    key={`${g.gate}-${idx}`}
                    className={`text-xs px-2 py-1 rounded border font-mono ${
                      g.result === "PASS"
                        ? "bg-accent-green/20 text-accent-green border-accent-green/40"
                        : g.result === "FAIL"
                        ? "bg-accent-red/20 text-accent-red border-accent-red/40"
                        : "bg-accent-amber/20 text-accent-amber border-accent-amber/40"
                    }`}
                    title={g.reason || ""}
                  >
                    {g.gate}: {g.result}
                  </span>
                ))}
              </div>
              {missionEvidence.gates.some((g) => g.gate === "GH_INTEGRITY" && g.result === "INCONCLUSIVE") && (
                <p className="text-xs text-accent-amber mt-2 mb-0">
                  {t("gate-integrity-w10-hint")}
                </p>
              )}
            </div>
          )}

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

          <FeedbackPanel
            key={mission.mission_id}
            missionId={mission.mission_id}
          />
        </Card>
      )}

      <Card className="mt-4">
        <div className="text-xs text-text-secondary mb-2">
          {t("recent-missions-heading")} ({missions.length})
        </div>
        {missions.length === 0 ? (
          <div className="text-sm text-text-secondary">
            {initialLoading ? tCommon("loading") : t("recent-missions-empty")}
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
                        {new Date(m.updated_at * 1000).toLocaleTimeString(locale)}
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
            {initialLoading ? tCommon("loading") : t("outcomes-empty")}
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
                      {new Date(o.recorded_at * 1000).toLocaleTimeString(locale)}
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
          {initialLoading ? (
            <span className="text-text-secondary">{tCommon("loading")}</span>
          ) : ledger ? (
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
        </div>
      </details>
    </div>
  </>;
  return (
    <CanvasWorkspace
      label={tWorkspace("heading")}
      doc={displayedArena}
      runs={workspaceArenas}
      busy={wsRunning}
      loading={initialLoading}
      pollError={arenaPollError}
      onRetry={() => setArenaPollError(false)}
      onSelect={(id) => {
        if (wsRunning) return;
        const selected = workspaceArenas.find(run => run.arena_id === id);
        if (selected) { setWorkspaceArena(selected); setArenaPendingId(null); setArenaPollError(false); }
      }}
      previews={{ evoforge: previewView(displayedArena?.lanes?.evoforge), single: previewView(displayedArena?.lanes?.single) }}
      agents={{ evoforge: arenaAgentPanel(displayedArena, 'evoforge'), single: arenaAgentPanel(displayedArena, 'single') }}
      participants={participants}
      history={perf?.history ?? null}
      renderPreview={(html, title) => <SandboxedPreview html={html} title={title}/>}
      overview={<StudioOverview running={wsRunning} runId={displayedArena?.arena_id} measured={arenaSummary?.equal_tools?.scored ?? null} verified={dashboard?.validated_improvements ?? null} participants={participants?.status === 'available' ? participants.participants.length : null} participantsMore={participants?.has_more} heldout={arenaSummary?.equal_tools?.heldout?.evoforge ?? null} singleHeldout={arenaSummary?.equal_tools?.heldout?.single ?? null} wins={arenaSummary?.equal_tools?.wins ?? null} signP={arenaSummary?.equal_tools?.stats?.sign_test_p ?? null} value={arenaSummary?.equal_tools?.value ?? null}/>}
      management={management}
      welcome={(close) => <WelcomeHero summary={arenaSummary} onClose={close}/>}
      composer={<PromptBar disabled={wsRunning} followUpArena={wsFollowUp} onStarted={(id) => { setArenaPendingId(id); setArenaPollError(false); }}/>} />
  );
}
