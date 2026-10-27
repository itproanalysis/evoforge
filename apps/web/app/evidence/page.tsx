"use client";
import { useEffect, useState } from "react";
import {
  EVIDENCE_STAGES,
  getEvent,
  getEvidence,
  listMissions,
  listOutcomes,
} from "../../lib/api";

const card: React.CSSProperties = {
  background: "#141b2d",
  border: "1px solid #263048",
  borderRadius: 10,
  padding: 14,
  marginTop: 16,
};

interface Link {
  stage: string;
  event_id: string | null;
}

function normalize(raw: unknown, fallbackId: string): Link[] {
  if (raw && typeof raw === "object") {
    const r = raw as Record<string, unknown>;
    const chain = r.chain as Array<{ stage?: string; event_id?: string | null }> | undefined;
    if (Array.isArray(chain)) {
      const byStage = new Map(chain.map((c) => [String(c.stage), c.event_id ?? null]));
      return EVIDENCE_STAGES.map((s) => ({
        stage: s,
        event_id: byStage.has(s) ? (byStage.get(s) as string | null) : null,
      }));
    }
    // Flat object: pick known stage keys if present.
    const keys = ["objective_version", "task", "candidate", "gate", "review", "pr", "outcome"];
    if (keys.some((k) => k in r)) {
      return EVIDENCE_STAGES.map((s, i) => ({
        stage: s,
        event_id: typeof r[keys[i]] === "string" ? (r[keys[i]] as string) : null,
      }));
    }
  }
  // Fallback: only id known → all links missing.
  void fallbackId;
  return EVIDENCE_STAGES.map((s) => ({ stage: s, event_id: null }));
}

export default function EvidencePage() {
  const [id, setId] = useState("cmd_demo");
  const [recentIds, setRecentIds] = useState<string[]>([]);
  const [links, setLinks] = useState<Link[] | null>(null);
  const [raw, setRaw] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState("");
  const [detailErr, setDetailErr] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);

  const fetchById = async (targetId: string) => {
    const clean = targetId.trim();
    if (!clean) return;
    setId(clean);
    setLoading(true);
    setErr("");
    try {
      const out = await getEvidence(clean);
      setLinks(normalize(out, clean));
      setRaw(JSON.stringify(out, null, 2));
      setSelected(null);
      setDetail("");
      setDetailErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setLinks(normalize(null, clean));
      setRaw("");
    } finally {
      setLoading(false);
    }
  };

  const fetchOne = async () => {
    await fetchById(id);
  };

  useEffect(() => {
    let qId = "";
    if (typeof window !== "undefined") {
      const sp = new URLSearchParams(window.location.search);
      qId = (sp.get("id") ?? "").trim();
    }
    if (qId) {
      void fetchById(qId);
    }
    void (async () => {
      const items: string[] = [];
      const seen = new Set<string>();
      try {
        const mRes = await listMissions();
        for (const m of mRes.missions ?? []) {
          for (const eid of [...(m.evidence_ids ?? [])].reverse()) {
            if (eid && !seen.has(eid)) {
              seen.add(eid);
              items.push(eid);
            }
          }
        }
      } catch {}
      try {
        const oRes = await listOutcomes();
        for (const o of oRes.outcomes ?? []) {
          for (const eid of [o.evidence_id, o.pr_evidence_id, o.run_evidence_id]) {
            if (eid && !seen.has(eid)) {
              seen.add(eid);
              items.push(eid);
            }
          }
        }
      } catch {}
      setRecentIds(items);
      if (!qId && items.length > 0) {
        void fetchById(items[0]);
      }
    })();
  }, []);

  const fetchEvent = async (eventId: string) => {
    setSelected(eventId);
    setDetailLoading(true);
    setDetailErr("");
    try {
      const out = await getEvent(eventId);
      setDetail(JSON.stringify(out, null, 2));
    } catch (e) {
      setDetailErr(e instanceof Error ? e.message : String(e));
      setDetail("");
    } finally {
      setDetailLoading(false);
    }
  };

  return (
    <main>
      <h1>Evidence Timeline</h1>
      <p style={{ color: "#8b96ad", fontSize: 13 }}>
        GET /v1/evidence/{"{id}"} · ObjectiveVersion→Task→Candidate→Gate→Review→PR→Outcome
      </p>
      <section style={card}>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            value={id}
            onChange={(e) => setId(e.target.value)}
            placeholder="evidence / command id"
            style={{ flex: "1 1 240px", padding: 8, borderRadius: 6, border: "1px solid #33405c", background: "#0b0e14", color: "#e8edf5" }}
          />
          <button
            onClick={fetchOne}
            disabled={loading || !id.trim()}
            style={{ padding: "8px 16px", borderRadius: 6, background: "#2563eb", color: "#fff", border: 0, cursor: "pointer" }}
          >
            {loading ? "Loading…" : "Fetch evidence"}
          </button>
        </div>
        {recentIds.length > 0 ? (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
            {recentIds.slice(0, 12).map((eid) => (
              <button
                key={eid}
                onClick={() => void fetchById(eid)}
                style={{
                  background: id === eid ? "#2563eb" : "#0f1524",
                  color: "#e8edf5",
                  border: "1px solid #33405c",
                  borderRadius: 6,
                  padding: "2px 8px",
                  cursor: "pointer",
                  fontSize: 12,
                }}
              >
                <code>{eid}</code>
              </button>
            ))}
          </div>
        ) : null}
        {err ? <p style={{ color: "#ef4444", fontSize: 13 }}>Error: {err}</p> : null}
      </section>

      {links ? (
        <section style={card}>
          <ol style={{ listStyle: "none", padding: 0, display: "grid", gap: 8 }}>
            {links.map((l) => (
              <li
                key={l.stage}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  border: "1px solid #263048",
                  borderRadius: 8,
                  padding: 10,
                  background: "#0f1524",
                  fontSize: 13,
                }}
              >
                <strong style={{ minWidth: 150 }}>{l.stage}</strong>
                {l.event_id ? (
                  <>
                    <button
                      onClick={() => fetchEvent(l.event_id as string)}
                      style={{
                        background: "transparent",
                        border: "1px solid #33405c",
                        borderRadius: 6,
                        padding: "2px 8px",
                        cursor: "pointer",
                        color: "#93c5fd",
                      }}
                    >
                      <code>{l.event_id}</code>
                    </button>
                    {l.stage === "Review" ? (
                      <span style={{ fontSize: 12, color: "#8b96ad" }}>
                        Review sealed summary via GET /v1/events/{l.event_id}
                      </span>
                    ) : null}
                  </>
                ) : (
                  <span
                    style={{
                      background: "#f59e0b",
                      color: "#0b0e14",
                      fontWeight: 700,
                      fontSize: 12,
                      padding: "2px 10px",
                      borderRadius: 20,
                    }}
                  >
                    증거 부족
                  </span>
                )}
              </li>
            ))}
          </ol>
          {selected ? (
            <div style={{ marginTop: 12 }}>
              <h3 style={{ fontSize: 13 }}>Event {selected}</h3>
              {detailLoading ? <p style={{ fontSize: 12 }}>Loading event…</p> : null}
              {detailErr ? <p style={{ color: "#ef4444", fontSize: 13 }}>Error: {detailErr}</p> : null}
              {detail ? (
                <pre style={{ background: "#0b0e14", border: "1px solid #263048", borderRadius: 8, padding: 12, fontSize: 12, overflow: "auto" }}>
                  {detail}
                </pre>
              ) : null}
            </div>
          ) : null}
          {raw ? (
            <pre style={{ background: "#0b0e14", border: "1px solid #263048", borderRadius: 8, padding: 12, fontSize: 12, overflow: "auto" }}>
              {raw}
            </pre>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}
