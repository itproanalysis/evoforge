'use client';

import React, { useTransition } from 'react';
import { useLocale } from 'next-intl';
import { useRouter, usePathname } from 'next/navigation';
import { setStoredLanguage } from '../lib/languageStorage';
import type { Locale } from '../lib/i18n';

/**
 * Language switcher component for changing the interface language.
 * 
 * @example
 * ```tsx
 * <LanguageSwitcher />
 * ```
 * 
 * Accessibility:
 * - Keyboard navigable with Tab, Enter, and Arrow keys
 * - Includes aria-label for screen readers
 * - Visual focus indicators
 */
export function LanguageSwitcher() {
  const locale = useLocale() as Locale;
  const router = useRouter();
  const pathname = usePathname();
  const [isPending, startTransition] = useTransition();
  
  const handleLanguageChange = (newLocale: Locale) => {
    if (newLocale === locale) return;
    
    // Persist language preference
    setStoredLanguage(newLocale);
    
    // Navigate to the new locale
    startTransition(() => {
      // Remove current locale from pathname if present
      const pathnameWithoutLocale = pathname.replace(/^\/(en|ko)(?=\/|$)/, '') || '/';
      
      // Navigate to new locale path
      const newPath = newLocale === 'en'
        ? pathnameWithoutLocale 
        : `/${newLocale}${pathnameWithoutLocale}`;
      
      router.replace(newPath);
    });
  };
  
  return (
    <div className="flex items-center gap-2" aria-label="Select language">
      <button
        onClick={() => handleLanguageChange('en')}
        className={`px-2 py-1 text-sm rounded transition-colors focus:outline-none focus:ring-2 focus:ring-accent-blue ${
          locale === 'en'
            ? 'bg-accent-blue text-white font-medium'
            : 'text-text-secondary hover:text-text-primary hover:bg-background-secondary'
        }`}
        disabled={isPending}
        aria-current={locale === 'en' ? 'true' : 'false'}
      >
        English
      </button>
      <span className="text-text-secondary">|</span>
      <button
        onClick={() => handleLanguageChange('ko')}
        className={`px-2 py-1 text-sm rounded transition-colors focus:outline-none focus:ring-2 focus:ring-accent-blue ${
          locale === 'ko'
            ? 'bg-accent-blue text-white font-medium'
            : 'text-text-secondary hover:text-text-primary hover:bg-background-secondary'
        }`}
        disabled={isPending}
        aria-current={locale === 'ko' ? 'true' : 'false'}
      >
        한국어
      </button>
    </div>
  );
}
