"use client";
import { useEffect, useRef, useState } from "react";
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
  getEvidence,
  getLedger,
  getMission,
  getPerformance,
  listMissions,
  listOutcomes,
  postMission,
  postMissionAdvance,
  postMissionCancel,
  postOutcome,
} from "../lib/api";

const card: React.CSSProperties = {
  background: "#141b2d",
  border: "1px solid #263048",
  borderRadius: 10,
  padding: 14,
  minWidth: 140,
  flex: "1 1 140px",
};

const label: React.CSSProperties = { fontSize: 12, color: "#8b96ad" };
const value: React.CSSProperties = {
  fontSize: 22,
  fontWeight: 700,
  marginTop: 4,
};

const TERMINAL: MissionState[] = ["PR_OPENED", "CANCELLED", "FAILED"];
const CHAIN: MissionState[] = ["GENERATED", "REVIEWED", "RAN", "PR_OPENED"];

function stateColor(s: string) {
  if (s === "PR_OPENED") return "#22c55e";
  if (s === "FAILED" || s === "CANCELLED") return "#ef4444";
  if (s === "RAN" || s === "REVIEWED") return "#38bdf8";
  return "#f59e0b";
}

function round1(val: number): number {
  return Math.round(val * 10) / 10;
}

export default function MissionControl() {
  const [goal, setGoal] = useState("Fix flaky login retry");
  const [repoRef, setRepoRef] = useState("HEAD");
  const [busy, setBusy] = useState(false);
  const [recordingOutcome, setRecordingOutcome] = useState(false);
  const [mergedSha, setMergedSha] = useState("");
  const [err, setErr] = useState("");
  const [initialLoading, setInitialLoading] = useState(true);
  const [mission, setMission] = useState<MissionDetail | null>(null);
  const [missionEvidence, setMissionEvidence] = useState<{
    gates?: Array<{ gate: string; result: string; reason?: string }>;
  } | null>(null);

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
  const [missions, setMissions] = useState<MissionSummary[]>([]);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const [dashboard, setDashboard] = useState<DashboardSnapshot | null>(null);
  const [ledger, setLedger] = useState<LedgerSnapshot | null>(null);
  const [perf, setPerf] = useState<PerformanceSnapshot | null>(null);
  const stopRef = useRef(false);
  const selectedIdRef = useRef<string | null>(null);

  const refreshState = async (missionId: string | null) => {
    const targetId = missionId ?? selectedIdRef.current;
    try {
      setDashboard(await getDashboard());
    } catch {}
    try {
      setLedger(await getLedger());
    } catch {}
    try {
      setPerf(await getPerformance());
    } catch {}
    try {
      const out = await listOutcomes();
      setOutcomes(out.outcomes ?? []);
    } catch {}
    let list: MissionSummary[] = [];
    try {
      const res = await listMissions();
      list = res.missions ?? [];
      setMissions(list);
    } catch {}
    const idToLoad = targetId || (list.length > 0 ? list[0].mission_id : null);
    if (idToLoad) {
      selectedIdRef.current = idToLoad;
      try {
        const d = await getMission(idToLoad);
        setMission(d);
        void fetchMissionEvidence(d);
      } catch {}
    }
    setInitialLoading(false);
  };

  useEffect(() => {
    void refreshState(null);
  }, []);

  // Poll the mission and the dashboard while a mission is active.
  useEffect(() => {
    if (!mission || TERMINAL.includes(mission.state)) return;
    const id = setInterval(() => {
      void refreshState(mission.mission_id);
    }, 2000);
    return () => clearInterval(id);
  }, [mission?.mission_id, mission?.state]);

  // All cards render only GET /v1/dashboard values; cost figures also appear
  // in the GET /v1/ledger snapshot below.
  const fmtCents = (n: number | null | undefined) =>
    typeof n === "number" ? `${n}¢` : "—";
  const metrics: { k: string; v: string }[] = dashboard
    ? [
        ...Object.entries(dashboard.missions_by_state).map(([s, n]) => ({
          k: `Missions: ${s}`,
          v: String(n),
        })),
        { k: "Active missions", v: String(dashboard.active_missions) },
        { k: "Validated (WVI)", v: String(dashboard.validated_improvements ?? 0) },
        { k: "Blocked merges", v: String(dashboard.blocked_merges) },
        { k: "Spent", v: fmtCents(dashboard.spent_cents) },
        { k: "Reserved", v: fmtCents(dashboard.reserved_cents) },
        { k: "Unknown holds", v: String(dashboard.unknown_holds) },
      ]
    : [];
  const unknownCount =
    ledger && Array.isArray(ledger.unknown_reservations)
      ? ledger.unknown_reservations.length
      : null;

  const handleRecordOutcome = async () => {
    if (!mission || !mergedSha.trim() || recordingOutcome) return;
    setRecordingOutcome(true);
    setErr("");
    try {
      await postOutcome(
        mission.mission_id,
        mergedSha.trim(),
        mission.pr_url || ""
      );
      setMergedSha("");
      await refreshState(mission.mission_id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
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
      const msg = e instanceof Error ? e.message : String(e);
      setErr(
        msg.includes("402")
          ? `budget exhausted: mission step refused with 402 (${msg})`
          : msg,
      );
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
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      await refreshState(mission.mission_id);
    }
  };

  const active = mission && !TERMINAL.includes(mission.state);

  return (
    <main>
      <h1 style={{ margin: "4px 0 4px" }}>Mission Control</h1>
      <p style={{ color: "#8b96ad", fontSize: 13, marginTop: 0 }}>
        POST {API_BASE}/v1/missions · single-command lifecycle
      </p>
      <section style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        {metrics.map((m) => (
          <div key={m.k} style={card}>
            <div style={label}>{m.k}</div>
            <div style={value}>{m.v}</div>
          </div>
        ))}
      </section>

      <section style={{ ...card, marginTop: 16 }}>
        <div style={label}>Performance (GET /v1/performance)</div>
        <div style={{ fontSize: 13, marginTop: 4 }}>
          {initialLoading ? (
            "Loading…"
          ) : perf && perf.comparison.status === "measured" && perf.comparison.verdict ? (
            <>
              비교: <code>{perf.comparison.verdict}</code>{" "}
              {typeof perf.comparison.delta_pp === "number"
                ? `Δ${round1(perf.comparison.delta_pp)}%p`
                : ""}
            </>
          ) : (
            "not measured yet"
          )}
        </div>
        <p style={{ marginBottom: 0 }}>
          <a href="/performance" style={{ color: "#7db4ff" }}>
            Performance →
          </a>
        </p>
      </section>

      <section style={{ ...card, marginTop: 16 }}>
        <div style={{ ...label, textTransform: "uppercase", fontWeight: 600 }}>Case-Based Contract Presets</div>
        <div style={{ display: "flex", gap: 8, marginTop: 6, marginBottom: 10, flexWrap: "wrap" }}>
          <button
            onClick={() => {
              setGoal(
                "should_retry(status) is True only for server errors (status >= 500). backoff(attempt) is 50 * 2**attempt ms with floor 100."
              );
            }}
            style={{ padding: "4px 10px", borderRadius: 6, border: "1px solid #33405c", background: "#0b0e14", color: "#e8edf5", cursor: "pointer", fontSize: 12 }}
          >
            Verified WVI Fix (PR #6)
          </button>
          <button
            onClick={() => {
              setGoal(
                "pipe(items) returns each positive int doubled; non-positive ints skipped; non-int raises ValueError. Empty returns []."
              );
            }}
            style={{ padding: "4px 10px", borderRadius: 6, border: "1px solid #33405c", background: "#0b0e14", color: "#e8edf5", cursor: "pointer", fontSize: 12 }}
          >
            Input & Exception Contract (EVAL_V1)
          </button>
          <button
            onClick={() => {
              setGoal(
                "shard(items, n) returns n lists differing by at most 1, larger first; n <= 0 raises ValueError. merge returns all."
              );
            }}
            style={{ padding: "4px 10px", borderRadius: 6, border: "1px solid #33405c", background: "#0b0e14", color: "#e8edf5", cursor: "pointer", fontSize: 12 }}
          >
            Partition Boundary Guarantee (PM-01)
          </button>
        </div>
        <div style={label}>Objective</div>
        <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
          <input
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            style={{ flex: "2 1 320px", padding: 8, borderRadius: 6, border: "1px solid #33405c", background: "#0b0e14", color: "#e8edf5" }}
          />
          <input
            value={repoRef}
            onChange={(e) => setRepoRef(e.target.value)}
            title="repo_ref"
            style={{ flex: "1 1 120px", padding: 8, borderRadius: 6, border: "1px solid #33405c", background: "#0b0e14", color: "#e8edf5" }}
          />
          <button
            onClick={runMission}
            disabled={busy || !goal.trim()}
            style={{ padding: "8px 16px", borderRadius: 6, background: "#2563eb", color: "#fff", border: 0, cursor: "pointer" }}
          >
            {busy ? "Running mission…" : "Run mission"}
          </button>
          {active ? (
            <button
              onClick={stopMission}
              style={{ padding: "8px 16px", borderRadius: 6, background: "#7f1d1d", color: "#fff", border: 0, cursor: "pointer" }}
            >
              Stop
            </button>
          ) : null}
        </div>
        {err ? <p style={{ color: "#ef4444" }}>Error: {err}</p> : null}
      </section>

      {mission ? (
        <section style={{ ...card, marginTop: 16 }}>
          <div style={label}>mission_id: {mission.mission_id}</div>
          <div style={{ marginTop: 8 }}>
            <span
              style={{
                display: "inline-block",
                padding: "2px 10px",
                borderRadius: 20,
                fontSize: 12,
                fontWeight: 700,
                color: "#0b0e14",
                background: stateColor(mission.state),
                marginRight: 8,
              }}
            >
              {mission.state}
            </span>
            <span style={{ fontSize: 13, color: "#aeb9cf" }}>{mission.goal}</span>
          </div>
          {mission.pr_url ? (
            <div style={{ fontSize: 13, marginTop: 8 }}>
              PR:{" "}
              <a href={mission.pr_url} style={{ color: "#22c55e" }}>
                {mission.pr_url}
              </a>
            </div>
          ) : null}
          <div style={{ fontSize: 13, marginTop: 8 }}>
            evidence:{" "}
            {mission.evidence_ids.length ? mission.evidence_ids.join(", ") : "—"}
          </div>
          {missionEvidence && missionEvidence.gates && missionEvidence.gates.length > 0 ? (
            <div style={{ marginTop: 8, padding: 8, borderRadius: 6, border: "1px solid #33405c", background: "#0b0e14" }}>
              <div style={{ ...label, textTransform: "uppercase", fontWeight: 600, marginBottom: 4 }}>Gate Diagnostics</div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {missionEvidence.gates.map((g, idx) => (
                  <span
                    key={`${g.gate}-${idx}`}
                    style={{
                      fontSize: 12,
                      fontFamily: "monospace",
                      padding: "2px 6px",
                      borderRadius: 4,
                      background: g.result === "PASS" ? "rgba(34,197,94,0.2)" : g.result === "FAIL" ? "rgba(239,68,68,0.2)" : "rgba(245,158,11,0.2)",
                      color: g.result === "PASS" ? "#22c55e" : g.result === "FAIL" ? "#ef4444" : "#f59e0b",
                    }}
                    title={g.reason || ""}
                  >
                    {g.gate}: {g.result}
                  </span>
                ))}
              </div>
              {missionEvidence.gates.some((g) => g.gate === "GH_INTEGRITY" && g.result === "INCONCLUSIVE") ? (
                <div style={{ color: "#f59e0b", fontSize: 12, marginTop: 4 }}>
                  {"Stability Hint (W10): Weak assertions detected (< 0.8 threshold). Exact == comparisons and pytest.raises required."}
                </div>
              ) : null}
            </div>
          ) : null}
          {mission.state === "PR_OPENED" ? (
            <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
              <input
                value={mergedSha}
                onChange={(e) => setMergedSha(e.target.value)}
                placeholder="merged_sha (POST /v1/outcomes)"
                style={{ flex: "1 1 200px", padding: 6, borderRadius: 6, border: "1px solid #33405c", background: "#0b0e14", color: "#e8edf5" }}
              />
              <button
                onClick={handleRecordOutcome}
                disabled={recordingOutcome || !mergedSha.trim()}
                style={{ padding: "6px 12px", borderRadius: 6, background: "#16a34a", color: "#fff", border: 0, cursor: "pointer" }}
              >
                {recordingOutcome ? "Recording…" : "Record WVI Outcome"}
              </button>
            </div>
          ) : null}
          <p>
            <a href="/evidence" style={{ color: "#7db4ff" }}>
              Evidence Timeline →
            </a>
          </p>
        </section>
      ) : null}

      {missions.length > 0 ? (
        <section style={{ ...card, marginTop: 16 }}>
          <div style={label}>Live Server Missions (GET /v1/missions)</div>
          <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
            {missions.map((m) => (
              <div
                key={m.mission_id}
                onClick={() => {
                  selectedIdRef.current = m.mission_id;
                  void getMission(m.mission_id).then((d) => { setMission(d); void fetchMissionEvidence(d); }).catch(() => {});
                }}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: 8,
                  borderRadius: 6,
                  border: "1px solid #263048",
                  background: "#0f1524",
                  cursor: "pointer",
                  fontSize: 13,
                }}
              >
                <span>
                  <code>{m.mission_id}</code> · <strong>{m.state}</strong> · {m.goal}
                </span>
                <span style={{ color: "#8b96ad" }}>
                  evidence: {m.evidence_ids.length}
                </span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {outcomes.length > 0 ? (
        <section style={{ ...card, marginTop: 16 }}>
          <div style={label}>Validated Outcomes · WVI (GET /v1/outcomes)</div>
          <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
            {outcomes.map((o, idx) => (
              <div
                key={`${o.mission_id}-${idx}`}
                style={{
                  padding: 8,
                  borderRadius: 6,
                  border: "1px solid #263048",
                  background: "#0f1524",
                  fontSize: 13,
                }}
              >
                <code>{o.mission_id}</code> · {o.outcome_status} · sha:{" "}
                <code>{o.merged_sha.slice(0, 12)}</code>{" "}
                {o.pr_url ? (
                  <a href={o.pr_url} style={{ color: "#7db4ff" }}>
                    {o.pr_url}
                  </a>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section style={{ ...card, marginTop: 16 }}>
        <div style={label}>Ledger snapshot (GET /v1/ledger)</div>
        <div style={{ fontSize: 13, marginTop: 4 }}>
          {ledger ? (
            <>
              spent_cents=<code>{ledger.spent_cents}</code> reserved_cents=
              <code>{ledger.reserved_cents}</code> unknown_reservations=
              <code>{unknownCount}</code>
            </>
          ) : (
            "—"
          )}
        </div>
      </section>
    </main>
  );
}
