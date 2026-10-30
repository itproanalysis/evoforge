'use client';

import { useTranslations } from 'next-intl';
import type { ArenaDoc } from '../lib/api';
import { shareComparison } from '../lib/share';

export function ShareComparisonBadge({ doc }: { doc: ArenaDoc }) {
  const t = useTranslations('share');
  const comparison = shareComparison(doc);
  return <li>{comparison.kind === 'multi_model' ? t('multi-model')
    : comparison.kind === 'same_builder' ? t('same-model', {model: comparison.model ?? '—'})
    : t('model-unconfirmed')}</li>;
}
