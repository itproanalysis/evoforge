'use client';

import { useLocale, useTranslations } from 'next-intl';
import type { Participant, MeasurementRecord } from '../lib/api';

export type StudioView = 'work' | 'people' | 'history';
const VIEWS: StudioView[] = ['work', 'people', 'history'];

export function StudioTabs({ active, onChange }: { active: StudioView; onChange: (view: StudioView) => void }) {
  const t = useTranslations('studio');
  return <div className="studio-tabs" role="tablist" aria-label={t('views')}>
    {VIEWS.map((view, index) => <button key={view} type="button" id={`studio-tab-${view}`} role="tab" aria-selected={active === view} aria-controls={`studio-panel-${view}`} tabIndex={active === view ? 0 : -1} onClick={() => onChange(view)} onKeyDown={event => {
      const targetIndex = event.key === 'ArrowRight' ? (index + 1) % VIEWS.length
        : event.key === 'ArrowLeft' ? (index + VIEWS.length - 1) % VIEWS.length
        : event.key === 'Home' ? 0 : event.key === 'End' ? VIEWS.length - 1 : null;
      if (targetIndex === null) return;
      event.preventDefault();
      onChange(VIEWS[targetIndex]);
      event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[targetIndex]?.focus();
    }}>{t(`view-${view}`)}</button>)}
  </div>;
}

export function StudioPeople({ people, available, loading, hasMore }: { people: Participant[]; available: boolean; loading: boolean; hasMore?: boolean }) {
  const t = useTranslations('studio');
  const tm = useTranslations('mission-control');
  const describe = (value: string) => tm.has(`participant-values.${value}`) ? tm(`participant-values.${value}`) : value;
  return <section className="studio-data-view" aria-label={t('view-people')}>
    <div className="studio-section-title"><h2>{t('view-people')}</h2><span>{t('participants-note')}</span></div>
    {loading || !available || people.length === 0 ? <p className="studio-data-empty">{t(loading ? 'loading' : !available ? 'people-unavailable' : 'people-empty')}</p> : <div className="studio-people-list">
      {people.map(person => <article className="studio-person" key={person.agent_id}>
        <div className="studio-person-monogram" aria-hidden="true">{person.agent_id.slice(0, 2).toUpperCase()}</div>
        <div className="studio-person-identity"><h3>{person.agent_id}</h3><p>{person.roles.map(describe).join(' · ') || '—'}</p></div>
        <div className="studio-person-states"><span>{t('connection')}: {describe(person.connection_state)}</span><span>{t('execution')}: {describe(person.execution_state)}</span></div>
      </article>)}
      {hasMore && <p className="studio-data-note">{tm('participants-more')}</p>}
    </div>}
  </section>;
}

export function StudioHistory({ records, available, loading }: { records: MeasurementRecord[]; available: boolean; loading: boolean }) {
  const t = useTranslations('studio');
  const locale = useLocale();
  const prefix = locale === 'en' ? '' : `/${locale}`;
  const ordered = [...records].sort((a, b) => b.created_at - a.created_at);
  const date = (seconds: number) => Number.isFinite(seconds) ? new Intl.DateTimeFormat(locale, {dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC'}).format(new Date(seconds * 1000)) : '—';
  return <section className="studio-data-view" aria-label={t('view-history')}>
    <div className="studio-section-title"><h2>{t('view-history')}</h2><a className="studio-text-link" href={`${prefix}/performance`}>{t('measurement-detail')} ↗</a></div>
    {loading || !available || ordered.length === 0 ? <p className="studio-data-empty">{t(loading ? 'loading' : !available ? 'history-unavailable' : 'history-empty')}</p> : <div className="studio-table-wrap"><table className="studio-history-table">
      <thead><tr><th>{t('history-run')}</th><th>{t('history-result')}</th><th>{t('history-source')}</th><th>{t('history-time')}</th><th><span className="sr-only">{t('history-evidence')}</span></th></tr></thead>
      <tbody>{ordered.map(record => <tr key={record.measurement_id}>
        <td><strong>{t(record.kind === 'X_SINGLE' ? 'history-single' : record.kind === 'PIPELINE' ? 'history-evoforge' : 'history-measurement')}</strong><span>{record.model} · {record.suite_version}</span></td>
        <td className="studio-numeric">{record.n > 0 ? `${record.passed} / ${record.n}` : '—'}</td>
        <td>{t(record.provider_stub === true ? 'source-test' : record.provider_stub === false ? 'source-model' : 'source-unknown')}</td>
        <td><time dateTime={Number.isFinite(record.created_at) ? new Date(record.created_at * 1000).toISOString() : undefined}>{date(record.created_at)}</time></td>
        <td>{record.evidence_id && <a className="studio-text-link" href={`${prefix}/evidence?id=${encodeURIComponent(record.evidence_id)}`}>{t('history-evidence')} ↗</a>}</td>
      </tr>)}</tbody>
    </table></div>}
  </section>;
}
