import type { TelegramThemeParams, TelegramWebApp } from './types';

// Telegram themeParams -> design tokens (UI_UX §3 "Тема", decision Q5):
// backgrounds and the main/secondary text follow Telegram; the brand's
// orange accent stays. A Telegram pair is applied only if its text keeps
// WCAG AA contrast (4.5:1) on its background; otherwise our tokens stay.
// On a dark background the shades used as text (accent-800, danger/success/
// warning-700) and their tinted backgrounds are replaced by dark-friendly
// ones, so orange and status texts stay readable; buttons keep the brand
// orange (bg-accent-700 with white text, 5.2:1). "Dark" is decided by the
// background's luminance, not by the declared colour scheme.

const HEX = /^#[0-9a-f]{6}$/i;
export const MIN_CONTRAST = 4.5;

export const DARK_OVERRIDES: Record<string, string> = {
  '--color-accent-50': '#3a2416',
  '--color-accent-100': '#4a2c18',
  '--color-accent-800': '#fdba74',
  '--color-danger-50': '#3b1416',
  '--color-danger-700': '#fca5a5',
  '--color-success-50': '#0f2e1c',
  '--color-success-700': '#86efac',
  '--color-warning-700': '#fcd34d',
  // Dish image backdrop (DEC-161 rev. 47): sinks below a dark Telegram
  // background instead of standing out as a grey square.
  '--color-plate': '#0f1720',
  '--color-plate-hi': '#1f2b38',
};
const DARK_LUMINANCE = 0.2;

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const n = Number.parseInt(hex.slice(1), 16);
  return (
    0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255)
  );
}

/** WCAG contrast ratio of two #rrggbb colours. */
export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

function color(value: string | undefined): string | undefined {
  return value && HEX.test(value) ? value : undefined;
}

/** CSS variables for the given theme; empty when Telegram gives nothing usable. */
export function themeVariables(params: TelegramThemeParams): Record<string, string> {
  const bg = color(params.bg_color);
  const text = color(params.text_color);
  if (!bg || !text || contrastRatio(text, bg) < MIN_CONTRAST) {
    return {}; // unreadable or missing: keep the brand tokens
  }
  const vars: Record<string, string> = {
    '--color-cream-50': bg,
    '--color-ink-900': text,
  };
  const surface = color(params.section_bg_color) ?? color(params.secondary_bg_color);
  if (surface && contrastRatio(text, surface) >= MIN_CONTRAST) {
    vars['--color-surface'] = surface;
  } else {
    vars['--color-surface'] = bg;
  }
  const secondary = color(params.secondary_bg_color);
  if (secondary && contrastRatio(text, secondary) >= MIN_CONTRAST) {
    vars['--color-cream-100'] = secondary;
  } else {
    // Without a readable secondary colour the brand's light cream-100 would
    // stay under Telegram's (possibly light) text (MA-4.6-C): use the surface,
    // whose contrast with the text is already checked above.
    vars['--color-cream-100'] = vars['--color-surface'];
  }
  const hint = color(params.hint_color) ?? color(params.subtitle_text_color);
  if (
    hint &&
    contrastRatio(hint, bg) >= MIN_CONTRAST &&
    contrastRatio(hint, vars['--color-surface']) >= MIN_CONTRAST
  ) {
    vars['--color-ink-600'] = hint;
  } else {
    vars['--color-ink-600'] = text; // a faint hint would be unreadable
  }
  const separator = color(params.section_separator_color);
  if (separator) {
    vars['--color-border'] = separator;
  }
  if (luminance(bg) < DARK_LUMINANCE) {
    Object.assign(vars, DARK_OVERRIDES);
  }
  return vars;
}

const applied = new Set<string>();

/** Applies the current Telegram theme to the document root. */
export function applyTelegramTheme(
  app: TelegramWebApp,
  root: HTMLElement = document.documentElement,
) {
  const vars = themeVariables(app.themeParams ?? {});
  for (const name of applied) {
    if (!(name in vars)) {
      root.style.removeProperty(name);
    }
  }
  applied.clear();
  for (const [name, value] of Object.entries(vars)) {
    root.style.setProperty(name, value);
    applied.add(name);
  }
  root.style.colorScheme = Object.keys(vars).length ? app.colorScheme : '';
}
