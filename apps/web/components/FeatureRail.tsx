'use client';

import { useEffect, useRef, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { usePathname } from 'next/navigation';
import { StudioIcon, StudioMark } from './StudioIcon';
import { LanguageSwitcher } from './LanguageSwitcher';

export const ITEMS = [
  { path: "/", key: "mission-control", icon: "home" },
  { path: "/arena", key: "arena", icon: "arena" },
  { path: "/replay", key: "replay", icon: "replay" },
  { path: "/evidence", key: "evidence", icon: "evidence" },
  { path: "/performance", key: "performance", icon: "performance" },
  { path: "/lab", key: "improvement-lab", icon: "lab" },
];
export const MORE_ITEMS = [
  { path: "/evolution", key: "autopilot", icon: "evolution" },
  { path: "/leaderboard", key: "leaderboard", icon: "leaderboard" },
];

export function FeatureRail() {
  const locale = useLocale();
  const t = useTranslations('navigation');
  const ts = useTranslations('studio');
  const prefix = locale === 'en' ? '' : `/${locale}`;
  const rawPath = (usePathname() ?? '/').replace(/^\/(en|ko)(?=\/|$)/, '') || '/';
  const routePath = rawPath === '/workspace' ? '/' : rawPath;
  const [moreOpen, setMoreOpen] = useState(() => MORE_ITEMS.some(item => item.path === routePath));
  const more = useRef<HTMLDetailsElement>(null);
  const mobileMore = useRef<HTMLDetailsElement>(null);
  // On phones the More menu would cover the page, so it never opens by itself (desktop reveals the current section).
  const [mobileOpen, setMobileOpen] = useState(false);
  useEffect(() => {
    if (!moreOpen && !mobileOpen) return;
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') { setMoreOpen(false); setMobileOpen(false); (window.innerWidth < 768 ? mobileMore.current : more.current)?.querySelector('summary')?.focus(); } };
    document.addEventListener('keydown', close);
    return () => document.removeEventListener('keydown', close);
  }, [moreOpen, mobileOpen]);
  const link = ({path, key, icon}: {path: string; key: string; icon: string}) => <a key={path} href={`${prefix}${path}`} title={t(key)} aria-label={t(key)} data-tooltip={t(key)} aria-current={routePath === path ? 'page' : undefined} className={`canvas-rail-link${routePath === path ? ' is-active' : ''}`}><StudioIcon name={icon}/><span className="canvas-rail-label">{t(key)}</span></a>;
  const content = <>
    <a href={prefix || '/'} className="canvas-rail-brand" title="EvoForge" aria-label="EvoForge"><StudioMark/></a>
    <div className="canvas-rail-items">{ITEMS.map(link)}</div>
    <details ref={more} open={moreOpen} onToggle={event => setMoreOpen(event.currentTarget.open)} className="canvas-rail-more">
      <summary aria-label={t('more')} title={t('more')}><StudioIcon name="more"/><span className="sr-only">{t('more')}</span></summary>
      <div className="canvas-more-menu">{MORE_ITEMS.map(item => <a href={`${prefix}${item.path}`} key={item.path} aria-current={routePath === item.path ? 'page' : undefined}>{t(item.key)}</a>)}</div>
    </details>
  </>;
  return <>
    <nav aria-label={ts('navigation')} className="canvas-rail hidden md:flex">{content}</nav>
    <nav aria-label={ts('navigation')} className="canvas-mobile-nav flex md:hidden fixed">{ITEMS.map(link)}<details ref={mobileMore} open={mobileOpen} onToggle={event => setMobileOpen(event.currentTarget.open)} className="canvas-rail-more"><summary aria-label={t('more')} title={t('more')}><StudioIcon name="more"/></summary><div className="canvas-more-menu">{MORE_ITEMS.map(item => <a href={`${prefix}${item.path}`} key={item.path}>{t(item.key)}</a>)}<LanguageSwitcher/></div></details></nav>
  </>;
}
