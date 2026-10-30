"use client";
import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  listFeedback,
  postFeedback,
  promoteFeedback,
  type FeedbackItem,
  type FeedbackKind,
} from "../lib/api";
import { Button } from "./ui";

const KINDS: FeedbackKind[] = ["bug", "missed_case", "praise", "other"];

export interface FeedbackPanelProps {
  missionId: string;
}

export function FeedbackPanel({ missionId }: FeedbackPanelProps) {
  const t = useTranslations("feedback");
  const locale = useLocale();
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [kind, setKind] = useState<FeedbackKind>("bug");
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [promotingId, setPromotingId] = useState<string | null>(null);
  const [err, setErr] = useState("");

  const refresh = useCallback(async () => {
    try {
      const res = await listFeedback();
      const all = Array.isArray(res?.feedback) ? res.feedback : [];
      setItems(all.filter((f) => f.mission_id === missionId));
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [missionId]);

  useEffect(() => {
    setLoading(true);
    void refresh();
  }, [refresh]);

  const submit = async () => {
    if (submitting || !text.trim()) return;
    setSubmitting(true);
    setErr("");
    try {
      await postFeedback(missionId, kind, text.trim());
      setText("");
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const promote = async (feedback_id: string) => {
    if (promotingId) return;
    setPromotingId(feedback_id);
    setErr("");
    try {
      await promoteFeedback(feedback_id);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPromotingId(null);
    }
  };

  return (
    <div className="mt-4 pt-3 border-t border-border">
      <div className="text-xs text-text-secondary mb-2">{t("heading")}</div>
      <div className="flex gap-2 flex-wrap">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as FeedbackKind)}
          aria-label={t("kind-label")}
          className="px-2 py-1.5 rounded border border-border bg-background-primary text-sm text-text-primary"
        >
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {t(`kinds.${k}`)}
            </option>
          ))}
        </select>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t("text-placeholder")}
          maxLength={2000}
          className="flex-[2_1_240px] px-2 py-1.5 rounded border border-border bg-background-primary text-sm text-text-primary"
        />
        <Button
          onClick={submit}
          disabled={submitting || !text.trim()}
          loading={submitting}
          variant="secondary"
        >
          {submitting ? t("submitting") : t("submit")}
        </Button>
      </div>
      {err && (
        <p role="alert" className="text-xs text-accent-red mt-2 mb-0">
          {t("error-prefix")}
          {err}
        </p>
      )}
      <div className="grid gap-2 mt-3">
        {loading ? (
          <p className="text-sm text-text-secondary mb-0">{t("loading")}</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-text-secondary mb-0">{t("empty")}</p>
        ) : (
          items.map((f) => (
            <div
              key={f.feedback_id}
              className="flex items-center justify-between flex-wrap gap-2 p-2.5 rounded-lg border border-border bg-background-primary text-sm"
            >
              <div className="flex items-center gap-2 flex-wrap min-w-0">
                <span className="text-xs px-2 py-0.5 rounded-full bg-background-elevated border border-border font-semibold">
                  {t(`kinds.${f.kind}`)}
                </span>
                <span className="text-text-primary break-words">{f.text}</span>
                {f.created_at ? (
                  <span className="text-xs text-text-secondary">
                    {new Date(f.created_at * 1000).toLocaleString(locale)}
                  </span>
                ) : null}
              </div>
              {f.promoted_mission_id ? (
                <span className="text-xs text-accent-green font-semibold">
                  {t("promoted")}: <code>{f.promoted_mission_id}</code>
                </span>
              ) : (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={promotingId === f.feedback_id}
                  loading={promotingId === f.feedback_id}
                  onClick={() => void promote(f.feedback_id)}
                >
                  {promotingId === f.feedback_id ? t("promoting") : t("promote")}
                </Button>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
