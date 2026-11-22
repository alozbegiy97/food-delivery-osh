import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DishArt } from './DishArt';
import { type DishArtKind, dishArtKind } from './dishArtKind';

// MA-4.6-A1: dish drawings of the "Печь" direction (DEC-161 rev. 47). The
// source file is read from disk (Vitest runs from the frontend root; the app
// tsconfig has no Node types, hence the dynamic import).
type Fs = { readFileSync(path: string, encoding: 'utf8'): string };
const fsModule = 'node:fs';
const { readFileSync } = (await import(/* @vite-ignore */ fsModule)) as Fs;
const source = readFileSync('src/features/catalog/components/DishArt.tsx', 'utf8');

const KINDS: DishArtKind[] = ['pizza', 'burger', 'wrap'];

function svgOf(container: HTMLElement): SVGSVGElement {
  const svg = container.querySelector('svg');
  if (!svg) {
    throw new Error('no <svg> rendered');
  }
  return svg;
}

/** The id prefix of one drawing (`dish…`), taken from its first id. */
function prefixOf(svg: SVGSVGElement): string {
  const first = svg.querySelector('[id]')?.getAttribute('id') ?? '';
  return first.slice(0, first.indexOf('-'));
}

/** Markup with the per-instance id prefix replaced, to compare drawings. */
function normalized(svg: SVGSVGElement): string {
  return svg.outerHTML.split(prefixOf(svg)).join('ID');
}

function layers(svg: SVGSVGElement): string[] {
  return [...svg.querySelectorAll('[data-layer]')].map((el) => el.getAttribute('data-layer') ?? '');
}

describe('dishArtKind: drawing by category slug', () => {
  it.each([
    ['pizza', 'pizza'],
    ['burgers', 'burger'],
    ['shawarma', 'wrap'],
  ])('%s -> %s', (slug, kind) => {
    expect(dishArtKind(slug)).toBe(kind);
  });

  it.each([
    'national',
    'salads',
    'soups',
    'desserts',
    'drinks',
    'Pizza',
    '',
    'toString',
    '__proto__',
  ])('%s -> null (the old motif stays)', (slug) => {
    expect(dishArtKind(slug)).toBeNull();
  });

  it('null and undefined -> null', () => {
    expect(dishArtKind(null)).toBeNull();
    expect(dishArtKind(undefined)).toBeNull();
  });
});

describe('DishArt: a decorative drawing', () => {
  it.each(KINDS)('%s is hidden from assistive technology and has no text', (kind) => {
    const { container } = render(<DishArt kind={kind} className="h-full w-full" />);
    const svg = svgOf(container);
    expect(svg.getAttribute('aria-hidden')).toBe('true');
    expect(svg.getAttribute('focusable')).toBe('false');
    expect(svg.getAttribute('viewBox')).toBe('0 0 200 200');
    expect(svg.getAttribute('data-dish-art')).toBe(kind);
    expect(svg.getAttribute('class')).toBe('h-full w-full');
    expect(svg.querySelector('title, desc, text')).toBeNull();
    expect(svg.textContent).toBe('');
  });

  it.each(KINDS)('%s loads nothing: no images, links, scripts or URLs', (kind) => {
    const { container } = render(<DishArt kind={kind} />);
    const svg = svgOf(container);
    expect(svg.querySelector('image, use, a, script, foreignObject, style')).toBeNull();
    for (const el of svg.querySelectorAll('*')) {
      for (const attr of el.attributes) {
        expect(attr.value, `${el.tagName} ${attr.name}`).not.toMatch(/https?:|data:|javascript:/i);
        if (attr.value.includes('url(')) {
          expect(attr.value, `${el.tagName} ${attr.name}`).toMatch(/^url\(#[A-Za-z0-9-]+\)$/);
        }
      }
    }
  });

  it.each(KINDS)('%s: every url(#…) points to an element of the same drawing', (kind) => {
    const { container } = render(<DishArt kind={kind} />);
    const svg = svgOf(container);
    const ids = new Set([...svg.querySelectorAll('[id]')].map((el) => el.id));
    const refs = [...svg.querySelectorAll('*')].flatMap((el) =>
      [...el.attributes].flatMap((attr) =>
        [...attr.value.matchAll(/url\(#([^)]+)\)/g)].map((m) => m[1]),
      ),
    );
    expect(refs.length).toBeGreaterThan(0);
    for (const ref of refs) {
      expect(ids.has(ref), ref).toBe(true);
    }
  });

  it('pizza is the neutral drawing: crust, sauce, cheese, mozzarella, basil; no pepperoni', () => {
    const { container } = render(<DishArt kind="pizza" />);
    const svg = svgOf(container);
    expect(layers(svg)).toEqual(['crust', 'sauce', 'cheese', 'mozzarella', 'basil', 'light']);
    expect(svg.querySelectorAll('[data-layer="mozzarella"] circle').length).toBeGreaterThanOrEqual(
      4,
    );
    expect(svg.querySelectorAll('[data-layer="basil"] > g').length).toBeGreaterThanOrEqual(5);
    expect(svg.outerHTML.toLowerCase()).not.toContain('pepperoni');
    expect(source.toLowerCase()).not.toContain('pepperoni');
  });

  it('burger and wrap have their own layers', () => {
    const burger = svgOf(render(<DishArt kind="burger" />).container);
    expect(layers(burger)).toEqual(['lettuce', 'cheddar', 'bun', 'light']);
    expect(burger.querySelectorAll('[data-layer="bun"] ellipse').length).toBeGreaterThan(30);
    const wrap = svgOf(render(<DishArt kind="wrap" />).container);
    expect(layers(wrap)).toEqual(['lavash', 'paper', 'filling', 'light']);
  });

  it('several drawings on one page never share an id', () => {
    const { container } = render(
      <>
        <DishArt kind="pizza" />
        <DishArt kind="pizza" />
        <DishArt kind="burger" />
        <DishArt kind="wrap" />
      </>,
    );
    const ids = [...container.querySelectorAll('[id]')].map((el) => el.id);
    expect(ids.length).toBeGreaterThan(10);
    expect(new Set(ids).size).toBe(ids.length);
    const [first, second] = container.querySelectorAll('svg');
    expect(prefixOf(first)).not.toBe(prefixOf(second));
    // Same picture, only the ids differ.
    expect(normalized(first)).toBe(normalized(second));
  });

  it.each(KINDS)('%s draws exactly the same picture on every render', (kind) => {
    const first = render(<DishArt kind={kind} />);
    const before = normalized(svgOf(first.container));
    first.unmount();
    const again = normalized(svgOf(render(<DishArt kind={kind} />).container));
    expect(again).toBe(before);
  });

  it.each(KINDS)('%s lite: the same layers without the expensive filters', (kind) => {
    const full = svgOf(render(<DishArt kind={kind} />).container);
    const lite = svgOf(render(<DishArt lite kind={kind} />).container);
    expect(layers(lite)).toEqual(layers(full));
    expect(lite.querySelectorAll('filter, feTurbulence')).toHaveLength(0);
    expect(lite.querySelector('[filter]')).toBeNull();
    // Every remaining url(#…) still resolves inside the drawing.
    const ids = new Set([...lite.querySelectorAll('[id]')].map((el) => el.id));
    for (const el of lite.querySelectorAll('[fill^="url("], [clip-path]')) {
      const ref = /url\(#([^)]+)\)/.exec(
        el.getAttribute('fill') ?? el.getAttribute('clip-path') ?? '',
      )?.[1];
      expect(ids.has(ref ?? ''), ref).toBe(true);
    }
  });

  it('full drawings keep their filters (the home page oven)', () => {
    const svg = svgOf(render(<DishArt kind="pizza" />).container);
    expect(svg.querySelectorAll('filter')).toHaveLength(2);
    expect(svg.querySelectorAll('[filter]').length).toBeGreaterThan(3);
  });

  it('the source uses plain JSX: no innerHTML and no external resources', () => {
    // Code only: the header comment itself says "no innerHTML".
    const code = source.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, '');
    expect(code.length).toBeGreaterThan(1000);
    expect(code).not.toMatch(/innerHTML|dangerouslySetInnerHTML/);
    expect(code).not.toMatch(/https?:/);
    expect(code).not.toMatch(
      /<image\b|\bimport\s+\w+\s+from\s+['"][^'"]+\.(png|jpe?g|webp|svg)['"]/,
    );
  });
});
