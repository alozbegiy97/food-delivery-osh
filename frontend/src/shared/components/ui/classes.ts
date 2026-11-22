// Class strings of the shared UI components (DEC-161, MA-4.6.1d). Every
// class is written out in full: Tailwind finds classes by scanning the source,
// so names are never built dynamically.
//
// Colours: only pairs whose contrast holds in every Telegram theme are used —
// ink-900/ink-600 on cream-50/surface (theme.ts accepts a theme only if these
// reach 4.5:1) and pairs whose two tokens change together (accent-50 with
// accent-800, *-50 with *-700, accent-700/the *-strong tokens with on-accent).
// cream-100 is not used: theme.ts may keep it light under a light text.

export function joinClasses(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'md' | 'lg';

export const BUTTON_BASE =
  'inline-flex items-center justify-center gap-2 rounded-full text-center font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60';

export const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-accent-700 text-on-accent hover:bg-accent-strong',
  secondary: 'bg-surface text-ink-900 ring-1 ring-border hover:ring-accent-600',
  ghost: 'text-ink-900 hover:bg-accent-50 hover:text-accent-800',
  danger: 'bg-danger-strong text-on-accent hover:bg-danger-strong/90',
};

/** Both sizes keep at least a 44 px (md) or 48 px (lg) touch target. */
export const BUTTON_SIZES: Record<ButtonSize, string> = {
  md: 'min-h-11 px-5 py-2',
  lg: 'min-h-12 px-6 py-2',
};

export interface ButtonClassOptions {
  variant?: ButtonVariant;
  size?: ButtonSize;
  fullWidth?: boolean;
  className?: string;
}

/** Button look; also for a router Link that should look like a button. */
export function buttonClasses({
  variant = 'primary',
  size = 'md',
  fullWidth = false,
  className,
}: ButtonClassOptions = {}): string {
  return joinClasses(
    BUTTON_BASE,
    BUTTON_VARIANTS[variant],
    BUTTON_SIZES[size],
    fullWidth && 'w-full',
    className,
  );
}

export const CHIP_BASE =
  'min-h-11 shrink-0 whitespace-nowrap rounded-full px-4 text-sm font-semibold transition-colors';

export const CHIP_STATES = {
  selected: 'bg-accent-700 text-on-accent',
  idle: 'bg-surface text-ink-900 ring-1 ring-border hover:ring-accent-600',
} as const;

/** Chip look; also for a NavLink chip (the link keeps aria-current). */
export function chipClasses(selected: boolean, className?: string): string {
  return joinClasses(CHIP_BASE, selected ? CHIP_STATES.selected : CHIP_STATES.idle, className);
}

export type CardTone = 'default' | 'raised';
export type CardPadding = 'none' | 'sm' | 'md';

export const CARD_TONES: Record<CardTone, string> = {
  default: 'rounded-card border border-border bg-surface',
  raised: 'rounded-card border border-border bg-surface shadow-[var(--shadow-card)]',
};

export const CARD_PADDING: Record<CardPadding, string> = {
  none: '',
  sm: 'p-4',
  md: 'p-4 sm:p-6',
};

export interface CardClassOptions {
  tone?: CardTone;
  padding?: CardPadding;
  className?: string;
}

/** Card look; also for a link that is itself the card (no nested links). */
export function cardClasses({
  tone = 'default',
  padding = 'md',
  className,
}: CardClassOptions = {}): string {
  return joinClasses(CARD_TONES[tone], CARD_PADDING[padding], className);
}

export type BadgeTone = 'neutral' | 'accent' | 'success' | 'danger';

export const BADGE_BASE =
  'inline-flex max-w-full items-center rounded-full px-3 py-1 text-xs font-semibold';

export const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: 'bg-surface text-ink-900 ring-1 ring-inset ring-border',
  accent: 'bg-accent-50 text-accent-800',
  success: 'bg-success-50 text-success-700',
  danger: 'bg-danger-50 text-danger-700',
};

export const SECTION_HEADER = {
  root: 'flex flex-wrap items-end justify-between gap-x-4 gap-y-2',
  title2: 'text-xl font-bold text-ink-900 [overflow-wrap:anywhere] sm:text-2xl',
  title3: 'text-lg font-bold text-ink-900 [overflow-wrap:anywhere] sm:text-xl',
  description: 'mt-1 text-ink-600',
} as const;
