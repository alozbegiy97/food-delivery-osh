import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import { useLanguage } from '../../../shared/i18n/useLanguage';
import type { QuoteOut } from '../../../shared/types/api';
import { Price } from '../../catalog/components/Price';
import { problemText } from '../messages';

/** Server quote: zone, fee, minimum and total; reasons why ordering is not
 * possible are explained in words (UI_UX_GUIDELINES §3 "Checkout"). */
export function QuoteSummary({
  quote,
  loading,
  failed,
}: {
  quote: QuoteOut | null;
  loading: boolean;
  failed: boolean;
}) {
  const { t } = useTranslation();
  const language = useLanguage();

  if (!quote) {
    return (
      <p role="status" className="text-sm text-ink-600">
        {failed
          ? t('checkout.quote.failed')
          : loading
            ? t('checkout.quote.loading')
            : t('checkout.quote.waiting')}
      </p>
    );
  }
  const itemProblem = quote.problems.some(
    (p) => p.code === 'ITEM_UNAVAILABLE' || p.code === 'MODIFIER_CONSTRAINT_VIOLATION',
  );
  return (
    <div className="flex flex-col gap-3" aria-busy={loading || undefined}>
      <dl className="flex flex-col gap-1 text-sm">
        <div className="flex justify-between gap-4">
          <dt className="text-ink-600">
            {t('checkout.quote.items', { count: quote.items_count })}
          </dt>
          <dd data-testid="quote-subtotal">
            <Price amount={quote.subtotal} />
          </dd>
        </div>
        {quote.delivery_type === 'delivery' && (
          <div className="flex justify-between gap-4">
            <dt className="text-ink-600">
              {t('checkout.quote.delivery')}
              {quote.zone && <span className="block text-xs">{quote.zone.name}</span>}
            </dt>
            <dd data-testid="quote-fee">
              {quote.zone ? <Price amount={quote.delivery_fee} /> : '—'}
            </dd>
          </div>
        )}
        <div className="flex justify-between gap-4">
          <dt className="text-ink-600">{t('checkout.quote.minimum')}</dt>
          <dd>
            <Price amount={quote.min_order_amount} />
          </dd>
        </div>
        <div className="mt-1 flex items-baseline justify-between gap-4 border-t border-border pt-2">
          <dt className="font-semibold">{t('checkout.quote.total')}</dt>
          <dd className="text-2xl font-bold" data-testid="quote-total" aria-live="polite">
            <Price amount={quote.total} />
          </dd>
        </div>
      </dl>
      {quote.problems.length > 0 && (
        <div role="alert" className="rounded-xl bg-danger-50 px-4 py-3 text-sm text-danger-700">
          <ul className="flex list-disc flex-col gap-1 pl-5">
            {quote.problems.map((problem) => (
              <li key={problem.code}>{problemText(t, problem, language)}</li>
            ))}
          </ul>
          {itemProblem && (
            <Link to="/cart" className="mt-2 inline-block font-semibold underline">
              {t('checkout.quote.toCart')}
            </Link>
          )}
        </div>
      )}
      <p className="text-xs text-ink-600">{t('checkout.quote.serverNote')}</p>
    </div>
  );
}
