import type { SerializedError } from '@reduxjs/toolkit';
import type { FetchBaseQueryError } from '@reduxjs/toolkit/query';
import type { TFunction } from 'i18next';

import { apiErrorInfo } from '../../shared/api/errors';
import type { Language } from '../../shared/i18n/languages';
import { LOCALE_TAGS } from '../../shared/i18n/useLanguage';
import type { ApiErrorBody, ProblemOut, QuoteOut } from '../../shared/types/api';
import { formatTyiyn, toTyiyn } from '../catalog/money';
import { RESTAURANT_TIMEZONE } from '../restaurant/time';

export function formatDateTime(value: string, language: Language): string {
  return new Intl.DateTimeFormat(LOCALE_TAGS[language], {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: RESTAURANT_TIMEZONE,
  }).format(new Date(value));
}

function money(t: TFunction, amount: unknown, language: Language): string {
  return typeof amount === 'string'
    ? t('money.amount', { amount: formatTyiyn(toTyiyn(amount), LOCALE_TAGS[language]) })
    : '';
}

/** Why the order cannot be placed (codes of API §1.1, DEC-148). */
export function problemText(t: TFunction, problem: ProblemOut, language: Language): string {
  const details = (problem.details ?? {}) as Record<string, unknown>;
  switch (problem.code) {
    case 'MIN_ORDER_NOT_REACHED':
      return t('checkout.problems.MIN_ORDER_NOT_REACHED', {
        min: money(t, details.min_order_amount, language),
        subtotal: money(t, details.subtotal, language),
      });
    case 'RESTAURANT_CLOSED':
      return typeof details.next_opening_at === 'string'
        ? t('checkout.problems.RESTAURANT_CLOSED_UNTIL', {
            when: formatDateTime(details.next_opening_at, language),
          })
        : t('checkout.problems.RESTAURANT_CLOSED');
    default:
      return t(`checkout.problems.${problem.code}`, {
        defaultValue: t('checkout.problems.default'),
      });
  }
}

export interface OrderErrorInfo {
  code: string;
  lines: string[];
  // PRICE_CHANGED carries the current quote (DEC-10).
  quote: QuoteOut | null;
}

/** Text for a failed POST /orders. */
export function orderErrorInfo(
  t: TFunction,
  error: FetchBaseQueryError | SerializedError | undefined,
  language: Language,
): OrderErrorInfo | null {
  const info = apiErrorInfo(error);
  if (!info) {
    return null;
  }
  const details =
    error && 'status' in error
      ? (error.data as Partial<ApiErrorBody> | undefined)?.error?.details
      : undefined;
  if (info.code === 'PRICE_CHANGED') {
    const quote = (details ?? null) as QuoteOut | null;
    return {
      code: info.code,
      quote,
      lines: [t('checkout.errors.PRICE_CHANGED', { total: money(t, quote?.total, language) })],
    };
  }
  if (t(`checkout.problems.${info.code}`, { defaultValue: '' })) {
    return {
      code: info.code,
      quote: null,
      lines: [problemText(t, { code: info.code, details }, language)],
    };
  }
  const fieldLines = info.fields.map((field) =>
    t(`checkout.fields.${field.field}`, { defaultValue: field.field }),
  );
  return {
    code: info.code,
    quote: null,
    lines: [
      t(`checkout.errors.${info.code}`, {
        defaultValue: t(`errors.codes.${info.code}`, { defaultValue: t('errors.codes.default') }),
      }),
      ...(fieldLines.length
        ? [t('checkout.errors.checkFields', { fields: fieldLines.join(', ') })]
        : []),
    ],
  };
}
