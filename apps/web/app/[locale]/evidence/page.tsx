"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { EVIDENCE_STAGES, getEvent, getEvidence } from "../../../lib/api";
import { Button, Input, Card } from "../../../components/ui";
import { getErrorMessageKey } from "../../../lib/apiErrors";

interface Link {
  stage: string;
  event_id: string | null;
}

function normalize(raw: unknown, fallbackId: string): Link[] {
  if (raw && typeof raw === "object") {
    const r = raw as Record<string, unknown>;
    const chain = r.chain as
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
    // Flat object: pick known stage keys if present.
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
  // Fallback: only id known → all links missing.
  void fallbackId;
  return EVIDENCE_STAGES.map((s) => ({ stage: s, event_id: null }));
}

export default function EvidencePage() {
  const t = useTranslations("evidence");
  const tErrors = useTranslations("errors");

  const [id, setId] = useState("cmd_demo");
  const [links, setLinks] = useState<Link[] | null>(null);
  const [raw, setRaw] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState("");
  const [detailErr, setDetailErr] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);

  const fetchOne = async () => {
    setLoading(true);
    setErr("");
    try {
      const out = await getEvidence(id);
      setLinks(normalize(out, id));
      setRaw(JSON.stringify(out, null, 2));
      setSelected(null);
      setDetail("");
      setDetailErr("");
    } catch (e) {
      const errorKey = getErrorMessageKey(e);
      setErr(tErrors(errorKey as any));
      setLinks(normalize(null, id));
      setRaw("");
    } finally {
      setLoading(false);
    }
  };

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
        {err && <p className="text-accent-red text-sm mt-2">{t("error-prefix")}{err}</p>}
      </Card>

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
                        Review sealed summary via GET /v1/events/{l.event_id}
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
                  {t("error-prefix")}{detailErr}
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
