import { describe, expect, it } from 'vitest';

import { formatPhoneInput, isCompletePhone } from './phone';

describe('phone mask', () => {
  it.each([
    ['+996 700 12 34 56', '+996 700 12 34 56'],
    ['996700123456', '+996 700 12 34 56'],
    ['0700123456', '+996 700 12 34 56'],
    ['700123456', '+996 700 12 34 56'],
    ['7001', '+996 700 1'],
    ['+996 (700) 12-34-56 99', '+996 700 12 34 56'],
    ['', ''],
    ['abc', ''],
  ])('%s -> %s', (raw, expected) => {
    expect(formatPhoneInput(raw)).toBe(expected);
  });

  it('knows when the number is complete', () => {
    expect(isCompletePhone('+996 700 12 34 56')).toBe(true);
    expect(isCompletePhone('+996 700 12')).toBe(false);
  });
});
