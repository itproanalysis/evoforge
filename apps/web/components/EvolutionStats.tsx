"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { getEvolutionStats, type EvolutionStatsResponse } from "../lib/api";
import { statsView, type ReplaySideKey } from "../lib/roundReplay";

type Props = { stats?: EvolutionStatsResponse | null };

const SIDES: ReplaySideKey[] = ["evoforge", "single"];

function clamp01(x: unknown): number | null {
  return typeof x === "number" && Number.isFinite(x) ? Math.min(1, Math.max(0, x)) : null;
}

export function EvolutionStats({ stats: initial }: Props) {
  const t = useTranslations("replay");
  const [stats, setStats] = useState<EvolutionStatsResponse | null>(initial ?? null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initial !== undefined) {
      setStats(initial);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const doc = await getEvolutionStats();
        if (!cancelled) setStats(doc);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "failed to load stats");
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  const view = statsView(stats);
  const verdict = view?.verdict ?? null;
  const verdictKey =
    verdict === "evoforge_better"
      ? "stats-evoforge-better"
      : verdict === "single_better"
        ? "stats-single-better"
        : "stats-not-significant";
  const method = stats && typeof stats.method === "string" ? stats.method : "";

  return (
    <section aria-label={t("stats-title")} className="mb-4 p-3 rounded-lg border border-border bg-background-secondary">
      <div className="flex items-center gap-2 flex-wrap">
        <h2 className="text-sm font-semibold">{t("stats-title")}</h2>
        {view && (
          <span
            data-verdict={verdict}
            className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border ${
              verdict === "not_significant"
                ? "bg-amber-950/60 text-amber-300 border-amber-500/40"
                : "bg-emerald-950/60 text-emerald-300 border-emerald-500/40"
            }`}
          >
            {t(verdictKey)}
          </span>
        )}
      </div>
      {error && <p style={{ color: "#f87171", fontSize: 12 }}>{error}</p>}
      {!view ? (
        <p className="mt-2 text-xs text-text-secondary">{t("stats-runs", { count: 0 })}</p>
      ) : (
        <>
          <p className="mt-2 text-xs text-text-secondary">{t("stats-runs", { count: view.runs })}</p>
          <div className="replay-columns grid grid-cols-1 md:grid-cols-2 gap-4 mt-2">
            {SIDES.map((side) => {
              const label = side === "evoforge" ? t("evoforge") : t("single");
              const v = view[side];
              const raw = stats?.by_side?.[side];
              const lo = clamp01(Array.isArray(raw?.wilson95) ? raw?.wilson95[0] : null);
              const hi = clamp01(Array.isArray(raw?.wilson95) ? raw?.wilson95[1] : null);
              const left = lo === null ? 0 : lo * 100;
              const width = lo === null || hi === null ? 0 : Math.max(0, (hi - lo) * 100);
              return (
                <div
                  key={side}
                  data-side={side}
                  className="p-3 rounded-lg border border-border bg-background-tertiary"
                >
                  <strong className="text-sm">{label}</strong>
                  <div className="mt-2 text-xs text-text-secondary flex gap-4 flex-wrap">
                    <span>
                      {t("stats-verified")}: <strong className="text-text-primary">{v.verified}</strong>
                    </span>
                    <span>
                      {t("stats-rate")}: <strong className="text-text-primary">{v.rate}</strong>
                    </span>
                    <span>
                      {t("stats-interval")}: <strong className="text-text-primary">{v.interval}</strong>
                    </span>
                    <span>
                      {t("stats-cost-per-verified")}:{" "}
                      <strong className="text-text-primary">{v.costPerVerified}</strong>
                    </span>
                  </div>
                  <div
                    className="mt-2 h-2 rounded bg-slate-800 relative overflow-hidden"
                    role="img"
                    aria-label={`${label} ${v.interval}`}
                    data-interval-bar={side}
                  >
                    <div
                      className="absolute top-0 bottom-0 rounded bg-accent-blue"
                      style={{ left: `${left}%`, width: `${width}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
          {method && (
            <p className="mt-2 text-xs text-text-secondary">
              {t("stats-method")}: {method}
            </p>
          )}
        </>
      )}
    </section>
  );
}

export default EvolutionStats;
