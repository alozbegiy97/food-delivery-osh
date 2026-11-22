import { useId, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { Link, useLocation, useNavigate } from 'react-router';

import type { ProductDetail } from '../../../shared/types/api';
import {
  MAX_INSTRUCTIONS_LENGTH,
  MAX_LINE_QUANTITY,
  useAddCartItemMutation,
} from '../../cart/cartApi';
import { cartErrorLines } from '../../cart/cartMessages';
import { useCartAccess } from '../../cart/useCartAccess';
import { ABOVE_NAV_BOTTOM } from '../../telegram/miniAppLayout';
import { selectTelegramActive } from '../../telegram/telegramSlice';
import {
  chooseSingle,
  initialConfiguration,
  previewPrice,
  selectVariant,
  setModifierQuantity,
  toggleMultiple,
  validate,
  type Configuration,
} from '../configurator';
import { ModifierGroupField, Stepper, VariantPicker } from './OptionPickers';
import { Price } from './Price';

interface ProductConfiguratorProps {
  product: ProductDetail;
}

/**
 * Size, dough, extras, quantity and wishes with a live PREVIEW price, and
 * "Add to cart". The server validates the selection and calculates every
 * price of the cart (DEC-08); success is shown only after it answered.
 * Guests go to the login page and come back here (DEC-13).
 */
export function ProductConfigurator({ product }: ProductConfiguratorProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const instructionsId = useId();
  const access = useCartAccess();
  const miniApp = useSelector(selectTelegramActive);
  const [config, setConfig] = useState<Configuration>(() => initialConfiguration(product));
  const [quantity, setQuantity] = useState(1);
  const [instructions, setInstructions] = useState('');
  const [addToCart, adding] = useAddCartItemMutation();

  const validation = useMemo(() => validate(product, config), [product, config]);
  const preview = useMemo(() => previewPrice(product, config), [product, config]);
  const modifierNames = useMemo(
    () =>
      new Map(
        product.modifier_groups.flatMap((group) => group.modifiers.map((m) => [m.id, m.name])),
      ),
    [product],
  );
  const variant = product.variants.find((v) => v.id === config.variantId);
  const showVariants = product.variants.length > 1;
  const errorLines = adding.isError ? cartErrorLines(t, adding.error) : [];
  const canAdd = validation.valid && access !== 'checking' && access !== 'staff';

  const onAdd = async () => {
    if (access === 'guest') {
      // The Mini App has no site login (DEC-152 п. 1): its session screens
      // handle a missing session; never navigate to /login from there.
      if (miniApp) {
        return;
      }
      const returnTo = `${location.pathname}${location.search}`;
      void navigate(`/login?returnTo=${encodeURIComponent(returnTo)}`);
      return;
    }
    if (!validation.valid || !config.variantId) {
      return;
    }
    try {
      await addToCart({
        product_id: product.id,
        variant_id: config.variantId,
        quantity,
        modifiers: Object.entries(config.modifiers).map(([id, count]) => ({ id, quantity: count })),
        special_instructions: instructions.trim() || null,
      }).unwrap();
      setQuantity(1);
      setInstructions('');
    } catch {
      // Shown from the mutation state below.
    }
  };

  return (
    <div className="flex flex-col gap-8">
      {!product.is_available && (
        <p role="status" className="rounded-xl bg-danger-50 px-4 py-3 font-medium text-danger-700">
          {t('product.productUnavailable')}
        </p>
      )}

      {showVariants && (
        <VariantPicker
          variants={product.variants}
          selected={config.variantId}
          onSelect={(variantId) => setConfig((current) => selectVariant(current, variantId))}
        />
      )}

      {product.modifier_groups.map((group) => (
        <ModifierGroupField
          key={group.id}
          group={group}
          config={config}
          problem={validation.problems[group.id] ?? null}
          showProblem
          onChooseSingle={(modifierId) =>
            setConfig((current) => chooseSingle(current, group, modifierId))
          }
          onToggle={(modifier) => setConfig((current) => toggleMultiple(current, group, modifier))}
          onQuantity={(modifier, quantity) =>
            setConfig((current) => setModifierQuantity(current, modifier, quantity))
          }
        />
      ))}

      <div className="flex flex-col gap-2">
        <label htmlFor={instructionsId} className="font-semibold">
          {t('product.instructions')}
        </label>
        <textarea
          id={instructionsId}
          rows={2}
          maxLength={MAX_INSTRUCTIONS_LENGTH}
          value={instructions}
          onChange={(event) => setInstructions(event.target.value)}
          placeholder={t('product.instructionsPlaceholder')}
          className="rounded-xl border border-border bg-surface px-3 py-2"
        />
        <p className="text-xs text-ink-600">
          {t('product.instructionsHint', { max: MAX_INSTRUCTIONS_LENGTH })}
        </p>
      </div>

      <section
        aria-label={t('product.summary')}
        // In the Mini App the pinned summary sits above the bottom tab bar and
        // the safe area instead of under them; the site keeps bottom-0.
        style={miniApp ? { bottom: ABOVE_NAV_BOTTOM } : undefined}
        className="sticky bottom-0 -mx-4 border-t border-border bg-surface/95 px-4 py-4 backdrop-blur sm:static sm:mx-0 sm:rounded-card sm:border sm:shadow-[var(--shadow-card)]"
      >
        {preview && (
          <details className="mb-3 text-sm text-ink-600">
            <summary className="cursor-pointer select-none">{t('product.breakdown')}</summary>
            <ul className="mt-2 space-y-1">
              <li className="flex justify-between gap-4">
                <span>{showVariants && variant ? variant.name : t('product.base')}</span>
                <Price tyiyn={preview.variantTyiyn} />
              </li>
              {preview.lines.map((line) => (
                <li key={line.modifierId} className="flex justify-between gap-4">
                  <span>
                    {modifierNames.get(line.modifierId)}
                    {line.quantity > 1 && ` × ${line.quantity}`}
                  </span>
                  <Price tyiyn={line.unitTyiyn * line.quantity} />
                </li>
              ))}
            </ul>
          </details>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm text-ink-600">{t('product.total')}</p>
            <p
              className="text-2xl font-bold text-ink-900"
              aria-live="polite"
              data-testid="preview-total"
            >
              {preview ? <Price tyiyn={preview.totalTyiyn * quantity} /> : '—'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Stepper
              label={t('product.quantity')}
              value={quantity}
              max={MAX_LINE_QUANTITY}
              onChange={setQuantity}
              disabled={adding.isLoading}
            />
            <button
              type="button"
              disabled={!canAdd || adding.isLoading}
              aria-describedby="cart-note"
              onClick={() => void onAdd()}
              className="min-h-12 rounded-full bg-accent-700 px-6 font-semibold text-on-accent hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
            >
              {adding.isLoading ? t('product.adding') : t('product.addToCart')}
            </button>
          </div>
        </div>
        {adding.isSuccess && !adding.isLoading && (
          <p role="status" className="mt-2 text-sm font-medium text-success-700">
            {t('product.added')}{' '}
            <Link to="/cart" className="underline">
              {t('product.goToCart')}
            </Link>
          </p>
        )}
        {errorLines.length > 0 && (
          <div role="alert" className="mt-2 text-sm text-danger-700">
            {errorLines.map((line) => (
              <p key={line}>{line}</p>
            ))}
          </div>
        )}
        {access === 'staff' && (
          <p role="status" className="mt-2 text-sm font-medium text-ink-600">
            {t('cart.staffOnly')}
          </p>
        )}
        {!validation.valid && product.is_available && (
          <p role="status" className="mt-2 text-sm font-medium text-danger-700">
            {t('product.completeChoice')}
          </p>
        )}
        <p id="cart-note" className="mt-2 text-xs text-ink-600">
          {access === 'guest' ? t('product.loginToAdd') : t('product.priceNote')}
        </p>
      </section>
    </div>
  );
}
