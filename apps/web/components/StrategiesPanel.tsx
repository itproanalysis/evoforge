"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  getEvolutionStrategies,
  promoteEvolutionStrategy,
} from "../lib/api";
import { strategiesView, type StrategiesOverview } from "../lib/roundReplay";

type Props = {
  strategies?: unknown;
  overview?: unknown;
};

function clamp01(x: unknown): number | null {
  return typeof x === "number" && Number.isFinite(x) ? Math.min(1, Math.max(0, x)) : null;
}

function intervalOf(overview: unknown, id: string): [number | null, number | null] {
  const o = overview && typeof overview === "object" ? (overview as Record<string, unknown>) : null;
  const cands = o && Array.isArray(o.candidates) ? o.candidates : [];
  for (const c of cands) {
    if (!c || typeof c !== "object") continue;
    const cand = c as Record<string, unknown>;
    if (cand.strategy_id !== id) continue;
    const evo =
      cand.evoforge && typeof cand.evoforge === "object"
        ? (cand.evoforge as Record<string, unknown>)
        : null;
    const w = evo?.wilson95;
    if (
      Array.isArray(w) &&
      typeof w[0] === "number" &&
      Number.isFinite(w[0]) &&
      typeof w[1] === "number" &&
      Number.isFinite(w[1])
    ) {
      return [w[0] as number, w[1] as number];
    }
    return [null, null];
  }
  return [null, null];
}

function reasonOf(body: unknown): string {
  if (body && typeof body === "object") {
    const rec = body as Record<string, unknown>;
    if (typeof rec.detail === "string" && rec.detail) return rec.detail;
    if (typeof rec.reason === "string" && rec.reason) return rec.reason;
  }
  return "promotion rejected";
}

export function StrategiesPanel({ strategies: initialStrategies, overview: initialOverview }: Props) {
  const t = useTranslations("replay");
  const initial = initialStrategies !== undefined ? initialStrategies : initialOverview;
  const [overview, setOverview] = useState<StrategiesOverview | null>(
    (initial as StrategiesOverview | null) ?? null,
  );
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const res = await getEvolutionStrategies();
      if (res.status === 200 && res.body && typeof res.body === "object") {
        setOverview(res.body as StrategiesOverview);
      } else {
        setError(reasonOf(res.body));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load strategies");
    }
  };

  useEffect(() => {
    if (initial !== undefined) {
      setOverview((initial as StrategiesOverview | null) ?? null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await getEvolutionStrategies();
        if (cancelled) return;
        if (res.status === 200 && res.body && typeof res.body === "object") {
          setOverview(res.body as StrategiesOverview);
        } else if (!cancelled) {
          setError(reasonOf(res.body));
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "failed to load strategies");
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  const view = strategiesView(overview);
  const operator = process.env.NEXT_PUBLIC_EVO_OPERATOR_CONTROLS === "1";

  const onPromote = async (id: string) => {
    if (busyId || !operator) return;
    setBusyId(id);
    setNotice(null);
    setError(null);
    try {
      const res = await promoteEvolutionStrategy(id);
      if (res.status === 200 || res.status === 201) {
        await refresh();
      } else {
        setNotice(reasonOf(res.body));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to promote strategy");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section aria-label={t("strategies-title")} className="mb-4 p-3 rounded-lg border border-border bg-background-secondary">
      <h2 className="text-sm font-semibold">{t("strategies-title")}</h2>
      {error && <p style={{ color: "#f87171", fontSize: 12 }}>{error}</p>}
      {notice && <p role="alert" style={{ color: "#fbbf24", fontSize: 12 }}>{notice}</p>}
      {!view ? (
        <p className="mt-2 text-xs text-text-secondary">{t("strategies-title")}</p>
      ) : (
        <>
          <div
            data-champion={view.champion.id}
            className="mt-2 p-3 rounded-lg border border-border bg-background-tertiary"
          >
            <strong className="text-sm">
              {t("strategies-champion")}: {view.champion.label}
            </strong>
            <div className="mt-1 text-xs text-text-secondary font-mono">{view.champion.id}</div>
          </div>
          <table className="mt-2 w-full text-xs">
            <thead>
              <tr className="text-text-secondary">
                <th className="text-left font-normal">{t("strategies-champion")}</th>
                <th className="text-left font-normal">{t("strategies-runs")}</th>
                <th className="text-left font-normal">{t("strategies-verified")}</th>
                <th className="text-left font-normal">{t("strategies-rate")}</th>
                <th className="text-left font-normal">{t("strategies-interval")}</th>
                <th className="text-left font-normal">{t("strategies-promotable")}</th>
              </tr>
            </thead>
            <tbody>
              {view.rows.map((row) => {
                const [lo, hi] = intervalOf(overview, row.id);
                const clo = clamp01(lo);
                const chi = clamp01(hi);
                const left = clo === null ? 0 : clo * 100;
                const width = clo === null || chi === null ? 0 : Math.max(0, (chi - clo) * 100);
                return (
                  <tr key={row.id} data-strategy={row.id} data-promotable={row.promotable ? "true" : "false"}>
                    <td className="py-1 pr-2">
                      <span className="font-mono">{row.id}</span>{" "}
                      <span className="text-text-secondary">{row.label}</span>
                      {row.isChampion && (
                        <span className="ml-1 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border border-border">
                          {t("strategies-champion")}
                        </span>
                      )}
                    </td>
                    <td className="py-1 pr-2">{row.runs}</td>
                    <td className="py-1 pr-2">{row.verified}</td>
                    <td className="py-1 pr-2">{row.rate}</td>
                    <td className="py-1 pr-2">
                      <span>{row.interval}</span>
                      <div
                        className="mt-1 h-2 rounded bg-slate-800 relative overflow-hidden"
                        role="img"
                        aria-label={`${row.id} ${row.interval}`}
                        data-interval-bar={row.id}
                      >
                        <div
                          className="absolute top-0 bottom-0 rounded bg-accent-blue"
                          style={{ left: `${left}%`, width: `${width}%` }}
                        />
                      </div>
                    </td>
                    <td className="py-1 pr-2">
                      {row.promotable && (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border border-emerald-500/40 bg-emerald-950/60 text-emerald-300">
                          {t("strategies-promotable")}
                        </span>
                      )}{" "}
                      {row.promotable && (
                        <button
                          type="button"
                          onClick={() => onPromote(row.id)}
                          disabled={!operator || busyId === row.id}
                          title={operator ? undefined : t("operator-only")}
                          className="px-2 py-0.5 rounded text-xs border border-border bg-background-secondary cursor-pointer font-semibold"
                        >
                          {t("strategies-promote")}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <h3 className="mt-3 text-sm font-semibold">{t("strategies-history")}</h3>
          {view.decisions.length === 0 ? (
            <p className="mt-1 text-xs text-text-secondary">{t("strategies-history")}</p>
          ) : (
            <ul className="mt-1 space-y-1 text-xs">
              {view.decisions.map((d, i) => (
                <li key={`${d.promoted}-${i}`} data-decision={d.promoted} className="font-mono">
                  {d.promoted} ← {d.previous}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

export default StrategiesPanel;
