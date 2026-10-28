"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  getArena,
  listArenas,
  postArena,
  type ArenaDoc,
} from "../../../lib/api";
import { Button, Card } from "../../../components/ui";

const BENCHMARK_TASKS: Record<"v2" | "v1", { id: string; goal: string }[]> = {
  v2: [
    { id: "SV2-AO-01", goal: "In bsearch.py, bsearch(seq, target) returns index in sorted sequence, or -1" },
    { id: "SV2-AO-02", goal: "In qsort.py, quicksort in-place with 3-way partition" },
    { id: "SV2-CD-01", goal: "In chat.py, handle network dropout with exponential backoff" },
    { id: "SV2-CI-01", goal: "In ci.py, saturated build queue fair scheduler" },
    { id: "SV2-PM-01", goal: "In parallel.py, multi-file atomic transaction commit" },
    { id: "SV2-SS-01", goal: "In auth.py, constant-time token comparison" },
  ],
  v1: [
    { id: "SV1-AO-01", goal: "In bsearch.py, return index of target in sorted sequence, or -1" },
    { id: "SV1-AO-02", goal: "In qsort.py, quicksort in-place with 3-way partition" },
    { id: "SV1-CD-01", goal: "In chat.py, exponential backoff with retry" },
    { id: "SV1-CI-01", goal: "In ci.py, fair task scheduler" },
  ],
};

function StatusPill({ status, passed, n }: { status: string; passed?: number; n?: number }) {
  if (status === "running") {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-950/60 text-amber-300 border border-amber-500/40">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
        RUNNING
      </span>
    );
  }
  if (status === "succeeded" || status === "finished") {
    if (passed !== undefined && n !== undefined && n > 0 && passed >= n) {
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-950/60 text-emerald-300 border border-emerald-500/40">
          ALL PASS ({passed}/{n})
        </span>
      );
    }
    return (
      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-950/60 text-rose-300 border border-rose-500/40">
        FAILED ({passed ?? 0}/{n ?? 0})
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-800 text-slate-300 border border-slate-700">
      {status.toUpperCase()}
    </span>
  );
}

export default function ArenaPage() {
  const t = useTranslations("arena");
  const [suiteVersion, setSuiteVersion] = useState<"v1" | "v2">("v2");
  const [selectedTaskId, setSelectedTaskId] = useState<string>("SV2-AO-01");
  const [customTaskId, setCustomTaskId] = useState<string>("");
  const [running, setRunning] = useState(false);
  const [activeArena, setActiveArena] = useState<ArenaDoc | null>(null);
  const [recentArenas, setRecentArenas] = useState<ArenaDoc[]>([]);
  const [error, setError] = useState<string | null>(null);

  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const activeTaskId = customTaskId.trim() || selectedTaskId;

  // Load recent arenas
  const refreshRecent = async () => {
    try {
      const res = await listArenas();
      if (res && Array.isArray(res.arenas)) {
        setRecentArenas(res.arenas);
        if (!activeArena && res.arenas.length > 0) {
          setActiveArena(res.arenas[0]);
        }
      }
    } catch (e) {
      console.warn("Failed to list arenas", e);
    }
  };

  useEffect(() => {
    refreshRecent();
  }, []);

  // Poll active arena if running
  useEffect(() => {
    if (!activeArena || activeArena.status !== "running") {
      if (pollRef.current) clearInterval(pollRef.current);
      setRunning(false);
      return;
    }

    setRunning(true);
    pollRef.current = setInterval(async () => {
      try {
        const doc = await getArena(activeArena.arena_id);
        setActiveArena(doc);
        if (doc.status !== "running") {
          setRunning(false);
          refreshRecent();
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch (err) {
        console.warn("Arena poll error", err);
      }
    }, 1500);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [activeArena?.arena_id, activeArena?.status]);

  const handleStartMatch = async () => {
    if (!activeTaskId) return;
    setError(null);
    setRunning(true);
    try {
      const res = await postArena(activeTaskId, suiteVersion);
      if (res && res.arena_id) {
        const seeded: ArenaDoc = {
          arena_id: res.arena_id,
          status: "running",
          suite_version: suiteVersion,
          task_id: activeTaskId,
          model: "muse-spark-1.3",
          goal: BENCHMARK_TASKS[suiteVersion]?.find((t) => t.id === activeTaskId)?.goal || activeTaskId,
          created_at: Date.now() / 1000,
          lanes: {
            single: {
              status: "running",
              attempts: 0,
              heldout: { passed: 0, n: 0 },
              outcome: "heldout_failed",
              cost_cents: 0,
              elapsed_ms: 0,
              diff: "",
              events: [{ seq: 1, ts: Date.now() / 1000, role: "system", message: "Single AI lane initialized" }],
            },
            evoforge: {
              status: "running",
              attempts: 0,
              heldout: { passed: 0, n: 0 },
              outcome: "heldout_failed",
              cost_cents: 0,
              elapsed_ms: 0,
              diff: "",
              events: [{ seq: 1, ts: Date.now() / 1000, role: "system", message: "EvoForge Pipeline lane initialized" }],
            },
          },
          verdict: { winner: "tie", reason: "Arena match in progress..." },
        };
        setActiveArena(seeded);
      }
    } catch (e: any) {
      setError(e.message || "Failed to start arena match");
      setRunning(false);
    }
  };

  const singleLane = activeArena?.lanes?.single;
  const evoLane = activeArena?.lanes?.evoforge;

  return (
    <div className="max-w-7xl mx-auto px-4 py-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border pb-6">
        <div>
          <div className="flex items-center gap-3">
            <span className="text-3xl">⚔️</span>
            <h1 className="text-2xl font-bold text-text-primary">{t("heading")}</h1>
            <span className="text-xs font-semibold px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-500/30">
              North Star A1/A2
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">{t("description")}</p>
        </div>

        {/* Task Selection & Run Action */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <label className="text-xs text-text-secondary font-medium">{t("suite-version")}:</label>
            <select
              value={suiteVersion}
              onChange={(e) => {
                const sv = e.target.value as "v1" | "v2";
                setSuiteVersion(sv);
                setSelectedTaskId(BENCHMARK_TASKS[sv]?.[0]?.id || "");
              }}
              className="bg-background-tertiary border border-border text-xs rounded px-2 py-1 text-text-primary"
              disabled={running}
            >
              <option value="v2">Sealed v2 (36 tasks)</option>
              <option value="v1">Sealed v1 (12 tasks)</option>
            </select>
          </div>

          <div className="flex items-center gap-2">
            <label className="text-xs text-text-secondary font-medium">{t("select-task")}:</label>
            <select
              value={selectedTaskId}
              onChange={(e) => {
                setSelectedTaskId(e.target.value);
                setCustomTaskId("");
              }}
              className="bg-background-tertiary border border-border text-xs rounded px-2 py-1 text-text-primary max-w-xs"
              disabled={running}
            >
              {BENCHMARK_TASKS[suiteVersion]?.map((tk) => (
                <option key={tk.id} value={tk.id}>
                  [{tk.id}] {tk.goal.slice(0, 42)}…
                </option>
              ))}
            </select>
          </div>

          <Button
            onClick={handleStartMatch}
            disabled={running || !activeTaskId}
            variant="primary"
            className="text-xs font-semibold px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white"
          >
            {running ? t("running-match") : t("run-match")}
          </Button>
        </div>
      </div>

      {error && (
        <div className="bg-red-950/50 border border-red-500/40 text-red-300 text-xs px-4 py-2.5 rounded-lg">
          {error}
        </div>
      )}

      {/* Task Goal Display */}
      {activeArena && (
        <Card className="bg-background-secondary border border-border p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <span className="text-xs font-mono uppercase tracking-wider text-text-tertiary">
                Task ID: {activeArena.task_id} ({activeArena.suite_version})
              </span>
              <p className="text-sm font-medium text-text-primary mt-1">{activeArena.goal}</p>
            </div>
            <div className="text-right">
              <span className="text-xs font-mono text-text-tertiary block">
                Arena ID: {activeArena.arena_id}
              </span>
              <span className="text-xs text-text-tertiary">
                Model: <span className="text-text-secondary font-mono">{activeArena.model}</span>
              </span>
            </div>
          </div>
        </Card>
      )}

      {/* Comparative Metrics Header Banner */}
      {activeArena && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Left Stats */}
          <Card className="p-4 bg-emerald-950/20 border border-emerald-500/30">
            <span className="text-xs font-semibold text-emerald-400 uppercase tracking-wider">
              {t("evoforge-lane")}
            </span>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-bold text-text-primary">
                {evoLane?.heldout.passed ?? 0}/{evoLane?.heldout.n ?? 0}
              </span>
              <span className="text-xs text-emerald-300 font-medium">hidden tests passed</span>
            </div>
            <div className="mt-2 text-xs text-text-secondary flex justify-between border-t border-emerald-500/20 pt-2">
              <span>{t("cost")}: <strong className="text-text-primary">{evoLane?.cost_cents ?? 0}¢</strong></span>
              <span>{t("attempts")}: <strong className="text-text-primary">{evoLane?.attempts ?? 0}</strong></span>
              <span>Outcome: <strong className="text-text-primary font-mono">{evoLane?.outcome ?? "—"}</strong></span>
            </div>
          </Card>

          {/* Verdict Banner (Center) */}
          <Card className={`p-4 border flex flex-col justify-center items-center text-center ${
            activeArena.verdict?.winner === "evoforge"
              ? "bg-emerald-950/40 border-emerald-500/50"
              : activeArena.verdict?.winner === "single"
              ? "bg-blue-950/40 border-blue-500/50"
              : "bg-background-tertiary border-border"
          }`}>
            <span className="text-xs uppercase tracking-wider text-text-tertiary font-bold mb-1">
              {t("winner-label")}
            </span>
            {activeArena.status === "running" ? (
              <div className="flex items-center gap-2 text-amber-400 font-semibold text-sm">
                <span className="animate-spin text-base">⚙️</span>
                <span>{t("running-match")}</span>
              </div>
            ) : (
              <div>
                <span className={`text-base font-extrabold ${
                  activeArena.verdict?.winner === "evoforge"
                    ? "text-emerald-400"
                    : activeArena.verdict?.winner === "single"
                    ? "text-blue-400"
                    : "text-text-secondary"
                }`}>
                  {activeArena.verdict?.winner === "evoforge"
                    ? "🏆 " + t("winner-evoforge")
                    : activeArena.verdict?.winner === "single"
                    ? "🤖 " + t("winner-single")
                    : "🤝 " + t("winner-tie")}
                </span>
                <p className="text-xs text-text-tertiary mt-1 max-w-sm">
                  {activeArena.verdict?.reason}
                </p>
              </div>
            )}
          </Card>

          {/* Right Stats */}
          <Card className="p-4 bg-blue-950/20 border border-blue-500/30">
            <span className="text-xs font-semibold text-blue-400 uppercase tracking-wider">
              {t("single-lane")}
            </span>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-bold text-text-primary">
                {singleLane?.heldout.passed ?? 0}/{singleLane?.heldout.n ?? 0}
              </span>
              <span className="text-xs text-blue-300 font-medium">hidden tests passed</span>
            </div>
            <div className="mt-2 text-xs text-text-secondary flex justify-between border-t border-blue-500/20 pt-2">
              <span>{t("cost")}: <strong className="text-text-primary">{singleLane?.cost_cents ?? 0}¢</strong></span>
              <span>{t("attempts")}: <strong className="text-text-primary">{singleLane?.attempts ?? 0}</strong></span>
              <span>Outcome: <strong className="text-text-primary font-mono">{singleLane?.outcome ?? "—"}</strong></span>
            </div>
          </Card>
        </div>
      )}

      {/* Split-Screen Lanes */}
      {activeArena && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* LEFT LANE: EvoForge */}
          <div className="space-y-4">
            <div className="flex items-center justify-between border-b-2 border-emerald-500/60 pb-2">
              <div>
                <h2 className="text-base font-bold text-emerald-400 flex items-center gap-2">
                  <span>⚡</span> {t("evoforge-lane")}
                </h2>
                <span className="text-xs text-text-tertiary">{t("evoforge-sub")}</span>
              </div>
              <StatusPill
                status={evoLane?.status || "pending"}
                passed={evoLane?.heldout.passed}
                n={evoLane?.heldout.n}
              />
            </div>

            {/* Diff Viewer */}
            <Card className="bg-background-secondary border border-border p-3 space-y-2">
              <div className="flex items-center justify-between text-xs text-text-tertiary font-mono">
                <span>{t("patch")}</span>
                <span>{evoLane?.diff ? `${evoLane.diff.length} chars` : "No patch"}</span>
              </div>
              <pre className="text-xs font-mono bg-black/60 p-3 rounded overflow-x-auto max-h-64 text-emerald-300 whitespace-pre">
                {evoLane?.diff || "// Waiting for candidate patch generation…"}
              </pre>
            </Card>

            {/* Event Timeline */}
            <Card className="bg-background-secondary border border-border p-3 space-y-2">
              <span className="text-xs font-semibold text-text-tertiary uppercase tracking-wider block">
                {t("events")} ({evoLane?.events.length || 0})
              </span>
              <div className="space-y-1.5 max-h-56 overflow-y-auto font-mono text-xs pr-1">
                {evoLane?.events.map((ev, i) => (
                  <div key={i} className="flex items-start gap-2 text-text-secondary bg-background-tertiary/40 px-2 py-1 rounded">
                    <span className="text-text-tertiary text-[10px] w-8">#{ev.seq}</span>
                    <span className={`text-[10px] uppercase font-bold px-1.5 py-0.5 rounded ${
                      ev.role === "builder" ? "bg-purple-900/40 text-purple-300" :
                      ev.role === "critic" ? "bg-blue-900/40 text-blue-300" :
                      ev.role === "runner" ? "bg-emerald-900/40 text-emerald-300" :
                      "bg-amber-900/40 text-amber-300"
                    }`}>
                      {ev.role}
                    </span>
                    <span className="text-text-primary flex-1 break-words">{ev.message}</span>
                  </div>
                ))}
              </div>
            </Card>
          </div>

          {/* RIGHT LANE: Single AI */}
          <div className="space-y-4">
            <div className="flex items-center justify-between border-b-2 border-blue-500/60 pb-2">
              <div>
                <h2 className="text-base font-bold text-blue-400 flex items-center gap-2">
                  <span>🤖</span> {t("single-lane")}
                </h2>
                <span className="text-xs text-text-tertiary">{t("single-sub")}</span>
              </div>
              <StatusPill
                status={singleLane?.status || "pending"}
                passed={singleLane?.heldout.passed}
                n={singleLane?.heldout.n}
              />
            </div>

            {/* Diff Viewer */}
            <Card className="bg-background-secondary border border-border p-3 space-y-2">
              <div className="flex items-center justify-between text-xs text-text-tertiary font-mono">
                <span>{t("patch")}</span>
                <span>{singleLane?.diff ? `${singleLane.diff.length} chars` : "No patch"}</span>
              </div>
              <pre className="text-xs font-mono bg-black/60 p-3 rounded overflow-x-auto max-h-64 text-blue-300 whitespace-pre">
                {singleLane?.diff || "// Waiting for candidate patch generation…"}
              </pre>
            </Card>

            {/* Event Timeline */}
            <Card className="bg-background-secondary border border-border p-3 space-y-2">
              <span className="text-xs font-semibold text-text-tertiary uppercase tracking-wider block">
                {t("events")} ({singleLane?.events.length || 0})
              </span>
              <div className="space-y-1.5 max-h-56 overflow-y-auto font-mono text-xs pr-1">
                {singleLane?.events.map((ev, i) => (
                  <div key={i} className="flex items-start gap-2 text-text-secondary bg-background-tertiary/40 px-2 py-1 rounded">
                    <span className="text-text-tertiary text-[10px] w-8">#{ev.seq}</span>
                    <span className={`text-[10px] uppercase font-bold px-1.5 py-0.5 rounded ${
                      ev.role === "builder" ? "bg-purple-900/40 text-purple-300" :
                      ev.role === "critic" ? "bg-blue-900/40 text-blue-300" :
                      ev.role === "runner" ? "bg-emerald-900/40 text-emerald-300" :
                      "bg-amber-900/40 text-amber-300"
                    }`}>
                      {ev.role}
                    </span>
                    <span className="text-text-primary flex-1 break-words">{ev.message}</span>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </div>
      )}

      {/* Recent Matches List */}
      <div className="mt-12 pt-8 border-t border-border">
        <h3 className="text-base font-bold text-text-primary mb-4 flex items-center gap-2">
          <span>📜</span> {t("recent-matches")}
        </h3>
        {recentArenas.length === 0 ? (
          <p className="text-xs text-text-tertiary">{t("empty-matches")}</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {recentArenas.map((ar) => (
              <div
                key={ar.arena_id}
                onClick={() => setActiveArena(ar)}
                className={`p-3 rounded-lg cursor-pointer transition border hover:border-emerald-500/60 ${
                  activeArena?.arena_id === ar.arena_id
                    ? "border-emerald-500 bg-emerald-950/20"
                    : "border-border bg-background-secondary"
                }`}
              >
                <div className="flex items-center justify-between text-xs font-mono text-text-tertiary">
                  <span>{ar.arena_id}</span>
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                    ar.verdict?.winner === "evoforge" ? "bg-emerald-950 text-emerald-300 border border-emerald-500/30" :
                    ar.verdict?.winner === "single" ? "bg-blue-950 text-blue-300 border border-blue-500/30" :
                    "bg-slate-800 text-slate-300"
                  }`}>
                    {ar.verdict?.winner || ar.status}
                  </span>
                </div>
                <p className="text-xs font-medium text-text-primary mt-1.5 line-clamp-2">
                  [{ar.task_id}] {ar.goal}
                </p>
                <div className="flex items-center justify-between text-[11px] text-text-secondary mt-2 pt-2 border-t border-border/50">
                  <span>Evo: {ar.lanes?.evoforge?.heldout?.passed ?? 0}/{ar.lanes?.evoforge?.heldout?.n ?? 0}</span>
                  <span>Single: {ar.lanes?.single?.heldout?.passed ?? 0}/{ar.lanes?.single?.heldout?.n ?? 0}</span>
                  <span className="font-semibold text-emerald-400">
                    {(ar.lanes?.evoforge?.cost_cents ?? 0) + (ar.lanes?.single?.cost_cents ?? 0)}¢
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
