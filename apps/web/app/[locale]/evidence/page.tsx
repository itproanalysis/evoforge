"use client";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  EVIDENCE_STAGES,
  getEvent,
  getEvidence,
  listMissions,
  listOutcomes,
} from "../../../lib/api";
import { Button, Input, Card } from "../../../components/ui";
import EvidenceGraph from "../../../components/EvidenceGraph";
import { buildEvidenceGraph } from "../../../lib/evidenceGraph";
import { getErrorMessageKey } from "../../../lib/apiErrors";

interface Link {
  stage: string;
  event_id: string | null;
}

interface RecentEvidenceItem {
  eid: string;
  label: string;
}

interface GateInput {
  gate: string;
  result: string;
  reason?: string;
}

function extractGates(raw: unknown): GateInput[] {
  if (raw && typeof raw === "object") {
    const r = raw as Record<string, unknown>;
    const gates = r.gates;
    if (Array.isArray(gates)) {
      return gates
        .filter((g) => g && typeof g === "object")
        .map((g) => {
          const o = g as Record<string, unknown>;
          const gate = typeof o.gate === "string" ? o.gate : "";
          const result = typeof o.result === "string" ? o.result : "";
          const reason = typeof o.reason === "string" ? o.reason : undefined;
          return reason === undefined
            ? { gate, result }
            : { gate, result, reason };
        })
        .filter((g) => g.gate && g.result);
    }
  }
  return [];
}

function normalize(raw: unknown, fallbackId: string): Link[] {
  if (raw && typeof raw === "object") {
    const r = raw as Record<string, unknown>;
    // mission_chain merges the stages over all of the mission's records (a run record predates its PR).
    const chain = (Array.isArray(r.mission_chain) ? r.mission_chain : r.chain) as
      | Array<{ stage?: string; event_id?: string | null }>
      | undefined;
    if (Array.isArray(chain)) {
      const byStage = new Map(
        chain.map((c) => [String(c.stage), c.event_id ?? null])
      );
      return EVIDENCE_STAGES.map((s) => ({
        stage: s,
        event_id: byStage.has(s) ? (byStage.get(s) as string | null) : null,
      }));
    }
    const keys = [
      "objective_version",
      "task",
      "candidate",
      "gate",
      "review",
      "pr",
      "outcome",
    ];
    if (keys.some((k) => k in r)) {
      return EVIDENCE_STAGES.map((s, i) => ({
        stage: s,
        event_id: typeof r[keys[i]] === "string" ? (r[keys[i]] as string) : null,
      }));
    }
  }
  void fallbackId;
  return EVIDENCE_STAGES.map((s) => ({ stage: s, event_id: null }));
}

export default function EvidencePage() {
  const t = useTranslations("evidence");
  const tErrors = useTranslations("errors");

  const [id, setId] = useState("cmd_demo");
  const [recentIds, setRecentIds] = useState<RecentEvidenceItem[]>([]);
  const [links, setLinks] = useState<Link[] | null>(null);
  const [evidence, setEvidence] = useState<{
    chain: Link[];
    gates: GateInput[];
  } | null>(null);
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
      setEvidence({ chain: normalize(out, clean), gates: extractGates(out) });
      setRaw(JSON.stringify(out, null, 2));
      setSelected(null);
      setDetail("");
      setDetailErr("");
    } catch (e) {
      const errorKey = getErrorMessageKey(e);
      setErr(tErrors(errorKey as any));
      setLinks(normalize(null, clean));
      setEvidence({ chain: normalize(null, clean), gates: [] });
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
      const items: RecentEvidenceItem[] = [];
      const seen = new Set<string>();
      try {
        const mRes = await listMissions();
        // Most complete missions first; probes and missions that never left CREATED have no chain to show.
        const rank: Record<string, number> = { PR_OPENED: 0, RAN: 1, REVIEWED: 2, GENERATED: 3 };
        const shown = (mRes.missions ?? [])
          .filter((m) => m.state !== "CREATED" && !/probe/i.test(m.goal ?? ""))
          .sort((a, b) => (rank[a.state] ?? 9) - (rank[b.state] ?? 9));
        for (const m of shown) {
          for (const eid of [...(m.evidence_ids ?? [])].reverse()) {
            if (eid && !seen.has(eid)) {
              seen.add(eid);
              items.push({ eid, label: `${m.mission_id} (${m.state})` });
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
              items.push({ eid, label: `verified improvement ${o.mission_id}` });
            }
          }
        }
      } catch {}
      setRecentIds(items);
      if (!qId && items.length > 0) {
        void fetchById(items[0].eid);
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
      const errorKey = getErrorMessageKey(e);
      setDetailErr(tErrors(errorKey as any));
      setDetail("");
    } finally {
      setDetailLoading(false);
    }
  };

  return (
    <main>
      <h1 className="text-2xl font-bold">{t("heading")}</h1>
      <p className="text-text-secondary text-sm">{t("description")}</p>

      <Card className="mt-4">
        <div className="flex gap-2">
          <Input
            value={id}
            onChange={(e) => setId(e.target.value)}
            placeholder={t("input-placeholder")}
            className="flex-1"
          />
          <Button
            onClick={fetchOne}
            disabled={loading || !id.trim()}
            loading={loading}
            variant="primary"
          >
            {loading ? t("loading") : t("fetch-button")}
          </Button>
        </div>
        <div className="mt-3">
          <div className="text-xs text-text-secondary mb-1.5">
            {t("recent-evidence-heading")}
          </div>
          {recentIds.length === 0 ? (
            <div className="text-xs text-text-secondary">
              {t("recent-evidence-empty")}
            </div>
          ) : (
            <div className="flex gap-1.5 flex-wrap">
              {recentIds.slice(0, 12).map((item) => (
                <button
                  key={item.eid}
                  onClick={() => void fetchById(item.eid)}
                  className={`text-xs px-2.5 py-1 rounded border cursor-pointer transition-colors ${
                    id === item.eid
                      ? "bg-accent-blue text-white border-accent-blue font-semibold"
                      : "bg-background-primary text-text-tertiary border-border hover:border-border-secondary"
                  }`}
                >
                  <code>{item.eid}</code>{" "}
                  <span className="opacity-75">· {item.label}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {err && (
          <p className="text-accent-red text-sm mt-2">
            {t("error-prefix")}
            {err}
          </p>
        )}
      </Card>

      {evidence && (
        <Card className="mt-4">
          <EvidenceGraph
            graph={buildEvidenceGraph(evidence.chain, evidence.gates ?? [])}
          />
        </Card>
      )}

      {links && (
        <Card className="mt-4">
          <ol className="list-none p-0 grid gap-2">
            {links.map((l) => (
              <li
                key={l.stage}
                className="flex items-center gap-2.5 border border-border rounded-lg p-2.5 bg-background-elevated text-sm"
              >
                <strong className="min-w-[150px]">
                  {t(`stages.${l.stage}` as any)}
                </strong>
                {l.event_id ? (
                  <>
                    <button
                      onClick={() => fetchEvent(l.event_id as string)}
                      className="bg-transparent border border-border-secondary rounded-md px-2 py-0.5 cursor-pointer text-blue-300 hover:bg-background-secondary"
                    >
                      <code>{l.event_id}</code>
                    </button>
                    {l.stage === "Review" && (
                      <span className="text-xs text-text-secondary">
                        {t("review-summary-hint")} GET /v1/events/{l.event_id}
                      </span>
                    )}
                  </>
                ) : (
                  <span className="bg-accent-amber text-background-primary font-bold text-xs px-2.5 py-0.5 rounded-badge">
                    {t("evidence-missing")}
                  </span>
                )}
              </li>
            ))}
          </ol>
          {selected && (
            <div className="mt-3">
              <h3 className="text-sm font-semibold">
                {t("event-label", { id: selected })}
              </h3>
              {detailLoading && <p className="text-xs">{t("loading-event")}</p>}
              {detailErr && (
                <p className="text-accent-red text-sm">
                  {t("error-prefix")}
                  {detailErr}
                </p>
              )}
              {detail && (
                <pre className="bg-background-primary border border-border rounded-lg p-3 text-xs overflow-auto mt-2">
                  {detail}
                </pre>
              )}
            </div>
          )}
          {raw && (
            <pre className="bg-background-primary border border-border rounded-lg p-3 text-xs overflow-auto mt-3">
              {raw}
            </pre>
          )}
        </Card>
      )}
    </main>
  );
}
