import { useTranslation } from 'react-i18next';

import { LOCALE_TAGS, useLanguage } from '../../../shared/i18n/useLanguage';
import { formatTyiyn, toTyiyn } from '../money';

interface PriceProps {
  amount?: string | null;
  tyiyn?: number;
  from?: boolean;
  className?: string;
}

/** Price in som ("550 сом", "от 550 сом"); the backend amount is shown as is. */
export function Price({ amount, tyiyn, from = false, className }: PriceProps) {
  const { t } = useTranslation();
  const language = useLanguage();
  const value = tyiyn ?? (amount ? toTyiyn(amount) : null);
  if (value === null) {
    return null;
  }
  const formatted = formatTyiyn(value, LOCALE_TAGS[language]);
  return (
    <span className={className}>
      {t(from ? 'money.from' : 'money.amount', { amount: formatted })}
    </span>
  );
}
