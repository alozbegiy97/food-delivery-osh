import { useTranslation } from 'react-i18next';

// The profile page `/tg/account` is TelegramProfilePage (DEC-160 п. 1).

/** Unknown `/tg/*` path; links only inside the Mini App. */
export function TelegramNotFoundPage() {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col gap-2 rounded-[var(--radius-card)] border border-border bg-surface p-6">
      <h1 className="text-xl font-bold">{t('telegram.notFound.title')}</h1>
      <p className="text-ink-600">{t('telegram.notFound.text')}</p>
    </section>
  );
}
