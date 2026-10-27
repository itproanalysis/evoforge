"use client";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  API_BASE,
  type DashboardSnapshot,
  type LedgerSnapshot,
  type MissionDetail,
  type MissionState,
  type PerformanceSnapshot,
  getDashboard,
  getLedger,
  getMission,
  getPerformance,
  postMission,
  postMissionAdvance,
  postMissionCancel,
} from "../../lib/api";
import { Button, Input, Card, Badge } from "../../components/ui";
import { Error as ErrorComponent } from "../../components/ui/Error";
import { getErrorMessageKey } from "../../lib/apiErrors";

const TERMINAL: MissionState[] = ["PR_OPENED", "CANCELLED", "FAILED"];
const CHAIN: MissionState[] = ["GENERATED", "REVIEWED", "RAN", "PR_OPENED"];

export default function MissionControl() {
  const t = useTranslations("mission-control");
  const tCommon = useTranslations("common");
  const tErrors = useTranslations("errors");

  const [goal, setGoal] = useState("Fix flaky login retry");
  const [repoRef, setRepoRef] = useState("HEAD");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [mission, setMission] = useState<MissionDetail | null>(null);
  const [dashboard, setDashboard] = useState<DashboardSnapshot | null>(null);
  const [ledger, setLedger] = useState<LedgerSnapshot | null>(null);
  const [perf, setPerf] = useState<PerformanceSnapshot | null>(null);
  const stopRef = useRef(false);

  const refreshState = async (missionId: string | null) => {
    try {
      setDashboard(await getDashboard());
    } catch {}
    try {
      setLedger(await getLedger());
    } catch {}
    if (missionId) {
      try {
        setMission(await getMission(missionId));
      } catch {}
    }
  };

  useEffect(() => {
    void refreshState(null);
    getPerformance().then(setPerf).catch(() => {});
  }, []);

  useEffect(() => {
    if (!mission || TERMINAL.includes(mission.state)) return;
    const id = setInterval(() => {
      void refreshState(mission.mission_id);
    }, 2000);
    return () => clearInterval(id);
  }, [mission?.mission_id, mission?.state]);

  const fmtCents = (n: number | null | undefined) =>
    typeof n === "number" ? `${n}¢` : "—";

  const metrics: { k: string; v: string }[] = dashboard
    ? [
        ...Object.entries(dashboard.missions_by_state).map(([s, n]) => ({
          k: `${t("metrics.missions-prefix")}${s}`,
          v: String(n),
        })),
        { k: t("metrics.active-missions"), v: String(dashboard.active_missions) },
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

  const runMission = async () => {
    if (busy || !goal.trim()) return;
    setBusy(true);
    stopRef.current = false;
    setErr("");
    setMission(null);
    try {
      const created = await postMission(goal, repoRef || "HEAD");
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
      if (mission) await refreshState(mission.mission_id);
      else await refreshState(null);
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

  return (
    <main>
      <h1 className="my-1 text-2xl font-bold">{t("heading")}</h1>
      <p className="text-text-secondary text-sm mt-0">
        {t("description")}
      </p>
      
      <section className="flex gap-3 flex-wrap mt-4">
        {metrics.map((m) => (
          <Card key={m.k} className="min-w-[140px] flex-1">
            <div className="text-xs text-text-secondary">{m.k}</div>
            <div className="text-2xl font-bold mt-1">{m.v}</div>
          </Card>
        ))}
      </section>

      <Card className="mt-4">
        <div className="text-xs text-text-secondary">Performance (GET /v1/performance)</div>
        <div className="text-sm mt-1">
          {perf && perf.comparison.status === "measured" && perf.comparison.verdict ? (
            <>
              비교: <code>{perf.comparison.verdict}</code>{" "}
              {typeof perf.comparison.delta_pp === "number"
                ? `Δ${perf.comparison.delta_pp.toFixed(1)}%p`
                : ""}
            </>
          ) : (
            "not measured yet"
          )}
        </div>
        <p className="mb-0 mt-2">
          <a href="/performance" className="text-accent-cyan hover:underline">
            Performance →
          </a>
        </p>
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
          <div className="text-xs text-text-secondary">
            {t("mission-id")}: {mission.mission_id}
          </div>
          <div className="mt-2">
            <Badge state={mission.state as MissionState}>
              {t(`states.${mission.state}` as any)}
            </Badge>
            <span className="text-sm text-text-secondary ml-2">{mission.goal}</span>
          </div>
          <div className="text-sm mt-2">
            {t("evidence-label")}:{" "}
            {mission.evidence_ids.length ? mission.evidence_ids.join(", ") : "—"}
          </div>
          <p className="mt-2">
            <a href="/evidence" className="text-text-link hover:underline">
              {t("evidence-link")}
            </a>
          </p>
        </Card>
      )}

      <Card className="mt-4">
        <div className="text-xs text-text-secondary">{t("ledger.heading")}</div>
        <div className="text-sm mt-1">
          {ledger ? (
            <>
              {t("ledger.spent-cents")}=<code>{ledger.spent_cents}</code>{" "}
              {t("ledger.reserved-cents")}=<code>{ledger.reserved_cents}</code>{" "}
              {t("ledger.unknown-reservations")}=<code>{unknownCount}</code>
            </>
          ) : (
            "—"
          )}
        </div>
      </Card>
    </main>
  );
}
