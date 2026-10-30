'use client';

import { useTranslations } from 'next-intl';
import type { PooledComparison as Row } from '../lib/api';

// Repeated measurements pooled per suite + harness (Critic-feedback pipeline only); see the API's pooled_basis.
export function PooledComparison({ rows, basis }: { rows?: Row[] | null; basis?: string | null }) {
  const t = useTranslations('performance');
  if (!rows || rows.length === 0) return null;
  const pct = (v: number | null) => (v === null ? '—' : `${(v * 100).toFixed(1)}%`);
  const iv = (w: [number, number]) => `${(w[0] * 100).toFixed(0)}–${(w[1] * 100).toFixed(0)}%`;
  return (
    <section aria-label={t('pooled-title')} className="mt-3 p-3 rounded-lg border border-border bg-background-secondary">
      <h2 className="text-sm font-semibold m-0">{t('pooled-title')}</h2>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-xs">
          <thead><tr className="text-text-secondary text-left">
            <th className="font-normal p-1">{t('pooled-suite')}</th><th className="font-normal p-1">{t('pooled-single')}</th>
            <th className="font-normal p-1">EvoForge</th><th className="font-normal p-1">{t('pooled-verdict')}</th>
          </tr></thead>
          <tbody>{rows.map(r => (
            <tr key={`${r.suite_version}-${r.harness_version}`} className="border-t border-border">
              <td className="p-1">{r.suite_version} · {r.harness_version}</td>
              <td className="p-1">{r.single.passed}/{r.single.n} ({pct(r.single.rate)}, {iv(r.single.wilson95)}) · {t('pooled-runs', { n: r.single.runs })}</td>
              <td className="p-1">{r.evoforge.passed}/{r.evoforge.n} ({pct(r.evoforge.rate)}, {iv(r.evoforge.wilson95)}) · {t('pooled-runs', { n: r.evoforge.runs })}</td>
              <td className="p-1">{t(`pooled-${r.verdict}`)}</td>
            </tr>))}
          </tbody>
        </table>
      </div>
      {basis && <p className="mt-2 text-xs text-text-secondary">{basis}</p>}
    </section>
  );
}
