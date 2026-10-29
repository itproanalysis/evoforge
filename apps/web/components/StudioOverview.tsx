'use client';

import { useLocale, useTranslations } from 'next-intl';
import { StudioIcon } from './StudioIcon';

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
    { label: t('verified'), value: verified, note: t('verified-note'), icon: 'evidence' },
    { label: t('matches'), value: measured, note: t('matches-note'), icon: 'arena' },
    { label: t('heldout'), value: heldout && heldout.n > 0 ? `${heldout.passed} / ${heldout.n}` : null, note: t('heldout-note'), icon: 'performance' },
    { label: t('participants'), value: participants === null ? null : `${participants}${participantsMore ? '+' : ''}`, note: t('participants-note'), icon: 'home' },
  ];
  return <>
    <section className="studio-hero" aria-labelledby="studio-title">
      <div className="studio-hero-copy">
        <span className="studio-eyebrow"><span className="studio-eyebrow-line"/> {t('eyebrow')}</span>
        <h1 id="studio-title">{t('title')}<br/><span>{t('title-accent')}</span></h1>
        <p>{t('description')}</p>
        <div className="studio-hero-actions">
          <a href={`${prefix}/replay`} className="studio-action-primary">{t('replay')}<StudioIcon name="arrow" width="17" height="17"/></a>
          <a href={`${prefix}/arena`} className="studio-action-link">{t('arena')}<StudioIcon name="arrow" width="17" height="17"/></a>
        </div>
      </div>
      <div className="studio-flow" aria-label={t('process')}>
        <div className="studio-flow-top"><span>{t('process')}</span><StudioIcon name="spark"/></div>
        <div className="studio-flow-path">
          {['plan', 'build', 'verify', 'evolve'].map((step, index) => <div className="studio-flow-step" key={step}><span className="studio-flow-number">0{index + 1}</span><span>{t(step)}</span><StudioIcon name={index === 3 ? 'spark' : 'arrow'} width="15" height="15"/></div>)}
        </div>
        <div className="studio-run-state"><span className={`studio-status-dot${running ? ' is-running' : ''}`}/><span>{t(running ? 'running' : runId ? 'recorded' : 'waiting')}</span>{runId && <code title={runId}>{runId}</code>}</div>
      </div>
    </section>
    <section className="studio-metrics" aria-label={t('metrics')}>
      {metrics.map(metric => <div className="studio-metric" key={metric.label}><div className="studio-metric-label">{metric.label}<StudioIcon name={metric.icon} width="16" height="16"/></div><div className="studio-metric-value">{metric.value ?? '—'}</div><p>{metric.note}</p></div>)}
    </section>
  </>;
}
