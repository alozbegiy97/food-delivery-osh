import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';

import type { ModifierGroupOut, ModifierOut, VariantOut } from '../../../shared/types/api';
import {
  canAddMore,
  modifierUnitPrice,
  type Configuration,
  type GroupProblem,
} from '../configurator';
import { toTyiyn } from '../money';
import { Price } from './Price';

const OPTION =
  'flex min-h-12 cursor-pointer items-center gap-3 rounded-xl border px-4 py-3 transition has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent-700';
const OPTION_ON = 'border-accent-700 bg-accent-50 ring-1 ring-accent-700';
const OPTION_OFF = 'border-border bg-surface hover:border-accent-600';
const OPTION_DISABLED = 'cursor-not-allowed border-border bg-cream-100 text-ink-600';

interface VariantPickerProps {
  variants: VariantOut[];
  selected: string | null;
  onSelect: (variantId: string) => void;
}

/** Size / variant choice; hidden by the caller when there is only one. */
export function VariantPicker({ variants, selected, onSelect }: VariantPickerProps) {
  const { t } = useTranslation();
  return (
    <fieldset>
      <legend className="mb-3 text-lg font-semibold">{t('product.size')}</legend>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {variants.map((variant) => {
          const active = variant.id === selected;
          return (
            <label
              key={variant.id}
              className={`${OPTION} flex-col !items-start !gap-1 ${
                !variant.is_available ? OPTION_DISABLED : active ? OPTION_ON : OPTION_OFF
              }`}
            >
              <input
                type="radio"
                name="variant"
                value={variant.id}
                checked={active}
                disabled={!variant.is_available}
                onChange={() => onSelect(variant.id)}
                className="sr-only"
              />
              <span className="font-semibold">{variant.name}</span>
              {variant.is_available ? (
                <Price amount={variant.price} className="text-sm text-ink-600" />
              ) : (
                <span className="text-sm">{t('product.optionUnavailable')}</span>
              )}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function ruleText(group: ModifierGroupOut, t: TFunction): string {
  if (group.selection_type === 'single') {
    return t('product.rules.chooseOne');
  }
  const { min_selections: min, max_selections: max } = group;
  if (max !== null && min > 0) {
    return t('product.rules.range', { min, max });
  }
  if (max !== null) {
    return t('product.rules.upTo', { count: max });
  }
  return min > 0 ? t('product.rules.atLeast', { count: min }) : t('product.rules.any');
}

interface StepperProps {
  label: string;
  value: number;
  max: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}

/** −/+ quantity control (1..max); also used by the cart. */
export function Stepper({ label, value, max, onChange, disabled = false }: StepperProps) {
  const { t } = useTranslation();
  const button =
    'flex h-9 w-9 items-center justify-center rounded-full bg-surface text-lg font-bold ring-1 ring-border hover:bg-cream-100 disabled:opacity-40';
  return (
    <div role="group" aria-label={label} className="flex items-center gap-2">
      <button
        type="button"
        className={button}
        aria-label={t('product.decrease')}
        disabled={disabled || value <= 1}
        onClick={() => onChange(value - 1)}
      >
        −
      </button>
      <span aria-live="polite" className="w-6 text-center font-semibold">
        {value}
      </span>
      <button
        type="button"
        className={button}
        aria-label={t('product.increase')}
        disabled={disabled || value >= max}
        onClick={() => onChange(value + 1)}
      >
        +
      </button>
    </div>
  );
}

interface ModifierGroupFieldProps {
  group: ModifierGroupOut;
  config: Configuration;
  problem: GroupProblem | null;
  showProblem: boolean;
  onChooseSingle: (modifierId: string | null) => void;
  onToggle: (modifier: ModifierOut) => void;
  onQuantity: (modifier: ModifierOut, quantity: number) => void;
}

export function ModifierGroupField({
  group,
  config,
  problem,
  showProblem,
  onChooseSingle,
  onToggle,
  onQuantity,
}: ModifierGroupFieldProps) {
  const { t } = useTranslation();
  const single = group.selection_type === 'single';
  const selectedCount = group.modifiers.filter((m) => config.modifiers[m.id]).length;
  const limitReached = !single && !canAddMore(group, config);
  const errorId = `group-${group.id}-error`;

  return (
    <fieldset aria-describedby={showProblem && problem ? errorId : undefined}>
      <legend className="flex w-full flex-wrap items-baseline justify-between gap-2">
        <span className="text-lg font-semibold">{group.name}</span>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
            group.is_required ? 'bg-accent-100 text-accent-800' : 'bg-cream-100 text-ink-600'
          }`}
        >
          {group.is_required ? t('product.required') : t('product.optional')}
        </span>
      </legend>
      <p className="mb-3 mt-1 text-sm text-ink-600">
        {ruleText(group, t)}
        {!single && group.max_selections !== null && (
          <> · {t('product.selectedOf', { count: selectedCount, max: group.max_selections })}</>
        )}
      </p>

      <div className="flex flex-col gap-2">
        {single && !group.is_required && (
          <label className={`${OPTION} ${selectedCount === 0 ? OPTION_ON : OPTION_OFF}`}>
            <input
              type="radio"
              name={`group-${group.id}`}
              checked={selectedCount === 0}
              onChange={() => onChooseSingle(null)}
              className="h-4 w-4 accent-accent-700"
            />
            <span className="flex-1">{t('product.noChoice')}</span>
          </label>
        )}
        {group.modifiers.map((modifier) => {
          const quantity = config.modifiers[modifier.id] ?? 0;
          const checked = quantity > 0;
          const blocked = !modifier.is_available || (!single && !checked && limitReached);
          const unit = toTyiyn(modifierUnitPrice(modifier, config.variantId));
          return (
            // flex-wrap: on narrow screens the stepper moves to its own line
            // (right-aligned) instead of pushing the row wider than the page.
            <div
              key={modifier.id}
              className={`${OPTION} flex-wrap justify-end ${
                !modifier.is_available
                  ? OPTION_DISABLED
                  : checked
                    ? OPTION_ON
                    : blocked
                      ? OPTION_DISABLED
                      : OPTION_OFF
              }`}
            >
              <label className="flex min-w-0 flex-auto cursor-[inherit] items-center gap-3">
                <input
                  type={single ? 'radio' : 'checkbox'}
                  name={`group-${group.id}`}
                  checked={checked}
                  disabled={blocked && !checked}
                  onChange={() => (single ? onChooseSingle(modifier.id) : onToggle(modifier))}
                  className="h-4 w-4 accent-accent-700"
                />
                <span className="min-w-0 flex-1 break-words">
                  <span className="font-medium">{modifier.name}</span>
                  {!modifier.is_available && (
                    <span className="ml-2 text-xs">({t('product.optionUnavailable')})</span>
                  )}
                </span>
                <span className="text-sm font-semibold text-ink-600">
                  {unit > 0 ? (
                    <>
                      +<Price tyiyn={unit} />
                    </>
                  ) : (
                    t('product.free')
                  )}
                </span>
              </label>
              {checked && modifier.max_quantity > 1 && (
                <Stepper
                  label={t('product.quantityOf', { name: modifier.name })}
                  value={quantity}
                  max={modifier.max_quantity}
                  onChange={(value) => onQuantity(modifier, value)}
                />
              )}
            </div>
          );
        })}
      </div>

      {limitReached && <p className="mt-2 text-sm text-ink-600">{t('product.limitReached')}</p>}
      {showProblem && problem && (
        <p id={errorId} role="alert" className="mt-2 text-sm font-medium text-danger-700">
          {t(`product.problems.${problem}`, { group: group.name })}
        </p>
      )}
    </fieldset>
  );
}
