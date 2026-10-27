import type { ReactNode } from "react";

export const metadata = {
  title: "EvoForge — Mission Control",
  description: "Hackathon Indie-track UI: generate → gate → review → PR → evidence.",
};

const link: React.CSSProperties = {
  color: "#cfe3ff",
  textDecoration: "none",
  fontSize: 14,
};

export default function RootLayout({ children }: { children: ReactNode }) {
  const raw = (process.env.NEXT_PUBLIC_API_BASE ?? "").trim();
  const apiBase = raw === "" ? "/api/evoforge (same-origin)" : raw;
  return (
    <html lang="ko">
      <body
        style={{
          margin: 0,
          fontFamily: "system-ui, -apple-system, sans-serif",
          background: "#0b0e14",
          color: "#e8edf5",
        }}
      >
        <header
          style={{
            display: "flex",
            alignItems: "center",
            gap: 20,
            padding: "12px 24px",
            background: "#111726",
            borderBottom: "1px solid #263048",
            position: "sticky",
            top: 0,
            zIndex: 10,
          }}
        >
          <a href="/" style={{ ...link, fontWeight: 800, fontSize: 18 }}>
            EvoForge
          </a>
          <nav style={{ display: "flex", gap: 16 }}>
            <a href="/" style={link}>
              Mission Control
            </a>
            <a href="/lab" style={link}>
              Improvement Lab
            </a>
            <a href="/evidence" style={link}>
              Evidence
            </a>
          </nav>
          <span style={{ marginLeft: "auto", fontSize: 12, color: "#8b96ad" }}>
            API: {apiBase}
          </span>
        </header>
        <div style={{ maxWidth: 1080, margin: "0 auto", padding: "24px" }}>
          {children}
        </div>
        <footer
          style={{ padding: "16px 24px", fontSize: 12, color: "#8b96ad" }}
        >
          Builder: Muse Spark 1.3 via Meta Model API · Gates: GH_INTEGRITY
          (oracle_ast + provisional D-054) · costs are provider_billed
          actuals in cents from GET /v1/ledger; UNKNOWN holds listed separately
        </footer>
      </body>
    </html>
  );
}
