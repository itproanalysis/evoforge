"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  getArena,
  getArenaLimits,
  getArenaSummary,
  getPromptChain,
  listArenas,
  postArena,
  type ArenaDoc,
  type ArenaSummary,
} from "../../../lib/api";
import { planFits } from "../../../lib/challenges";
import { Button, Card } from "../../../components/ui";
import { laneView, arenaVerdict, arenaCost, costLabel, manifestView, previewView, promptArenaView, canFollowUp, promptChainView } from "../../../lib/arenaStatus";
import { SandboxedPreview } from "../../../components/SandboxedPreview";
import { PromptBar } from "../../../components/PromptBar";
import { shareUrl } from "../../../lib/share";

const BENCHMARK_TASKS: Record<"v1" | "v2" | "v3" | "v4" | "v5", { id: string; goal: string }[]> = {
  v5: [
    { id: "SV5-AO-01", goal: "In semver_range.py, check if a version satisfies an npm-style range" },
    { id: "SV5-AO-02", goal: "In intervals.py, merge labelled half-open intervals by priority" },
    { id: "SV5-CD-01", goal: "In reassemble.py, rebuild chat messages from out-of-order chunks" },
    { id: "SV5-CD-02", goal: "In retry.py, compute backoff waits with cap, jitter and budget" },
    { id: "SV5-CI-01", goal: "In shard_plan.py, split CI tests across shards with pinning" },
    { id: "SV5-CI-02", goal: "In junit_merge.py, merge CI attempts into final suite results" },
    { id: "SV5-PM-01", goal: "In tokens.py and calc.py, tokenize and evaluate expressions" },
    { id: "SV5-PM-02", goal: "In money.py and invoice.py, price invoice lines with tax" },
    { id: "SV5-SEC-01", goal: "In path_guard.py, join user paths safely under a root" },
    { id: "SV5-SEC-02", goal: "In jwt_lite.py, verify HS256 JWTs and return payload" },
    { id: "SV5-SS-01", goal: "In duration.py, parse and format durations like 1h30m" },
    { id: "SV5-SS-02", goal: "In slugify.py, make URL slugs like cafe-au-lait" },
  ],
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
  v3: [
    { id: "SV3-AO-01", goal: "In bsearch.py, bsearch(seq, target) returns index in sorted sequence, or -1" },
    { id: "SV3-AO-02", goal: "In topk.py, topk(items, k) returns the k largest elements in descending order" },
    { id: "SV3-AO-03", goal: "In dedupe.py, dedupe(items) removes duplicates, keeping first occurrence order" },
    { id: "SV3-AO-04", goal: "In window.py, max_window_sum(values, k) returns the largest sum of k consecutive values" },
    { id: "SV3-CI-01", goal: "In ci.py, saturated build queue fair scheduler" },
    { id: "SV3-SS-01", goal: "In auth.py, constant-time token comparison" },
  ],
  v4: [
    { id: "SV4-AO-01", goal: "In barchart.py, render(values, ...) returns an SVG bar chart" },
    { id: "SV4-AO-02", goal: "In sparkline.py, render(points, ...) returns an SVG sparkline" },
    { id: "SV4-CD-01", goal: "In transcript.py, render(messages) returns an ordered transcript list" },
    { id: "SV4-CI-01", goal: "In results_table.py, render(results) returns a results table" },
    { id: "SV4-SEC-01", goal: "In comment.py, render(author, text) returns an escaped comment article" },
    { id: "SV4-SS-01", goal: "In badge.py, render(status) returns a status badge span" },
  ],
};

function StatusPill({ status, passed, n }: { status: string; passed?: number; n?: number }) {
  const t = useTranslations("arena");
  if (status === "running") {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
        RUNNING
      </span>
    );
  }
  if (status === "succeeded") {
    if (passed !== undefined && n !== undefined && n > 0 && passed >= n) {
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
          ALL PASS ({passed}/{n})
        </span>
      );
    }
    if (passed !== undefined && n !== undefined && n > 0 && passed >= 0 && passed < n) return (
      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-50 text-rose-700 border border-rose-200">
        FAILED ({passed ?? 0}/{n ?? 0})
      </span>
    );
    return <span className="text-xs text-text-secondary">{t("result-unconfirmed")}</span>;
  }
  return (
    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-600 border border-slate-200">
      {status === "failed" ? t("status-failed") : status === "pending" ? t("status-pending") : status === "inconclusive" ? t("status-inconclusive") : status.toUpperCase()}
    </span>
  );
}

export default function ArenaPage() {
  const t = useTranslations("arena");
  const locale = useLocale();
  const tp = useTranslations("plan");
  const [suiteVersion, setSuiteVersion] = useState<"v1" | "v2" | "v3" | "v4" | "v5">("v5");
  const [selectedTaskId, setSelectedTaskId] = useState<string>("SV5-AO-01");
  const [customTaskId, setCustomTaskId] = useState<string>("");
  const [feedback, setFeedback] = useState<"heldout" | "critic">("critic");
  const [starting, setStarting] = useState(false);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [pollError, setPollError] = useState(false);
  const [activeArena, setActiveArena] = useState<ArenaDoc | null>(null);
  const [recentArenas, setRecentArenas] = useState<ArenaDoc[]>([]);
  const [summary, setSummary] = useState<ArenaSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chainRounds, setChainRounds] = useState<ArenaDoc[] | null>(null);
  const [selectedRoundId, setSelectedRoundId] = useState<string | null>(null);
  const [limits, setLimits] = useState<{ daily_limit: number; used_today: number; remaining: number } | null>(null);

  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const activeTaskId = customTaskId.trim() || selectedTaskId;
  const trackedId = pendingId ?? (activeArena?.status === "running" ? activeArena.arena_id : null);
  const running = starting || !!trackedId;

  // Load recent arenas
  const refreshSummary = async () => {
    try {
      const s = await getArenaSummary();
      if (s && typeof s === "object") {
        setSummary(s);
      }
    } catch (e) {
      console.warn("Failed to load arena summary", e);
    }
  };

  const refreshRecent = async () => {
    try {
      const res = await listArenas();
      if (res && Array.isArray(res.arenas)) {
        setRecentArenas(res.arenas);
      }
    } catch (e) {
      console.warn("Failed to list arenas", e);
    }
    try {
      const lim = await getArenaLimits();
      if (lim && typeof lim === "object") setLimits(lim);
    } catch {}
    void refreshSummary();
  };

  useEffect(() => {
    refreshRecent();
    void getArenaLimits().then((lim) => {
      if (lim && typeof lim === "object") setLimits(lim);
    }).catch(() => {});
  }, []);

  // Poll the returned server ID. A failed lookup pauses polling so the user
  // can retry the same job without accidentally starting another paid job.
  useEffect(() => {
    if (!trackedId || pollError) return;
    let active = true;
    let inFlight = false;
    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const doc = await getArena(trackedId);
        if (!active) return;
        if (doc.arena_id !== trackedId) throw new Error("arena id mismatch");
        setActiveArena(doc);
        setPendingId(null);
        setError(null);
        if (doc.status !== "running") void refreshRecent();
      } catch {
        if (active) {
          setPollError(true);
          setError(t("poll-error"));
        }
      } finally {
        inFlight = false;
      }
    };
    void poll();
    pollRef.current = setInterval(() => void poll(), 1500);
    return () => {
      active = false;
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [trackedId, pollError]);

  const isPromptArena = activeArena?.mode === "prompt";
  const chainArenaId = isPromptArena ? activeArena?.arena_id ?? null : null;

  // Load the prompt chain for a prompt arena and poll it while the newest
  // round is still running.
  useEffect(() => {
    if (!chainArenaId) {
      setSelectedRoundId(null);
      return;
    }
    let cancelled = false;
    let inFlight = false;
    let timer: NodeJS.Timeout | null = null;
    const load = async () => {
      if (inFlight || cancelled) return;
      inFlight = true;
      try {
        const res = await getPromptChain(chainArenaId);
        if (cancelled) return;
        if (res && Array.isArray(res.rounds)) {
          setChainRounds(res.rounds);
          const rows = promptChainView(res.rounds);
          const newest = rows[rows.length - 1];
          if (newest && !newest.running && timer) {
            clearInterval(timer);
            timer = null;
          }
        }
      } catch {
        // Keep the last confirmed chain while polling.
      } finally {
        inFlight = false;
      }
    };
    void load();
    timer = setInterval(() => void load(), 1500);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [chainArenaId]);

  const handleStartMatch = async () => {
    if (!activeTaskId || running) return;
    // Starting an arena spends model credits: anyone may start within the
    // server's daily limit, with a cost warning confirmed up front.
    let remaining: number | null = limits ? limits.remaining : null;
    try {
      const lim = await getArenaLimits();
      if (lim && typeof lim === "object") {
        setLimits(lim);
        remaining = lim.remaining;
      }
    } catch {}
    if (!planFits(remaining, 1)) return;
    if (typeof window !== "undefined" && !window.confirm(t("cost-confirm"))) return;
    setError(null);
    setPollError(false);
    setStarting(true);
    setActiveArena(null);
    try {
      const res = await postArena(activeTaskId, suiteVersion, feedback);
      if (!res?.arena_id) throw new Error("missing arena id");
      setPendingId(res.arena_id);
    } catch (cause) {
      const status = cause instanceof Error ? /^(\d{3})\b/.exec(cause.message)?.[1] : undefined;
      const reason = status === "402" ? t("error-budget")
        : status ? t("error-http", { status })
          : t("error-noresponse");
      setError(`${reason} ${t("error-hint")}`);
      void refreshRecent();
    } finally {
      setStarting(false);
    }
  };

  const singleLane = activeArena?.lanes?.single;
  const evoLane = activeArena?.lanes?.evoforge;
  const evoView = laneView(evoLane);
  const singleView = laneView(singleLane);
  const manifest = manifestView(activeArena);
  const promptView = promptArenaView(activeArena);
  const evoPreview = previewView(evoLane);
  const singlePreview = previewView(singleLane);
  const verdict = arenaVerdict(activeArena);
  const limitBlocked = limits !== null && !planFits(limits.remaining, 1);
  const verificationInconclusive = activeArena?.verdict?.winner === "inconclusive"
    || evoView.outcome === "verification_inconclusive" || singleView.outcome === "verification_inconclusive";
  const chainView = isPromptArena
    ? promptChainView(chainRounds ?? (activeArena ? [activeArena] : []))
    : [];
  const selectedChainRow = chainView.find((r) => r.arenaId === selectedRoundId)
    ?? chainView[chainView.length - 1] ?? null;
  const followUpArena = canFollowUp(activeArena) ? activeArena : null;

  return (
    <div className="mx-auto pb-40 space-y-8">
      {/* Header */}
      <header className="arena-header">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">{t("heading")}</h1>
          <p className="text-sm text-text-secondary mt-1">{t("description")}</p>
        </div>
        <span className="arena-quota" role="status">
          {limits
            ? tp("remaining-today", { remaining: limits.remaining, total: limits.daily_limit })
            : tp("remaining-today", { remaining: "—", total: "—" })}
        </span>
      </header>
      {limitBlocked && (
        <p role="alert" className="text-xs text-text-secondary">{tp("limit-reached")}</p>
      )}

      {/* Scoreboard over every stored arena match */}
      {summary && (() => {
        const eq = summary.equal_tools;
        const wins = eq?.wins ?? { evoforge: 0, single: 0, tie: 0 };
        const share = (h: { passed: number; n: number } | undefined) => (h && h.n > 0 ? Math.round((100 * h.passed) / h.n) : 0);
        const stats = eq?.stats;
        const p = stats?.sign_test_p;
        const pText = typeof p === "number" && Number.isFinite(p) ? String(p) : "—";
        const significant = typeof p === "number" && Number.isFinite(p) ? p < 0.05 : !!stats?.significant;
        const lanes = [
          { key: "evoforge", label: t("summary-heldout-evoforge"), h: eq?.heldout?.evoforge, cost: eq?.cost_cents?.evoforge ?? 0 },
          { key: "single", label: t("summary-heldout-single"), h: eq?.heldout?.single, cost: eq?.cost_cents?.single ?? 0 },
        ];
        return (
          <section className="arena-board" aria-labelledby="arena-board-title">
            <div className="arena-board-head">
              <div>
                <h2 id="arena-board-title">{t("summary-heading")}</h2>
                <p>{t("board-sub", { n: eq?.scored ?? 0 })}</p>
              </div>
              <span className="arena-chip">{t("summary-equal-tools")}</span>
            </div>
            <div className="arena-tiles">
              <div className="arena-tile is-evoforge"><span>{t("summary-evoforge-wins")}</span><strong>{wins.evoforge ?? 0}</strong></div>
              <div className="arena-tile is-single"><span>{t("summary-single-wins")}</span><strong>{wins.single ?? 0}</strong></div>
              <div className="arena-tile"><span>{t("summary-ties")}</span><strong>{wins.tie ?? 0}</strong></div>
            </div>
            <div className="arena-bars">
              <p className="arena-bars-title">{t("hidden-tests")}</p>
              {lanes.map((lane) => (
                <div key={lane.key} className={`arena-bar is-${lane.key}`}>
                  <span className="arena-bar-label">{lane.label}</span>
                  <span className="arena-bar-track"><span style={{ width: `${share(lane.h)}%` }} /></span>
                  <span className="arena-bar-value">{share(lane.h)}% <small>{lane.h?.passed ?? 0}/{lane.h?.n ?? 0} · {lane.cost}¢</small></span>
                </div>
              ))}
            </div>
            <p className={`arena-verdict${significant ? " is-significant" : ""}`}>
              {significant ? t("summary-significant", { p: pText }) : t("summary-not-significant", { p: pText })}
            </p>
            <details className="arena-more">
              <summary>{t("summary-all-matches")}</summary>
              <dl className="arena-more-grid">
                <div><dt>{t("summary-total")}</dt><dd>{summary.total ?? 0}</dd></div>
                <div><dt>{t("summary-scored")}</dt><dd>{summary.scored ?? 0}</dd></div>
                <div><dt>{t("summary-evoforge-wins")}</dt><dd>{summary.wins?.evoforge ?? 0}</dd></div>
                <div><dt>{t("summary-single-wins")}</dt><dd>{summary.wins?.single ?? 0}</dd></div>
                <div><dt>{t("summary-ties")}</dt><dd>{summary.wins?.tie ?? 0}</dd></div>
                <div><dt>{t("summary-running")}</dt><dd>{summary.running ?? 0}</dd></div>
                <div><dt>{t("summary-failed")}</dt><dd>{summary.failed ?? 0}</dd></div>
                <div><dt>{t("summary-unscorable")}</dt><dd>{summary.unscorable ?? 0}</dd></div>
                <div><dt>{t("summary-inconclusive")}</dt><dd>{summary.inconclusive ?? 0}</dd></div>
                <div><dt>{t("summary-heldout-evoforge")}</dt><dd>{summary.heldout?.evoforge?.passed ?? 0}/{summary.heldout?.evoforge?.n ?? 0}</dd></div>
                <div><dt>{t("summary-heldout-single")}</dt><dd>{summary.heldout?.single?.passed ?? 0}/{summary.heldout?.single?.n ?? 0}</dd></div>
                <div><dt>{t("summary-cost-judge")}</dt><dd>{summary.cost_cents?.judge ?? 0}¢</dd></div>
              </dl>
              {typeof summary.basis === "string" && summary.basis.length > 0 && (
                <p className="arena-basis">{summary.basis}</p>
              )}
            </details>
          </section>
        );
      })()}

      <details className="arena-bench">
        <summary>
          <span>
            <strong>{t("bench-title")}</strong>
            <small>{t("bench-sub")}</small>
          </span>
        </summary>
        {/* Task Selection & Run Action */}
        <div className="arena-bench-controls">
          <div className="flex items-center gap-2 w-full sm:w-auto min-w-0">
            <label className="text-xs text-text-secondary font-medium shrink-0">{t("suite-version")}:</label>
            <select
              value={suiteVersion}
              onChange={(e) => {
                const sv = e.target.value as "v1" | "v2" | "v3" | "v4" | "v5";
                setSuiteVersion(sv);
                setSelectedTaskId(BENCHMARK_TASKS[sv]?.[0]?.id || "");
              }}
              className="bg-background-tertiary border border-border text-xs rounded px-2 py-1 text-text-primary flex-1 min-w-0 sm:flex-none"
              disabled={running}
            >
              <option value="v5">Sealed v5 (12 hard tasks)</option>
              <option value="v4">Sealed v4 (12 tasks)</option>
              <option value="v3">Sealed v3 (48 tasks)</option>
              <option value="v2">Sealed v2 (36 tasks)</option>
              <option value="v1">Sealed v1 (12 tasks)</option>
            </select>
          </div>

          <div className="flex items-center gap-2 w-full sm:w-auto min-w-0">
            <label className="text-xs text-text-secondary font-medium shrink-0">{t("feedback-label")}:</label>
            <select
              value={feedback}
              onChange={(e) => setFeedback(e.target.value as "heldout" | "critic")}
              className="bg-background-tertiary border border-border text-xs rounded px-2 py-1 text-text-primary flex-1 min-w-0 sm:flex-none"
              disabled={running}
              aria-label={t("feedback-label")}
            >
              <option value="critic">{t("feedback-critic")}</option>
              <option value="heldout">{t("feedback-heldout")}</option>
            </select>
          </div>

          <div className="flex items-center gap-2 w-full sm:w-auto min-w-0">
            <label className="text-xs text-text-secondary font-medium shrink-0">{t("select-task")}:</label>
            <select
              value={selectedTaskId}
              onChange={(e) => {
                setSelectedTaskId(e.target.value);
                setCustomTaskId("");
              }}
              className="bg-background-tertiary border border-border text-xs rounded px-2 py-1 text-text-primary flex-1 min-w-0 sm:flex-none sm:max-w-xs"
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
            disabled={running || !activeTaskId || limitBlocked}
            variant="primary"
            className="text-sm font-semibold px-4 py-2"
            title={limitBlocked ? tp("limit-reached") : undefined}
          >
            {running ? t("running-match") : t("run-match")}
          </Button>
          <span className="text-xs text-text-secondary" role="status">
            {limits
              ? tp("remaining-today", { remaining: limits.remaining, total: limits.daily_limit })
              : tp("remaining-today", { remaining: "—", total: "—" })}
          </span>
        </div>
      </details>

      {error && (
        <div role="alert" className="bg-red-50 border border-red-200 text-red-700 text-xs px-4 py-2.5 rounded-lg">
          {error}
          {pollError && trackedId && <button type="button" onClick={() => { setPollError(false); setError(null); }} className="ml-3 underline">{t("retry-status")}</button>}
        </div>
      )}
      {starting && <p className="text-sm text-text-secondary">{t("requesting")}</p>}
      {pendingId && !activeArena && <p className="text-sm text-text-secondary">{t("checking", { id: pendingId })}</p>}
      {activeArena?.status === "failed" && <p role="alert" className="text-sm text-red-700">{t("run-failed")}: {activeArena.error || t("run-no-reason")} {t("run-retry-hint")}</p>}

      {/* Task Goal Display */}
      {activeArena && (
        <Card className="bg-background-secondary border border-border p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <span className="arena-chip">
                {activeArena.task_id} · {activeArena.suite_version}
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
              {(activeArena.status === "succeeded" || activeArena.status === "failed") && (
                <a className="arena-share-link" href={shareUrl("", locale, activeArena.arena_id)}>{t("open-result")} →</a>
              )}
            </div>
          </div>
        </Card>
      )}

      {/* Fairness manifest strip */}
      {activeArena && manifest && (
        <Card className="bg-background-secondary border border-border p-4">
          <span className="text-xs font-semibold text-text-tertiary uppercase tracking-wider block">
            {t("manifest-heading")}
          </span>
          <div className="mt-2 grid grid-cols-1 md:grid-cols-3 gap-2 text-xs font-mono">
            <span className="text-text-secondary">{t("manifest-spec")}: <strong className="text-text-primary">{manifest.spec ?? "—"}</strong></span>
            <span className="text-text-secondary">{t("manifest-heldout")}: <strong className="text-text-primary">{manifest.heldout ?? "—"}</strong></span>
            <span className="text-text-secondary">{t("manifest-base")}: <strong className="text-text-primary">{manifest.baseTree ?? "—"}</strong></span>
          </div>
          <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
            <span className="text-text-secondary">
              {t("evoforge-lane")}: {t("manifest-harness")} <strong className="text-text-primary font-mono">{manifest.evoforge.harness ?? "—"}</strong>
              {" · "}{t("attempts")} <strong className="text-text-primary">{manifest.evoforge.attempts ?? "—"}</strong>
              {" · "}{t("feedback-label")} <strong className="text-text-primary font-mono">{manifest.evoforge.feedback ?? "—"}</strong>
            </span>
            <span className="text-text-secondary">
              {t("single-lane")}: {t("manifest-harness")} <strong className="text-text-primary font-mono">{manifest.single.harness ?? "—"}</strong>
              {" · "}{t("attempts")} <strong className="text-text-primary">{manifest.single.attempts ?? "—"}</strong>
              {" · "}{t("feedback-label")} <strong className="text-text-primary font-mono">{manifest.single.feedback ?? "—"}</strong>
            </span>
          </div>
          {manifest.upperBound && (
            <p role="note" className="mt-2 text-xs font-semibold text-amber-700">
              {t("manifest-upper-bound")}
            </p>
          )}
          {manifest.disclosure && (
            <p className="mt-2 text-xs text-text-tertiary">{manifest.disclosure}</p>
          )}
        </Card>
      )}

      {/* Comparative Metrics Header Banner */}
      {activeArena && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Left Stats */}
          <Card className="p-4 bg-emerald-50 border border-emerald-200">
            <span className="text-xs font-semibold text-emerald-700 uppercase tracking-wider">
              {t("evoforge-lane")}
            </span>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-bold text-text-primary">
                {evoView.score ?? (evoView.outcome === "verification_inconclusive" ? t("status-inconclusive") : evoView.status === "failed" ? t("status-failed") : t("status-waiting"))}
              </span>
              {evoView.score && <span className="text-xs text-emerald-700 font-medium">{t("sealed-pass")}</span>}
            </div>
            <div className="mt-2 text-xs text-text-secondary flex justify-between border-t border-emerald-200 pt-2">
              <span>{costLabel(evoView.costState)}: <strong className="text-text-primary">{evoView.cost === null ? "—" : `${evoView.cost}¢`}</strong></span>
              <span>{t("attempts")}: <strong className="text-text-primary">{evoView.attempts ?? "—"}</strong></span>
              <span>{t("result-label")}: <strong className="text-text-primary font-mono">{evoView.outcome ?? t("outcome-unknown")}</strong></span>
            </div>
          </Card>

          {/* Verdict Banner (Center) */}
          <Card className={`p-4 border flex flex-col justify-center items-center text-center ${
            verdict?.winner === "evoforge"
              ? "bg-emerald-50 border-emerald-200"
              : verdict?.winner === "single"
              ? "bg-blue-50 border-blue-200"
              : "bg-background-tertiary border-border"
          }`}>
            <span className="text-xs uppercase tracking-wider text-text-tertiary font-bold mb-1">
              {t("winner-label")}
            </span>
            {activeArena.status === "running" ? (
              <div className="flex items-center gap-2 text-amber-700 font-semibold text-sm">
                <span aria-hidden="true" className="inline-block h-3.5 w-3.5 rounded-full border-2 border-amber-200 border-t-amber-600 animate-spin"></span>
                <span>{t("running-match")}</span>
              </div>
            ) : !verdict ? (
              <div className="text-text-secondary text-sm">{verificationInconclusive ? t("verdict-inconclusive") : activeArena.status === "failed" ? t("verdict-failed") : t("result-unconfirmed")}</div>
            ) : (
              <div>
                <span className={`text-base font-extrabold ${
                  verdict.winner === "evoforge"
                    ? "text-emerald-700"
                    : verdict.winner === "single"
                    ? "text-blue-700"
                    : "text-text-secondary"
                }`}>
                  {verdict.winner === "evoforge"
                    ? t("winner-evoforge")
                    : verdict.winner === "single"
                    ? t("winner-single")
                    : t("winner-tie")}
                </span>
                <p className="text-xs text-text-tertiary mt-1 max-w-sm">
                  {verdict.reason}
                </p>
              </div>
            )}
          </Card>

          {/* Right Stats */}
          <Card className="p-4 bg-blue-50 border border-blue-200">
            <span className="text-xs font-semibold text-blue-700 uppercase tracking-wider">
              {t("single-lane")}
            </span>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-bold text-text-primary">
                {singleView.score ?? (singleView.outcome === "verification_inconclusive" ? t("status-inconclusive") : singleView.status === "failed" ? t("status-failed") : t("status-waiting"))}
              </span>
              {singleView.score && <span className="text-xs text-blue-700 font-medium">{t("sealed-pass")}</span>}
            </div>
            <div className="mt-2 text-xs text-text-secondary flex justify-between border-t border-blue-200 pt-2">
              <span>{costLabel(singleView.costState)}: <strong className="text-text-primary">{singleView.cost === null ? "—" : `${singleView.cost}¢`}</strong></span>
              <span>{t("attempts")}: <strong className="text-text-primary">{singleView.attempts ?? "—"}</strong></span>
              <span>{t("result-label")}: <strong className="text-text-primary font-mono">{singleView.outcome ?? t("outcome-unknown")}</strong></span>
            </div>
          </Card>
        </div>
      )}

      {/* Prompt-arena acceptance panel (above the lanes) */}
      {activeArena && promptView && (
        <Card className="bg-background-secondary border border-border p-4">
          <span className="text-xs font-semibold text-text-tertiary uppercase tracking-wider block">
            {t("prompt-heading")}
          </span>
          <p className="text-sm font-medium text-text-primary mt-1 whitespace-pre-wrap">{promptView.prompt}</p>
          <p className="mt-2 text-xs text-text-secondary">
            {t("prompt-acceptance", { count: promptView.acceptanceCount, dropped: promptView.dropped })}
          </p>
          {promptView.scorable === false && (
            <p role="alert" className="mt-2 text-xs font-semibold text-amber-700">
              {t("prompt-unscorable")}
            </p>
          )}
          <p className="mt-2 text-xs text-text-secondary">
            {t("prompt-judge-cost", { cost: promptView.judgeCost })}
          </p>
          {promptView.judge && (
            <p className="mt-1 text-xs text-text-tertiary">{promptView.judge}</p>
          )}
        </Card>
      )}

      {/* Prompt-chain round timeline (above the lanes) */}
      {activeArena && promptView && chainView.length > 0 && (
        <Card className="bg-background-secondary border border-border p-4">
          <span className="text-xs font-semibold text-text-tertiary uppercase tracking-wider block">
            {t("prompt-chain-title")}
          </span>
          <div className="mt-2 flex flex-wrap gap-2">
            {chainView.map((row) => {
              const badge = row.running
                ? t("prompt-chain-running")
                : row.unscorable
                  ? t("prompt-chain-unscorable")
                  : row.winner
                    ? t(`winner-${row.winner}` as "winner-evoforge")
                    : t("prompt-chain-unscorable");
              const selected = selectedChainRow?.arenaId === row.arenaId;
              return (
                <button
                  key={row.arenaId || `r${row.round}`}
                  type="button"
                  onClick={() => setSelectedRoundId(row.arenaId)}
                  aria-pressed={selected}
                  className={`px-2.5 py-1.5 rounded text-xs border text-left ${selected ? "border-emerald-500 bg-emerald-50" : "border-border bg-background-tertiary/40"}`}
                >
                  <span className="font-bold font-mono">R{row.round}</span>
                  <span className="block max-w-56 truncate text-text-secondary">{row.prompt}</span>
                  <span className="block font-mono text-text-secondary">
                    {t("prompt-chain-single")}: {row.single} · {t("prompt-chain-evoforge")}: {row.evoforge}
                  </span>
                  <span className="block text-text-tertiary">{badge}</span>
                </button>
              );
            })}
          </div>
          {selectedChainRow && (
            <div className="mt-3 space-y-2">
              <p className="text-sm font-medium text-text-primary whitespace-pre-wrap">
                {t("prompt-chain-round", { n: selectedChainRow.round })}: {selectedChainRow.prompt}
              </p>
              <p className="text-xs text-text-secondary font-mono">
                {t("prompt-chain-single")}: {selectedChainRow.single} · {t("prompt-chain-evoforge")}: {selectedChainRow.evoforge}
                {" · "}{t("prompt-chain-winner")}: {selectedChainRow.winner ?? (selectedChainRow.running ? t("prompt-chain-running") : t("prompt-chain-unscorable"))}
              </p>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div className="space-y-1">
                  <span className="text-xs text-text-tertiary font-mono">{t("evoforge-lane")}</span>
                  {selectedChainRow.evoforgePreview ? (
                    <SandboxedPreview html={selectedChainRow.evoforgePreview} title={`chain-${selectedChainRow.arenaId}-evoforge`} />
                  ) : (
                    <p className="text-xs text-text-tertiary">{t("preview-pending")}</p>
                  )}
                </div>
                <div className="space-y-1">
                  <span className="text-xs text-text-tertiary font-mono">{t("single-lane")}</span>
                  {selectedChainRow.singlePreview ? (
                    <SandboxedPreview html={selectedChainRow.singlePreview} title={`chain-${selectedChainRow.arenaId}-single`} />
                  ) : (
                    <p className="text-xs text-text-tertiary">{t("preview-pending")}</p>
                  )}
                </div>
              </div>
            </div>
          )}
        </Card>
      )}

      {/* Split-Screen Lanes */}
      {activeArena && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* LEFT LANE: EvoForge */}
          <div className="space-y-4">
            <div className="flex items-center justify-between border-b-2 border-emerald-200 pb-2">
              <div>
                <h2 className="text-base font-bold text-emerald-700 flex items-center gap-2">
                  {t("evoforge-lane")}
                </h2>
                <span className="text-xs text-text-tertiary">{t("evoforge-sub")}</span>
              </div>
              <StatusPill
                status={evoView.outcome === "verification_inconclusive" ? "inconclusive" : evoView.status}
                passed={evoView.score ? evoLane?.heldout.passed : undefined}
                n={evoView.score ? evoLane?.heldout.n : undefined}
              />
            </div>
            {evoView.status === "failed" && <p role="alert" className="text-sm text-red-700">{t("lane-failed")}: {evoView.error || t("no-reason")}</p>}

            {/* Diff Viewer */}
            <Card className="bg-background-secondary border border-border p-3 space-y-2">
              <div className="flex items-center justify-between text-xs text-text-tertiary font-mono">
                <span>{t("patch")}</span>
                <span>{evoLane?.diff ? `${evoLane.diff.length} chars` : "No patch"}</span>
              </div>
              <pre className="text-xs font-mono bg-slate-50 border border-slate-200 p-3 rounded overflow-x-auto max-h-64 text-emerald-700 whitespace-pre">
                {evoLane?.diff || "// Waiting for candidate patch generation…"}
              </pre>
            </Card>

            {/* Side-by-side preview */}
            <Card className="bg-background-secondary border border-border p-3 space-y-2">
              <div className="flex items-center justify-between text-xs text-text-tertiary font-mono">
                <span>{t("preview-heading")}</span>
                <span>
                  {evoPreview.source === "candidate" ? t("preview-candidate")
                    : evoPreview.source === "base" ? t("preview-base-unchanged")
                    : evoPreview.source === "pending" ? t("preview-pending")
                    : t("preview-none")}
                </span>
              </div>
              {evoPreview.html ? (
                <SandboxedPreview html={evoPreview.html} title={`evoforge-${activeArena.arena_id}`} />
              ) : (
                <p className="text-xs text-text-tertiary">
                  {evoPreview.source === "none" && evoPreview.error
                    ? `${t("preview-none")}: ${evoPreview.error}`
                    : evoPreview.source === "pending" ? t("preview-pending") : t("preview-none")}
                </p>
              )}
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
                      ev.role === "builder" ? "bg-purple-50 text-purple-700" :
                      ev.role === "critic" ? "bg-blue-50 text-blue-700" :
                      ev.role === "runner" ? "bg-emerald-50 text-emerald-700" :
                      "bg-amber-50 text-amber-700"
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
            <div className="flex items-center justify-between border-b-2 border-blue-200 pb-2">
              <div>
                <h2 className="text-base font-bold text-blue-700 flex items-center gap-2">
                  {t("single-lane")}
                </h2>
                <span className="text-xs text-text-tertiary">{t("single-sub")}</span>
              </div>
              <StatusPill
                status={singleView.outcome === "verification_inconclusive" ? "inconclusive" : singleView.status}
                passed={singleView.score ? singleLane?.heldout.passed : undefined}
                n={singleView.score ? singleLane?.heldout.n : undefined}
              />
            </div>
            {singleView.status === "failed" && <p role="alert" className="text-sm text-red-700">{t("lane-failed")}: {singleView.error || t("no-reason")}</p>}

            {/* Diff Viewer */}
            <Card className="bg-background-secondary border border-border p-3 space-y-2">
              <div className="flex items-center justify-between text-xs text-text-tertiary font-mono">
                <span>{t("patch")}</span>
                <span>{singleLane?.diff ? `${singleLane.diff.length} chars` : "No patch"}</span>
              </div>
              <pre className="text-xs font-mono bg-slate-50 border border-slate-200 p-3 rounded overflow-x-auto max-h-64 text-blue-700 whitespace-pre">
                {singleLane?.diff || "// Waiting for candidate patch generation…"}
              </pre>
            </Card>

            {/* Side-by-side preview */}
            <Card className="bg-background-secondary border border-border p-3 space-y-2">
              <div className="flex items-center justify-between text-xs text-text-tertiary font-mono">
                <span>{t("preview-heading")}</span>
                <span>
                  {singlePreview.source === "candidate" ? t("preview-candidate")
                    : singlePreview.source === "base" ? t("preview-base-unchanged")
                    : singlePreview.source === "pending" ? t("preview-pending")
                    : t("preview-none")}
                </span>
              </div>
              {singlePreview.html ? (
                <SandboxedPreview html={singlePreview.html} title={`single-${activeArena.arena_id}`} />
              ) : (
                <p className="text-xs text-text-tertiary">
                  {singlePreview.source === "none" && singlePreview.error
                    ? `${t("preview-none")}: ${singlePreview.error}`
                    : singlePreview.source === "pending" ? t("preview-pending") : t("preview-none")}
                </p>
              )}
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
                      ev.role === "builder" ? "bg-purple-50 text-purple-700" :
                      ev.role === "critic" ? "bg-blue-50 text-blue-700" :
                      ev.role === "runner" ? "bg-emerald-50 text-emerald-700" :
                      "bg-amber-50 text-amber-700"
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
      <section className="arena-recent" aria-labelledby="arena-recent-title">
        <h2 id="arena-recent-title">{t("recent-matches")}</h2>
        {recentArenas.length === 0 ? (
          <p className="text-sm text-text-tertiary">{t("empty-matches")}</p>
        ) : (
          <ul className="arena-list">
            {recentArenas.map((ar) => {
              const result = arenaVerdict(ar);
              const evoResult = laneView(ar.lanes?.evoforge);
              const singleResult = laneView(ar.lanes?.single);
              const cost = arenaCost(ar);
              const inconclusive = ar.verdict?.winner === "inconclusive" || evoResult.outcome === "verification_inconclusive" || singleResult.outcome === "verification_inconclusive";
              const label = result?.winner === "evoforge" ? t("winner-evoforge")
                : result?.winner === "single" ? t("winner-single")
                : result?.winner === "tie" ? t("winner-tie")
                : ar.status === "running" ? t("status-running")
                : inconclusive ? t("verdict-inconclusive")
                : ar.status === "failed" ? t("status-failed")
                : t("result-unconfirmed");
              const score = (v: typeof evoResult) => v.score ?? "—";
              return (
                <li key={ar.arena_id}>
                  <button
                    type="button"
                    title={ar.arena_id}
                    aria-pressed={activeArena?.arena_id === ar.arena_id}
                    onClick={() => { if (!running) { setActiveArena(ar); setPollError(false); setError(null); } }}
                    className="arena-row"
                  >
                    <span className={`arena-pill is-${result?.winner ?? (ar.status === "running" ? "running" : "none")}`}>{label}</span>
                    <span className="arena-row-main">
                      <strong>{ar.goal}</strong>
                      <small>{ar.mode === "prompt" ? t("row-prompt") : ar.task_id}</small>
                    </span>
                    <span className="arena-row-score">
                      <span><em>EvoForge</em> {score(evoResult)}</span>
                      <span><em>{t("row-single")}</em> {score(singleResult)}</span>
                    </span>
                    <span className="arena-row-cost">{cost === null ? "—" : `${cost}¢`}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <PromptBar
        disabled={running}
        followUpArena={followUpArena}
        onStarted={(id) => {
          setPendingId(id);
          setActiveArena(null);
          setPollError(false);
          setError(null);
        }}
      />
    </div>
  );
}
