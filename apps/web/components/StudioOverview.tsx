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
};

// All values are supplied by the existing API state. Missing evidence remains —.
export function StudioOverview({ running, runId, measured, verified, participants, participantsMore = false, heldout }: Props) {
  const t = useTranslations('studio');
  const locale = useLocale();
  const prefix = locale === 'en' ? '' : `/${locale}`;
  const metrics = [
    { label: t('verified'), value: verified, note: t('verified-note') },
    { label: t('matches'), value: measured, note: t('matches-note') },
    { label: t('heldout'), value: heldout && heldout.n > 0 ? `${heldout.passed} / ${heldout.n}` : null, note: t('heldout-note') },
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
  </>;
}
