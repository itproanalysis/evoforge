import { NextIntlClientProvider } from 'next-intl';
import { getMessages, getTranslations } from 'next-intl/server';
import { notFound } from 'next/navigation';
import { FeatureRail } from '../../components/FeatureRail';
import { LanguageSwitcher } from '../../components/LanguageSwitcher';
import { StudioBreadcrumb } from '../../components/StudioBreadcrumb';
import { StudioIcon } from '../../components/StudioIcon';
import '../../styles/globals.css';
import '../../styles/canvas.css';
import '../../styles/pages.css';

const locales = ['en', 'ko'];

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'titles' });
  const tLayout = await getTranslations({ locale, namespace: 'layout' });

  return {
    title: t('home'),
    description: tLayout('description'),
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
  const ts = await getTranslations('studio');
  const tLayout = await getTranslations('layout');
  const prefix = locale === 'en' ? '' : `/${locale}`;

  return (
    <html lang={locale}>
      <body className="m-0 font-sans bg-background-primary text-text-primary">
        <NextIntlClientProvider messages={messages}>
          <a href="#workspace-content" className="studio-skip">{ts('skip')}</a>
          <div className="studio-shell">
            <FeatureRail />
            <div className="studio-column flex-1">
              <header className="studio-topbar">
                <StudioBreadcrumb />
                <div className="flex items-center gap-5">
                  <a href={`${prefix}/replay`} className="studio-action-link hidden lg:inline-flex">{ts('replay')}<StudioIcon name="arrow" width="14" height="14"/></a>
                  <div className="hidden md:block">
                    <LanguageSwitcher />
                  </div>
                </div>
              </header>
              <div id="workspace-content" className="studio-content">{children}</div>
              <footer className="studio-footer"><span>EvoForge</span><p>{tLayout('footer')}</p></footer>
            </div>
          </div>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
