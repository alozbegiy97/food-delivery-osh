import { useTranslation } from 'react-i18next';

import type { ChartOut } from '../../../shared/types/api';
import { toTyiyn } from '../../catalog/money';

const W = 640;
const H = 220;
const PAD = { left: 40, right: 56, top: 16, bottom: 32 };

/**
 * Two lines on one SVG (DEC-150 п. 6, no chart library): orders by the date
 * of creation (left axis) and revenue by the date of completion (right
 * axis). The legend states the different principles (DEC-111).
 */
export function DashboardChart({ chart }: { chart: ChartOut }) {
  const { t } = useTranslation();
  const points = chart.points;
  const orders = points.map((p) => p.orders_created);
  const revenue = points.map((p) => toTyiyn(p.revenue) / 100);
  const maxOrders = Math.max(1, ...orders);
  const maxRevenue = Math.max(1, ...revenue);
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const x = (i: number) =>
    PAD.left + (points.length > 1 ? (innerW * i) / (points.length - 1) : innerW / 2);
  const y = (value: number, max: number) => PAD.top + innerH - (innerH * value) / max;
  const line = (values: number[], max: number) =>
    values
      .map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v, max).toFixed(1)}`)
      .join(' ');

  return (
    <figure className="flex flex-col gap-2">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={t('admin.dashboard.chartLabel')}
        className="h-auto w-full"
      >
        {[0, 0.5, 1].map((share) => (
          <g key={share}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={PAD.top + innerH * (1 - share)}
              y2={PAD.top + innerH * (1 - share)}
              className="stroke-border"
              strokeDasharray={share === 0 ? undefined : '4 4'}
            />
            <text
              x={PAD.left - 6}
              y={PAD.top + innerH * (1 - share) + 4}
              textAnchor="end"
              className="fill-ink-600 text-[10px]"
            >
              {Math.round(maxOrders * share)}
            </text>
            <text
              x={W - PAD.right + 6}
              y={PAD.top + innerH * (1 - share) + 4}
              className="fill-ink-600 text-[10px]"
            >
              {Math.round(maxRevenue * share)}
            </text>
          </g>
        ))}
        <path
          d={line(orders, maxOrders)}
          fill="none"
          className="stroke-accent-700"
          strokeWidth={2.5}
        />
        <path
          d={line(revenue, maxRevenue)}
          fill="none"
          className="stroke-success-700"
          strokeWidth={2.5}
          strokeDasharray="6 4"
        />
        {points.map((p, i) => (
          <g key={p.date}>
            <circle cx={x(i)} cy={y(orders[i], maxOrders)} r={3.5} className="fill-accent-700">
              <title>{`${p.date}: ${t('admin.dashboard.ordersLine')} — ${p.orders_created}`}</title>
            </circle>
            <circle cx={x(i)} cy={y(revenue[i], maxRevenue)} r={3.5} className="fill-success-700">
              <title>{`${p.date}: ${t('admin.dashboard.revenueLine')} — ${p.revenue}`}</title>
            </circle>
            <text x={x(i)} y={H - 10} textAnchor="middle" className="fill-ink-600 text-[10px]">
              {p.date.slice(5)}
            </text>
          </g>
        ))}
      </svg>
      <figcaption className="flex flex-wrap gap-4 text-xs text-ink-600">
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-0.5 w-6 bg-accent-700" />
          {t('admin.dashboard.ordersLine')}
        </span>
        <span className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="inline-block h-0.5 w-6 border-t-2 border-dashed border-success-700"
          />
          {t('admin.dashboard.revenueLine')}
        </span>
      </figcaption>
      <table className="sr-only">
        <caption>{t('admin.dashboard.chartLabel')}</caption>
        <thead>
          <tr>
            <th>{t('admin.dashboard.date')}</th>
            <th>{t('admin.dashboard.ordersLine')}</th>
            <th>{t('admin.dashboard.revenueLine')}</th>
          </tr>
        </thead>
        <tbody>
          {points.map((p) => (
            <tr key={p.date}>
              <td>{p.date}</td>
              <td>{p.orders_created}</td>
              <td>{p.revenue}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
