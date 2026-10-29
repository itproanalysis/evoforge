"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { postPromptArena, postPromptFollowup, type ArenaDoc } from "../lib/api";
import { canFollowUp } from "../lib/arenaStatus";

type Props = {
  onStarted?: (arenaId: string) => void;
  disabled?: boolean;
  followUpArena?: ArenaDoc | null;
};

export function PromptBar({ onStarted, disabled, followUpArena }: Props) {
  const t = useTranslations("arena");
  const [prompt, setPrompt] = useState("");
  const [feedback, setFeedback] = useState<"critic" | "heldout">("critic");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Starting a prompt arena spends model credits: operator-only, with a cost
  // warning confirmed up front.
  const operator = process.env.NEXT_PUBLIC_EVO_OPERATOR_CONTROLS === "1";
  const text = prompt.trim();
  const followUp = canFollowUp(followUpArena);
  const followUpId = followUp && followUpArena ? followUpArena.arena_id : null;

  const onStart = async () => {
    if (busy || disabled || !operator || !text) return;
    if (typeof window !== "undefined" && !window.confirm(t("cost-confirm"))) return;
    setBusy(true);
    setError(null);
    try {
      const res = followUpId
        ? await postPromptFollowup(followUpId, text)
        : await postPromptArena(text, feedback, "tolerant");
      if (!res?.arena_id) throw new Error("missing arena id");
      setPrompt("");
      onStarted?.(res.arena_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to start prompt arena");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        position: "fixed",
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 40,
        borderTop: "1px solid var(--border, #1e293b)",
        background: "var(--background, #0f172a)",
        padding: "10px 16px",
      }}
    >
      <div className="max-w-7xl mx-auto flex items-end gap-3 flex-wrap">
        <label className="flex-1 min-w-52 text-xs flex flex-col gap-1">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            maxLength={2000}
            rows={2}
            placeholder={t(followUp ? "prompt-followup-placeholder" : "prompt-placeholder")}
            aria-label={t(followUp ? "prompt-followup-placeholder" : "prompt-placeholder")}
            className="w-full px-2 py-1 rounded text-xs border border-border bg-background-secondary text-text-primary"
          />
          <span className="text-text-tertiary font-mono">
            {prompt.length}/2000
          </span>
        </label>
        {!followUp && (
          <label className="text-xs flex items-center gap-1.5">
            {t("feedback-label")}
            <select
              value={feedback}
              onChange={(e) => setFeedback(e.target.value as "critic" | "heldout")}
              className="px-2 py-1 rounded text-xs border border-border bg-background-secondary cursor-pointer"
              aria-label={t("feedback-label")}
            >
              <option value="critic">{t("feedback-critic")}</option>
              <option value="heldout">{t("feedback-heldout")}</option>
            </select>
          </label>
        )}
        <button
          type="button"
          onClick={onStart}
          disabled={busy || disabled || !operator || !text}
          title={operator ? undefined : t("operator-only")}
          className="px-3 py-1 rounded text-xs border border-border bg-background-secondary cursor-pointer font-semibold"
        >
          {t(followUp ? "prompt-followup-start" : "prompt-start")}
        </button>
        {error && <span style={{ color: "#f87171", fontSize: 12 }}>{error}</span>}
      </div>
      <p className="max-w-7xl mx-auto mt-1 text-xs text-text-secondary">{t("prompt-equal-tools")}</p>
      {!operator && <p className="max-w-7xl mx-auto mt-1 text-xs text-text-secondary">{t("operator-only")}</p>}
    </div>
  );
}

export default PromptBar;
