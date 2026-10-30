"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { getArenaLimits, postPromptArena, postPromptFollowup, type ArenaDoc } from "../lib/api";
import { canFollowUp } from "../lib/arenaStatus";
import { CHALLENGES, planFits } from "../lib/challenges";
import { StudioIcon } from './StudioIcon';

type Props = {
  onStarted?: (arenaId: string) => void;
  disabled?: boolean;
  followUpArena?: ArenaDoc | null;
};

export function PromptBar({ onStarted, disabled, followUpArena }: Props) {
  const t = useTranslations("arena");
  const tp = useTranslations("plan");
  const ts = useTranslations("studio");
  const tc = useTranslations("canvas");
  const locale = useLocale();
  const [rounds, setRounds] = useState<string[]>([""]);
  const [feedback, setFeedback] = useState<"critic" | "heldout">("critic");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [limits, setLimits] = useState<{ daily_limit: number; used_today: number; remaining: number } | null>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const firstRound = rounds[0] ?? "";

  useEffect(() => {
    const field = textarea.current;
    if (!field) return;
    field.style.height = 'auto';
    field.style.height = `${Math.max(42, Math.min(field.scrollHeight, 144))}px`;
  }, [firstRound, rounds.length]);

  const refreshLimits = async () => {
    try {
      const lim = await getArenaLimits();
      if (lim && typeof lim === "object") setLimits(lim);
    } catch {
      setLimits(null);
    }
  };

  useEffect(() => {
    void refreshLimits();
  }, []);

  // Starting a prompt arena spends model credits: anyone may start within
  // the server's daily limit, with a cost warning confirmed up front.
  const followUp = canFollowUp(followUpArena);
  // A finished run can be continued, but a brand-new plan (rounds, challenges) must stay one click away.
  const [newRun, setNewRun] = useState(false);
  const followUpId = followUp && followUpArena && !newRun ? followUpArena.arena_id : null;

  const missions = followUpId
    ? []
    : rounds.map((r) => r.trim()).filter((r) => r.length > 0);
  const needed = followUpId ? 1 : missions.length;
  const remaining = limits ? limits.remaining : null;
  const limited = followUpId ? false : !planFits(remaining, needed);
  const text = (followUpId ? firstRound : (rounds[0] ?? "")).trim();
  const canStart = followUpId
    ? text.length > 0
    : missions.length > 0 && missions[0].length > 0;

  // Round fields R1..R5 ("Add round" up to 5 total, remove for R2+).
  const setRound = (index: number, value: string) => {
    setRounds((prev) => prev.map((r, i) => (i === index ? value : r)));
  };

  const addRound = () => {
    setRounds((prev) => (prev.length >= 5 ? prev : [...prev, ""]));
  };

  const removeRound = (index: number) => {
    setRounds((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== index)));
  };

  const applyChallenge = (id: string) => {
    if (!id) return;
    const found = CHALLENGES.find((c) => c.id === id);
    if (!found) return;
    const list = (locale === "ko" ? found.rounds.ko : found.rounds.en).slice(0, 5);
    if (list.length > 0) setRounds(list);
  };

  const onStart = async () => {
    if (busy || disabled || limited) return;
    if (followUpId) {
      if (!text) return;
    } else if (missions.length === 0) {
      return;
    }
    if (typeof window !== "undefined" && !window.confirm(t("cost-confirm"))) return;
    setBusy(true);
    setError(null);
    try {
      const res = followUpId
        ? await postPromptFollowup(followUpId, text)
        : await postPromptArena(missions[0], feedback, "tolerant", missions.slice(1));
      if (!res?.arena_id) throw new Error("missing arena id");
      if (!followUpId) setRounds([""]);
      else setRounds([""]);
      onStarted?.(res.arena_id);
      void refreshLimits();
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to start prompt arena");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="studio-composer fixed bottom-4">
      <div className="studio-composer-inner flex items-end gap-3 flex-wrap">
        {followUp && (
          <div className="studio-composer-mode" role="group" aria-label={tp("mode")}>
            <button type="button" aria-pressed={!newRun} onClick={() => setNewRun(false)}>{tp("continue")}</button>
            <button type="button" aria-pressed={newRun} onClick={() => setNewRun(true)}>{tp("new-run")}</button>
          </div>
        )}
        {followUpId ? (
          <label className="flex-1 min-w-52 text-xs flex flex-col gap-1">
            <textarea
              ref={textarea}
              value={firstRound}
              onChange={(e) => setRound(0, e.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.repeat && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  void onStart();
                }
              }}
              maxLength={2000}
              rows={1}
              placeholder={tc('followup')}
              aria-label={t("prompt-followup-placeholder")}
              className="w-full px-2 py-1 rounded text-xs border border-border bg-background-secondary text-text-primary"
            />
            <span className="text-text-tertiary font-mono">
              {firstRound.length}/2000
            </span>
          </label>
        ) : (
          <div className="flex-1 min-w-52 flex flex-col gap-2">
            {rounds.map((value, i) => (
              <label key={i} className="text-xs flex flex-col gap-1">
                <span className="text-text-tertiary font-mono">
                  {tp("round-label", { n: i + 1 })} R{i + 1}
                </span>
                <span className="flex items-start gap-2">
                  <textarea
                    ref={i === 0 ? textarea : undefined}
                    value={value}
                    onChange={(e) => setRound(i, e.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.repeat && !event.nativeEvent.isComposing) {
                        event.preventDefault();
                        void onStart();
                      }
                    }}
                    maxLength={2000}
                    rows={1}
                    placeholder={i === 0 ? tc('prompt') : t("prompt-followup-placeholder")}
                    aria-label={i === 0 ? t("prompt-placeholder") : t("prompt-followup-placeholder")}
                    className="w-full px-2 py-1 rounded text-xs border border-border bg-background-secondary text-text-primary"
                  />
                  {i > 0 && (
                    <button
                      type="button"
                      onClick={() => removeRound(i)}
                      aria-label={tp("remove-round")}
                      title={tp("remove-round")}
                      className="px-2 py-1 rounded text-xs border border-border cursor-pointer"
                    >
                      {tp("remove-round")}
                    </button>
                  )}
                </span>
                <span className="text-text-tertiary font-mono">
                  {value.length}/2000
                </span>
              </label>
            ))}
            {rounds.length < 5 && (
              <button
                type="button"
                onClick={addRound}
                className="px-2 py-1 rounded text-xs border border-border cursor-pointer self-start"
              >
                {tp("add-round")}
              </button>
            )}
            <label className="text-xs flex items-center gap-1.5">
              <span className="text-text-tertiary">{tp("challenges")}</span>
              <select
                value=""
                onChange={(e) => applyChallenge(e.target.value)}
                aria-label={tp("challenges")}
                className="px-2 py-1 rounded text-xs border border-border bg-background-secondary cursor-pointer max-w-full"
              >
                <option value="">{tp("challenges")}</option>
                {CHALLENGES.map((c) => (
                  <option key={c.id} value={c.id}>
                    {locale === "ko" ? c.title.ko : c.title.en}
                  </option>
                ))}
              </select>
            </label>
            <span className="text-text-tertiary font-mono text-xs" role="status">
              {limits
                ? tp("remaining-today", { remaining: limits.remaining, total: limits.daily_limit })
                : tp("remaining-today", { remaining: "—", total: "—" })}
            </span>
            {limited && (
              <span role="alert" className="text-xs" style={{ color: "#a2352e" }}>
                {tp("limit-reached")}
              </span>
            )}
          </div>
        )}
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
          disabled={busy || disabled || !canStart || limited}
          title={limited ? tp("limit-reached") : t("prompt-start")}
          aria-label={t(followUp ? "prompt-followup-start" : "prompt-start")}
          className="studio-submit px-3 py-1 rounded text-xs border border-border cursor-pointer font-semibold"
        >
          <StudioIcon name="arrow" width="17" height="17" className="canvas-send-arrow"/>
          <span className="sr-only">{t(followUp ? "prompt-followup-start" : "prompt-start")}</span>
        </button>
        {error && <span style={{ color: "#a2352e", fontSize: 12 }}>{error}</span>}
      </div>
      {followUp && <p className="sr-only">{t("prompt-equal-tools")}</p>}
    </div>
  );
}

export default PromptBar;
