import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import {
  MAX_INSTRUCTIONS_LENGTH,
  MAX_LINE_QUANTITY,
  useClearCartMutation,
  useDeleteCartItemMutation,
  useUpdateCartItemMutation,
} from '../../features/cart/cartApi';
import { cartErrorLines, issueText } from '../../features/cart/cartMessages';
import { useCustomerCart } from '../../features/cart/useCartAccess';
import { DishImage } from '../../features/catalog/components/DishImage';
import { Stepper } from '../../features/catalog/components/OptionPickers';
import { Price } from '../../features/catalog/components/Price';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';
import type { CartItemOut } from '../../shared/types/api';

const LINK_BUTTON =
  'inline-flex min-h-11 items-center justify-center rounded-full px-4 text-sm font-semibold ring-1 ring-border hover:bg-cream-100 disabled:opacity-60';

function InstructionsEditor({ item, onDone }: { item: CartItemOut; onDone: () => void }) {
  const { t } = useTranslation();
  const id = useId();
  const [value, setValue] = useState(item.special_instructions ?? '');
  const [update, state] = useUpdateCartItemMutation();
  const errors = state.isError ? cartErrorLines(t, state.error) : [];
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        void update({ id: item.id, body: { special_instructions: value.trim() || null } })
          .unwrap()
          .then(onDone)
          .catch(() => undefined);
      }}
    >
      <label htmlFor={id} className="text-sm font-medium">
        {t('product.instructions')}
      </label>
      <textarea
        id={id}
        rows={2}
        maxLength={MAX_INSTRUCTIONS_LENGTH}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        className="rounded-xl border border-border bg-surface px-3 py-2"
      />
      {errors.map((line) => (
        <p key={line} role="alert" className="text-sm text-danger-700">
          {line}
        </p>
      ))}
      <p className="text-xs text-ink-600">{t('cart.mergeHint')}</p>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={state.isLoading}
          className="inline-flex min-h-11 items-center rounded-full bg-accent-700 px-4 text-sm font-semibold text-white disabled:opacity-60"
        >
          {state.isLoading ? t('cart.saving') : t('cart.save')}
        </button>
        <button type="button" className={LINK_BUTTON} onClick={onDone}>
          {t('cart.cancel')}
        </button>
      </div>
    </form>
  );
}

function CartLine({ item }: { item: CartItemOut }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [update, updating] = useUpdateCartItemMutation();
  const [remove, removing] = useDeleteCartItemMutation();
  const busy = updating.isLoading || removing.isLoading;
  const errors = [
    ...(updating.isError ? cartErrorLines(t, updating.error) : []),
    ...(removing.isError ? cartErrorLines(t, removing.error) : []),
  ];

  return (
    <li
      className={[
        'flex flex-col gap-4 rounded-card border bg-surface p-4 sm:flex-row',
        item.is_available ? 'border-border' : 'border-danger-700/40',
      ].join(' ')}
      aria-busy={busy || undefined}
    >
      <Link
        to={`/menu/${item.product_id}`}
        className="w-24 shrink-0 self-start overflow-hidden rounded-xl border border-border"
      >
        <DishImage imageUrl={item.image_url} alt="" />
      </Link>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 className="font-bold">
              <Link to={`/menu/${item.product_id}`} className="hover:underline">
                {item.product_name}
              </Link>
            </h2>
            {item.variant_name && <p className="text-sm text-ink-600">{item.variant_name}</p>}
          </div>
          <div className="text-right">
            <p className="font-bold" data-testid="line-total">
              {item.line_total ? <Price amount={item.line_total} /> : '—'}
            </p>
            {item.unit_price && item.quantity > 1 && (
              <p className="text-xs text-ink-600">
                {t('cart.perUnit')} <Price amount={item.unit_price} />
              </p>
            )}
          </div>
        </div>

        {item.modifiers.length > 0 && (
          <ul className="text-sm text-ink-600">
            {item.modifiers.map((modifier) => (
              <li key={modifier.id}>
                {modifier.group_name ? `${modifier.group_name}: ` : ''}
                {modifier.name}
                {modifier.quantity > 1 && ` × ${modifier.quantity}`}
                {Number(modifier.unit_price) > 0 && (
                  <>
                    {' '}
                    (+
                    <Price amount={modifier.unit_price} />)
                  </>
                )}
              </li>
            ))}
          </ul>
        )}

        {!editing && item.special_instructions && (
          <p className="text-sm">
            <span className="font-medium">{t('cart.instructions')}:</span>{' '}
            {item.special_instructions}
          </p>
        )}

        {item.issues.length > 0 && (
          <div role="alert" className="rounded-xl bg-danger-50 px-3 py-2 text-sm text-danger-700">
            <p className="font-semibold">{t('cart.lineUnavailable')}</p>
            <ul className="list-disc pl-5">
              {item.issues.map((issue, index) => (
                <li key={index}>{issueText(t, issue)}</li>
              ))}
            </ul>
          </div>
        )}

        {editing ? (
          <InstructionsEditor item={item} onDone={() => setEditing(false)} />
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <Stepper
              label={t('cart.quantityOf', { name: item.product_name })}
              value={item.quantity}
              max={MAX_LINE_QUANTITY}
              disabled={busy}
              onChange={(quantity) => void update({ id: item.id, body: { quantity } })}
            />
            <button
              type="button"
              className={LINK_BUTTON}
              disabled={busy}
              onClick={() => setEditing(true)}
            >
              {item.special_instructions ? t('cart.editInstructions') : t('cart.addInstructions')}
            </button>
            <button
              type="button"
              className={`${LINK_BUTTON} text-danger-700`}
              disabled={busy}
              onClick={() => void remove(item.id)}
              aria-label={t('cart.removeLabel', { name: item.product_name })}
            >
              {t('cart.remove')}
            </button>
          </div>
        )}
        {errors.map((line) => (
          <p key={line} role="alert" className="text-sm text-danger-700">
            {line}
          </p>
        ))}
      </div>
    </li>
  );
}

/** `/cart`: lines, quantities, wishes, server totals (UI_UX_GUIDELINES §3 "Cart"). */
export function CartPage() {
  const { t } = useTranslation();
  const { access, cart } = useCustomerCart();
  const [clear, clearing] = useClearCartMutation();
  const [confirmClear, setConfirmClear] = useState(false);

  const heading = <h1 className="text-3xl font-extrabold tracking-tight">{t('cart.title')}</h1>;

  if (access === 'staff') {
    return (
      <div className="flex flex-col gap-6">
        {heading}
        <EmptyState title={t('cart.staffTitle')} text={t('cart.staffOnly')} />
      </div>
    );
  }
  if (access === 'checking' || cart.isLoading) {
    return (
      <div className="flex flex-col gap-6" aria-busy="true">
        {heading}
        <p role="status" className="text-ink-600">
          {t('cart.loading')}
        </p>
        <div className="h-28 animate-pulse rounded-card bg-cream-100" />
        <div className="h-28 animate-pulse rounded-card bg-cream-100" />
      </div>
    );
  }
  if (cart.isError || !cart.data) {
    return (
      <div className="flex flex-col gap-6">
        {heading}
        <ErrorState
          title={t('cart.errorTitle')}
          text={t('menu.errorText')}
          onRetry={() => void cart.refetch()}
          retrying={cart.isFetching}
        />
      </div>
    );
  }

  const data = cart.data;
  if (data.items.length === 0) {
    return (
      <div className="flex flex-col gap-6">
        {heading}
        <EmptyState
          title={t('cart.emptyTitle')}
          text={t('cart.emptyText')}
          action={
            <Link
              to="/menu"
              className="inline-flex min-h-11 items-center rounded-full bg-accent-700 px-6 font-semibold text-white"
            >
              {t('cart.toMenu')}
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {heading}
        {confirmClear ? (
          <div
            role="alertdialog"
            aria-label={t('cart.clearQuestion')}
            className="flex flex-wrap items-center gap-2 rounded-xl bg-danger-50 p-3"
          >
            <span className="text-sm font-medium text-danger-700">{t('cart.clearQuestion')}</span>
            <button
              type="button"
              className="inline-flex min-h-11 items-center rounded-full bg-danger-strong px-4 text-sm font-semibold text-on-accent"
              disabled={clearing.isLoading}
              onClick={() => {
                setConfirmClear(false);
                void clear();
              }}
            >
              {t('cart.clearConfirm')}
            </button>
            <button type="button" className={LINK_BUTTON} onClick={() => setConfirmClear(false)}>
              {t('cart.cancel')}
            </button>
          </div>
        ) : (
          <button type="button" className={LINK_BUTTON} onClick={() => setConfirmClear(true)}>
            {t('cart.clear')}
          </button>
        )}
      </div>
      {clearing.isError && (
        <p role="alert" className="text-sm text-danger-700">
          {cartErrorLines(t, clearing.error).join(' ')}
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem] lg:items-start">
        <ul className="flex flex-col gap-4" aria-label={t('cart.linesLabel')}>
          {data.items.map((item) => (
            <CartLine key={item.id} item={item} />
          ))}
        </ul>

        <aside
          aria-label={t('cart.summary')}
          className="flex flex-col gap-3 rounded-card border border-border bg-surface p-5 shadow-[var(--shadow-card)] lg:sticky lg:top-24"
        >
          <p className="flex justify-between text-sm text-ink-600">
            <span>{t('cart.itemsCount')}</span>
            <span data-testid="items-count">{data.items_count}</span>
          </p>
          <p className="flex items-baseline justify-between">
            <span className="font-semibold">{t('cart.subtotal')}</span>
            <span className="text-2xl font-bold" data-testid="subtotal" aria-live="polite">
              <Price amount={data.subtotal} />
            </span>
          </p>
          {data.has_issues && (
            <p role="alert" className="text-sm font-medium text-danger-700">
              {t('cart.fixIssues')}
            </p>
          )}
          {data.has_issues ? (
            <button
              type="button"
              disabled
              aria-describedby="checkout-note"
              className="min-h-12 rounded-full bg-accent-700 px-6 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              {t('cart.checkout')}
            </button>
          ) : (
            <Link
              to="/checkout"
              aria-describedby="checkout-note"
              className="inline-flex min-h-12 items-center justify-center rounded-full bg-accent-700 px-6 font-semibold text-on-accent hover:bg-accent-strong"
            >
              {t('cart.checkout')}
            </Link>
          )}
          <p id="checkout-note" className="text-xs text-ink-600">
            {t('cart.serverPrices')}
          </p>
        </aside>
      </div>
    </div>
  );
}
