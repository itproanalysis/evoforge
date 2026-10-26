"use client";
import { useEffect, useState } from "react";
import {
  type GateVerdict,
  postCreatePR,
  postReview,
} from "../../lib/api";

const card: React.CSSProperties = {
  background: "#141b2d",
  border: "1px solid #263048",
  borderRadius: 10,
  padding: 14,
  marginTop: 16,
};

export default function Lab() {
  const [diff, setDiff] = useState("");
  const [tests, setTests] = useState<string[]>([]);
  const [gates, setGates] = useState<GateVerdict[]>([]);
  const [candidateId, setCandidateId] = useState("cand_local");
  const [review, setReview] = useState("");
  const [sealed, setSealed] = useState<string[]>([]);
  const [pr, setPr] = useState("");
  const [busy, setBusy] = useState<"review" | "pr" | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    try {
      const c = localStorage.getItem("evoforge.candidate");
      const g = localStorage.getItem("evoforge.gates");
      if (c) {
        const cand = JSON.parse(c);
        setDiff(cand.diff ?? "");
        setTests(cand.tests ?? []);
        if (cand.id) setCandidateId(cand.id);
      }
      if (g) setGates(JSON.parse(g));
    } catch {}
  }, []);

  const inconclusive = gates.some((g) => g.result === "INCONCLUSIVE");
  const failed = gates.some((g) => g.result === "FAIL");
  const mergeBlocked = inconclusive || failed;

  const doReview = async () => {
    setBusy("review");
    setErr("");
    try {
      const out = await postReview(candidateId, gates);
      setReview(
        `verdict=${out.verdict}${out.reason ? ` reason=${out.reason}` : ""}`,
      );
      setSealed(out.sealed_tests ?? []);
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
      const out = await postCreatePR(candidateId);
      setPr(out.pr_url ?? out.pr_id ?? JSON.stringify(out.raw ?? out));
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
          candidate_id{" "}
          <input
            value={candidateId}
            onChange={(e) => setCandidateId(e.target.value)}
            style={{ marginLeft: 8, padding: 6, borderRadius: 6, border: "1px solid #33405c", background: "#0b0e14", color: "#e8edf5" }}
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
            disabled={busy !== null}
            style={{ padding: "8px 16px", borderRadius: 6, background: "#7c3aed", color: "#fff", border: 0, cursor: "pointer" }}
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
