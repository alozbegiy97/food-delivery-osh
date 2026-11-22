import { useTranslation } from 'react-i18next';

import { useGetHealthQuery } from '../../shared/api/healthApi';

// Stage 1 technical page (DEC A7): verifies routing, i18n and RTK Query
// against the real API. Replaced by real pages from Stage 3–4.
export function SystemStatusPage() {
  const { t } = useTranslation();
  const { data, isLoading, isError, isFetching, refetch } = useGetHealthQuery();

  return (
    <section aria-labelledby="status-title" className="max-w-xl">
      <h1 id="status-title" className="text-2xl font-bold">
        {t('status.title')}
      </h1>
      <p className="mt-2 text-ink-600">{t('status.description')}</p>

      <div
        className="mt-6 rounded-card border border-border bg-surface p-5 shadow-sm"
        aria-busy={isLoading || isFetching}
        aria-live="polite"
      >
        {isLoading && (
          <div>
            <p className="text-ink-600">{t('status.loading')}</p>
            <div className="mt-3 space-y-2" aria-hidden="true">
              <div className="h-4 w-2/3 animate-pulse rounded bg-cream-100" />
              <div className="h-4 w-1/2 animate-pulse rounded bg-cream-100" />
            </div>
          </div>
        )}

        {isError && !isLoading && (
          <div role="alert">
            <p className="font-semibold text-danger-700">{t('status.errorTitle')}</p>
            <p className="mt-1 text-ink-600">{t('status.errorDescription')}</p>
          </div>
        )}

        {data && !isError && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2">
            <dt className="text-ink-600">{t('status.overall')}</dt>
            <dd
              className={
                data.status === 'ok'
                  ? 'font-semibold text-success-700'
                  : 'font-semibold text-warning-700'
              }
            >
              {data.status === 'ok' ? t('status.values.ok') : t('status.values.degraded')}
            </dd>
            <dt className="text-ink-600">{t('status.database')}</dt>
            <dd className="font-semibold text-success-700">{t('status.values.ok')}</dd>
            <dt className="text-ink-600">{t('status.postgis')}</dt>
            <dd className="font-semibold">{data.postgis ?? t('status.values.notInstalled')}</dd>
          </dl>
        )}

        {!isLoading && (
          <button
            type="button"
            onClick={() => void refetch()}
            disabled={isFetching}
            className="mt-5 min-h-11 rounded-full bg-accent-700 px-5 font-semibold text-on-accent hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isFetching ? t('status.checking') : t('status.retry')}
          </button>
        )}
      </div>
    </section>
  );
}
