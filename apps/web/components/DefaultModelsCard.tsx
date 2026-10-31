'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import { getModelDefaults } from '../lib/api';
import { modelDefaultsView, modelName, type ModelDefaultsView } from '../lib/modelDefaults';

export function DefaultModelsStatus({ view, loading, onRetry }: {
  view: ModelDefaultsView;
  loading: boolean;
  onRetry: () => void;
}) {
  const t = useTranslations('models');
  return <section className="canvas-model-defaults" aria-labelledby="default-models-title" aria-busy={loading}>
    <header>
      <h3 id="default-models-title">{t(view.profile === 'collaborative' ? 'title' : 'setup')}</h3>
      <span className={view.status === 'ready' ? 'is-ready' : ''} role="status">{t(loading ? 'loading' : view.status)}</span>
    </header>
    {view.status === 'ready' && !loading && <p>{t('keyless')}</p>}
    {view.participants.length > 0 && <ul>{view.participants.map(item => <li key={`${item.role}:${item.model}`}>
      <span><strong>{modelName(item.model)}</strong><small>{t(item.role)}</small></span>
      <small>{t(item.configured ? 'connected' : 'missing')}</small>
    </li>)}</ul>}
    {!loading && view.status !== 'ready' && <p className="canvas-model-note">{t(view.status === 'unknown' ? 'unavailable' : 'incomplete')}<button type="button" onClick={onRetry}>{t('retry')}</button></p>}
  </section>;
}

export function DefaultModelsCard() {
  const [view, setView] = useState<ModelDefaultsView>({status: 'unknown', profile: null, participants: []});
  const [loading, setLoading] = useState(true);
  const generation = useRef(0);
  const refresh = useCallback(async () => {
    const current = ++generation.current;
    setLoading(true);
    try {
      const result = await getModelDefaults();
      if (current === generation.current) setView(modelDefaultsView(result));
    } catch {
      if (current === generation.current) setView({status: 'unknown', profile: null, participants: []});
    } finally {
      if (current === generation.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
    return () => { generation.current++; };
  }, [refresh]);
  return <DefaultModelsStatus view={view} loading={loading} onRetry={() => { void refresh(); }}/>;
}
