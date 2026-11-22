import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

export function NotFoundPage() {
  const { t } = useTranslation();

  return (
    <section aria-labelledby="not-found-title">
      <h1 id="not-found-title" className="text-2xl font-bold">
        {t('notFound.title')}
      </h1>
      <p className="mt-2 text-ink-600">{t('notFound.description')}</p>
      <Link
        to="/"
        className="mt-5 inline-flex min-h-11 items-center rounded-full bg-accent-700 px-5 font-semibold text-on-accent hover:bg-accent-strong"
      >
        {t('notFound.backHome')}
      </Link>
    </section>
  );
}
