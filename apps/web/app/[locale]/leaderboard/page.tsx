"use client";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { type LeaderEntry, type MemoryPattern, getLeaderboard, getMemory } from "../../../lib/api";
import { Card } from "../../../components/ui";
import { getErrorMessageKey } from "../../../lib/apiErrors";

export default function Leaderboard() {
  const t = useTranslations("leaderboard");
  const tErrors = useTranslations("errors");
  const [leaders, setLeaders] = useState<LeaderEntry[]>([]);
  const [patterns, setPatterns] = useState<MemoryPattern[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    getLeaderboard().then((r) => setLeaders(r.leaders ?? [])).catch((e) => setErr(tErrors(getErrorMessageKey(e))));
    getMemory().then((r) => setPatterns(r.patterns ?? [])).catch((e) => setErr(tErrors(getErrorMessageKey(e))));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <h1>{t("heading")}</h1>
      <p style={{ color: "#6b7684" }}>{t("description")}</p>
      {err && <p style={{ color: "#f04452" }}>{err}</p>}
      <Card>
        <h3>{t("wins-heading", { count: leaders.length })}</h3>
        {leaders.length === 0 && <p style={{ color: "#6b7684" }}>{t("empty")}</p>}
        {leaders.map((l, i) => (
          <div key={l.evolution_id} style={{ borderTop: "1px solid #e5e8eb", padding: "8px 0", fontSize: 13 }}>
            <strong>#{i + 1}</strong> {l.goal.slice(0, 90)} · {t("score")}: {l.best_score.toFixed(1)} · {l.generations_used} gen
            {l.proof_evidence_id && <span> · <a href={`/verify/${l.proof_evidence_id}`}>{t("proof-link")}</a></span>}
          </div>
        ))}
      </Card>
      <div style={{ marginTop: 16 }}>
        <Card>
          <h3>{t("memory-heading", { count: patterns.length })}</h3>
          {patterns.map((p) => (
            <div key={p.pattern_id} style={{ fontSize: 12, color: "#6b7684", marginTop: 4 }}>
              {p.pattern_id.slice(0, 12)} · {(p.keywords ?? []).slice(0, 8).join(", ")} · {t("score")}: {p.fitness_score.toFixed(1)}
              {p.proof_evidence_id && <span> · <a href={`/verify/${p.proof_evidence_id}`}>{t("proof-link")}</a></span>}
            </div>
          ))}
        </Card>
      </div>
    </div>
  );
}
