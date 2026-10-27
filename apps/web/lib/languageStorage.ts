import type { Locale } from './i18n';

const STORAGE_KEY = 'evoforge.language';

/**
 * Retrieves the stored language preference from localStorage.
 * Returns null if no valid preference is stored or if localStorage is unavailable (SSR).
 */
export function getStoredLanguage(): Locale | null {
  if (typeof window === 'undefined') return null;
  
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === 'ko' || stored === 'en' ? stored : null;
  } catch {
    // Ignore storage errors (e.g., SecurityError in private browsing)
    return null;
  }
}

/**
 * Persists the language preference to localStorage.
 * Silently fails if localStorage is unavailable (SSR) or throws an error.
 */
export function setStoredLanguage(locale: Locale): void {
  if (typeof window === 'undefined') return;
  
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // Ignore storage errors
  }
}
