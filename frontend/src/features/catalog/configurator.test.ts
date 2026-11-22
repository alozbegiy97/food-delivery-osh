import { describe, expect, it } from 'vitest';

import { MARGHERITA, SHAWARMA } from '../../test/catalogFixtures';
import {
  chooseSingle,
  initialConfiguration,
  modifierUnitPrice,
  previewPrice,
  selectVariant,
  setModifierQuantity,
  toggleMultiple,
  validate,
} from './configurator';
import { formatTyiyn, toTyiyn } from './money';

const [dough, extras] = MARGHERITA.modifier_groups;
const [cheese, mushrooms, jalapeno, olives] = extras.modifiers;

describe('money', () => {
  it('converts API decimal strings to tyiyn without float errors', () => {
    expect(toTyiyn('550.00')).toBe(55000);
    expect(toTyiyn('0.10') + toTyiyn('0.20')).toBe(30);
    expect(toTyiyn('7.5')).toBe(750);
    expect(() => toTyiyn('abc')).toThrow();
  });

  it('formats amounts per locale', () => {
    expect(formatTyiyn(125000, 'ru-RU').replace(/\s/g, ' ')).toBe('1 250');
    expect(formatTyiyn(125050, 'ru-RU').replace(/\s/g, ' ')).toBe('1 250,50');
  });
});

describe('configurator', () => {
  it('starts with the first available size and a required dough (DEC-128)', () => {
    const config = initialConfiguration(MARGHERITA);
    expect(config.variantId).toBe('v-30');
    expect(config.modifiers).toEqual({ 'm-thin': 1 });
    expect(validate(MARGHERITA, config).valid).toBe(true);
  });

  it('uses the per-size extra price when it exists (DATABASE_SCHEMA §5.6)', () => {
    expect(modifierUnitPrice(cheese, 'v-30')).toBe('60.00');
    expect(modifierUnitPrice(cheese, 'v-40')).toBe('80.00');
  });

  it('previews size + extras × quantity', () => {
    let config = initialConfiguration(MARGHERITA);
    config = toggleMultiple(config, extras, cheese);
    config = setModifierQuantity(config, cheese, 2);
    config = toggleMultiple(config, extras, mushrooms);
    expect(previewPrice(MARGHERITA, config)?.totalTyiyn).toBe(55000 + 2 * 6000 + 5000);

    config = selectVariant(config, 'v-40');
    expect(previewPrice(MARGHERITA, config)?.totalTyiyn).toBe(75000 + 2 * 8000 + 7000);
  });

  it('clamps quantity to 1..max_quantity', () => {
    let config = toggleMultiple(initialConfiguration(MARGHERITA), extras, cheese);
    config = setModifierQuantity(config, cheese, 5);
    expect(config.modifiers['m-cheese']).toBe(2);
    config = setModifierQuantity(config, cheese, 0);
    expect(config.modifiers['m-cheese']).toBe(1);
    // Quantity of an unselected modifier is ignored.
    expect(setModifierQuantity(config, mushrooms, 2).modifiers['m-mushrooms']).toBeUndefined();
  });

  it('never exceeds max_selections of distinct extras (DEC-81)', () => {
    let config = initialConfiguration(MARGHERITA);
    for (const modifier of [cheese, mushrooms, jalapeno]) {
      config = toggleMultiple(config, extras, modifier);
    }
    expect(Object.keys(config.modifiers)).toHaveLength(4); // dough + 3 extras
    const extra = { ...olives, id: 'm-extra', is_available: true };
    const group = { ...extras, modifiers: [...extras.modifiers, extra] };
    expect(toggleMultiple(config, group, extra).modifiers['m-extra']).toBeUndefined();
    // Unchecking frees a slot.
    config = toggleMultiple(config, extras, cheese);
    expect(toggleMultiple(config, group, extra).modifiers['m-extra']).toBe(1);
  });

  it('refuses unavailable modifiers', () => {
    const config = toggleMultiple(initialConfiguration(MARGHERITA), extras, olives);
    expect(config.modifiers['m-olives']).toBeUndefined();
  });

  it('reports a missing required dough', () => {
    const config = chooseSingle(initialConfiguration(MARGHERITA), dough, null);
    const result = validate(MARGHERITA, config);
    expect(result.valid).toBe(false);
    expect(result.problems).toEqual({ 'g-dough': 'required' });
  });

  it('allows an optional single group to stay empty and switches choices', () => {
    let config = initialConfiguration(SHAWARMA);
    expect(config.modifiers).toEqual({});
    expect(validate(SHAWARMA, config).valid).toBe(true);
    const [sauce] = SHAWARMA.modifier_groups;
    config = chooseSingle(config, sauce, 'm-garlic');
    config = chooseSingle(config, sauce, 'm-hot');
    expect(config.modifiers).toEqual({ 'm-hot': 1 });
  });

  it('is invalid for an unavailable product or size', () => {
    const soldOut = { ...MARGHERITA, is_available: false };
    expect(validate(soldOut, initialConfiguration(soldOut)).valid).toBe(false);
    const noSizes = {
      ...MARGHERITA,
      variants: MARGHERITA.variants.map((v) => ({ ...v, is_available: false })),
    };
    const config = initialConfiguration(noSizes);
    expect(config.variantId).toBeNull();
    expect(previewPrice(noSizes, config)).toBeNull();
    expect(validate(noSizes, config).variantMissing).toBe(true);
  });
});
