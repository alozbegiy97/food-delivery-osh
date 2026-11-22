import { describe, expect, it } from 'vitest';

import {
  contrastRatio,
  DARK_OVERRIDES,
  MIN_CONTRAST,
  themeVariables,
} from '../features/telegram/theme';

// Regression tests for the design tokens (DEC-161, MA-4.6.1a). Values are
// parsed from the real tokens.css, then checked by value and by contrast.
// The file is read from disk: with `css: false` (vite.config.ts) Vitest does
// not return CSS sources for `?raw`, and the app tsconfig has no Node types.
// Vitest runs from the frontend root (jsdom gives import.meta.url no file URL).
type Fs = {
  readFileSync(path: string, encoding: 'utf8'): string;
  readFileSync(path: string): Uint8Array;
};
type Crypto = {
  createHash(algorithm: 'sha256'): {
    update(data: Uint8Array): { digest(encoding: 'hex'): string };
  };
};
const fsModule = 'node:fs';
const cryptoModule = 'node:crypto';
const { readFileSync } = (await import(/* @vite-ignore */ fsModule)) as Fs;
const { createHash } = (await import(/* @vite-ignore */ cryptoModule)) as Crypto;
const tokensCss = readFileSync('src/styles/tokens.css', 'utf8');
const indexCss = readFileSync('src/styles/index.css', 'utf8');

function parseTokens(css: string): Map<string, string[]> {
  const block = /@theme\s*\{([\s\S]*?)\n\}/.exec(css);
  if (!block) {
    throw new Error('@theme block not found in tokens.css');
  }
  const body = block[1].replace(/\/\*[\s\S]*?\*\//g, '');
  const tokens = new Map<string, string[]>();
  for (const [, name, value] of body.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
    tokens.set(name, [...(tokens.get(name) ?? []), value.trim()]);
  }
  return tokens;
}

const tokens = parseTokens(tokensCss);

function value(name: string): string {
  const values = tokens.get(name);
  if (!values) {
    throw new Error(`${name} is not defined in tokens.css`);
  }
  return values[0];
}

const NEW_TOKENS: Record<string, string> = {
  '--color-accent-strong': '#9a3412',
  '--color-on-accent': '#ffffff',
  '--color-danger-strong': '#b91c1c',
  '--color-success-strong': '#15803d',
  '--color-scrim': '#1f2328',
  '--color-on-scrim': '#ffffff',
};

// Values before MA-4.6 (the admin UI and all screens depend on them).
const EXISTING_TOKENS: Record<string, string> = {
  '--color-cream-50': '#fffaf3',
  '--color-cream-100': '#fbf1e3',
  '--color-surface': '#ffffff',
  '--color-border': '#eadfce',
  '--color-ink-900': '#1f2328',
  '--color-ink-600': '#4b525a',
  '--color-accent-50': '#fff4eb',
  '--color-accent-100': '#ffe4cc',
  '--color-accent-600': '#ea580c',
  '--color-accent-700': '#c2410c',
  '--color-accent-800': '#9a3412',
  '--color-success-50': '#ecfdf3',
  '--color-success-700': '#15803d',
  '--color-warning-700': '#a16207',
  '--color-danger-50': '#fef2f2',
  '--color-danger-700': '#b91c1c',
  '--radius-card': '1rem',
  '--shadow-card': '0 1px 2px rgb(31 35 40 / 0.06), 0 8px 24px -12px rgb(31 35 40 / 0.18)',
  '--font-sans':
    "'Inter', 'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif",
};

// Telegram themes: a typical dark one and a light one.
const DARK_THEME = {
  bg_color: '#212121',
  text_color: '#ffffff',
  hint_color: '#aaaaaa',
  secondary_bg_color: '#181818',
  section_bg_color: '#2c2c2c',
  section_separator_color: '#3a3a3a',
};
const LIGHT_THEME = {
  bg_color: '#ffffff',
  text_color: '#000000',
  hint_color: '#707579',
  secondary_bg_color: '#f4f4f5',
  section_bg_color: '#ffffff',
  section_separator_color: '#e7e7e7',
};

describe('design tokens (tokens.css)', () => {
  it('reads the real tokens.css', () => {
    expect(tokensCss.length).toBeGreaterThan(0);
    expect(tokens.size).toBeGreaterThanOrEqual(
      Object.keys(EXISTING_TOKENS).length + Object.keys(NEW_TOKENS).length,
    );
  });

  it('defines every token exactly once', () => {
    for (const [name, values] of tokens) {
      expect(values, name).toHaveLength(1);
    }
  });

  it.each(Object.entries(NEW_TOKENS))('defines %s as %s', (name, expected) => {
    expect(value(name)).toBe(expected);
  });

  it.each(Object.entries(EXISTING_TOKENS))('keeps %s unchanged', (name, expected) => {
    expect(value(name)).toBe(expected);
  });

  it.each([
    ['--color-on-accent', '--color-accent-strong'],
    ['--color-on-accent', '--color-danger-strong'],
    ['--color-on-accent', '--color-success-strong'],
    ['--color-on-scrim', '--color-scrim'],
  ])('%s on %s reaches WCAG AA (4.5:1)', (text, background) => {
    expect(MIN_CONTRAST).toBe(4.5);
    expect(contrastRatio(value(text), value(background))).toBeGreaterThanOrEqual(4.5);
  });
});

describe('fixed tokens and the Telegram theme (theme.ts)', () => {
  const fixed = Object.keys(NEW_TOKENS);

  it('the theme mapping really applies a dark and a light theme', () => {
    const dark = themeVariables(DARK_THEME);
    expect(dark['--color-cream-50']).toBe(DARK_THEME.bg_color);
    expect(dark['--color-accent-800']).toBe(DARK_OVERRIDES['--color-accent-800']);
    const light = themeVariables(LIGHT_THEME);
    expect(light['--color-cream-50']).toBe(LIGHT_THEME.bg_color);
    expect(light).not.toHaveProperty('--color-accent-800');
  });

  it.each(fixed)('%s is not overridden in dark or light Telegram themes', (name) => {
    expect(DARK_OVERRIDES).not.toHaveProperty(name);
    expect(themeVariables(DARK_THEME)).not.toHaveProperty(name);
    expect(themeVariables(LIGHT_THEME)).not.toHaveProperty(name);
  });
});

// MA-4.6-A1: dish image backdrop of the "Печь" direction (DEC-161 rev. 47).
// Decorative (no text on it): checked for presence, the light direction of
// the gradient and its behaviour in the Telegram themes.
describe('plate tokens (DEC-161 rev. 47)', () => {
  const PLATE: Record<string, string> = {
    '--color-plate': '#2a2f35',
    '--color-plate-hi': '#3a4048',
  };
  const DARK_PLATE: Record<string, string> = {
    '--color-plate': '#0f1720',
    '--color-plate-hi': '#1f2b38',
  };
  // Brightness compared through the contrast with black (monotonic in luminance).
  const lighter = (a: string, b: string) =>
    contrastRatio(a, '#000000') > contrastRatio(b, '#000000');
  const effective = (vars: Record<string, string>, name: string) => vars[name] ?? value(name);

  it.each(Object.entries(PLATE))('defines %s as %s', (name, expected) => {
    expect(value(name)).toBe(expected);
  });

  it('the dark Telegram theme replaces both, the light theme keeps the site values', () => {
    const dark = themeVariables(DARK_THEME);
    const light = themeVariables(LIGHT_THEME);
    for (const [name, expected] of Object.entries(DARK_PLATE)) {
      expect(DARK_OVERRIDES[name], name).toBe(expected);
      expect(dark[name], name).toBe(expected);
      expect(light, name).not.toHaveProperty(name);
    }
  });

  it.each([
    ['site', {}],
    ['light', LIGHT_THEME],
    ['dark', DARK_THEME],
  ])('%s: plate-hi is the lit centre, lighter than plate', (_, params) => {
    const vars = themeVariables(params);
    expect(lighter(effective(vars, '--color-plate-hi'), effective(vars, '--color-plate'))).toBe(
      true,
    );
  });

  it('on the site and in the light theme the plate clearly stands out from the page', () => {
    for (const params of [{}, LIGHT_THEME]) {
      const vars = themeVariables(params);
      expect(
        contrastRatio(effective(vars, '--color-plate'), effective(vars, '--color-cream-50')),
      ).toBeGreaterThanOrEqual(3);
    }
  });

  it('in the dark theme the plate sinks below the background instead of turning grey', () => {
    const vars = themeVariables(DARK_THEME);
    expect(lighter(DARK_THEME.bg_color, effective(vars, '--color-plate'))).toBe(true);
    expect(lighter(value('--color-plate'), DARK_THEME.bg_color)).toBe(true); // the site value would not
  });
});

// MA-4.6.1b: buttons and badges with white text use the fixed tokens. The
// effective value of a token is the Telegram override if any, else tokens.css.
describe('white-text backgrounds under the Telegram themes (MA-4.6.1b)', () => {
  const THEMES = { site: {}, light: LIGHT_THEME, dark: DARK_THEME };
  const effective = (vars: Record<string, string>, name: string) => vars[name] ?? value(name);

  it.each(Object.entries(THEMES))(
    '%s: fixed tokens keep the brand value of the replaced shade',
    (_, params) => {
      const vars = themeVariables(params);
      expect(effective(vars, '--color-accent-strong')).toBe(value('--color-accent-800'));
      expect(effective(vars, '--color-danger-strong')).toBe(value('--color-danger-700'));
      expect(effective(vars, '--color-success-strong')).toBe(value('--color-success-700'));
      expect(effective(vars, '--color-scrim')).toBe(value('--color-ink-900'));
    },
  );

  it('the old shades lose white-text contrast in the dark theme', () => {
    const vars = themeVariables(DARK_THEME);
    for (const name of ['--color-accent-800', '--color-danger-700', '--color-success-700']) {
      expect(contrastRatio('#ffffff', effective(vars, name)), name).toBeLessThan(MIN_CONTRAST);
    }
    expect(contrastRatio('#ffffff', effective(vars, '--color-ink-900'))).toBeLessThan(MIN_CONTRAST);
  });

  it.each(
    Object.keys(THEMES).flatMap((theme) =>
      [
        ['--color-on-accent', '--color-accent-strong'],
        ['--color-on-accent', '--color-accent-700'],
        ['--color-on-accent', '--color-danger-strong'],
        ['--color-on-accent', '--color-success-strong'],
        ['--color-on-scrim', '--color-scrim'],
      ].map(([text, background]) => [theme, text, background]),
    ),
  )('%s theme: %s on %s reaches 4.5:1', (theme, text, background) => {
    const vars = themeVariables(THEMES[theme as keyof typeof THEMES]);
    expect(
      contrastRatio(effective(vars, text), effective(vars, background)),
    ).toBeGreaterThanOrEqual(MIN_CONTRAST);
  });
});

// MA-4.6.1c: Inter 4.1 is bundled locally (DEC-161 p. 1, rev. 46). The CSS is
// parsed, and the referenced files are checked by size and SHA-256.
describe('local Inter font (index.css)', () => {
  const css = indexCss.replace(/\/\*[\s\S]*?\*\//g, '');
  const faces = [...css.matchAll(/@font-face\s*\{([^}]*)\}/g)].map((m) => m[1]);
  const prop = (face: string, name: string) =>
    new RegExp(`(?:^|;|\\s)${name}\\s*:\\s*([^;]+);`).exec(face)?.[1].trim();
  const sha256 = (path: string) => createHash('sha256').update(readFileSync(path)).digest('hex');

  it('declares exactly one @font-face: Inter, local WOFF2, weights 100-900, swap', () => {
    expect(faces).toHaveLength(1);
    const face = faces[0];
    expect(prop(face, 'font-family')).toBe("'Inter'");
    expect(prop(face, 'src')).toBe("url('./fonts/inter-variable.woff2') format('woff2')");
    expect(prop(face, 'font-weight')).toBe('100 900');
    expect(prop(face, 'font-style')).toBe('normal');
    expect(prop(face, 'font-display')).toBe('swap');
  });

  it('--font-sans starts with the bundled family and keeps the system fallbacks', () => {
    const families = value('--font-sans')
      .split(',')
      .map((family) => family.trim());
    expect(families[0]).toBe(prop(faces[0], 'font-family'));
    expect(families.slice(1)).toEqual([
      "'Segoe UI'",
      'system-ui',
      '-apple-system',
      "'Helvetica Neue'",
      'Arial',
      'sans-serif',
    ]);
  });

  it('loads nothing from other origins (no CDN, no external @import)', () => {
    for (const source of [indexCss, tokensCss]) {
      for (const [, url] of source.matchAll(/url\(\s*['"]?([^'")]+)/g)) {
        expect(url, url).toMatch(/^\.\.?\//);
      }
      for (const [, target] of source.matchAll(/@import\s+['"]([^'"]+)['"]/g)) {
        expect(target, target).not.toMatch(/^(https?:)?\/\//);
      }
      expect(source).not.toMatch(/fonts\.(googleapis|gstatic)\.com/);
    }
  });

  it('the referenced file is the verified Inter 4.1 WOFF2', () => {
    const font = readFileSync('src/styles/fonts/inter-variable.woff2');
    expect(font.byteLength).toBe(352240);
    expect(String.fromCharCode(...font.subarray(0, 4))).toBe('wOF2');
    expect(sha256('src/styles/fonts/inter-variable.woff2')).toBe(
      '693b77d4f32ee9b8bfc995589b5fad5e99adf2832738661f5402f9978429a8e3',
    );
  });

  it('ships the SIL OFL 1.1 license next to the font', () => {
    expect(sha256('src/styles/fonts/OFL.txt')).toBe(
      '262481e844521b326f5ecd053e59b98c8b2da78c8ee1bdbb6e8174305e54935a',
    );
    const license = readFileSync('src/styles/fonts/OFL.txt', 'utf8');
    expect(license).toContain('The Inter Project Authors');
    expect(license).toContain('SIL Open Font License, Version 1.1');
  });
});
