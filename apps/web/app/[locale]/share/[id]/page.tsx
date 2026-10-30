"use client";
import { use, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { getArena, getArenaProof, type ArenaDoc, type ArenaLane } from "../../../../lib/api";
import { manifestView, previewView } from "../../../../lib/arenaStatus";
import { shareText } from "../../../../lib/share";
import { SandboxedPreview } from "../../../../components/SandboxedPreview";

type Side = "evoforge" | "single";

// One lane of the result: its hidden-test score as a number and a bar, its cost, and why it lost
// points when the patch never ran.
function LaneScore({ side, lane, leading }: { side: Side; lane: ArenaLane | undefined; leading: boolean }) {
  const t = useTranslations("share");
  const tc = useTranslations("canvas");
  const held = lane?.heldout;
  const scored = held && Number.isInteger(held.passed) && Number.isInteger(held.n) && held.n > 0;
  const pct = scored ? Math.round((100 * held.passed) / held.n) : 0;
  const note = lane?.outcome === "apply_failed" ? tc("patch-not-applied")
    : lane?.outcome === "empty_diff" ? tc("no-patch")
    : null;
  return (
    <div className={`share-lane is-${side}${leading ? " is-leading" : ""}`}>
      <span className="share-lane-name">{side === "evoforge" ? "EvoForge" : t("single")}</span>
      <strong className="share-lane-score">{scored ? `${held.passed}/${held.n}` : "—"}</strong>
      <span className="share-lane-bar" aria-hidden="true"><span style={{ width: `${pct}%` }} /></span>
      <span className="share-lane-meta">
        {t("hidden-tests")} {scored ? `${pct}%` : "—"} · {t("cost")} {Number.isInteger(lane?.cost_cents) ? `${lane?.cost_cents}¢` : "—"}
      </span>
      {note && <span className="share-lane-note">{note}</span>}
    </div>
  );
}

// An arena certificate is verified by the arena id itself (GET /v1/proof/<arena_id>).
function ShareDetails({ doc, certificateId }: { doc: ArenaDoc; certificateId: string | null }) {
  const t = useTranslations("share");
  const locale = useLocale();
  const manifest = manifestView(doc);
  const evoLane = doc.lanes?.evoforge;
  const singleLane = doc.lanes?.single;
  const evoPreview = previewView(evoLane);
  const singlePreview = previewView(singleLane);
  const evoHtml = evoPreview.html ?? evoLane?.preview_html ?? null;
  const singleHtml = singlePreview.html ?? singleLane?.preview_html ?? null;
  const prompt = doc.prompt || doc.goal || doc.task_id || doc.arena_id;
  const verdict = doc.verdict;
  const winner = verdict?.winner ?? null;
  const prefix = locale === "ko" ? "/ko" : "";
  const homeHref = prefix || "/";
  const proofId = certificateId ? doc.arena_id : null;
  const [copied, setCopied] = useState(false);
  const share = async () => {
    const url = window.location.href;
    const nav = navigator as Navigator & { share?: (data: { url?: string; text?: string }) => Promise<void> };
    if (typeof nav.share === "function") {
      try { await nav.share({ url, text: shareText(doc, locale) }); } catch {}
      return;
    }
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  };
  const when = typeof doc.created_at === "number"
    ? new Intl.DateTimeFormat(locale === "ko" ? "ko-KR" : "en-US", { dateStyle: "medium", timeZone: locale === "ko" ? "Asia/Seoul" : "UTC" }).format(new Date(doc.created_at * 1000))
    : null;

  return (
    <main className="share-page">
      <section className={`share-hero is-${winner ?? "none"}`} aria-labelledby="share-verdict">
        <p className="share-kicker">EvoForge · {t("title")}{when ? ` · ${when}` : ""}</p>
        <h1 id="share-verdict">{winner && t.has(`winner-${winner}`) ? t(`winner-${winner}`) : t("result-pending")}</h1>
        <blockquote className="share-prompt"><span>{prompt}</span></blockquote>
        <div className="share-versus">
          <LaneScore side="evoforge" lane={evoLane} leading={winner === "evoforge"} />
          <span className="share-vs" aria-hidden="true">vs</span>
          <LaneScore side="single" lane={singleLane} leading={winner === "single"} />
        </div>
        <ul className="share-trust">
          <li>{t("same-model", { model: doc.model || "—" })}</li>
          <li>{t("same-tests")}</li>
          {certificateId && <li>{t("signed")}</li>}
        </ul>
        <div className="share-actions">
          <button type="button" className="share-primary" onClick={() => void share()}>{copied ? t("copied") : t("share-this")}</button>
          {proofId && <a className="share-secondary" href={`${prefix}/verify/${encodeURIComponent(proofId)}`}>{t("open-proof")}</a>}
          <a className="share-link" href={homeHref}>{t("try-own")} →</a>
        </div>
      </section>

      <section className="share-built" aria-labelledby="share-built-title">
        <h2 id="share-built-title">{t("what-built")}</h2>
        <div className="share-previews">
          <article className="share-preview" aria-label="EvoForge">
            <header>EvoForge</header>
            {evoHtml ? <SandboxedPreview html={evoHtml} title={`share-${doc.arena_id}-evoforge`} /> : <div className="share-preview-empty">{t("no-preview")}</div>}
          </article>
          <article className="share-preview" aria-label={t("single")}>
            <header>{t("single")}</header>
            {singleHtml ? <SandboxedPreview html={singleHtml} title={`share-${doc.arena_id}-single`} /> : <div className="share-preview-empty">{t("no-preview")}</div>}
          </article>
        </div>
      </section>

      <details className="perf-section share-fine">
        <summary>{t("fine-print")}</summary>
        <div>
          {verdict?.reason && <p>{t("result")}: {verdict.reason}</p>}
          {manifest?.disclosure && <p>{manifest.disclosure}</p>}
          {certificateId && <p>{t("certificate")}: <code>{certificateId}</code></p>}
          <p><code>{doc.arena_id}</code></p>
        </div>
      </details>
    </main>
  );
}

export default function SharePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const t = useTranslations("share");
  const [doc, setDoc] = useState<ArenaDoc | null>(null);
  const [proofId, setProofId] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [arena, cert] = await Promise.allSettled([getArena(id), getArenaProof(id)]);
      if (cancelled) return;
      if (arena.status === "fulfilled") setDoc(arena.value);
      else setMissing(true);
      const c = cert.status === "fulfilled" ? cert.value : null;
      setProofId(c?.certificate_id ?? null);
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (missing) return <p className="share-page share-status">{t("not-found")}</p>;
  if (doc === null) return <p className="share-page share-status">{t("loading")}</p>;
  return <ShareDetails doc={doc} certificateId={proofId} />;
}
