"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { SandboxedPreview } from "./SandboxedPreview";
import {
  firstLatest,
  latestCommonRound,
  nextRound,
  roundView,
  totalsView,
} from "../lib/roundReplay";
import type { EvolutionRun } from "../lib/api";

type Props = { run: EvolutionRun };

const DOT_COLORS: Record<string, string> = {
  READY: "#12a66e",
  UNVERIFIED: "#e88400",
  FAILED: "#f04452",
  PENDING: "#b0b8c1",
};

const BADGE_CLASSES: Record<string, string> = {
  READY: "bg-emerald-50 text-emerald-700 border-emerald-200",
  UNVERIFIED: "bg-amber-50 text-amber-700 border-amber-200",
  FAILED: "bg-rose-50 text-rose-700 border-rose-200",
  PENDING: "bg-slate-100 text-slate-600 border-slate-200",
};

function StatusBadge({ status }: { status: string }) {
  const cls = BADGE_CLASSES[status] ?? BADGE_CLASSES.PENDING;
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border ${cls}`}
    >
      <span
        className="w-1.5 h-1.5 rounded-full mr-1.5"
        style={{ background: DOT_COLORS[status] ?? DOT_COLORS.PENDING }}
      />
      {status}
    </span>
  );
}

export function RoundReplay({ run }: Props) {
  const t = useTranslations("replay");
  const rounds = useMemo(() => {
    const list = Array.isArray(run.rounds) ? [...run.rounds] : [];
    list.sort((a, b) => a.index - b.index);
    return list;
  }, [run]);
  const latest = latestCommonRound(run);
  const [first, last] = firstLatest(run);
  const [selected, setSelected] = useState<number>(latest || rounds[0]?.index || 1);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    setSelected(latestCommonRound(run) || (rounds[0]?.index ?? 1));
    setPlaying(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.run_id]);

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      const nx = nextRound(selected, run);
      if (nx === null) {
        setPlaying(false);
      } else {
        setSelected(nx);
      }
    }, 1200);
    return () => clearInterval(id);
  }, [playing, selected, run]);

  const view = roundView(run, selected);
  const totals = totalsView(run);
  const disclosure =
    run.manifest && typeof run.manifest.disclosure === "string" ? run.manifest.disclosure : "";

  return (
    <div>
      <style>{`@media (max-width: 768px) { .replay-columns { grid-template-columns: 1fr !important; } }`}</style>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200">
          {t("recorded-run")}
        </span>
        <span className="text-sm font-semibold">{run.title ?? run.run_id}</span>
        <span className="text-xs text-text-secondary font-mono">{run.run_id}</span>
      </div>

      <div className="flex items-center gap-2 flex-wrap mt-3" role="group" aria-label="rounds">
        <button
          type="button"
          onClick={() => setSelected(first)}
          className="px-2.5 py-1 rounded text-xs border border-border bg-background-secondary cursor-pointer"
        >
          {t("first")}
        </button>
        {rounds.map((r) => {
          const v = roundView(run, r.index);
          const active = r.index === selected;
          return (
            <button
              key={r.index}
              type="button"
              aria-pressed={active}
              data-round={r.index}
              onClick={() => setSelected(r.index)}
              className={`px-2.5 py-1 rounded text-xs border cursor-pointer inline-flex items-center gap-1.5 ${
                active
                  ? "bg-accent-blue text-white border-accent-blue font-bold"
                  : "bg-background-secondary border-border"
              }`}
            >
              R{r.index}
              <span
                className="w-1.5 h-1.5 rounded-full"
                title={`evoforge:${v?.sides.evoforge.status ?? "PENDING"}`}
                style={{ background: DOT_COLORS[v?.sides.evoforge.status ?? "PENDING"] }}
              />
              <span
                className="w-1.5 h-1.5 rounded-full"
                title={`single:${v?.sides.single.status ?? "PENDING"}`}
                style={{ background: DOT_COLORS[v?.sides.single.status ?? "PENDING"] }}
              />
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => setSelected(last)}
          className="px-2.5 py-1 rounded text-xs border border-border bg-background-secondary cursor-pointer"
        >
          {t("latest")}
        </button>
        <button
          type="button"
          onClick={() => setPlaying((p) => !p)}
          className="px-2.5 py-1 rounded text-xs border border-border bg-background-secondary cursor-pointer"
        >
          {playing ? t("pause") : t("play")}
        </button>
      </div>

      {view && (
        <div className="mt-2 text-sm font-medium">
          {view.name} · R{view.index}
        </div>
      )}

      <div className="replay-columns grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
        {(["evoforge", "single"] as const).map((side) => {
          const label = side === "evoforge" ? t("evoforge") : t("single");
          const s = view?.sides[side];
          const html = s?.previewHtml ?? null;
          return (
            <div key={side} className="p-3 rounded-lg border border-border bg-background-secondary">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <strong className="text-sm">{label}</strong>
                <StatusBadge status={s?.status ?? "PENDING"} />
              </div>
              <div className="mt-2 text-xs text-text-secondary flex gap-4 flex-wrap">
                <span>
                  {t("score")}: <strong className="text-text-primary">{s?.score ?? "—"}</strong>
                </span>
                <span>
                  {t("cost")}: <strong className="text-text-primary">{s?.cost ?? "—"}</strong>
                </span>
              </div>
              <div className="mt-2">
                {html !== null ? (
                  <SandboxedPreview html={html} title={`${label} R${selected}`} />
                ) : (
                  <p className="text-xs text-text-secondary">{t("pending")}</p>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 p-3 rounded-lg border border-border bg-background-tertiary text-xs flex gap-4 flex-wrap">
        <strong>{t("totals")}:</strong>
        <span>
          {t("evoforge")}: {totals.evoforge.cost} · {totals.evoforge.verified} · {totals.evoforge.elapsed}ms
        </span>
        <span>
          {t("single")}: {totals.single.cost} · {totals.single.verified} · {totals.single.elapsed}ms
        </span>
      </div>
      {disclosure && <p className="mt-2 text-xs text-text-secondary">{disclosure}</p>}
    </div>
  );
}

export default RoundReplay;
