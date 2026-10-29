'use client';

import { usePathname } from 'next/navigation';
import { useTranslations } from 'next-intl';

export function StudioBreadcrumb() {
  const pathname = (usePathname() ?? '/').replace(/^\/(en|ko)(?=\/|$)/, '') || '/';
  const t = useTranslations('navigation');
  const ts = useTranslations('studio');
  const route = pathname.split('/')[1];
  const labels: Record<string, string> = {
    arena: 'arena', replay: 'replay', evidence: 'evidence', performance: 'performance',
    lab: 'improvement-lab', evolution: 'autopilot', leaderboard: 'leaderboard',
    workspace: 'mission-control', verify: 'evidence',
  };
  return <div className="studio-breadcrumb"><span>{ts('workspace')}</span><span aria-hidden="true">/</span><strong>{labels[route] ? t(labels[route]) : ts('overview')}</strong></div>;
}
