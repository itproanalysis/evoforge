"use client";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  type EvalSuite,
  type GateVerdict,
  getEvalSuites,
  postCreatePR,
  postRun,
  type SealedTest,
  postReview,
} from "../../../lib/api";
import { Button, Input, Card } from "../../../components/ui";
import { getErrorMessageKey } from "../../../lib/apiErrors";

export default function Lab() {
  const t = useTranslations("lab");
  const tErrors = useTranslations("errors");

  const [diff, setDiff] = useState("");
  const [goal, setGoal] = useState("");
  const [tests, setTests] = useState<string[]>([]);
  const [gates, setGates] = useState<GateVerdict[]>([]);
  const [review, setReview] = useState("");
  const [sealed, setSealed] = useState<string[]>([]);
  const [pr, setPr] = useState("");
  const [busy, setBusy] = useState<"review" | "eval" | "pr" | null>(null);
  const [err, setErr] = useState("");
  const [sealedTests, setSealedTests] = useState<SealedTest[]>([]);
  const [reviewEvidenceId, setReviewEvidenceId] = useState("");
  const [repo, setRepo] = useState("");
  const [baseSha, setBaseSha] = useState("HEAD");
  const [runInfo, setRunInfo] = useState("");
  const [evalId, setEvalId] = useState("");
  const [suites, setSuites] = useState<EvalSuite[]>([]);
  const [suitesNote, setSuitesNote] = useState("");

  useEffect(() => {
    try {
      const c = localStorage.getItem("evoforge.candidate");
      const g = localStorage.getItem("evoforge.gates");
      const gg = localStorage.getItem("evoforge.goal");
      if (c) {
        const cand = JSON.parse(c);
        setDiff(cand.diff ?? "");
        const t = cand.tests ?? [];
        setTests(
          t.map((x: unknown) =>
            typeof x === "string"
              ? x
              : (x as { code?: string }).code ?? JSON.stringify(x)
          )
        );
      }
      if (gg) setGoal(JSON.parse(gg));
      if (g) setGates(JSON.parse(g));
    } catch {}
  }, []);

  useEffect(() => {
    let live = true;
    getEvalSuites()
      .then((out) => {
        if (live) setSuites(out.suites ?? []);
      })
      .catch((e) => {
        if (live)
          setSuitesNote(
            `sealed suites unavailable: ${e instanceof Error ? e.message : String(e)}`
          );
      });
    return () => {
      live = false;
    };
  }, []);

  const inconclusive = gates.some((g) => g.result === "INCONCLUSIVE");
  const failed = gates.some((g) => g.result === "FAIL");
  const mergeBlocked = inconclusive || failed;
  const prReady = evalId !== "" && gates.length > 0 && !mergeBlocked;

  const doRun = async () => {
    setBusy("eval");
    setErr("");
    try {
      const out = await postRun(repo, baseSha, diff, tests, reviewEvidenceId);
      setGates(out.gates);
      setEvalId(out.evidence_id);
      const v = out.run.visible;
      const h = out.run.heldout;
      setRunInfo(
        t("run-info", {
          visPass: v.pass,
          visN: v.n,
          visTimeout: v.timed_out ? " (timeout)" : "",
          heldPass: h.pass,
          heldN: h.n,
          heldTimeout: h.timed_out ? " (timeout)" : "",
          base: out.run.base.slice(0, 12),
        })
      );
    } catch (e) {
      setEvalId("");
      setRunInfo("");
      const errorKey = getErrorMessageKey(e);
      setErr(tErrors(errorKey as any));
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
      setReview(
        t("review-verdict", {
          verdict: `${result} findings=${n}${out.stub ? " (stub, no MODEL_API_KEY)" : ""}`,
        })
      );
      setReviewEvidenceId(out.evidence_id ?? "");
      const st: SealedTest[] = (out.sealed_tests ?? []).map((t) =>
        typeof t === "string"
          ? { kind: "", code_sha256: "", code_len: t.length }
          : {
              kind: t.kind ?? "",
              code_sha256: t.code_sha256 ?? "",
              code_len: t.code_len ?? 0,
            }
      );
      setSealedTests(st);
      setSealed(
        st.map(
          (t) =>
            `[${t.kind}] sha256:${t.code_sha256.slice(0, 12)} len:${t.code_len}`
        )
      );
    } catch (e) {
      const errorKey = getErrorMessageKey(e);
      setErr(tErrors(errorKey as any));
      setSealed([]);
      setSealedTests([]);
      setReviewEvidenceId("");
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
        `goal=${goal}`
      );
      setPr(out.pr?.html_url ?? JSON.stringify(out));
    } catch (e) {
      const errorKey = getErrorMessageKey(e);
      setErr(tErrors(errorKey as any));
    } finally {
      setBusy(null);
    }
  };

  return (
    <main>
      <h1 className="text-2xl font-bold">{t("heading")}</h1>
      <p className="text-text-secondary text-sm">{t("description")}</p>

      <Card className="mt-4">
        <label className="text-xs text-text-secondary">
          {t("goal-label")}{" "}
          <Input
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder={t("goal-placeholder")}
            className="ml-2 w-[420px]"
          />
        </label>
        <h3 className="text-lg font-semibold mt-4">{t("candidate-diff")}</h3>
        <pre className="bg-background-primary border border-border rounded-lg p-3 overflow-auto text-xs whitespace-pre-wrap">
          {diff || t("goal-placeholder")}
        </pre>
        <h3 className="text-lg font-semibold mt-4">
          {t("tests-heading", { count: tests.length })}
        </h3>
        <ul className="list-disc pl-5">
          {tests.map((test, i) => (
            <li key={i} className="text-sm">
              <code>{test}</code>
            </li>
          ))}
        </ul>
      </Card>

      <Card className="mt-4">
        <h3 className="text-lg font-semibold mt-0">
          {t("server-run-heading")}
        </h3>
        <p className="text-text-secondary text-xs">{t("server-run-description")}</p>
        <div className="flex gap-3 items-center">
          <label className="text-xs text-text-secondary">
            {t("repo-path-label")}
            <Input
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
              placeholder={t("repo-path-placeholder")}
              className="ml-2 w-[280px]"
            />
          </label>
          <label className="text-xs text-text-secondary">
            {t("base-sha-label")}
            <Input
              value={baseSha}
              onChange={(e) => setBaseSha(e.target.value)}
              className="ml-2 w-[140px]"
            />
          </label>
        </div>
        <div className="mt-3">
          <Button
            onClick={doRun}
            disabled={busy !== null || !repo || !reviewEvidenceId}
            loading={busy === "eval"}
            variant="secondary"
            title={!reviewEvidenceId ? t("review-button") : ""}
          >
            {busy === "eval"
              ? t("running")
              : t("run-on-server", { count: sealedTests.length })}
          </Button>
        </div>
        {runInfo && <p className="text-sm mt-2">{runInfo}</p>}
        {evalId && (
          <ul className="text-sm mt-2">
            {gates.map((g) => (
              <li key={g.gate}>
                <code>{g.gate}</code>={g.result}{" "}
                <span className="text-text-secondary">{g.reason}</span>
              </li>
            ))}
            <li className="text-text-secondary">
              evidence: <code>{evalId}</code>
            </li>
          </ul>
        )}
      </Card>

      <Card className="mt-4">
        <h3 className="text-lg font-semibold mt-0">
          {t("sealed-suites-heading")}
        </h3>
        <p className="text-text-secondary text-xs">
          {t("sealed-suites-description")}
        </p>
        {suitesNote && <p className="text-accent-amber text-sm">{suitesNote}</p>}
        <ul className="text-sm">
          {suites.map((s) => (
            <li key={s.family}>
              <code>{s.family}</code> tasks={s.task_count}{" "}
              <span className="text-text-secondary">
                kinds: {s.heldout_kinds.join(", ")}
              </span>
            </li>
          ))}
        </ul>
      </Card>

      <Card className="mt-4">
        <div className="flex gap-2 flex-wrap">
          <Button
            onClick={doReview}
            disabled={busy !== null}
            loading={busy === "review"}
            variant="primary"
          >
            {busy === "review" ? t("reviewing") : t("review-button")}
          </Button>
          <Button
            onClick={doPR}
            disabled={busy !== null || !prReady}
            loading={busy === "pr"}
            variant="primary"
            title={prReady ? "" : t("merge-blocked-description")}
          >
            {busy === "pr" ? t("creating-pr") : t("create-pr")}
          </Button>
          <Button
            disabled={mergeBlocked}
            variant={mergeBlocked ? "ghost" : "primary"}
            title={mergeBlocked ? t("merge-blocked-description") : ""}
          >
            {mergeBlocked ? t("merge-blocked") : t("merge")}
          </Button>
        </div>
        {mergeBlocked && (
          <p className="text-accent-amber text-sm mt-2">
            {t("merge-blocked-description")}
          </p>
        )}
        {err && <p className="text-accent-red text-sm mt-2">{t("error-prefix")}{err}</p>}
        {review && (
          <p className="text-sm mt-2">
            <strong>{review}</strong>
          </p>
        )}
        {sealed.length > 0 && (
          <>
            <h4 className="text-base font-semibold mt-3">
              {t("sealed-tests-heading", { count: sealed.length })}
            </h4>
            <ul className="text-sm">
              {sealed.map((s, i) => (
                <li key={i}>
                  <code>{s}</code>
                </li>
              ))}
            </ul>
          </>
        )}
        {pr && (
          <p className="text-sm mt-2">
            {t("pr-created", { url: pr })}
          </p>
        )}
      </Card>
    </main>
  );
}
