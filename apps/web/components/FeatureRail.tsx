'use client';

import { useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { usePathname } from 'next/navigation';

export const ITEMS = [
  { path: "/", key: "mission-control", icon: "◉" },
  { path: "/arena", key: "arena", icon: "⚔️" },
  { path: "/replay", key: "replay", icon: "▶" },
  { path: "/evidence", key: "evidence", icon: "📜" },
  { path: "/performance", key: "performance", icon: "📈" },
  { path: "/lab", key: "improvement-lab", icon: "🧪" },
];

export const MORE_ITEMS = [
  { path: "/evolution", key: "autopilot", icon: "🤖" },
  { path: "/leaderboard", key: "leaderboard", icon: "🏆" },
];

function stripLocalePrefix(pathname: string): string {
  const stripped = pathname.replace(/^\/(en)(?=\/|$)/, '');
  return stripped === '' ? '/' : stripped;
}

function linkClass(isActive: boolean): string {
  const base = 'flex items-center gap-2 rounded px-3 py-2 text-sm no-underline';
  return isActive
    ? `${base} bg-background-secondary text-text-primary font-semibold`
    : `${base} text-text-tertiary hover:text-text-primary`;
}

export function FeatureRail() {
  const locale = useLocale();
  const t = useTranslations('navigation');
  const pathname = usePathname() ?? '';
  const [open, setOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const prefix = locale === 'ko' ? '' : `/${locale}`;
  const routePath = stripLocalePrefix(pathname);

  const renderLink = ({ path, key, icon }: { path: string; key: string; icon: string }) => {
    const href = `${prefix}${path}`;
    const isActive = routePath === path;
    return (
      <a
        key={path}
        href={href}
        aria-current={isActive ? "page" : undefined}
        className={linkClass(isActive)}
      >
        <span aria-hidden="true">{icon}</span>
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
        className="flex w-full items-center gap-2 rounded px-3 py-2 text-sm text-text-tertiary hover:text-text-primary"
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
      <div className="flex items-center gap-2 px-4 py-2 md:hidden">
        <button
          type="button"
          aria-label="Open menu"
          aria-expanded={open}
          aria-controls="feature-rail-drawer"
          onClick={() => setOpen(true)}
          className="rounded px-2 py-1 text-xl text-text-primary"
        >
          ☰
        </button>
        <span className="text-sm font-semibold text-text-primary">{t('mission-control')}</span>
      </div>
      <nav
        aria-label="Feature navigation"
        className="hidden md:flex w-56 shrink-0 flex-col gap-1 border-r border-border px-3 py-4"
      >
        {ITEMS.map(renderLink)}
        {moreSection('desktop')}
      </nav>
      {open && (
        <div id="feature-rail-drawer" className="fixed inset-0 z-50 md:hidden">
          <button
            type="button"
            aria-label="Close menu"
            onClick={() => setOpen(false)}
            className="absolute inset-0 bg-black/50"
          />
          <nav
            aria-label="Feature navigation"
            className="absolute left-0 top-0 flex h-full w-64 flex-col gap-1 bg-background-primary px-3 py-4"
          >
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close menu"
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
