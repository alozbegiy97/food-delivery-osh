import { useEffect, useId, useRef, useState } from 'react';
import { Controller, useForm, useWatch } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router';

import { useGetAddressesQuery } from '../../features/addresses/addressesApi';
import { useMeQuery } from '../../features/auth/authApi';
import { useCustomerCart } from '../../features/cart/useCartAccess';
import { useGetRestaurantQuery } from '../../features/catalog/catalogApi';
import { Price } from '../../features/catalog/components/Price';
import { DeliveryMap } from '../../features/checkout/components/DeliveryMap';
import { QuoteSummary } from '../../features/checkout/components/QuoteSummary';
import { orderErrorInfo } from '../../features/checkout/messages';
import type { MapPoint } from '../../features/checkout/point';
import {
  checkoutSchema,
  LIMITS,
  newIdempotencyKey,
  type CheckoutForm,
  type CheckoutValues,
} from '../../features/checkout/schema';
import { useCreateOrderMutation, useGetQuoteMutation } from '../../features/orders/ordersApi';
import { useGetPaymentMethodsQuery } from '../../features/payments/paymentsApi';
import { useTelegramClosingConfirmation } from '../../features/telegram/useTelegramClosingConfirmation';
import { EmptyState } from '../../shared/components/StateViews';
import { TextField } from '../../shared/components/TextField';
import { useLanguage } from '../../shared/i18n/useLanguage';
import { formatPhoneInput } from '../../shared/lib/phone';
import { zodResolver } from '../../shared/lib/zodResolver';
import type { OrderCreate, QuoteIn, QuoteOut } from '../../shared/types/api';

const BOX = 'rounded-card border border-border bg-surface p-5 shadow-[var(--shadow-card)]';

function Choice({
  name,
  value,
  checked,
  label,
  hint,
  disabled,
  onChange,
}: {
  name: string;
  value: string;
  checked: boolean;
  label: string;
  hint?: string;
  disabled?: boolean;
  onChange: () => void;
}) {
  return (
    <label
      className={[
        'flex cursor-pointer items-start gap-3 rounded-xl border p-3',
        checked ? 'border-accent-600 bg-accent-50' : 'border-border',
        disabled ? 'cursor-not-allowed opacity-60' : '',
      ].join(' ')}
    >
      <input
        type="radio"
        name={name}
        value={value}
        checked={checked}
        disabled={disabled}
        onChange={onChange}
        className="mt-1 accent-accent-700"
      />
      <span>
        <span className="font-semibold">{label}</span>
        {hint && <span className="block text-sm text-ink-600">{hint}</span>}
      </span>
    </label>
  );
}

/**
 * `/checkout` (UI_UX_GUIDELINES §3): delivery or pickup, address on the map
 * (or a saved one), contacts, comment, payment (cash only until stage 7,
 * DEC-148), the server quote and confirmation. The button is locked while
 * the request runs; a retry reuses the same Idempotency-Key; success is
 * shown only after the backend created the order.
 */
export function CheckoutPage() {
  const { t } = useTranslation();
  const language = useLanguage();
  const navigate = useNavigate();
  const commentId = useId();
  const { access, cart } = useCustomerCart();
  const me = useMeQuery();
  const addresses = useGetAddressesQuery(undefined, { skip: access !== 'customer' });
  const restaurant = useGetRestaurantQuery();
  const methods = useGetPaymentMethodsQuery();
  const [chosenMethod, setChosenMethod] = useState<string | null>(null);
  const methodCodes = (methods.data?.items ?? []).map((m) => m.code);
  // The first active method is preselected; the server checks it again.
  const paymentMethod =
    chosenMethod && methodCodes.includes(chosenMethod) ? chosenMethod : (methodCodes[0] ?? null);
  const [getQuote, quoteState] = useGetQuoteMutation();
  const [createOrder, creating] = useCreateOrderMutation();
  // The last quote and the request it answers; shown only while it matches.
  const [quoteResult, setQuoteResult] = useState<{ key: string; data: QuoteOut } | null>(null);
  const [point, setPoint] = useState<MapPoint | null>(null);
  const [priceChanged, setPriceChanged] = useState(false);
  // One key per checkout attempt; a retry after a network error reuses it.
  const [idempotencyKey] = useState(newIdempotencyKey);

  const {
    register,
    control,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<CheckoutForm, unknown, CheckoutValues>({
    resolver: zodResolver(checkoutSchema),
    defaultValues: {
      delivery_type: 'delivery',
      address_mode: 'new',
      address_id: '',
      address_text: '',
      entrance: '',
      floor: '',
      apartment: '',
      address_comment: '',
      label: '',
      save_address: false,
      customer_name: '',
      customer_phone: '',
      comment: '',
    },
  });
  const deliveryType = useWatch({ control, name: 'delivery_type' });
  const addressMode = useWatch({ control, name: 'address_mode' });
  const addressId = useWatch({ control, name: 'address_id' });
  const saveAddress = useWatch({ control, name: 'save_address' });

  // Prefill contacts from the profile once it is known.
  const prefilled = useRef(false);
  useEffect(() => {
    if (me.data && !prefilled.current) {
      prefilled.current = true;
      setValue('customer_name', me.data.full_name);
      if (me.data.phone) {
        setValue('customer_phone', formatPhoneInput(me.data.phone));
      }
    }
  }, [me.data, setValue]);

  // Saved addresses with a point: offer the default one first.
  const usable = (addresses.data?.items ?? []).filter((a) => a.latitude && a.longitude);
  const pickedDefault = useRef(false);
  useEffect(() => {
    if (!pickedDefault.current && usable.length > 0) {
      pickedDefault.current = true;
      const preferred = usable.find((a) => a.is_default) ?? usable[0];
      setValue('address_mode', 'saved');
      setValue('address_id', preferred.id);
    }
  }, [usable, setValue]);

  // Ask the server for a quote whenever the way of getting the order or the point changes.
  const quoteBody: QuoteIn | null =
    deliveryType === 'pickup'
      ? { delivery_type: 'pickup' }
      : addressMode === 'saved'
        ? addressId
          ? { delivery_type: 'delivery', address_id: addressId }
          : null
        : point
          ? { delivery_type: 'delivery', address: point }
          : null;
  const quoteKey = JSON.stringify(quoteBody);
  useEffect(() => {
    if (access !== 'customer' || !quoteBody) {
      return;
    }
    let active = true;
    void getQuote({ body: quoteBody, language })
      .unwrap()
      .then((result) => {
        if (active) {
          setQuoteResult({ key: quoteKey, data: result });
          setPriceChanged(false);
        }
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
    // quoteKey describes quoteBody; the cart total changes only with the cart.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quoteKey, access, language, getQuote, cart.data?.subtotal]);
  const quote = quoteBody && quoteResult?.key === quoteKey ? quoteResult.data : null;

  // Mini App only (no-op on the site): ask before closing while a customer's
  // non-empty cart is being checked out (DEC-152 п. 11).
  useTelegramClosingConfirmation(access === 'customer' && (cart.data?.items.length ?? 0) > 0);

  if (access === 'staff') {
    return <EmptyState title={t('cart.staffTitle')} text={t('cart.staffOnly')} />;
  }
  if (access === 'checking' || cart.isLoading) {
    return (
      <p role="status" className="text-ink-600">
        {t('checkout.loading')}
      </p>
    );
  }
  if (cart.data && cart.data.items.length === 0) {
    return (
      <EmptyState
        title={t('checkout.emptyTitle')}
        text={t('checkout.emptyText')}
        action={
          <Link
            to="/menu"
            className="inline-flex min-h-11 items-center rounded-full bg-accent-700 px-6 font-semibold text-white"
          >
            {t('cart.toMenu')}
          </Link>
        }
      />
    );
  }

  const failure = creating.isError ? orderErrorInfo(t, creating.error, language) : null;
  const canSubmit =
    Boolean(quote?.can_place_order) &&
    Boolean(paymentMethod) &&
    !creating.isLoading &&
    !quoteState.isLoading;

  const onSubmit = handleSubmit(async (values) => {
    if (!quote || !quote.can_place_order || !paymentMethod) {
      return;
    }
    const body: OrderCreate = {
      delivery_type: values.delivery_type,
      customer_name: values.customer_name,
      customer_phone: values.customer_phone,
      comment: values.comment || null,
      payment_method_code: paymentMethod,
      expected_total: quote.total,
      language,
      save_address: false,
    };
    if (values.delivery_type === 'delivery') {
      if (values.address_mode === 'saved') {
        body.address_id = values.address_id;
      } else {
        if (!point) {
          return;
        }
        body.address = {
          address_text: values.address_text,
          latitude: point.latitude,
          longitude: point.longitude,
          entrance: values.entrance || null,
          floor: values.floor || null,
          apartment: values.apartment || null,
          comment: values.address_comment || null,
          label: values.label || null,
        };
        body.save_address = values.save_address;
      }
    }
    try {
      const created = await createOrder({ body, idempotencyKey }).unwrap();
      // mock_card: the demo payment screen comes next (DEC-149).
      const next =
        created.payment_method_code === 'mock_card'
          ? `/orders/${created.id}/pay`
          : `/orders/${created.id}`;
      void navigate(next, { replace: true });
    } catch (error) {
      const info = orderErrorInfo(t, error as Parameters<typeof orderErrorInfo>[1], language);
      if (info?.quote) {
        // DEC-10: show the new calculation and ask to confirm again.
        setQuoteResult({ key: quoteKey, data: info.quote });
        setPriceChanged(true);
      }
    }
  });

  const fieldError = (message?: string) => (message ? t(message) : undefined);
  const needsPoint = deliveryType === 'delivery' && addressMode === 'new' && !point;

  return (
    <form noValidate onSubmit={onSubmit} className="flex flex-col gap-6">
      <header>
        <Link to="/cart" className="text-sm font-semibold text-accent-800 hover:underline">
          ← {t('checkout.backToCart')}
        </Link>
        <h1 className="mt-1 text-3xl font-extrabold tracking-tight">{t('checkout.title')}</h1>
      </header>

      <div className="grid gap-6 lg:grid-cols-[1fr_22rem] lg:items-start">
        <div className="flex flex-col gap-6">
          <fieldset className={BOX}>
            <legend className="px-1 text-lg font-bold">{t('checkout.method.title')}</legend>
            <div className="mt-2 grid gap-3 sm:grid-cols-2">
              <Choice
                name="delivery_type"
                value="delivery"
                checked={deliveryType === 'delivery'}
                label={t('checkout.method.delivery')}
                hint={
                  restaurant.data && !restaurant.data.delivery_enabled
                    ? t('checkout.method.disabled')
                    : undefined
                }
                onChange={() => setValue('delivery_type', 'delivery')}
              />
              <Choice
                name="delivery_type"
                value="pickup"
                checked={deliveryType === 'pickup'}
                label={t('checkout.method.pickup')}
                hint={
                  restaurant.data?.address
                    ? t('checkout.method.pickupAt', { address: restaurant.data.address })
                    : undefined
                }
                onChange={() => setValue('delivery_type', 'pickup')}
              />
            </div>
          </fieldset>

          {deliveryType === 'delivery' && (
            <fieldset className={`${BOX} flex flex-col gap-4`}>
              <legend className="px-1 text-lg font-bold">{t('checkout.address.title')}</legend>
              {usable.length > 0 && (
                <div className="flex flex-col gap-2">
                  {usable.map((address) => (
                    <Choice
                      key={address.id}
                      name="address_choice"
                      value={address.id}
                      checked={addressMode === 'saved' && addressId === address.id}
                      label={address.label ?? address.address_text}
                      hint={address.label ? address.address_text : undefined}
                      onChange={() => {
                        setValue('address_mode', 'saved');
                        setValue('address_id', address.id);
                      }}
                    />
                  ))}
                  <Choice
                    name="address_choice"
                    value="new"
                    checked={addressMode === 'new'}
                    label={t('checkout.address.new')}
                    onChange={() => setValue('address_mode', 'new')}
                  />
                </div>
              )}
              {errors.address_id?.message && (
                <p className="text-sm text-danger-700">{t(errors.address_id.message)}</p>
              )}
              {addressMode === 'new' && (
                <>
                  <DeliveryMap
                    point={point}
                    onPick={setPoint}
                    center={
                      restaurant.data?.latitude && restaurant.data.longitude
                        ? [restaurant.data.latitude, restaurant.data.longitude]
                        : null
                    }
                  />
                  <TextField
                    label={t('checkout.fields.address_text')}
                    maxLength={LIMITS.addressText}
                    autoComplete="street-address"
                    error={fieldError(errors.address_text?.message)}
                    {...register('address_text')}
                  />
                  <div className="grid gap-3 sm:grid-cols-3">
                    <TextField
                      label={t('checkout.fields.entrance')}
                      maxLength={LIMITS.entrance}
                      error={fieldError(errors.entrance?.message)}
                      {...register('entrance')}
                    />
                    <TextField
                      label={t('checkout.fields.floor')}
                      maxLength={LIMITS.floor}
                      error={fieldError(errors.floor?.message)}
                      {...register('floor')}
                    />
                    <TextField
                      label={t('checkout.fields.apartment')}
                      maxLength={LIMITS.apartment}
                      error={fieldError(errors.apartment?.message)}
                      {...register('apartment')}
                    />
                  </div>
                  <TextField
                    label={t('checkout.fields.address_comment')}
                    maxLength={LIMITS.addressComment}
                    hint={t('checkout.hints.addressComment')}
                    error={fieldError(errors.address_comment?.message)}
                    {...register('address_comment')}
                  />
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="accent-accent-700"
                      {...register('save_address')}
                    />
                    {t('checkout.fields.save_address')}
                  </label>
                  {saveAddress && (
                    <TextField
                      label={t('checkout.fields.label')}
                      maxLength={LIMITS.label}
                      placeholder={t('checkout.hints.label')}
                      error={fieldError(errors.label?.message)}
                      {...register('label')}
                    />
                  )}
                </>
              )}
            </fieldset>
          )}

          <fieldset className={`${BOX} flex flex-col gap-4`}>
            <legend className="px-1 text-lg font-bold">{t('checkout.contacts.title')}</legend>
            <TextField
              label={t('checkout.fields.customer_name')}
              maxLength={LIMITS.customerName}
              autoComplete="name"
              error={fieldError(errors.customer_name?.message)}
              {...register('customer_name')}
            />
            <Controller
              control={control}
              name="customer_phone"
              render={({ field }) => (
                <TextField
                  label={t('checkout.fields.customer_phone')}
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  placeholder="+996 700 12 34 56"
                  error={fieldError(errors.customer_phone?.message)}
                  name={field.name}
                  ref={field.ref}
                  value={field.value}
                  onBlur={field.onBlur}
                  onChange={(event) => field.onChange(formatPhoneInput(event.target.value))}
                />
              )}
            />
            <div className="flex flex-col gap-1">
              <label htmlFor={commentId} className="text-sm font-medium">
                {t('checkout.fields.comment')}
              </label>
              <textarea
                id={commentId}
                rows={2}
                maxLength={LIMITS.comment}
                className="rounded-md border border-border bg-surface px-3 py-2"
                {...register('comment')}
              />
              {errors.comment?.message && (
                <p className="text-sm text-danger-700">{t(errors.comment.message)}</p>
              )}
            </div>
          </fieldset>

          <fieldset className={BOX}>
            <legend className="px-1 text-lg font-bold">{t('checkout.payment.title')}</legend>
            <div className="mt-2 grid gap-3 sm:grid-cols-2">
              {methodCodes.map((code) => (
                <Choice
                  key={code}
                  name="payment"
                  value={code}
                  checked={paymentMethod === code}
                  label={t(`checkout.payment.methods.${code}`, { defaultValue: code })}
                  hint={t(`checkout.payment.hints.${code}`, { defaultValue: '' }) || undefined}
                  onChange={() => setChosenMethod(code)}
                />
              ))}
            </div>
            {methods.isError && (
              <p role="alert" className="mt-2 text-sm text-danger-700">
                {t('checkout.payment.loadError')}
              </p>
            )}
          </fieldset>
        </div>

        <aside
          aria-label={t('checkout.summary')}
          className={`${BOX} flex flex-col gap-4 lg:sticky lg:top-24`}
        >
          <h2 className="text-lg font-bold">{t('checkout.summary')}</h2>
          {cart.data && (
            <ul className="flex flex-col gap-1 text-sm">
              {cart.data.items.map((item) => (
                <li key={item.id} className="flex justify-between gap-3">
                  <span>
                    {item.product_name}
                    {item.variant_name && ` · ${item.variant_name}`} × {item.quantity}
                  </span>
                  {item.line_total && <Price amount={item.line_total} />}
                </li>
              ))}
            </ul>
          )}
          {needsPoint ? (
            <p className="text-sm text-ink-600">{t('checkout.quote.needPoint')}</p>
          ) : (
            <QuoteSummary
              quote={quote}
              loading={quoteState.isLoading}
              failed={quoteState.isError}
            />
          )}
          {priceChanged && (
            <p role="alert" className="rounded-xl bg-accent-50 px-4 py-3 text-sm font-medium">
              {t('checkout.priceChangedConfirm')}
            </p>
          )}
          {failure && !failure.quote && (
            <div role="alert" className="rounded-xl bg-danger-50 px-4 py-3 text-sm text-danger-700">
              {failure.lines.map((line) => (
                <p key={line}>{line}</p>
              ))}
            </div>
          )}
          <button
            type="submit"
            disabled={!canSubmit}
            className="min-h-12 rounded-full bg-accent-700 px-6 font-semibold text-on-accent hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
          >
            {creating.isLoading
              ? t('checkout.placing')
              : priceChanged
                ? t('checkout.confirmNewTotal')
                : t('checkout.place')}
          </button>
          <p className="text-xs text-ink-600">{t('checkout.placeNote')}</p>
        </aside>
      </div>
    </form>
  );
}
