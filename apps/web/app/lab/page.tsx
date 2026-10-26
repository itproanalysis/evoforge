"use client";
import { useEffect, useState } from "react";
import {
  type GateVerdict,
  postCreatePR,
  postEvaluate,
  postReview,
} from "../../lib/api";

const field: React.CSSProperties = {
  marginLeft: 6,
  padding: 4,
  borderRadius: 6,
  border: "1px solid #33405c",
  background: "#0b0e14",
  color: "#e8edf5",
  width: 64,
};

const card: React.CSSProperties = {
  background: "#141b2d",
  border: "1px solid #263048",
  borderRadius: 10,
  padding: 14,
  marginTop: 16,
};

export default function Lab() {
  const [diff, setDiff] = useState("");
  const [goal, setGoal] = useState("");
  const [tests, setTests] = useState<string[]>([]);
  const [gates, setGates] = useState<GateVerdict[]>([]);
  const [review, setReview] = useState("");
  const [sealed, setSealed] = useState<string[]>([]);
  const [pr, setPr] = useState("");
  const [busy, setBusy] = useState<"review" | "eval" | "pr" | null>(null);
  const [err, setErr] = useState("");
  const [heldoutKinds, setHeldoutKinds] = useState("compositional, negative, boundary");
  const [counts, setCounts] = useState({ vis_pass: 0, vis_n: 0, held_pass: 0, held_n: 0 });
  const [evalId, setEvalId] = useState("");

  useEffect(() => {
    try {
      const c = localStorage.getItem("evoforge.candidate");
      const g = localStorage.getItem("evoforge.gates");
      const gg = localStorage.getItem("evoforge.goal");
      if (c) {
        const cand = JSON.parse(c);
        setDiff(cand.diff ?? "");
        const t = cand.tests ?? [];
        setTests(t.map((x: unknown) => (typeof x === "string" ? x : (x as { code?: string }).code ?? JSON.stringify(x))));
      }
      if (gg) setGoal(JSON.parse(gg));
      if (g) setGates(JSON.parse(g));
    } catch {}
  }, []);

  const inconclusive = gates.some((g) => g.result === "INCONCLUSIVE");
  const failed = gates.some((g) => g.result === "FAIL");
  const mergeBlocked = inconclusive || failed;
  const prReady = evalId !== "" && gates.length > 0 && !mergeBlocked;

  const doEvaluate = async () => {
    setBusy("eval");
    setErr("");
    try {
      const out = await postEvaluate(diff, tests, {
        heldout_kinds: heldoutKinds.split(",").map((s) => s.trim()).filter(Boolean),
        ...counts,
      });
      setGates(out.gates);
      setEvalId(out.evidence_id);
    } catch (e) {
      setEvalId("");
      setErr(`evaluate API: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const doReview = async () => {
    setBusy("review");
    setErr("");
    try {
      const out = await postReview(goal || "unspecified goal", diff);
      const result = out.review?.result ?? "INCONCLUSIVE";
      const n = out.review?.findings?.length ?? 0;
      setReview(`verdict=${result} findings=${n}${out.stub ? " (stub, no MODEL_API_KEY)" : ""}`);
      setSealed(
        (out.sealed_tests ?? []).map((t) =>
          typeof t === "string" ? t : (t.code ?? JSON.stringify(t)),
        ),
      );
    } catch (e) {
      // Backend may not implement review yet — keep sealed local tests visible.
      setErr(`review API: ${e instanceof Error ? e.message : String(e)} (미구현이면 로컬 sealed tests 사용)`);
      setSealed(tests);
      setReview("verdict=INCONCLUSIVE reason=review endpoint unavailable, human needed");
    } finally {
      setBusy(null);
    }
  };

  const doPR = async () => {
    setBusy("pr");
    setErr("");
    try {
      const out = await postCreatePR(
        evalId,
        `EvoForge: ${goal.slice(0, 60) || "candidate"}`,
        `goal=${goal}`,
      );
      setPr(out.pr?.html_url ?? JSON.stringify(out));
    } catch (e) {
      setErr(`pr API: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <main>
      <h1>Improvement Lab</h1>
      <p style={{ color: "#8b96ad", fontSize: 13 }}>
        candidate diff → sealed tests → review → PR. INCONCLUSIVE는 머지 차단.
      </p>

      <section style={card}>
        <label style={{ fontSize: 12, color: "#8b96ad" }}>
          goal{" "}
          <input
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="Mission Control에서 입력한 목표"
            style={{ marginLeft: 8, padding: 6, borderRadius: 6, border: "1px solid #33405c", background: "#0b0e14", color: "#e8edf5", width: 420 }}
          />
        </label>
        <h3>Candidate diff</h3>
        <pre
          style={{
            background: "#0b0e14",
            border: "1px solid #263048",
            borderRadius: 8,
            padding: 12,
            overflow: "auto",
            fontSize: 12,
            whiteSpace: "pre-wrap",
          }}
        >
          {diff || "Mission Control에서 Generate 후 여기로 오거나 diff를 붙여넣으세요."}
        </pre>
        <h3>Tests ({tests.length})</h3>
        <ul>
          {tests.map((t, i) => (
            <li key={i} style={{ fontSize: 13 }}>
              <code>{t}</code>
            </li>
          ))}
        </ul>
      </section>

      <section style={card}>
        <h3 style={{ marginTop: 0 }}>Gate evaluation (POST /v1/gates/evaluate)</h3>
        <p style={{ color: "#8b96ad", fontSize: 12 }}>
          실행 통계는 Runner 결과를 입력합니다. 0건 실행은 증거 부족(INCONCLUSIVE)이며 PR이 차단됩니다.
        </p>
        <label style={{ fontSize: 12, color: "#8b96ad" }}>
          held-out kinds
          <input
            value={heldoutKinds}
            onChange={(e) => setHeldoutKinds(e.target.value)}
            style={{ ...field, width: 280 }}
          />
        </label>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 8 }}>
          {(["vis_pass", "vis_n", "held_pass", "held_n"] as const).map((k) => (
            <label key={k} style={{ fontSize: 12, color: "#8b96ad" }}>
              {k}
              <input
                type="number"
                min={0}
                value={counts[k]}
                onChange={(e) => setCounts({ ...counts, [k]: Math.max(0, Math.trunc(Number(e.target.value) || 0)) })}
                style={field}
              />
            </label>
          ))}
        </div>
        <button
          onClick={doEvaluate}
          disabled={busy !== null || !diff}
          style={{ marginTop: 10, padding: "8px 16px", borderRadius: 6, background: "#0891b2", color: "#fff", border: 0, cursor: "pointer" }}
        >
          {busy === "eval" ? "Evaluating…" : "Evaluate gates"}
        </button>
        {evalId ? (
          <ul style={{ fontSize: 13 }}>
            {gates.map((g) => (
              <li key={g.gate}>
                <code>{g.gate}</code>={g.result} <span style={{ color: "#8b96ad" }}>{g.reason}</span>
              </li>
            ))}
            <li style={{ color: "#8b96ad" }}>evidence: <code>{evalId}</code></li>
          </ul>
        ) : null}
      </section>

      <section style={card}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            onClick={doReview}
            disabled={busy !== null}
            style={{ padding: "8px 16px", borderRadius: 6, background: "#16a34a", color: "#fff", border: 0, cursor: "pointer" }}
          >
            {busy === "review" ? "Reviewing…" : "Review (POST /v1/candidates/review)"}
          </button>
          <button
            onClick={doPR}
            disabled={busy !== null || !prReady}
            title={prReady ? "서버 평가 전부 PASS" : "서버 게이트 평가가 전부 PASS여야 PR 생성 가능"}
            style={{ padding: "8px 16px", borderRadius: 6, background: prReady ? "#7c3aed" : "#3a4358", color: "#fff", border: 0, cursor: prReady ? "pointer" : "not-allowed" }}
          >
            {busy === "pr" ? "Creating…" : "Create PR (POST /v1/pr/create)"}
          </button>
          <span title={mergeBlocked ? "예외 승인 필요" : "merge 가능"}>
            <button
              disabled={mergeBlocked}
              style={{
                padding: "8px 16px",
                borderRadius: 6,
                background: mergeBlocked ? "#3a4358" : "#2563eb",
                color: "#fff",
                border: 0,
                cursor: mergeBlocked ? "not-allowed" : "pointer",
              }}
            >
              Merge{mergeBlocked ? " (차단됨)" : ""}
            </button>
          </span>
        </div>
        {mergeBlocked ? (
          <p style={{ color: "#f59e0b", fontSize: 13 }} title="예외 승인 필요">
            INCONCLUSIVE/FAIL 게이트가 있어 Merge가 비활성화됩니다. 예외 승인이
            필요합니다.
          </p>
        ) : null}
        {err ? <p style={{ color: "#ef4444", fontSize: 13 }}>{err}</p> : null}
        {review ? (
          <p style={{ fontSize: 13 }}>
            review verdict: <strong>{review}</strong>
          </p>
        ) : null}
        {sealed.length > 0 ? (
          <>
            <h4>Sealed tests ({sealed.length})</h4>
            <ul>
              {sealed.map((t, i) => (
                <li key={i} style={{ fontSize: 13 }}>
                  <code>{t}</code>
                </li>
              ))}
            </ul>
          </>
        ) : null}
        {pr ? (
          <p style={{ fontSize: 13 }}>
            PR: <code>{pr}</code>
          </p>
        ) : null}
      </section>
    </main>
  );
}
