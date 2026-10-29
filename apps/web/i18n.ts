import { notFound } from 'next/navigation';
import { getRequestConfig } from 'next-intl/server';

export default getRequestConfig(async ({ requestLocale }) => {
  // Await requestLocale (required in next-intl 4.x)
  let locale = await requestLocale;
  
  // Validate that the incoming `locale` parameter is valid
  const locales = ['en', 'ko'];
  if (!locale || !locales.includes(locale)) {
    locale = 'ko'; // Match the middleware's default locale.
  }

  return {
    locale,
    messages: (await import(`./messages/${locale}.json`)).default
  };
});
