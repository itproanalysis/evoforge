"use client";
import { use, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { getArena, getArenaProof, type ArenaDoc } from "../../../../lib/api";
import { manifestView, previewView } from "../../../../lib/arenaStatus";
import { SandboxedPreview } from "../../../../components/SandboxedPreview";

export function ShareDetails({ doc, certificateId }: { doc: ArenaDoc; certificateId: string | null }) {
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
  const homeHref = locale === "ko" ? "/ko" : "/";

  return (
    <main className="studio-home canvas-workspace" style={{ maxWidth: "100%", overflowWrap: "anywhere" }}>
      <h1>{t("title")}</h1>
      <p style={{ maxWidth: "100%", whiteSpace: "pre-wrap" }}>{prompt}</p>
      <div className="canvas-stage is-compare" style={{ maxWidth: "100%", padding: "0 0 24px" }}>
        <article className="canvas-output" aria-label="EvoForge">
          <header className="canvas-output-header">
            <strong>EvoForge</strong>
            <div className="canvas-output-numbers">
              <span>{evoLane?.heldout ? `${evoLane.heldout.passed}/${evoLane.heldout.n}` : "—"}</span>
              <span className="canvas-number-divider" aria-hidden="true">·</span>
              <span>{Number.isInteger(evoLane?.cost_cents) ? `${evoLane?.cost_cents}¢` : "—"}</span>
            </div>
          </header>
          <div className="canvas-output-body">
            {evoHtml ? (
              <SandboxedPreview html={evoHtml} title={`share-${doc.arena_id}-evoforge`} />
            ) : (
              <div className="canvas-empty">—</div>
            )}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, padding: "12px 20px", fontSize: 12, maxWidth: "100%" }}>
            <span>heldout {evoLane?.heldout ? `${evoLane.heldout.passed}/${evoLane.heldout.n}` : "—"}</span>
            <span>cost_cents {Number.isInteger(evoLane?.cost_cents) ? `${evoLane?.cost_cents}¢` : "—"}</span>
          </div>
        </article>
        <article className="canvas-output" aria-label="single">
          <header className="canvas-output-header">
            <strong>single</strong>
            <div className="canvas-output-numbers">
              <span>{singleLane?.heldout ? `${singleLane.heldout.passed}/${singleLane.heldout.n}` : "—"}</span>
              <span className="canvas-number-divider" aria-hidden="true">·</span>
              <span>{Number.isInteger(singleLane?.cost_cents) ? `${singleLane?.cost_cents}¢` : "—"}</span>
            </div>
          </header>
          <div className="canvas-output-body">
            {singleHtml ? (
              <SandboxedPreview html={singleHtml} title={`share-${doc.arena_id}-single`} />
            ) : (
              <div className="canvas-empty">—</div>
            )}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, padding: "12px 20px", fontSize: 12, maxWidth: "100%" }}>
            <span>heldout {singleLane?.heldout ? `${singleLane.heldout.passed}/${singleLane.heldout.n}` : "—"}</span>
            <span>cost_cents {Number.isInteger(singleLane?.cost_cents) ? `${singleLane?.cost_cents}¢` : "—"}</span>
          </div>
        </article>
      </div>
      <section className="canvas-conditions" style={{ maxWidth: "100%" }}>
        <p>
          verdict {verdict?.winner ?? "—"}
          {verdict?.reason ? ` · ${verdict.reason}` : ""}
        </p>
        {manifest?.disclosure && <p>{manifest.disclosure}</p>}
        {certificateId && <p>{t("certificate")}: {certificateId}</p>}
        <p>
          <a href={homeHref}>{t("try-own")}</a>
        </p>
      </section>
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
      try {
        const arena = await getArena(id);
        if (!cancelled) setDoc(arena);
      } catch {
        if (!cancelled) setMissing(true);
      }
      try {
        const cert = await getArenaProof(id);
        if (!cancelled) setProofId(cert?.certificate_id ?? null);
      } catch {
        if (!cancelled) setProofId(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (missing) return <p className="studio-home">{t("not-found")}</p>;
  if (doc === null) return <p className="studio-home">{t("title")}</p>;
  return <ShareDetails doc={doc} certificateId={proofId} />;
}
