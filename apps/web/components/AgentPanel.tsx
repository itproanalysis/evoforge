"use client";

import { useTranslations } from "next-intl";
import { agentPanel } from "../lib/roundReplay";
import type { ReplaySideKey } from "../lib/roundReplay";
import type { EvolutionRun } from "../lib/api";

type Props = { run: EvolutionRun };

const DOT_COLORS: Record<string, string> = {
  active: "#34d399",
  done: "#94a3b8",
  idle: "#64748b",
};

const SIDES: ReplaySideKey[] = ["evoforge", "single"];

// Canonical agent lanes in display order: builder, critic, runner, gate.
// The single-AI lane has no Critic, so its critic row stays idle.
const ROLE_ORDER = ["builder", "critic", "runner", "gate"] as const;

export function AgentPanel({ run }: Props) {
  const t = useTranslations("replay");
  return (
    <div className="mt-3">
      <h3 className="text-sm font-semibold">{t("agents")}</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-2">
        {SIDES.map((side) => {
          const rows = [...agentPanel(run, side)].sort(
            (a, b) => ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role),
          );
          const label = side === "evoforge" ? t("evoforge") : t("single");
          return (
            <div
              key={side}
              className="p-3 rounded-lg border border-border bg-background-secondary"
              data-side={side}
            >
              <strong className="text-sm">{label}</strong>
              <ul className="mt-2 space-y-1.5">
                {rows.map((row) => (
                  <li key={row.role} className="flex items-start gap-2 text-xs">
                    <span
                      className={`state-dot state-dot-${row.state}`}
                      title={row.state}
                      style={{
                        background: DOT_COLORS[row.state] ?? DOT_COLORS.idle,
                        width: 8,
                        height: 8,
                        borderRadius: 9999,
                        display: "inline-block",
                        marginTop: 3,
                        flexShrink: 0,
                      }}
                    />
                    <span className="font-mono font-semibold w-14 flex-shrink-0">
                      {row.role}
                    </span>
                    <span className="text-text-secondary">{t(row.state)}</span>
                    <span className="text-text-primary break-words">
                      {row.message ?? "—"}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default AgentPanel;
