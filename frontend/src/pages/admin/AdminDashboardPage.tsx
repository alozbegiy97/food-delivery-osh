import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Price } from '../../features/catalog/components/Price';
import { AdminSection } from '../../features/admin/components/AdminUi';
import { DashboardChart } from '../../features/admin/components/DashboardChart';
import {
  STAFF_POLLING_MS,
  useDashboardChartQuery,
  useDashboardSummaryQuery,
  useDashboardTopQuery,
  type PeriodArgs,
} from '../../features/admin/opsApi';
import { ErrorState } from '../../shared/components/StateViews';

function Metric({
  label,
  hint,
  children,
}: {
  label: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-card border border-border bg-surface p-4">
      <p className="text-sm text-ink-600">{label}</p>
      <p className="mt-1 text-2xl font-extrabold">{children}</p>
      <p className="mt-1 text-xs text-ink-600">{hint}</p>
    </div>
  );
}

/** Dashboard (DEC-90, DEC-111, DEC-114): one period for all metrics; the
 * active orders are "now" and do not depend on it. */
export function AdminDashboardPage() {
  const { t } = useTranslation();
  const [period, setPeriod] = useState<PeriodArgs>({});
  const options = { pollingInterval: STAFF_POLLING_MS };
  const summary = useDashboardSummaryQuery(period, options);
  const chart = useDashboardChartQuery(period, options);
  const top = useDashboardTopQuery(period, options);
  const input = 'min-h-11 rounded-lg border border-border bg-surface px-3';

  if (summary.isError || chart.isError || top.isError) {
    return (
      <ErrorState
        title={t('admin.loadError')}
        text={t('menu.errorText')}
        onRetry={() => {
          void summary.refetch();
          void chart.refetch();
          void top.refetch();
        }}
      />
    );
  }
  const data = summary.data;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold">{t('admin.sections.dashboard')}</h1>
          {data && (
            <p className="text-sm text-ink-600">
              {t('admin.dashboard.period', {
                from: data.period.date_from,
                to: data.period.date_to,
              })}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-sm font-medium">
            {t('admin.dashboard.dateFrom')}
            <input
              type="date"
              className={input}
              value={period.dateFrom ?? ''}
              onChange={(e) => setPeriod({ ...period, dateFrom: e.target.value || undefined })}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium">
            {t('admin.dashboard.dateTo')}
            <input
              type="date"
              className={input}
              value={period.dateTo ?? ''}
              onChange={(e) => setPeriod({ ...period, dateTo: e.target.value || undefined })}
            />
          </label>
          <button
            type="button"
            className="min-h-11 rounded-full px-4 text-sm font-semibold ring-1 ring-border"
            onClick={() => setPeriod({})}
          >
            {t('admin.dashboard.lastWeek')}
          </button>
        </div>
      </header>

      {!data ? (
        <p role="status" className="text-ink-600">
          {t('admin.loading')}
        </p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Metric label={t('admin.dashboard.orders')} hint={t('admin.dashboard.ordersHint')}>
            <span data-testid="metric-orders">{data.orders_count}</span>
          </Metric>
          <Metric label={t('admin.dashboard.revenue')} hint={t('admin.dashboard.revenueHint')}>
            <Price amount={data.revenue} />
          </Metric>
          <Metric label={t('admin.dashboard.average')} hint={t('admin.dashboard.averageHint')}>
            <Price amount={data.average_check} />
          </Metric>
          <Metric label={t('admin.dashboard.active')} hint={t('admin.dashboard.activeHint')}>
            <span data-testid="metric-active">{data.active_orders}</span>
          </Metric>
        </div>
      )}

      <AdminSection
        title={t('admin.dashboard.chartTitle')}
        description={t('admin.dashboard.chartHint')}
      >
        {chart.data ? (
          <DashboardChart chart={chart.data} />
        ) : (
          <p className="text-ink-600">{t('admin.loading')}</p>
        )}
      </AdminSection>

      <AdminSection
        title={t('admin.dashboard.topTitle')}
        description={t('admin.dashboard.topHint')}
      >
        {!top.data ? (
          <p className="text-ink-600">{t('admin.loading')}</p>
        ) : top.data.items.length === 0 ? (
          <p className="text-sm text-ink-600">{t('admin.dashboard.topEmpty')}</p>
        ) : (
          <ol className="flex flex-col gap-1 text-sm">
            {top.data.items.map((item, index) => (
              <li key={item.product_id ?? index} className="flex justify-between gap-3">
                <span>
                  {index + 1}. {item.product_name}
                </span>
                <span className="font-semibold">
                  {t('admin.dashboard.pieces', { count: item.quantity })}
                </span>
              </li>
            ))}
          </ol>
        )}
      </AdminSection>
    </div>
  );
}
