'use client';

import { useLocale, useTranslations } from 'next-intl';
import type { ArenaSummary } from '../lib/api';
import { StudioIcon } from './StudioIcon';

// First-visit introduction over the canvas: what EvoForge is, how a run works and what the measured
// record says, with the numbers read from the arena summary (never typed in).
export function WelcomeHero({ summary, onClose }: { summary: ArenaSummary | null; onClose: () => void }) {
  const t = useTranslations('welcome');
  const tw = useTranslations('workspace');
  const locale = useLocale();
  const prefix = locale === 'en' ? '' : `/${locale}`;
  const eq = summary?.equal_tools;
  const share = (h?: { passed: number; n: number }) => (h && h.n > 0 ? Math.round((100 * h.passed) / h.n) : null);
  const evoShare = share(eq?.heldout?.evoforge);
  const singleShare = share(eq?.heldout?.single);
  const tryIt = () => {
    onClose();
    // The composer lives at the bottom of the canvas; put the cursor there.
    setTimeout(() => document.querySelector<HTMLTextAreaElement>('.studio-composer textarea')?.focus(), 50);
  };
  const steps = [
    { title: t('step-1'), body: tw('intro-step-1') },
    { title: t('step-2'), body: tw('intro-step-2') },
    { title: t('step-3'), body: tw('intro-step-3') },
  ];
  return (
    <div className="welcome-layer" role="dialog" aria-modal="false" aria-labelledby="welcome-title">
      <section className="welcome-card">
        <button type="button" className="welcome-close" onClick={onClose} aria-label={t('close')} title={t('close')}>
          <StudioIcon name="close" width="18" height="18" />
        </button>
        <span className="welcome-eyebrow"><StudioIcon name="spark" width="14" height="14" />{t('eyebrow')}</span>
        <h1 id="welcome-title">{t('title')}</h1>
        <p className="welcome-sub">{tw('intro')}</p>
        <ol className="welcome-steps">
          {steps.map((step, i) => (
            <li key={step.title}>
              <span className="welcome-step-n">{i + 1}</span>
              <strong>{step.title}</strong>
              <p>{step.body}</p>
            </li>
          ))}
        </ol>
        {eq && (eq.scored ?? 0) > 0 && (
          <dl className="welcome-stats">
            <div>
              <dt>{t('stat-record', { n: eq.scored })}</dt>
              <dd>{eq.wins?.evoforge ?? 0}<span> {t('stat-wins')}</span> · {eq.wins?.single ?? 0}<span> {t('stat-losses')}</span></dd>
            </div>
            {evoShare !== null && singleShare !== null && (
              <div>
                <dt>{t('stat-hidden')}</dt>
                <dd>{evoShare}%<span> vs {singleShare}%</span></dd>
              </div>
            )}
            <div>
              <dt>{t('stat-signed')}</dt>
              <dd>Ed25519</dd>
            </div>
          </dl>
        )}
        <div className="welcome-actions">
          <button type="button" className="welcome-primary" onClick={tryIt}>{t('cta-try')}</button>
          <button type="button" className="welcome-secondary" onClick={onClose}>{t('cta-watch')}</button>
          <a className="welcome-link" href={`${prefix}/arena`}>{t('cta-scoreboard')} <StudioIcon name="arrow" width="14" height="14" /></a>
        </div>
      </section>
    </div>
  );
}
