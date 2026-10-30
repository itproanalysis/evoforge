"use client";
import { use, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { type ProofCertificate, getArenaProof, getProof, getProofKey } from "../../../../lib/api";
import { Card } from "../../../../components/ui";
import { getErrorMessageKey } from "../../../../lib/apiErrors";

export default function VerifyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const t = useTranslations("verify");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const [cert, setCert] = useState<ProofCertificate | null>(null);
  const [serverKey, setServerKey] = useState<string | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      try {
        // Match results (job_…) have their own certificate; everything else is an evidence certificate.
        const c = id.startsWith("job_") ? ((await getArenaProof(id)) as unknown as ProofCertificate | null) : await getProof(id);
        if (!c) throw new Error("404 certificate not found");
        setCert(c);
      } catch (e) {
        setErr(tErrors(getErrorMessageKey(e)));
      }
    })();
  }, [id]);

  useEffect(() => {
    (async () => {
      try {
        const key = await getProofKey();
        setServerKey(key.public_key ?? null);
      } catch {
        setServerKey(null);
      }
    })();
  }, []);

  if (err) return <p className="text-sm text-red-600">{err}</p>;
  if (!cert) return <p className="text-sm text-text-secondary">{t("loading")}</p>;

  const fingerprint = cert.public_key ? cert.public_key.slice(0, 16) : "";
  const keyMatches =
    cert.public_key != null && serverKey != null ? cert.public_key === serverKey : null;
  const sealedKinds = (cert.sealed_kinds ?? []).join(", ");
  const heldoutGate = (cert.gates ?? []).find((g) => /heldout|sealed/i.test(g.gate));

  // A match certificate (kind "arena") carries the match winner as its verdict; it is verified when its
  // signature checks out.
  const isArena = (cert as unknown as { kind?: string }).kind === "arena";
  const verified = isArena ? cert.verify?.ok === true && keyMatches !== false : cert.verdict === "VERIFIED";
  const gates = cert.gates ?? [];
  const lanes = (cert as unknown as { lanes?: Record<string, { heldout?: { passed?: number; n?: number } }> }).lanes;
  const score = (side: string) => { const h = lanes?.[side]?.heldout; return h && Number.isInteger(h.passed) && Number.isInteger(h.n) ? `${h.passed}/${h.n}` : "—"; };
  const arenaScores = isArena && lanes ? { evoforge: score("evoforge"), single: score("single") } : null;
  const gatesPassed = gates.filter((g) => g.result === "PASS").length;
  const checks: { ok: boolean | null; label: string }[] = [
    { ok: cert.verify ? !!cert.verify.ok : null, label: t("check-signature") },
    { ok: keyMatches, label: t("check-key") },
    ...(gates.length > 0 ? [{ ok: gatesPassed === gates.length, label: t("check-gates", { passed: gatesPassed, total: gates.length }) }] : []),
    ...(arenaScores ? [{ ok: true, label: t("check-arena", arenaScores) }] : []),
  ];

  return (
    <div className="studio-light verify-page max-w-3xl space-y-4">
      <section className={`verify-hero${verified ? " is-verified" : " is-failed"}`}>
        <span className="verify-badge" aria-hidden="true">{verified ? "✓" : "!"}</span>
        <p className="verify-kicker">{t("heading")}{isArena ? "" : ` · ${cert.verdict}`}</p>
        <h1>{verified ? t("hero-verified") : t("hero-failed")}</h1>
        <p className="verify-sub">{t("description")}</p>
        <ul className="verify-checks">
          {checks.map((c) => (
            <li key={c.label} className={c.ok === null ? "is-unknown" : c.ok ? "is-ok" : "is-bad"}>
              <span aria-hidden="true">{c.ok === null ? "–" : c.ok ? "✓" : "✕"}</span>
              {c.label}
            </li>
          ))}
        </ul>
      </section>
      <details className="perf-section verify-details">
      <summary>{t("details")}</summary>
      <Card className="bg-background-secondary border border-border">
        {cert.signed ? (
          <p className="text-sm text-text-primary">
            {t("signed-fingerprint")}: <code className="font-mono">{fingerprint}</code>
          </p>
        ) : (
          <p className="text-sm text-text-secondary">{t("unsigned")}</p>
        )}
        <dl className="grid gap-1.5 text-sm mt-3" style={{ gridTemplateColumns: "minmax(80px, 140px) minmax(0, 1fr)" }}>
          <dt className="text-text-secondary">{t("certificate-label")}</dt><dd className="m-0 font-mono break-all text-text-primary">{cert.certificate_id}</dd>
          <dt className="text-text-secondary">{t("evidence-label")}</dt><dd className="m-0 font-mono break-all text-text-primary">{cert.evidence_id}</dd>
          <dt className="text-text-secondary">{t("issued-label")}</dt><dd className="m-0 text-text-primary">{new Date(cert.issued_at * 1000).toLocaleString(locale)}</dd>
          <dt className="text-text-secondary">{t("signature-label")}</dt><dd className="m-0 font-mono break-all text-text-primary">{cert.signature}</dd>
          <dt className="text-text-secondary">{t("verify-label")}</dt><dd className="m-0 text-text-primary">{cert.verify?.ok ? `✅ ${cert.verify.reason}` : `❌ ${cert.verify?.reason}`}</dd>
          <dt className="text-text-secondary">{t("server-key-label")}</dt>
          <dd className="m-0 font-mono break-all text-text-primary">
            {serverKey ?? t("server-key-unavailable")}
          </dd>
          <dt className="text-text-secondary">{t("key-match-label")}</dt>
          <dd className="m-0 text-text-primary">
            {keyMatches === null
              ? t("key-match-unknown")
              : keyMatches
                ? `✅ ${t("key-match")}`
                : `❌ ${t("key-mismatch")}`}
          </dd>
          <dt className="text-text-secondary">{t("diff-label")}</dt><dd className="m-0 font-mono break-all text-text-primary">{cert.diff_sha256 || "—"}</dd>
          {cert.sealed_count > 0 ? (
            <>
              <dt className="text-text-secondary">{t("sealed-label")}</dt>
              <dd className="m-0 text-text-primary">{sealedKinds ? t("sealed-value", { count: cert.sealed_count, kinds: sealedKinds }) : cert.sealed_count}</dd>
            </>
          ) : heldoutGate ? (
            <>
              <dt className="text-text-secondary">{t("sealed-label")}</dt>
              <dd className="m-0 text-text-primary">{heldoutGate.gate} = {heldoutGate.result}{heldoutGate.reason ? ` ${heldoutGate.reason}` : ""}</dd>
            </>
          ) : null}
        </dl>
      </Card>
      </details>
      {(gates.length > 0 || (cert.chain ?? []).length > 0) && <details className="perf-section verify-details">
      <summary>{t("gates")} · {t("chain")}</summary>
      <Card className="bg-background-secondary border border-border">
        <h3 className="text-base font-semibold m-0 text-text-primary">{t("gates")}</h3>
        {(cert.gates ?? []).map((g) => (
          <div key={g.gate} className="text-sm text-text-primary">{g.gate} = <strong>{g.result}</strong> <span className="text-text-secondary">{g.reason}</span></div>
        ))}
        <h3 className="text-base font-semibold mt-3 text-text-primary">{t("chain")}</h3>
        {(cert.chain ?? []).map((c) => (
          <div key={c.stage} className="text-sm text-text-primary">{c.stage}: {c.event_id ?? "—"}</div>
        ))}
      </Card>
      </details>}
    </div>
  );
}
