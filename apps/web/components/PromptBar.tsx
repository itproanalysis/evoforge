"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { postPromptArena, postPromptFollowup, type ArenaDoc } from "../lib/api";
import { canFollowUp } from "../lib/arenaStatus";
import { StudioIcon } from './StudioIcon';

type Props = {
  onStarted?: (arenaId: string) => void;
  disabled?: boolean;
  followUpArena?: ArenaDoc | null;
};

export function PromptBar({ onStarted, disabled, followUpArena }: Props) {
  const t = useTranslations("arena");
  const ts = useTranslations("studio");
  const tc = useTranslations("canvas");
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
    <div className="studio-composer fixed bottom-4">
      <div className="studio-composer-inner flex items-end gap-3 flex-wrap">
        <label className="flex-1 min-w-52 text-xs flex flex-col gap-1">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.repeat && !event.nativeEvent.isComposing) {
                event.preventDefault();
                void onStart();
              }
            }}
            maxLength={2000}
            rows={1}
            placeholder={tc(followUp ? 'followup' : 'prompt')}
            aria-label={t(followUp ? "prompt-followup-placeholder" : "prompt-placeholder")}
            className="w-full px-2 py-1 rounded text-xs border border-border bg-background-secondary text-text-primary"
          />
          <span className="text-text-tertiary font-mono">
            {prompt.length}/2000
          </span>
        </label>
        {!followUp && (
          <details className="studio-composer-settings" onKeyDown={event => { if (event.key === 'Escape') { event.currentTarget.open = false; event.currentTarget.querySelector('summary')?.focus(); } }}>
          <summary aria-label={ts('settings')} title={ts('settings')}><StudioIcon name="settings" width="17" height="17"/><span className="sr-only">{ts('settings')}</span></summary>
          <div>
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
          <p className="studio-composer-note">{t("prompt-equal-tools")}</p>
          </div>
          </details>
        )}
        <button
          type="button"
          onClick={onStart}
          disabled={busy || disabled || !operator || !text}
          title={operator ? t("prompt-start") : tc('readonly')}
          aria-label={t(followUp ? "prompt-followup-start" : "prompt-start")}
          className="studio-submit px-3 py-1 rounded text-xs border border-border cursor-pointer font-semibold"
        >
          <StudioIcon name="arrow" width="17" height="17" className="canvas-send-arrow"/>
          <span className="sr-only">{t(followUp ? "prompt-followup-start" : "prompt-start")}</span>
        </button>
        {error && <span style={{ color: "#a2352e", fontSize: 12 }}>{error}</span>}
      </div>
      {followUp && <p className="sr-only">{t("prompt-equal-tools")}</p>}
      {!operator && <p className="sr-only">{t("operator-only")}</p>}
    </div>
  );
}

export default PromptBar;
