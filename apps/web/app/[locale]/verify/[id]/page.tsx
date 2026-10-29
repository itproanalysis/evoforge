"use client";
import { use, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { type ProofCertificate, getProof, getProofKey } from "../../../../lib/api";
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
        setCert(await getProof(id));
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

  if (err) return <p style={{ color: "#f87171" }}>{err}</p>;
  if (!cert) return <p>{t("loading")}</p>;

  const fingerprint = cert.public_key ? cert.public_key.slice(0, 16) : "";
  const keyMatches =
    cert.public_key != null && serverKey != null ? cert.public_key === serverKey : null;

  return (
    <div>
      <h1>{t("heading")} <span style={{ fontSize: 13, background: cert.verdict === "VERIFIED" ? "#34d399" : "#f87171", color: "#0b0e14", padding: "2px 10px", borderRadius: 12 }}>{cert.verdict}</span></h1>
      <p style={{ color: "#8b93a7" }}>{t("description")}</p>
      <Card>
        {cert.signed ? (
          <p style={{ color: "#34d399", fontSize: 13 }}>
            Ed25519 signed · {t("signed-fingerprint")}: <span style={{ fontFamily: "monospace" }}>{fingerprint}</span>
          </p>
        ) : (
          <p style={{ color: "#fbbf24", fontSize: 13 }}>{t("unsigned")}</p>
        )}
        <dl style={{ display: "grid", gridTemplateColumns: "minmax(80px, 140px) minmax(0, 1fr)", gap: 6, fontSize: 13, overflowWrap: "anywhere" }}>
          <dt>certificate</dt><dd style={{ margin: 0, fontFamily: "monospace" }}>{cert.certificate_id}</dd>
          <dt>evidence</dt><dd style={{ margin: 0, fontFamily: "monospace" }}>{cert.evidence_id}</dd>
          <dt>issued</dt><dd style={{ margin: 0 }}>{new Date(cert.issued_at * 1000).toLocaleString(locale)}</dd>
          <dt>signature</dt><dd style={{ margin: 0, fontFamily: "monospace", wordBreak: "break-all" }}>{cert.signature}</dd>
          <dt>verify</dt><dd style={{ margin: 0 }}>{cert.verify?.ok ? `✅ ${cert.verify.reason}` : `❌ ${cert.verify?.reason}`}</dd>
          <dt>{t("server-key-label")}</dt>
          <dd style={{ margin: 0, fontFamily: "monospace", wordBreak: "break-all" }}>
            {serverKey ?? t("server-key-unavailable")}
          </dd>
          <dt>{t("key-match-label")}</dt>
          <dd style={{ margin: 0 }}>
            {keyMatches === null
              ? t("key-match-unknown")
              : keyMatches
                ? `✅ ${t("key-match")}`
                : `❌ ${t("key-mismatch")}`}
          </dd>
          <dt>diff sha256</dt><dd style={{ margin: 0, fontFamily: "monospace", wordBreak: "break-all" }}>{cert.diff_sha256 || "—"}</dd>
          <dt>sealed</dt><dd style={{ margin: 0 }}>{cert.sealed_count} ({(cert.sealed_kinds ?? []).join(", ")})</dd>
        </dl>
      </Card>
      <Card>
        <h3>{t("gates")}</h3>
        {(cert.gates ?? []).map((g) => (
          <div key={g.gate} style={{ fontSize: 13 }}>{g.gate} = <strong>{g.result}</strong> <span style={{ color: "#8b93a7" }}>{g.reason}</span></div>
        ))}
        <h3 style={{ marginTop: 12 }}>{t("chain")}</h3>
        {(cert.chain ?? []).map((c) => (
          <div key={c.stage} style={{ fontSize: 13 }}>{c.stage}: {c.event_id ?? "—"}</div>
        ))}
      </Card>
    </div>
  );
}
