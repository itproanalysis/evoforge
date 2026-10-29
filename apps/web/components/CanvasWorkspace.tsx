'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslations } from 'next-intl';
import type { ArenaDoc, MeasurementRecord, Participant } from '../lib/api';
import { laneView, manifestView, type ArenaAgentRow, type PreviewSource } from '../lib/arenaStatus';
import { StudioIcon } from './StudioIcon';
import { StudioHistory, StudioPeople } from './StudioViews';

type Panel = 'activity' | 'history' | 'metrics' | 'admin' | null;
type View = 'preview' | 'diff' | 'tests';
type Preview = { html: string | null; source: PreviewSource; error: string | null };
type Props = {
  label: string;
  doc: ArenaDoc | null;
  runs: ArenaDoc[];
  busy: boolean;
  loading: boolean;
  pollError: boolean;
  onSelect: (id: string) => void;
  onRetry: () => void;
  previews: Record<'evoforge' | 'single', Preview>;
  agents: Record<'evoforge' | 'single', ArenaAgentRow[]>;
  participants: {status: string; participants: Participant[]; has_more?: boolean} | null;
  history: MeasurementRecord[] | null;
  overview: ReactNode;
  management: ReactNode;
  composer: ReactNode;
  renderPreview: (html: string, title: string) => ReactNode;
};

export function CanvasWorkspace(props: Props) {
  const t = useTranslations('canvas');
  const ts = useTranslations('studio');
  const [view, setView] = useState<View>('preview');
  const [compare, setCompare] = useState(true);
  const [panel, setPanel] = useState<Panel>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (panel && element && !element.open) element.showModal();
    if (!panel && element?.open) element.close();
  }, [panel]);
  const runs = props.doc && !props.runs.some(run => run.arena_id === props.doc?.arena_id)
    ? [props.doc, ...props.runs] : props.runs;
  const sides: ('evoforge' | 'single')[] = compare ? ['evoforge', 'single'] : ['evoforge'];
  const manifest = manifestView(props.doc);
  const views: View[] = ['preview', 'diff', 'tests'];
  const iconButton = (icon: string, label: string, action: () => void) => <button type="button" className="canvas-icon-button" aria-label={label} title={label} onClick={action}><StudioIcon name={icon} width="17" height="17"/></button>;
  return <main className="canvas-workspace studio-home" aria-label={props.label}>
    <header className="canvas-toolbar">
      <div className="canvas-file">
        <span className="canvas-product">EvoForge</span><span className="canvas-slash" aria-hidden="true">/</span>
        <select aria-label={t('runs')} value={props.doc?.arena_id ?? ''} disabled={props.busy || runs.length === 0} onChange={event => props.onSelect(event.target.value)}>
          {!props.doc && <option value="">{t(props.busy ? 'running' : 'untitled')}</option>}
          {runs.map(run => <option key={run.arena_id} value={run.arena_id}>{(run.prompt || run.goal || run.task_id || run.arena_id).slice(0, 38)}</option>)}
        </select>
        <span className={`canvas-record${props.busy ? ' is-running' : ''}`}>{t(props.busy ? 'running' : props.doc ? 'recorded' : 'waiting')}</span>
        {props.pollError && iconButton('evolution', t('retry'), props.onRetry)}
      </div>
      <div className="canvas-toolbar-actions">
        {iconButton('users', t('activity'), () => setPanel('activity'))}
        {iconButton('history', t('history'), () => setPanel('history'))}
        {iconButton('performance', t('metrics'), () => setPanel('metrics'))}
        {iconButton('settings', t('settings'), () => setPanel('admin'))}
      </div>
    </header>
    <div className="canvas-viewbar">
      <div className="canvas-view-tabs" role="tablist" aria-label={t('views')}>
        {views.map((item, index) => <button type="button" id={`canvas-tab-${item}`} key={item} role="tab" aria-selected={view === item} aria-controls="canvas-results" tabIndex={view === item ? 0 : -1} onClick={() => setView(item)} onKeyDown={event => {
          const next = event.key === 'ArrowRight' ? (index + 1) % views.length : event.key === 'ArrowLeft' ? (index + views.length - 1) % views.length : event.key === 'Home' ? 0 : event.key === 'End' ? views.length - 1 : null;
          if (next === null) return;
          event.preventDefault(); setView(views[next]);
          event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
        }}>{t(item)}</button>)}
      </div>
      <button type="button" className={`canvas-icon-button${compare ? ' is-selected' : ''}`} aria-label={t('compare')} title={t('compare')} aria-pressed={compare} onClick={() => setCompare(value => !value)}><StudioIcon name="arena" width="16" height="16"/></button>
    </div>
    <section id="canvas-results" role="tabpanel" aria-labelledby={`canvas-tab-${view}`} tabIndex={0} className={`canvas-stage${compare ? ' is-compare' : ''}`}>
      {sides.map(side => {
        const lane = props.doc?.lanes?.[side];
        const result = laneView(lane);
        const preview = props.previews[side];
        const name = side === 'evoforge' ? 'EvoForge' : t('single');
        return <article className="canvas-output" key={side} aria-label={name}>
          <header className="canvas-output-header">
            <strong>{name}</strong>
            <div className="canvas-output-numbers">
              <span title={t('score')}>{result.score ?? '—'}</span><span aria-hidden="true">·</span>
              <span title={ts(`cost-${result.costState}`)}>{result.cost === null ? '—' : `${result.cost}¢`}</span>
              {preview.source === 'base' && <span className="canvas-base" title={t('base-detail')}>{t('base')}</span>}
            </div>
          </header>
          <div className="canvas-output-body">
            {view === 'preview' && (preview.html ? props.renderPreview(preview.html, `${props.doc?.arena_id ?? 'empty'}-${side}`) : <div className="canvas-empty">{t(result.status === 'failed' ? 'failed' : props.busy ? 'running' : 'empty')}</div>)}
            {view === 'diff' && (lane?.diff ? <pre className="canvas-source">{lane.diff}</pre> : <div className="canvas-empty">{t('empty')}</div>)}
            {view === 'tests' && <div className="canvas-test-result"><span>{t('score')}</span><strong>{result.score ?? '—'}</strong><small>{t(result.result === 'passed' ? 'passed' : result.result === 'not_passed' ? 'not-passed' : 'unconfirmed')}</small></div>}
          </div>
        </article>;
      })}
    </section>
    {props.composer}
    <dialog ref={dialog} className="canvas-inspector" aria-labelledby="canvas-inspector-title" onCancel={event => {event.preventDefault(); setPanel(null);}} onClick={event => {
      if (event.target !== event.currentTarget) return;
      const box = event.currentTarget.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) setPanel(null);
    }}>
      <header><h2 id="canvas-inspector-title">{panel ? t(panel === 'admin' ? 'settings' : panel) : ''}</h2>{iconButton('close', t('close'), () => setPanel(null))}</header>
      <div className="canvas-inspector-content">
        {panel === 'activity' && <>
          {(['evoforge', 'single'] as const).map(side => <section className="canvas-agent-list" key={side}><h3>{side === 'evoforge' ? 'EvoForge' : t('single')}</h3>{props.agents[side].map(row => <div key={row.role}><span>{ts(`role-${row.role}`)}</span><small>{ts(`agent-${row.state}`)}</small>{row.message && <details><summary>{ts('event-detail')}</summary><p>{row.message}</p></details>}</div>)}</section>)}
          <StudioPeople people={props.participants?.participants ?? []} available={props.participants?.status === 'available'} loading={props.loading} hasMore={props.participants?.has_more}/>
        </>}
        {panel === 'history' && <StudioHistory records={props.history ?? []} available={props.history !== null} loading={props.loading}/>}
        {panel === 'metrics' && <>{props.overview}<section className="canvas-conditions"><h3>{t('conditions')}</h3><p>{props.doc?.prompt || props.doc?.goal || '—'}</p><code>{props.doc?.arena_id ?? '—'}</code>{manifest && <><dl><dt>{t('spec')}</dt><dd>{manifest.spec ?? '—'}</dd><dt>{t('base')}</dt><dd>{manifest.baseTree ?? '—'}</dd></dl><p>{manifest.disclosure ?? '—'}</p></>}{(['evoforge', 'single'] as const).map(side => <p key={side}>{side === 'evoforge' ? 'EvoForge' : t('single')} · {ts(`cost-${laneView(props.doc?.lanes?.[side]).costState}`)}</p>)}</section></>}
        {panel === 'admin' && props.management}
      </div>
    </dialog>
  </main>;
}
