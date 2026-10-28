"use client";
import { useEffect, useState } from "react";
import { comparisonProvenance, provenance, viewProvenance, type Provenance } from "../../lib/performanceProvenance";
import {
  API_BASE,
  getEvalSuites,
  getPerformance,
  runBaseline,
  runPipeline,
  type EvalSuite,
  type MeasurementView,
  type PerformanceSnapshot,
} from "../../lib/api";

const card: React.CSSProperties = {
  background: "#141b2d",
  border: "1px solid #263048",
  borderRadius: 10,
  padding: 14,
  marginTop: 16,
  width: "100%",
  maxWidth: "100%",
  boxSizing: "border-box",
  overflowWrap: "break-word",
};

const label: React.CSSProperties = { fontSize: 12, color: "#8b96ad" };
const value: React.CSSProperties = {
  fontSize: 22,
  fontWeight: 700,
  marginTop: 4,
  overflowWrap: "break-word",
};

function fmtPct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

const provenanceLabel: Record<Provenance, string> = {
  simulated: "모의 공급사 평가",
  recorded: "공급사 호출 경로 기록 · 독립 검증 전",
  unknown: "공급사 출처 미확인",
};

function fmtInterval(iv: [number, number] | undefined): string {
  if (!iv || iv.length !== 2) return "—";
  return `${(iv[0] * 100).toFixed(1)}–${(iv[1] * 100).toFixed(1)}%`;
}

function fmtCents(n: number | null | undefined): string {
  return typeof n === "number" ? `${n}¢` : "—";
}

function fmtDelta(pp: number | null): string {
  if (typeof pp !== "number") return "—";
  const sign = pp > 0 ? "+" : "";
  return `${sign}${pp.toFixed(1)}%p`;
}

function verdictKo(snap: PerformanceSnapshot | null): string {
  if (!snap || snap.comparison.status !== "measured" || !snap.comparison.verdict) {
    return "아직 측정되지 않음";
  }
  if (snap.comparison.verdict === "improved") return "개선됨";
  if (snap.comparison.verdict === "worse") return "악화됨";
  return "명확한 차이 없음";
}

function MeasureCard({
  title,
  kind,
  view,
  costPerSolved,
}: {
  title: string;
  kind: string;
  view: MeasurementView | null;
  costPerSolved: number | null;
}) {
  if (!view) {
    return (
      <div style={{ ...card, flex: "1 1 160px", minWidth: 0 }}>
        <div style={label}>{title}</div>
        <div style={value}>—</div>
      </div>
    );
  }
  if (view.status !== "measured") {
    return (
      <div style={{ ...card, flex: "1 1 160px", minWidth: 0 }}>
        <div style={label}>{title}</div>
        <div style={{ ...value, fontSize: 16 }}>측정 전 · not_measured</div>
        <div style={{ fontSize: 13, color: "#aeb9cf", marginTop: 4 }}>
          {view.reason || `${kind} not measured yet`}
        </div>
      </div>
    );
  }
  const rec = view.record;
  const rate = typeof view.pass_rate === "number" ? view.pass_rate : (rec?.pass_rate ?? 0);
  const evId = view.evidence_id ?? rec?.evidence_id;
  return (
    <div style={{ ...card, flex: "1 1 160px", minWidth: 0 }}>
      <div style={label}>{title}</div>
      <div style={value}>{fmtPct(rate)}</div>
      <div style={{ fontSize: 12, color: "#aeb9cf" }}>{provenanceLabel[viewProvenance(view)]}</div>
      <div style={{ fontSize: 13, color: "#aeb9cf", marginTop: 4 }}>
        {view.passed ?? rec?.passed} / {view.n ?? rec?.n} · 95% 구간{" "}
        {fmtInterval(view.wilson95 ?? rec?.wilson95)}
      </div>
      <div style={{ fontSize: 13, marginTop: 4 }}>
        해결당 비용: {fmtCents(costPerSolved)} · 총 비용:{" "}
        {fmtCents(view.cost_cents ?? rec?.cost_cents)}
      </div>
      <div style={{ fontSize: 12, color: "#8b96ad", marginTop: 4 }}>
        {view.suite_version ?? rec?.suite_version} · {view.model ?? rec?.model} ·{" "}
        {view.harness_version ?? rec?.harness_version}
      </div>
      {evId ? (
        <div style={{ fontSize: 12, marginTop: 6 }}>
          증거:{" "}
          <a
            href={`/evidence?id=${encodeURIComponent(evId)}`}
            style={{ color: "#7db4ff", textDecoration: "none" }}
          >
            <code>{evId}</code> →
          </a>
        </div>
      ) : null}
    </div>
  );
}

export default function PerformancePage() {
  const [perf, setPerf] = useState<PerformanceSnapshot | null>(null);
  const [suites, setSuites] = useState<EvalSuite[]>([]);
  const [suiteVersion, setSuiteVersion] = useState<string>("v0");
  const [busy, setBusy] = useState<"baseline" | "pipeline" | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [autoPoll, setAutoPoll] = useState(true);
  const [lastUpdated, setLastUpdated] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setSyncing(true);
    try {
      setPerf(await getPerformance());
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
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
  }, []);

  useEffect(() => {
    if (!autoPoll && busy === null) return;
    const id = setInterval(() => {
      void refresh();
    }, busy !== null ? 3000 : 5000);
    return () => clearInterval(id);
  }, [autoPoll, busy]);

  const doBaseline = async () => {
    if (busy) return;
    setBusy("baseline");
    setErr("");
    try {
      await runBaseline();
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setErr(
        msg.includes("402") ? `예산 거부(402): 기준 측정 차단 — ${msg}` : msg,
      );
    } finally {
      setBusy(null);
    }
  };

  const doPipeline = async () => {
    if (busy) return;
    setBusy("pipeline");
    setErr("");
    try {
      await runPipeline();
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setErr(
        msg.includes("402") ? `예산 거부(402): Pipeline 측정 차단 — ${msg}` : msg,
      );
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
  for (const s of suites) {
    families.set(s.family, { suite: s });
  }
  const baseFam = perf?.baseline.record?.per_family ?? perf?.baseline.per_family;
  const pipeFam = perf?.pipeline.record?.per_family ?? perf?.pipeline.per_family;
  if (baseFam) {
    for (const [fam, v] of Object.entries(baseFam)) {
      const cur = families.get(fam) ?? {};
      families.set(fam, { ...cur, base: v });
    }
  }
  if (pipeFam) {
    for (const [fam, v] of Object.entries(pipeFam)) {
      const cur = families.get(fam) ?? {};
      families.set(fam, { ...cur, pipe: v });
    }
  }

  const history = perf?.history ?? [];
  const prod = perf?.production ?? null;
  const measured = perf?.comparison.status === "measured";

  return (
    <main style={{ width: "100%", maxWidth: "100%", boxSizing: "border-box" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 10,
        }}
      >
        <div>
          <h1 style={{ margin: "4px 0 4px" }}>Performance</h1>
          <p style={{ color: "#8b96ad", fontSize: 13, marginTop: 0 }}>
            GET {API_BASE}/v1/performance · 측정된 숫자만 표시
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span
            style={{
              fontSize: 12,
              color: "#8b96ad",
              padding: "4px 10px",
              borderRadius: 20,
              border: "1px solid #263048",
              background: "#141b2d",
            }}
          >
            {syncing ? "동기화 중…" : "실시간 연결됨"}
            {lastUpdated ? ` · ${lastUpdated}` : ""}
          </span>
          <button
            onClick={() => setAutoPoll((v) => !v)}
            style={{
              padding: "5px 10px",
              borderRadius: 6,
              fontSize: 12,
              background: autoPoll ? "#2563eb" : "#141b2d",
              color: "#e8edf5",
              border: "1px solid #33405c",
              cursor: "pointer",
            }}
          >
            {autoPoll ? "자동 갱신 ON (5초)" : "자동 갱신 OFF"}
          </button>
          <button
            onClick={() => void refresh()}
            disabled={syncing}
            style={{
              padding: "5px 10px",
              borderRadius: 6,
              fontSize: 12,
              background: "#141b2d",
              color: "#e8edf5",
              border: "1px solid #33405c",
              cursor: "pointer",
            }}
          >
            새로고침
          </button>
        </div>
      </div>

      <section style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <MeasureCard
          title="X_SINGLE 기준 통과율"
          kind="X_SINGLE"
          view={perf?.baseline ?? null}
          costPerSolved={perf?.cost_per_solved_cents.baseline ?? null}
        />
        <MeasureCard
          title="PIPELINE 통과율"
          kind="PIPELINE"
          view={perf?.pipeline ?? null}
          costPerSolved={perf?.cost_per_solved_cents.pipeline ?? null}
        />
        <div style={{ ...card, flex: "1 1 160px", minWidth: 0 }}>
          <div style={label}>개선 여부 (Wilson 95% 구간 비교)</div>
          {loading && !perf ? (
            <div style={{ fontSize: 13, color: '#aeb9cf', marginTop: 4 }}>불러오는 중…</div>
          ) : measured && perf ? (
            <>
              <div style={value}>{verdictKo(perf)}</div>
              <div style={{ fontSize: 12, color: "#aeb9cf" }}>{provenanceLabel[comparisonProvenance(perf.baseline, perf.pipeline)]}</div>
              <div style={{ fontSize: 13, color: "#aeb9cf", marginTop: 4 }}>
                변화량 {fmtDelta(perf.comparison.delta_pp)} · verdict=
                {perf.comparison.verdict}
              </div>
            </>
          ) : (
            <>
              <div style={{ ...value, fontSize: 16 }}>측정 전 · not_measured</div>
              <div style={{ fontSize: 13, color: "#aeb9cf", marginTop: 4 }}>
                {perf?.comparison.reason || "비교할 측정이 아직 없음"}
              </div>
            </>
          )}
        </div>
      </section>

      <section style={card}>
        <div style={label}>측정 실행</div>
        <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
          <button
            onClick={doBaseline}
            disabled={busy !== null}
            style={{ padding: "8px 16px", borderRadius: 6, background: "#2563eb", color: "#fff", border: 0, cursor: "pointer", maxWidth: "100%" }}
          >
            {busy === "baseline" ? "측정 중…" : "X_SINGLE 기준 측정"}
          </button>
          <button
            onClick={doPipeline}
            disabled={busy !== null}
            style={{ padding: "8px 16px", borderRadius: 6, background: "#0891b2", color: "#fff", border: 0, cursor: "pointer", maxWidth: "100%" }}
          >
            {busy === "pipeline" ? "측정 중…" : "Pipeline 개선 측정"}
          </button>
        </div>
        {err ? <p style={{ color: "#ef4444", overflowWrap: "break-word" }}>Error: {err}</p> : null}
        {loading ? <p style={{ fontSize: 13, color: "#8b96ad" }}>불러오는 중…</p> : null}
      </section>

      <section style={card}>
        <div style={label}>분야별 결과 (per-family · Sealed {suiteVersion})</div>
        {loading && !perf ? (
          <div style={{ fontSize: 13, color: '#aeb9cf', marginTop: 4 }}>불러오는 중…</div>
        ) : !baseFam && !pipeFam ? (
          <div style={{ fontSize: 13, color: "#aeb9cf", marginTop: 4 }}>
            측정 전 (not_measured) — {perf?.comparison.reason || "분야별 측정이 아직 없음"}
          </div>
        ) : null}
        {families.size > 0 ? (
          <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
            {[...families.entries()].map(([fam, v]) => (
              <div
                key={fam}
                style={{ border: "1px solid #263048", borderRadius: 8, padding: 10, background: "#0f1524", fontSize: 13, overflowWrap: "break-word" }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 6 }}>
                  <strong style={{ overflowWrap: "break-word" }}>{fam}</strong>
                  {v.suite ? (
                    <span style={{ fontSize: 12, color: "#8b96ad" }}>
                      tasks={v.suite.task_count} · kinds: {v.suite.heldout_kinds.join(", ")}
                    </span>
                  ) : null}
                </div>
                <div style={{ color: "#aeb9cf", marginTop: 4 }}>
                  X_SINGLE: {v.base ? `${v.base.passed}/${v.base.n}` : "not_measured"} ·{" "}
                  PIPELINE: {v.pipe ? `${v.pipe.passed}/${v.pipe.n}` : "not_measured"}
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </section>

      <section style={card}>
        <div style={label}>측정 기록 (history, 오래된 순)</div>
        {loading && !perf ? (
          <div style={{ fontSize: 13, color: '#aeb9cf', marginTop: 4 }}>불러오는 중…</div>
        ) : history.length === 0 ? (
          <div style={{ fontSize: 13, color: "#aeb9cf", marginTop: 4 }}>
            측정 전 (not_measured) — 측정 기록이 아직 없음
          </div>
        ) : (
          <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
            {history.map((m) => {
              const pct = m.n > 0 ? Math.max(0, Math.min(100, (m.passed / m.n) * 100)) : 0;
              return (
                <div
                  key={m.measurement_id}
                  style={{ border: "1px solid #263048", borderRadius: 8, padding: 10, background: "#0f1524", fontSize: 13, minWidth: 0, overflowWrap: "break-word" }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 6 }}>
                    <div>
                      <code style={{ overflowWrap: "break-word" }}>{m.kind}</code>{" "}
                      {m.passed}/{m.n} ({fmtPct(m.pass_rate)}) · {fmtCents(m.cost_cents)}
                    </div>
                    {m.evidence_id ? (
                      <a
                        href={`/evidence?id=${encodeURIComponent(m.evidence_id)}`}
                        style={{ color: "#7db4ff", fontSize: 12, textDecoration: "none" }}
                      >
                        <code>{m.evidence_id}</code> →
                      </a>
                    ) : null}
                  </div>
                  <div
                    style={{ height: 8, borderRadius: 4, background: "#263048", marginTop: 6, width: "100%", maxWidth: "100%" }}
                  >
                    <div
                      style={{ height: 8, borderRadius: 4, background: "#22c55e", width: `${pct}%`, maxWidth: "100%" }}
                    />
                  </div>
                  <div style={{ fontSize: 12, color: "#8b96ad", marginTop: 4 }}>
                    {m.measurement_id} · {m.suite_version} · {m.model} · {provenanceLabel[provenance(m.provider_stub)]} · {new Date(m.created_at * 1000).toLocaleString()}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section style={card}>
        <div style={label}>운영 표본 (production, /v1/runs 증거 기준)</div>
        {loading && !perf ? (
          <div style={{ fontSize: 13, color: '#aeb9cf', marginTop: 4 }}>불러오는 중…</div>
        ) : !prod ? (
          <div style={{ fontSize: 13, color: "#aeb9cf", marginTop: 4 }}>
            측정 전 (not_measured) — 운영 표본이 아직 없음
          </div>
        ) : (
          <div style={{ fontSize: 13, marginTop: 4, overflowWrap: "break-word" }}>
            runs=<code>{prod.runs}</code> gate_pass=<code>{prod.gate_pass}</code>{" "}
            gate_fail=<code>{prod.gate_fail}</code> gate_inconclusive=
            <code>{prod.gate_inconclusive}</code> heldout=
            <code>
              {typeof prod.heldout_pass_rate_pct === "number"
                ? `${prod.heldout_pass_rate_pct.toFixed(1)}%`
                : "—"}
            </code>
            <div style={{ fontSize: 12, color: "#8b96ad", marginTop: 4 }}>{prod.sample_note}</div>
          </div>
        )}
      </section>

      <section style={card}>
        <div style={label}>측정 방법 (how measured)</div>
        <ul style={{ fontSize: 13, paddingLeft: 18, margin: "8px 0 0", overflowWrap: "break-word" }}>
          <li>
            suite: {perf?.baseline.record?.suite_version ?? perf?.pipeline.record?.suite_version ?? suiteVersion ?? "—"}
            {suites.length > 0 ? ` (분야: ${suites.map((s) => s.family).join(", ")})` : null}
          </li>
          <li>
            n: {perf?.baseline.record?.n ?? perf?.baseline.n ?? perf?.pipeline.record?.n ?? perf?.pipeline.n ?? "—"} ·{" "}
            model: {perf?.baseline.record?.model ?? perf?.pipeline.record?.model ?? "muse-spark-1.3"}
          </li>
          <li>
            시도 횟수: X_SINGLE은 작업당 1회, PIPELINE은 작업당 최대 3회
            {typeof perf?.pipeline.record?.attempts_total === "number" ||
            typeof perf?.pipeline.attempts_total === "number"
              ? ` (최근 측정 시도 ${perf?.pipeline.record?.attempts_total ?? perf?.pipeline.attempts_total}회)`
              : null}
          </li>
          <li>Wilson 95% 구간으로 비교: PIPELINE 하한이 기준 상한을 넘을 때만 개선됨으로 판정</li>
          <li>예산 상한: 서버 설정 EVO_EVAL_MAX_CENTS를 초과하면 402로 거부</li>
          <li>저장소: {perf?.storage ?? "—"}</li>
        </ul>
      </section>
    </main>
  );
}
