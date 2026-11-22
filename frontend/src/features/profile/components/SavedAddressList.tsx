import { useTranslation } from 'react-i18next';

import { EmptyState, ErrorState } from '../../../shared/components/StateViews';
import { useGetAddressesQuery } from '../../addresses/addressesApi';

/**
 * Saved addresses of the customer, read only (DEC-160 п. 4): no editing,
 * deleting or choosing the default here; a new address is saved at checkout
 * (DEC-157 п. 3). "Повторить" repeats only the address request.
 */
export function SavedAddressList() {
  const { t } = useTranslation();
  const addresses = useGetAddressesQuery();

  if (addresses.isLoading) {
    return (
      <p role="status" className="text-sm text-ink-600">
        {t('telegram.profile.addresses.loading')}
      </p>
    );
  }
  if (addresses.isError || !addresses.data) {
    return (
      <ErrorState
        title={t('telegram.profile.addresses.errorTitle')}
        text={t('telegram.profile.errorText')}
        onRetry={() => void addresses.refetch()}
        retrying={addresses.isFetching}
      />
    );
  }
  const { items } = addresses.data;
  if (items.length === 0) {
    return (
      <EmptyState
        title={t('telegram.profile.addresses.emptyTitle')}
        text={t('telegram.profile.addresses.emptyText')}
      />
    );
  }
  return (
    <ul className="flex flex-col gap-3" aria-label={t('telegram.profile.addresses.listLabel')}>
      {items.map((address) => {
        const details = [
          address.entrance && t('orders.entrance', { value: address.entrance }),
          address.floor && t('orders.floor', { value: address.floor }),
          address.apartment && t('orders.apartment', { value: address.apartment }),
        ].filter(Boolean);
        return (
          <li
            key={address.id}
            className="flex flex-col gap-1 rounded-xl border border-border bg-surface px-4 py-3 text-sm"
          >
            {(address.label || address.is_default) && (
              <div className="flex flex-wrap items-center gap-2">
                {address.label && (
                  <span className="min-w-0 font-semibold break-words">{address.label}</span>
                )}
                {address.is_default && (
                  <span className="shrink-0 rounded-full bg-accent-50 px-2.5 py-0.5 text-xs font-semibold text-accent-800">
                    {t('telegram.profile.addresses.default')}
                  </span>
                )}
              </div>
            )}
            <p className="break-words">{address.address_text}</p>
            {details.length > 0 && <p className="text-ink-600">{details.join(', ')}</p>}
            {address.comment && <p className="break-words text-ink-600">{address.comment}</p>}
          </li>
        );
      })}
    </ul>
  );
}
