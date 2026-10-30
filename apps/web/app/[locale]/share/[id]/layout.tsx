import { getTranslations } from 'next-intl/server';
import { fetchArenaForPreview, laneScore } from '../../../../lib/serverArena';

// Link-preview text for one shared result: the verdict and both scores, so the message that carries
// the link already says who won.
export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  const t = await getTranslations({ locale, namespace: 'titles' });
  const ts = await getTranslations({ locale, namespace: 'share' });
  const doc = await fetchArenaForPreview(id);
  if (!doc) return { title: t('share') };
  const evo = laneScore(doc, 'evoforge');
  const single = laneScore(doc, 'single');
  const winner = doc.verdict?.winner;
  const verdict = winner && ts.has(`winner-${winner}`) ? ts(`winner-${winner}`) : t('share');
  const scores = `EvoForge ${evo ? `${evo.passed}/${evo.n}` : '—'} · ${ts('single')} ${single ? `${single.passed}/${single.n}` : '—'}`;
  const prompt = (doc.prompt || doc.goal || '').replace(/\s+/g, ' ').trim().slice(0, 140);
  const description = [scores, prompt].filter(Boolean).join(' — ');
  return {
    title: `${verdict} · ${t('share')}`,
    description,
    openGraph: { title: verdict, description, type: 'article' },
    twitter: { card: 'summary_large_image', title: verdict, description },
  };
}

export default function ShareResultLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
