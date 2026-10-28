"use client";
import { use, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { type ProofCertificate, getProof } from "../../../../lib/api";
import { Card } from "../../../../components/ui";
import { getErrorMessageKey } from "../../../../lib/apiErrors";

export default function VerifyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const t = useTranslations("verify");
  const tErrors = useTranslations("errors");
  const [cert, setCert] = useState<ProofCertificate | null>(null);
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

  if (err) return <p style={{ color: "#f87171" }}>{err}</p>;
  if (!cert) return <p>{t("loading")}</p>;

  return (
    <div>
      <h1>{t("heading")} <span style={{ fontSize: 13, background: cert.verdict === "VERIFIED" ? "#34d399" : "#f87171", color: "#0b0e14", padding: "2px 10px", borderRadius: 12 }}>{cert.verdict}</span></h1>
      <p style={{ color: "#8b93a7" }}>{t("description")}</p>
      <Card>
        <dl style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 6, fontSize: 13 }}>
          <dt>certificate</dt><dd style={{ margin: 0, fontFamily: "monospace" }}>{cert.certificate_id}</dd>
          <dt>evidence</dt><dd style={{ margin: 0, fontFamily: "monospace" }}>{cert.evidence_id}</dd>
          <dt>issued</dt><dd style={{ margin: 0 }}>{new Date(cert.issued_at * 1000).toLocaleString()}</dd>
          <dt>signature</dt><dd style={{ margin: 0, fontFamily: "monospace", wordBreak: "break-all" }}>{cert.signature}</dd>
          <dt>verify</dt><dd style={{ margin: 0 }}>{cert.verify?.ok ? `✅ ${cert.verify.reason}` : `❌ ${cert.verify?.reason}`}</dd>
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
