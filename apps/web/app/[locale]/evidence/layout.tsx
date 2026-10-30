import { getTranslations } from 'next-intl/server';

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'titles' });
  return { title: t('evidence') };
}

export default function EvidenceLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
