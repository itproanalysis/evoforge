import { NextIntlClientProvider } from 'next-intl';
import { getMessages, getTranslations } from 'next-intl/server';
import { notFound } from 'next/navigation';
import { FeatureRail } from '../../components/FeatureRail';
import { LanguageSwitcher } from '../../components/LanguageSwitcher';
import '../../styles/globals.css';

const locales = ['en', 'ko'];

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'layout' });
  
  return {
    title: t('title'),
    description: t('description'),
  };
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  // Validate locale
  if (!locales.includes(locale)) {
    notFound();
  }

  const messages = await getMessages();
  const tCommon = await getTranslations('common');
  const tLayout = await getTranslations('layout');

  const raw = (process.env.NEXT_PUBLIC_API_BASE ?? '').trim();
  const apiBase = raw === '' ? '/api/evoforge (same-origin)' : raw;
  const prefix = locale === 'ko' ? '' : `/${locale}`;

  return (
    <html lang={locale}>
      <body className="m-0 font-sans bg-background-primary text-text-primary">
        <NextIntlClientProvider messages={messages}>
          <header className="flex items-center gap-5 px-6 py-3 bg-background-tertiary border-b border-border sticky top-0 z-10 flex-wrap">
            <a
              href={prefix || '/'}
              className="text-text-tertiary no-underline font-extrabold text-xl hover:text-text-primary"
            >
              {tCommon('app-name')}
            </a>
            <div className="ml-auto flex items-center gap-4">
              <LanguageSwitcher />
              <span className="text-xs text-text-secondary">
                {tCommon('api-label')}: {apiBase}
              </span>
            </div>
          </header>
          <div className="flex">
            {/* Primary feature navigation (including /replay) renders here via <FeatureRail/>. */}
            <FeatureRail />
            <div className="flex-1 min-w-0">
              <div className="max-w-[1080px] mx-auto px-6 py-6">
                {children}
              </div>
              <footer className="px-6 py-4 text-xs text-text-secondary">
                {tLayout('footer')}
              </footer>
            </div>
          </div>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
