import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { OvenMark } from './OvenMark';

// MA-4.6-A1: brand mark of the "Печь" direction (DEC-161 rev. 47).
describe('OvenMark', () => {
  it('is decorative and coloured only through design tokens', () => {
    const { container } = render(<OvenMark className="h-9 w-8" />);
    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute('aria-hidden')).toBe('true');
    expect(svg?.getAttribute('focusable')).toBe('false');
    expect(svg?.getAttribute('class')).toBe('h-9 w-8');
    expect(svg?.textContent).toBe('');
    const paths = [...container.querySelectorAll('path')];
    expect(paths.map((path) => path.getAttribute('class'))).toEqual([
      'fill-scrim',
      'fill-accent-600',
      'fill-accent-100',
    ]);
    for (const el of container.querySelectorAll('*')) {
      expect(el.getAttribute('fill'), el.tagName).toBeNull();
      expect(el.getAttribute('style'), el.tagName).toBeNull();
    }
  });
});
