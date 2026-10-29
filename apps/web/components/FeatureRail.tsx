'use client';

import { useEffect, useRef, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { usePathname } from 'next/navigation';
import { StudioIcon, StudioMark } from './StudioIcon';

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

function stripLocalePrefix(pathname: string): string {
  const stripped = pathname.replace(/^\/(en|ko)(?=\/|$)/, '');
  return stripped === '' ? '/' : stripped;
}

function linkClass(isActive: boolean): string {
  return `studio-nav-link${isActive ? ' is-active' : ''}`;
}

export function FeatureRail() {
  const locale = useLocale();
  const t = useTranslations('navigation');
  const ts = useTranslations('studio');
  const pathname = usePathname() ?? '';
  const [open, setOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(() => MORE_ITEMS.some(({ path }) => stripLocalePrefix(pathname) === path));
  const menuButton = useRef<HTMLButtonElement>(null);
  const drawer = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const priorOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const first = drawer.current?.querySelector<HTMLButtonElement>('button:not([tabindex="-1"])');
    first?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
      if (event.key !== 'Tab') return;
      const nodes = drawer.current?.querySelectorAll<HTMLElement>('button:not([tabindex="-1"]), a[href]');
      if (!nodes?.length) return;
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', onKey);
    return () => { document.body.style.overflow = priorOverflow; document.removeEventListener('keydown', onKey); menuButton.current?.focus(); };
  }, [open]);
  const prefix = locale === 'en' ? '' : `/${locale}`;
  const routePath = stripLocalePrefix(pathname);

  const renderLink = ({ path, key, icon }: { path: string; key: string; icon: string }) => {
    const href = `${prefix}${path}`;
    const isActive = path === '/' ? routePath === '/' : routePath === path || routePath.startsWith(`${path}/`);
    return (
      <a
        key={path}
        href={href}
        aria-current={isActive ? "page" : undefined}
        className={linkClass(isActive)}
        onClick={() => setOpen(false)}
      >
        <StudioIcon name={icon}/>
        <span>{t(key)}</span>
      </a>
    );
  };

  const moreSection = (idPrefix: string) => (
    <div>
      <button
        type="button"
        aria-expanded={moreOpen}
        aria-controls={`${idPrefix}-more-links`}
        onClick={() => setMoreOpen((v) => !v)}
        className="studio-nav-link studio-nav-more"
      >
        <span aria-hidden="true">{moreOpen ? '▾' : '▸'}</span>
        <span>{t('more')}</span>
      </button>
      {moreOpen && (
        <div id={`${idPrefix}-more-links`} className="flex flex-col gap-1 pl-4">
          {MORE_ITEMS.map(renderLink)}
        </div>
      )}
    </div>
  );

  return (
    <>
      <div className="studio-mobile-bar md:hidden">
        <button
          type="button"
          aria-label={ts("open-menu")}
          ref={menuButton}
          aria-expanded={open}
          aria-controls="feature-rail-drawer"
          onClick={() => setOpen(true)}
          className="rounded px-2 py-1 text-xl text-text-primary"
        >
          ☰
        </button>
        <a href={prefix || '/'} className="studio-brand"><StudioMark/><span>EvoForge</span></a>
      </div>
      <nav
        aria-label={ts("navigation")}
        className="studio-rail hidden md:flex"
      >
        <a href={prefix || '/'} className="studio-brand"><StudioMark/><span>EvoForge</span></a>
        <p className="studio-nav-caption">{ts('workspace')}</p>
        {ITEMS.map(renderLink)}
        {moreSection('desktop')}
        <div className="studio-rail-note"><span className="studio-rail-project">E / {ts('project')}</span><a href={`${prefix}/replay`}>{ts('replay')} <span aria-hidden="true">↗</span></a></div>
      </nav>
      {open && (
        <div ref={drawer} id="feature-rail-drawer" role="dialog" aria-modal="true" aria-label={ts("navigation")} className="fixed inset-0 z-50 md:hidden">
          <button
            type="button"
            aria-label={ts("close-menu")}
            onClick={() => setOpen(false)}
            className="absolute inset-0 bg-black/70"
            tabIndex={-1}
          />
          <nav
            aria-label={ts("navigation")}
            className="studio-mobile-drawer"
          >
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label={ts("close-menu")}
              className="self-end rounded px-2 py-1 text-text-tertiary"
            >
              ✕
            </button>
            {ITEMS.map(renderLink)}
            {moreSection('mobile')}
          </nav>
        </div>
      )}
    </>
  );
}
