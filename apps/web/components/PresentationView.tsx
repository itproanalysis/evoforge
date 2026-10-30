"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { SandboxedPreview } from "./SandboxedPreview";
import { presentationFrames } from "../lib/roundReplay";
import type { EvolutionRun } from "../lib/api";

type Props = { run: EvolutionRun; onExit?: () => void };

export function PresentationView({ run, onExit }: Props) {
  const t = useTranslations("replay");
  const frames = useMemo(() => presentationFrames(run), [run]);
  const rounds = useMemo(() => frames.filter((f) => f.kind === "round"), [frames]);
  const [pos, setPos] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    setPos(0);
    setPaused(false);
  }, [run.run_id]);

  useEffect(() => {
    if (paused || frames.length === 0) return;
    const id = setInterval(() => {
      setPos((p) => (p + 1) % frames.length);
    }, 4000);
    return () => clearInterval(id);
  }, [paused, frames.length]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (onExit) onExit();
      } else if (e.key === "ArrowRight") {
        setPos((p) => (frames.length === 0 ? 0 : (p + 1) % frames.length));
      } else if (e.key === "ArrowLeft") {
        setPos((p) => (frames.length === 0 ? 0 : (p - 1 + frames.length) % frames.length));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [frames.length, onExit]);

  const frame = frames.length === 0 ? null : frames[pos % frames.length];
  const manifest = (run as { manifest?: Record<string, unknown> | null }).manifest ?? null;
  const comparisonMode =
    manifest && typeof manifest.comparison_mode === "string" && manifest.comparison_mode
      ? manifest.comparison_mode
      : manifest && typeof manifest.disclosure === "string"
        ? manifest.disclosure
        : "";
  const firstRound = rounds.length > 0 ? rounds[0] : null;
  const latestRound =
    rounds.length > 0 ? rounds[rounds.length - 1] : null;

  const goNext = () => setPos((p) => (frames.length === 0 ? 0 : (p + 1) % frames.length));
  const goPrevious = () => setPos((p) => (frames.length === 0 ? 0 : (p - 1 + frames.length) % frames.length));

  return (
    <div
      className="aspect-video w-full overflow-auto rounded-xl border border-border bg-background-primary p-4"
      style={{ aspectRatio: "16 / 9" }}
      aria-label={`Recorded run ${run.run_id}`}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200">
          {t("recorded-run")}
        </span>
        <span className="text-sm font-semibold">Recorded run {run.run_id}</span>
        {comparisonMode && (
          <span className="text-xs text-text-secondary">
            {t("comparison-mode")}: {comparisonMode}
          </span>
        )}
      </div>

      {frame?.kind === "round" && (
        <div className="mt-2">
          <h2 className="text-lg font-bold">
            {frame.name} · R{frame.index}
          </h2>
          <div className="mt-1 text-xs text-text-secondary flex gap-4 flex-wrap">
            <span>
              {t("evoforge")}: {frame.evoforge.status} · {t("score")} {frame.evoforge.score} · {t("cost")}{" "}
              {frame.cost.evoforge}
            </span>
            <span>
              {t("single")}: {frame.single.status} · {t("score")} {frame.single.score} · {t("cost")}{" "}
              {frame.cost.single}
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
            <div>
              <strong className="text-sm">{t("evoforge")}</strong>
              <div className="text-xs text-text-secondary">
                {frame.evoforge.status} · {frame.evoforge.score} · {frame.cost.evoforge}
              </div>
              <div className="mt-2 min-h-[320px]">
                {frame.evoforge.previewHtml !== null ? (
                  <SandboxedPreview html={frame.evoforge.previewHtml} title={`EvoForge R${frame.index}`} />
                ) : (
                  <p className="text-xs text-text-secondary">{t("pending")}</p>
                )}
              </div>
            </div>
            <div>
              <strong className="text-sm">{t("single")}</strong>
              <div className="text-xs text-text-secondary">
                {frame.single.status} · {frame.single.score} · {frame.cost.single}
              </div>
              <div className="mt-2 min-h-[320px]">
                {frame.single.previewHtml !== null ? (
                  <SandboxedPreview html={frame.single.previewHtml} title={`Single AI R${frame.index}`} />
                ) : (
                  <p className="text-xs text-text-secondary">{t("pending")}</p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {frame?.kind === "summary" && (
        <div className="mt-2">
          <h2 className="text-lg font-bold">{t("summary")}</h2>
          <div className="mt-1 text-xs text-text-secondary flex gap-4 flex-wrap">
            <span>
              {t("evoforge")}: {t("verified")} {frame.verified.evoforge}
            </span>
            <span>
              {t("single")}: {t("verified")} {frame.verified.single}
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
            <div>
              <strong className="text-sm">
                {t("evoforge")} · R{frame.first} / R{frame.latest}
              </strong>
              <div className="mt-2">
                {firstRound && firstRound.kind === "round" && firstRound.evoforge.previewHtml !== null ? (
                  <SandboxedPreview html={firstRound.evoforge.previewHtml} title={`EvoForge R${frame.first}`} />
                ) : (
                  <p className="text-xs text-text-secondary">R{frame.first}</p>
                )}
              </div>
              <div className="mt-2">
                {latestRound && latestRound.kind === "round" && latestRound.evoforge.previewHtml !== null ? (
                  <SandboxedPreview html={latestRound.evoforge.previewHtml} title={`EvoForge R${frame.latest}`} />
                ) : (
                  <p className="text-xs text-text-secondary">R{frame.latest}</p>
                )}
              </div>
            </div>
            <div>
              <strong className="text-sm">
                {t("single")} · R{frame.first} / R{frame.latest}
              </strong>
              <div className="mt-2">
                {firstRound && firstRound.kind === "round" && firstRound.single.previewHtml !== null ? (
                  <SandboxedPreview html={firstRound.single.previewHtml} title={`Single AI R${frame.first}`} />
                ) : (
                  <p className="text-xs text-text-secondary">R{frame.first}</p>
                )}
              </div>
              <div className="mt-2">
                {latestRound && latestRound.kind === "round" && latestRound.single.previewHtml !== null ? (
                  <SandboxedPreview html={latestRound.single.previewHtml} title={`Single AI R${frame.latest}`} />
                ) : (
                  <p className="text-xs text-text-secondary">R{frame.latest}</p>
                )}
              </div>
            </div>
          </div>
          <p className="mt-2 text-xs text-text-secondary">{frame.label}</p>
        </div>
      )}

      <div className="mt-3 flex items-center gap-2 flex-wrap" role="group" aria-label="presentation controls">
        <button
          type="button"
          onClick={() => setPaused((p) => !p)}
          className="px-2.5 py-1 rounded text-xs border border-border bg-background-secondary cursor-pointer"
        >
          {paused ? t("play") : t("pause")}
        </button>
        <button
          type="button"
          onClick={goPrevious}
          className="px-2.5 py-1 rounded text-xs border border-border bg-background-secondary cursor-pointer"
        >
          {t("previous")}
        </button>
        <button
          type="button"
          onClick={goNext}
          className="px-2.5 py-1 rounded text-xs border border-border bg-background-secondary cursor-pointer"
        >
          {t("next")}
        </button>
        <button
          type="button"
          onClick={() => onExit && onExit()}
          title="Exit (Esc)"
          className="px-2.5 py-1 rounded text-xs border border-border bg-background-secondary cursor-pointer"
        >
          {t("exit")}
        </button>
      </div>
    </div>
  );
}

export default PresentationView;
