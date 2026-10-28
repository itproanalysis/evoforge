"use client";
import { use, useEffect, useState } from "react";
import { type ProofCertificate, getProof } from "../../../lib/api";

export default function VerifyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [cert, setCert] = useState<ProofCertificate | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    getProof(id).then(setCert).catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [id]);
  return (
    <main style={{ maxWidth: 860, margin: "0 auto", padding: 24, color: "#e8edf5", background: "#0b0e14", minHeight: "100vh", fontSize: 14 }}>
      <nav style={{ display: "flex", gap: 12, fontSize: 13, flexWrap: "wrap" }}>
        <a href="/" style={{ color: "#7db4ff", textDecoration: "none" }}>Mission Control</a>
        <a href="/evolution" style={{ color: "#7db4ff", textDecoration: "none" }}>Autopilot</a>
        <a href="/evidence" style={{ color: "#7db4ff", textDecoration: "none" }}>Evidence</a>
      </nav>
      <h1>Proof certificate</h1>
      {err && <p style={{ color: "#f87171" }}>{err}</p>}
      {!cert && !err && <p style={{ color: "#8b93a7" }}>Loading…</p>}
      {cert && (
        <div>
          <p>
            <strong>{cert.verdict}</strong> · {cert.verify?.ok ? `✅ ${cert.verify.reason}` : `❌ ${cert.verify?.reason}`}
          </p>
          <pre style={{ background: "#141b2d", padding: 12, borderRadius: 8, overflowX: "auto", fontSize: 12 }}>
            {JSON.stringify(cert, null, 2)}
          </pre>
        </div>
      )}
    </main>
  );
}
