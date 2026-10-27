"use client";
import { useEffect, useRef, useState } from "react";
import {
  API_BASE,
  type DashboardSnapshot,
  type LedgerSnapshot,
  type MissionDetail,
  type MissionState,
  getDashboard,
  getLedger,
  getMission,
  postMission,
  postMissionAdvance,
  postMissionCancel,
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

export default function MissionControl() {
  const [goal, setGoal] = useState("Fix flaky login retry");
  const [repoRef, setRepoRef] = useState("HEAD");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [mission, setMission] = useState<MissionDetail | null>(null);
  const [dashboard, setDashboard] = useState<DashboardSnapshot | null>(null);
  const [ledger, setLedger] = useState<LedgerSnapshot | null>(null);
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
      const msg = e instanceof Error ? e.message : String(e);
      setErr(
        msg.includes("402")
          ? `budget exhausted: mission step refused with 402 (${msg})`
          : msg,
      );
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
          <div style={{ fontSize: 13, marginTop: 8 }}>
            evidence:{" "}
            {mission.evidence_ids.length ? mission.evidence_ids.join(", ") : "—"}
          </div>
          <p>
            <a href="/evidence" style={{ color: "#7db4ff" }}>
              Evidence Timeline →
            </a>
          </p>
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
