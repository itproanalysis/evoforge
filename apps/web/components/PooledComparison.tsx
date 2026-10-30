'use client';

import { useTranslations } from 'next-intl';
import type { PooledComparison as Row } from '../lib/api';

// Repeated measurements pooled per suite + harness (Critic-feedback pipeline only); see the API's pooled_basis.
// The newest suite that still separates the two sides leads; saturated or older suites follow as one line each.
export function PooledComparison({ rows, basis }: { rows?: Row[] | null; basis?: string | null }) {
  const t = useTranslations('performance');
  if (!rows || rows.length === 0) return null;
  const lead = [...rows].reverse().find(r => r.verdict !== 'saturated') ?? rows[rows.length - 1];
  const others = rows.filter(r => r !== lead);
  const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`);
  const iv = (w: [number, number]) => `${Math.round(w[0] * 100)}–${Math.round(w[1] * 100)}%`;
  const lanes = [
    { key: 'evoforge', label: 'EvoForge', side: lead.evoforge },
    { key: 'single', label: t('pooled-single'), side: lead.single },
  ];
  return (
    <section aria-label={t('pooled-title')} className="perf-hero">
      <div className="perf-hero-head">
        <div>
          <h2>{t('pooled-title')}</h2>
          <p>{lead.suite_version} · {lead.harness_version} · {t('pooled-runs', { n: lead.evoforge.runs })}</p>
        </div>
        <span className={`perf-verdict is-${lead.verdict}`}>{t(`pooled-${lead.verdict}`)}</span>
      </div>
      <div className="perf-lanes">
        {lanes.map(lane => (
          <div key={lane.key} className={`perf-lane is-${lane.key}`}>
            <span className="perf-lane-label">{lane.label}</span>
            <strong className="perf-lane-rate">{pct(lane.side.rate)}</strong>
            <span className="perf-range" aria-hidden="true">
              <span className="perf-range-band" style={{ left: `${lane.side.wilson95[0] * 100}%`, width: `${(lane.side.wilson95[1] - lane.side.wilson95[0]) * 100}%` }} />
              {lane.side.rate !== null && <span className="perf-range-dot" style={{ left: `${lane.side.rate * 100}%` }} />}
            </span>
            <span className="perf-lane-meta">{lane.side.passed}/{lane.side.n} · {t('pooled-interval')} {iv(lane.side.wilson95)}</span>
          </div>
        ))}
      </div>
      {others.length > 0 && (
        <ul className="perf-other">
          {others.map(r => (
            <li key={`${r.suite_version}-${r.harness_version}`}>
              <span>{r.suite_version} · {r.harness_version}</span>
              <span>EvoForge {r.evoforge.passed}/{r.evoforge.n} · {t('pooled-single')} {r.single.passed}/{r.single.n}</span>
              <span className={`perf-verdict is-${r.verdict}`}>{t(`pooled-${r.verdict}`)}</span>
            </li>
          ))}
        </ul>
      )}
      {basis && (
        <details className="perf-basis">
          <summary>{t('pooled-how')}</summary>
          <p>{basis}</p>
        </details>
      )}
    </section>
  );
}
