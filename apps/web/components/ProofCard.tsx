"use client";
import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  getPerformance,
  type MeasurementRecord,
} from "../lib/api";
import { bestHarnessComparison } from "../lib/evolutionTimeline";

export interface ProofCardProps {
  history?: MeasurementRecord[] | null;
  loading?: boolean;
  className?: string;
}

function round1(val: number): number {
  return Math.round(val * 10) / 10;
}

function formatPct(rate: number | null | undefined): string {
  return typeof rate === "number" && Number.isFinite(rate)
    ? `${round1(rate * 100)}%`
    : "—";
}

function clamp01(v: number): number {
  if (typeof v !== "number" || Number.isNaN(v)) return 0;
  return Math.min(1, Math.max(0, v));
}

export function ProofCard(props: ProofCardProps) {
  const t = useTranslations("mission-control");
  const tCommon = useTranslations("common");
  const [fetched, setFetched] = useState<MeasurementRecord[] | null>(null);
  const [fetching, setFetching] = useState(false);

  const hasHistoryProp = Array.isArray(props.history);

  useEffect(() => {
    if (hasHistoryProp) return;
    let alive = true;
    setFetching(true);
    getPerformance()
      .then((snap) => {
        if (!alive) return;
        setFetched(Array.isArray(snap?.history) ? snap.history : []);
      })
      .catch(() => {
        if (!alive) return;
        setFetched([]);
      })
      .finally(() => {
        if (!alive) return;
        setFetching(false);
      });
    return () => {
      alive = false;
    };
  }, [hasHistoryProp]);

  const loading = props.loading ?? fetching;
  const history = hasHistoryProp
    ? (props.history as MeasurementRecord[])
    : fetched;

  const comparison = useMemo(() => {
    if (loading && !hasHistoryProp && fetched === null) return undefined;
    if (!Array.isArray(history)) return null;
    return bestHarnessComparison(history);
  }, [history, loading, hasHistoryProp, fetched]);

  const badgeKey =
    comparison && comparison !== undefined
      ? comparison.verdict === "improved"
        ? "proof.badge-improved"
        : comparison.verdict === "worse"
          ? "proof.badge-worse"
          : "proof.badge-unclear"
      : null;

  const deltaText =
    comparison && comparison !== undefined && comparison !== null
      ? `${comparison.delta_pp > 0 ? "+" : ""}${round1(comparison.delta_pp)}%p`
      : "";

  return (
    <section
      data-testid="proof-card"
      aria-live="polite"
      className={props.className ?? "mt-4"}
      style={{ maxWidth: "100%" }}
    >
      <style>{`@keyframes proof-fade-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}.proof-enter{animation:proof-fade-in 400ms ease-out}@media (prefers-reduced-motion:reduce){.proof-enter{animation:none !important}}`}</style>
      <div
        className="proof-enter motion-reduce:animate-none border border-border rounded-card bg-background-primary p-3 min-w-0 w-full"
        style={{ maxWidth: "100%" }}
      >
        {loading && comparison === undefined ? (
          <p data-testid="proof-loading" className="text-sm text-text-secondary mb-0">
            {tCommon("loading")}
          </p>
        ) : comparison === null ? (
          <div className="min-w-0">
            <h2 className="text-base font-semibold m-0">{t("proof.heading")}</h2>
            <p data-testid="proof-empty" className="text-sm text-text-secondary mb-0 mt-1">
              {t("proof.empty")}
            </p>
            <p className="text-xs text-text-secondary mt-2 mb-0">{t("proof.rule")}</p>
            <a
              data-testid="proof-link"
              href="/performance"
              className="text-xs text-accent-cyan hover:underline"
            >
              {t("proof.link")}
            </a>
          </div>
        ) : comparison !== undefined && comparison !== null ? (
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap min-w-0">
              <h2 className="text-base font-semibold m-0 min-w-0">
                {t("proof.heading")}
              </h2>
              {badgeKey ? (
                <span
                  data-testid="proof-verdict"
                  className={`text-xs px-2 py-0.5 rounded-full border font-semibold whitespace-nowrap ${
                    comparison.verdict === "improved"
                      ? "bg-accent-green/20 text-accent-green border-accent-green/40"
                      : comparison.verdict === "worse"
                        ? "bg-accent-red/20 text-accent-red border-accent-red/40"
                        : "bg-accent-amber/20 text-accent-amber border-accent-amber/40"
                  }`}
                >
                  {t(badgeKey as never)}
                </span>
              ) : null}
            </div>
            <p className="text-xs text-text-secondary mt-1 mb-0 break-words">
              {comparison.suite_version} · {comparison.model} · {deltaText}
            </p>
            <div className="flex gap-3 flex-wrap mt-3 min-w-0">
              <div data-testid="proof-from" className="flex-1 min-w-[140px]">
                <div className="text-xs text-text-secondary">
                  {t("proof.from-label")} · {comparison.from.harness_version}
                </div>
                <div className="text-2xl font-bold mt-0.5">
                  {formatPct(comparison.from.pass_rate)}
                </div>
                <div className="text-xs text-text-secondary">
                  {comparison.from.passed}/{comparison.from.n} ·{" "}
                  {t("proof.interval-label")}{" "}
                  {formatPct(comparison.from.lo)}–{formatPct(comparison.from.hi)}
                </div>
              </div>
              <div data-testid="proof-to" className="flex-1 min-w-[140px]">
                <div className="text-xs text-text-secondary">
                  {t("proof.to-label")} · {comparison.to.harness_version}
                </div>
                <div className="text-2xl font-bold mt-0.5">
                  {formatPct(comparison.to.pass_rate)}
                </div>
                <div className="text-xs text-text-secondary">
                  {comparison.to.passed}/{comparison.to.n} ·{" "}
                  {t("proof.interval-label")}{" "}
                  {formatPct(comparison.to.lo)}–{formatPct(comparison.to.hi)}
                </div>
              </div>
            </div>
            <div
              data-testid="proof-bar"
              role="img"
              aria-label={`${comparison.from.harness_version} ${formatPct(comparison.from.lo)}-${formatPct(comparison.from.hi)}, ${comparison.to.harness_version} ${formatPct(comparison.to.lo)}-${formatPct(comparison.to.hi)}`}
              className="relative w-full mt-3 rounded-full bg-background-elevated border border-border"
              style={{ height: 10, maxWidth: "100%" }}
            >
              <div
                data-testid="proof-bar-from"
                title={`${comparison.from.harness_version} ${formatPct(comparison.from.lo)}-${formatPct(comparison.from.hi)}`}
                className="absolute rounded-full"
                style={{
                  left: `${clamp01(comparison.from.lo) * 100}%`,
                  width: `${Math.max(0, (clamp01(comparison.from.hi) - clamp01(comparison.from.lo)) * 100)}%`,
                  top: 1,
                  bottom: 1,
                  backgroundColor: "#38bdf8",
                  opacity: 0.85,
                }}
              />
              <div
                data-testid="proof-bar-to"
                title={`${comparison.to.harness_version} ${formatPct(comparison.to.lo)}-${formatPct(comparison.to.hi)}`}
                className="absolute rounded-full"
                style={{
                  left: `${clamp01(comparison.to.lo) * 100}%`,
                  width: `${Math.max(0, (clamp01(comparison.to.hi) - clamp01(comparison.to.lo)) * 100)}%`,
                  top: 1,
                  bottom: 1,
                  backgroundColor: "#22c55e",
                  opacity: 0.85,
                }}
              />
            </div>
            <div className="flex justify-between text-xs text-text-secondary mt-1">
              <span>0%</span>
              <span>100%</span>
            </div>
            {comparison.pipeline ? (
              <p
                data-testid="proof-pipeline"
                className="text-sm text-text-secondary mt-2 mb-0 break-words"
              >
                {t("proof.pipeline-label")}: {formatPct(comparison.pipeline.pass_rate)}{" "}
                ({comparison.pipeline.passed}/{comparison.pipeline.n})
              </p>
            ) : null}
            <p data-testid="proof-rule" className="text-xs text-text-secondary mt-2 mb-0">
              {t("proof.rule")}
            </p>
            <a
              data-testid="proof-link"
              href="/performance"
              className="text-xs text-accent-cyan hover:underline"
            >
              {t("proof.link")}
            </a>
          </div>
        ) : null}
      </div>
    </section>
  );
}

export default ProofCard;
