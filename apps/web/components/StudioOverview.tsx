'use client';

import { useLocale, useTranslations } from 'next-intl';

type Props = {
  running: boolean;
  runId?: string;
  measured: number | null;
  verified: number | null;
  participants: number | null;
  participantsMore?: boolean;
  heldout: { passed: number; n: number } | null;
  // Same-tools comparison: the single AI's hidden-test result, wins/ties and the sign-test p (never one side alone).
  singleHeldout?: { passed: number; n: number } | null;
  wins?: { evoforge: number; single: number; tie: number } | null;
  signP?: number | null;
  value?: { extra_solved: number; extra_cost_cents: number; cents_per_extra_solved: number | null } | null;
};

// All values are supplied by the existing API state. Missing evidence remains —.
export function StudioOverview({ running, runId, measured, verified, participants, participantsMore = false, heldout, singleHeldout = null, wins = null, signP = null, value = null }: Props) {
  const t = useTranslations('studio');
  const ta = useTranslations('arena');
  const frac = (h: { passed: number; n: number } | null) => h && h.n > 0 ? `${h.passed} / ${h.n}` : null;
  const both = frac(heldout) && frac(singleHeldout) ? `${frac(heldout)} vs ${frac(singleHeldout)}` : frac(heldout);
  const locale = useLocale();
  const prefix = locale === 'en' ? '' : `/${locale}`;
  const metrics = [
    { label: t('verified'), value: verified, note: t('verified-note') },
    { label: t('matches'), value: measured, note: t('matches-note') },
    { label: t('heldout'), value: both, note: t('heldout-note') },
    { label: t('participants'), value: participants === null ? null : `${participants}${participantsMore ? '+' : ''}`, note: t('participants-note') },
  ];
  return <>
    <section className="studio-masthead" aria-labelledby="studio-title">
      <div>
        <h1 id="studio-title">{t('title')}</h1>
        <p>{t('description')}</p>
      </div>
      <div className="studio-masthead-aside">
        <div className="studio-run-state"><span className={`studio-status-dot${running ? ' is-running' : ''}`}/><span>{t(running ? 'running' : runId ? 'recorded' : 'waiting')}</span>{runId && <code title={runId}>{runId}</code>}</div>
        <a href={`${prefix}/replay`} className="studio-text-link">{t('replay')} <span aria-hidden="true">↗</span></a>
      </div>
    </section>
    <section className="studio-metrics" aria-label={t('metrics')}>
      {metrics.map(metric => <div className="studio-metric" key={metric.label}><div className="studio-metric-label">{metric.label}</div><div className="studio-metric-value">{metric.value ?? '—'}</div><p>{metric.note}</p></div>)}
    </section>
    {wins && <p className="studio-result-line">
      {t('result-line', { evoforge: wins.evoforge, single: wins.single, tie: wins.tie })}
      {signP !== null
        ? <>{' — '}{ta(signP < 0.05 ? 'summary-significant' : 'summary-not-significant', { p: signP.toFixed(2) })}</>
        : wins.evoforge + wins.single === 0 ? <>{' — '}{t('no-decisive')}</> : null}
    </p>}
    {value && value.extra_solved > 0 && value.cents_per_extra_solved !== null && <p className="studio-result-line">
      {t('value-line', { solved: value.extra_solved, cents: value.cents_per_extra_solved })}
    </p>}
  </>;
}
