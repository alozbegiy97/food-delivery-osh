import type { ModifierGroupOut, ModifierOut, ProductDetail } from '../../shared/types/api';
import { toTyiyn } from './money';

/**
 * Product configuration on the client (UI_UX_GUIDELINES §3 "Product detail").
 *
 * Rules come from the API data and the approved decisions only:
 * - modifier price for a variant: the `variant_prices` override if present,
 *   otherwise `price_delta` (DATABASE_SCHEMA.md §5.6);
 * - per-modifier quantity 1..max_quantity; min/max selections count distinct
 *   modifiers; required groups must be filled; `single` allows one option
 *   (DEC-81, §5.7). Dough is a required `single` group (DEC-128).
 *
 * The total is a PREVIEW for display only: the cart and order totals are
 * always calculated by the backend (DEC-08).
 */

export interface Configuration {
  variantId: string | null;
  // modifier id -> quantity (>= 1); absent means not selected
  modifiers: Record<string, number>;
}

export function modifierUnitPrice(modifier: ModifierOut, variantId: string | null): string {
  const override = modifier.variant_prices.find((price) => price.variant_id === variantId);
  return override ? override.price_delta : modifier.price_delta;
}

function selectedIn(group: ModifierGroupOut, config: Configuration): ModifierOut[] {
  return group.modifiers.filter((modifier) => (config.modifiers[modifier.id] ?? 0) > 0);
}

/** First available variant; required single groups get their first available option. */
export function initialConfiguration(product: ProductDetail): Configuration {
  const variant = product.variants.find((v) => v.is_available) ?? null;
  const modifiers: Record<string, number> = {};
  for (const group of product.modifier_groups) {
    if (group.selection_type === 'single' && group.is_required) {
      const first = group.modifiers.find((m) => m.is_available);
      if (first) {
        modifiers[first.id] = 1;
      }
    }
  }
  return { variantId: variant?.id ?? null, modifiers };
}

export function selectVariant(config: Configuration, variantId: string): Configuration {
  return { ...config, variantId };
}

/** Radio choice in a single group; `null` clears an optional group. */
export function chooseSingle(
  config: Configuration,
  group: ModifierGroupOut,
  modifierId: string | null,
): Configuration {
  const modifiers = { ...config.modifiers };
  for (const modifier of group.modifiers) {
    delete modifiers[modifier.id];
  }
  if (modifierId !== null) {
    modifiers[modifierId] = 1;
  }
  return { ...config, modifiers };
}

export function canAddMore(group: ModifierGroupOut, config: Configuration): boolean {
  return group.max_selections === null || selectedIn(group, config).length < group.max_selections;
}

/** Checkbox in a multiple group; refuses to exceed max_selections. */
export function toggleMultiple(
  config: Configuration,
  group: ModifierGroupOut,
  modifier: ModifierOut,
): Configuration {
  const modifiers = { ...config.modifiers };
  if (modifiers[modifier.id]) {
    delete modifiers[modifier.id];
  } else if (modifier.is_available && canAddMore(group, config)) {
    modifiers[modifier.id] = 1;
  }
  return { ...config, modifiers };
}

export function setModifierQuantity(
  config: Configuration,
  modifier: ModifierOut,
  quantity: number,
): Configuration {
  if (!config.modifiers[modifier.id]) {
    return config;
  }
  const clamped = Math.min(Math.max(quantity, 1), modifier.max_quantity);
  return { ...config, modifiers: { ...config.modifiers, [modifier.id]: clamped } };
}

export type GroupProblem = 'required' | 'tooFew' | 'tooMany' | 'unavailable';

export function groupProblem(group: ModifierGroupOut, config: Configuration): GroupProblem | null {
  const selected = selectedIn(group, config);
  if (selected.some((modifier) => !modifier.is_available)) {
    return 'unavailable';
  }
  if (group.is_required && selected.length === 0) {
    return 'required';
  }
  if (selected.length < group.min_selections) {
    return 'tooFew';
  }
  if (group.max_selections !== null && selected.length > group.max_selections) {
    return 'tooMany';
  }
  return null;
}

export interface Validation {
  valid: boolean;
  variantMissing: boolean;
  problems: Record<string, GroupProblem>;
}

export function validate(product: ProductDetail, config: Configuration): Validation {
  const variant = product.variants.find((v) => v.id === config.variantId);
  const problems: Record<string, GroupProblem> = {};
  for (const group of product.modifier_groups) {
    const problem = groupProblem(group, config);
    if (problem) {
      problems[group.id] = problem;
    }
  }
  const variantMissing = !variant || !variant.is_available;
  return {
    valid: product.is_available && !variantMissing && Object.keys(problems).length === 0,
    variantMissing,
    problems,
  };
}

export interface PriceLine {
  modifierId: string;
  quantity: number;
  unitTyiyn: number;
}

export interface PricePreview {
  variantTyiyn: number;
  lines: PriceLine[];
  totalTyiyn: number;
}

/** Preview price of one item; null when no variant is chosen. */
export function previewPrice(product: ProductDetail, config: Configuration): PricePreview | null {
  const variant = product.variants.find((v) => v.id === config.variantId);
  if (!variant) {
    return null;
  }
  const lines: PriceLine[] = [];
  for (const group of product.modifier_groups) {
    for (const modifier of group.modifiers) {
      const quantity = config.modifiers[modifier.id] ?? 0;
      if (quantity > 0) {
        lines.push({
          modifierId: modifier.id,
          quantity,
          unitTyiyn: toTyiyn(modifierUnitPrice(modifier, variant.id)),
        });
      }
    }
  }
  const variantTyiyn = toTyiyn(variant.price);
  const totalTyiyn = lines.reduce(
    (sum, line) => sum + line.unitTyiyn * line.quantity,
    variantTyiyn,
  );
  return { variantTyiyn, lines, totalTyiyn };
}
