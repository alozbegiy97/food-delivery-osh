import { useTranslation } from 'react-i18next';

import { useLanguage } from '../../../shared/i18n/useLanguage';
import type { PaymentOut } from '../../../shared/types/api';
import { Price } from '../../catalog/components/Price';
import { formatDateTime } from '../../checkout/messages';

/** Payment attempts of an order, oldest first (DEC-149). */
export function PaymentAttempts({ payments }: { payments: PaymentOut[] }) {
  const { t } = useTranslation();
  const language = useLanguage();
  if (payments.length === 0) {
    return null;
  }
  return (
    <ol className="flex flex-col gap-1 text-sm" aria-label={t('payments.attemptsLabel')}>
      {payments.map((payment, index) => (
        <li key={payment.id} className="flex flex-wrap items-center justify-between gap-2">
          <span>
            {t('payments.attempt', { number: index + 1 })} ·{' '}
            {t(`orders.paymentMethod.${payment.method_code}`, {
              defaultValue: payment.method_code,
            })}{' '}
            · <span className="font-semibold">{t(`payments.status.${payment.status}`)}</span>
          </span>
          <span className="text-ink-600">
            <Price amount={payment.amount} /> · {formatDateTime(payment.created_at, language)}
          </span>
        </li>
      ))}
    </ol>
  );
}
