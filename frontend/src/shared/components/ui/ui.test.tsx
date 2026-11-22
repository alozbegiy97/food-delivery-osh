import { fireEvent, render, screen } from '@testing-library/react';
import { Link, MemoryRouter, NavLink } from 'react-router';
import { describe, expect, it, vi } from 'vitest';

import { contrastRatio, MIN_CONTRAST, themeVariables } from '../../../features/telegram/theme';
import type { TelegramThemeParams } from '../../../features/telegram/types';
import { Badge, Button, buttonClasses, Card, Chip, chipClasses, SectionHeader } from '.';
import {
  BADGE_TONES,
  BUTTON_SIZES,
  BUTTON_VARIANTS,
  CARD_TONES,
  CHIP_STATES,
  SECTION_HEADER,
} from './classes';

// Shared UI components (DEC-161, MA-4.6.1d): semantics, states and the
// contrast of every colour pair they use, in all Telegram themes below.

describe('Button', () => {
  it('requires the type at compile time and renders the given one', () => {
    // @ts-expect-error Button.type is required (a typeless button submits forms)
    const typeless = <Button>Без типа</Button>;
    expect(typeless).toBeTruthy();

    render(
      <>
        <Button type="button">Обычная</Button>
        <Button type="submit">Отправить</Button>
        <Button type="reset">Сбросить</Button>
      </>,
    );
    expect(screen.getByRole('button', { name: 'Обычная' })).toHaveAttribute('type', 'button');
    expect(screen.getByRole('button', { name: 'Отправить' })).toHaveAttribute('type', 'submit');
    expect(screen.getByRole('button', { name: 'Сбросить' })).toHaveAttribute('type', 'reset');
  });

  it('keeps native submit, reset and the form attribute', () => {
    const onSubmit = vi.fn((event: { preventDefault(): void }) => event.preventDefault());
    render(
      <>
        <form aria-label="Форма" id="order-form" onSubmit={onSubmit}>
          <input aria-label="Имя" defaultValue="Айбек" />
          <Button type="submit">Отправить</Button>
          <Button type="reset">Сбросить</Button>
        </form>
        <Button type="submit" form="order-form">
          Снаружи
        </Button>
      </>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Отправить' }));
    expect(onSubmit).toHaveBeenCalledTimes(1);

    const input = screen.getByRole('textbox', { name: 'Имя' });
    fireEvent.change(input, { target: { value: 'Другое' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сбросить' }));
    expect(input).toHaveValue('Айбек');

    const outside = screen.getByRole<HTMLButtonElement>('button', { name: 'Снаружи' });
    expect(outside.form).toBe(screen.getByRole('form', { name: 'Форма' }));
  });

  it('loading keeps the accessible name, marks busy and blocks repeated clicks', () => {
    const onClick = vi.fn();
    const { container } = render(
      <Button type="button" loading onClick={onClick}>
        Сохранить
      </Button>,
    );
    const button = screen.getByRole('button', { name: 'Сохранить' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
    expect(container.querySelector('[aria-hidden="true"]')).not.toBeNull();
    fireEvent.click(button);
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('disabled blocks clicks; an idle button is not busy and passes aria attributes', () => {
    const onClick = vi.fn();
    render(
      <>
        <Button type="button" disabled onClick={onClick}>
          Нельзя
        </Button>
        <Button type="button" aria-describedby="hint" onClick={onClick}>
          Можно
        </Button>
        <p id="hint">Подсказка</p>
      </>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Нельзя' }));
    expect(onClick).not.toHaveBeenCalled();
    const idle = screen.getByRole('button', { name: 'Можно' });
    expect(idle).not.toHaveAttribute('aria-busy');
    expect(idle).toHaveAccessibleDescription('Подсказка');
    fireEvent.click(idle);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('keeps 44/48 px touch targets (class level: CSS is off in Vitest)', () => {
    render(
      <>
        <Button type="button">Средняя</Button>
        <Button type="button" size="lg">
          Большая
        </Button>
      </>,
    );
    expect(screen.getByRole('button', { name: 'Средняя' })).toHaveClass('min-h-11');
    expect(screen.getByRole('button', { name: 'Большая' })).toHaveClass('min-h-12');
    expect(BUTTON_SIZES.md).toContain('min-h-11');
    expect(BUTTON_SIZES.lg).toContain('min-h-12');
  });

  it('buttonClasses on a Link keeps the link semantics', () => {
    render(
      <MemoryRouter>
        <Link to="/menu" className={buttonClasses({ variant: 'secondary' })}>
          В меню
        </Link>
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: 'В меню' })).toHaveAttribute('href', '/menu');
    expect(screen.queryByRole('button')).toBeNull();
  });
});

describe('Card', () => {
  it('renders the requested element and nothing interactive', () => {
    render(
      <>
        <Card as="article">Статья</Card>
        <ul>
          <Card as="li">Пункт</Card>
        </ul>
        <Card as="section" aria-labelledby="card-title">
          <SectionHeader id="card-title" title="Раздел" />
        </Card>
        <Card>Блок</Card>
      </>,
    );
    expect(screen.getByRole('article')).toHaveTextContent('Статья');
    expect(screen.getByRole('listitem')).toHaveTextContent('Пункт');
    expect(screen.getByRole('region', { name: 'Раздел' })).toBeInTheDocument();
    expect(screen.getByText('Блок').tagName).toBe('DIV');
    expect(screen.queryAllByRole('button')).toHaveLength(0);
    expect(screen.queryAllByRole('link')).toHaveLength(0);
  });
});

describe('Badge', () => {
  it('shows the status as text, without a role', () => {
    render(<Badge tone="success">Доставлен</Badge>);
    const badge = screen.getByText('Доставлен');
    expect(badge.tagName).toBe('SPAN');
    expect(badge).not.toHaveAttribute('role');
    expect(screen.queryByRole('status')).toBeNull();
  });
});

describe('Chip', () => {
  it('is a button with aria-pressed and never aria-current', () => {
    const onClick = vi.fn();
    render(
      <>
        <Chip selected onClick={onClick}>
          Все
        </Chip>
        <Chip selected={false}>Пицца</Chip>
      </>,
    );
    const on = screen.getByRole('button', { name: 'Все' });
    expect(on).toHaveAttribute('type', 'button');
    expect(on).toHaveAttribute('aria-pressed', 'true');
    expect(on).not.toHaveAttribute('aria-current');
    expect(screen.getByRole('button', { name: 'Пицца' })).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(on);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('a NavLink chip keeps link semantics with aria-current, without aria-pressed', () => {
    render(
      <MemoryRouter initialEntries={['/menu']}>
        <NavLink to="/menu" className={({ isActive }) => chipClasses(isActive)}>
          Меню
        </NavLink>
        <NavLink to="/orders" className={({ isActive }) => chipClasses(isActive)}>
          Заказы
        </NavLink>
      </MemoryRouter>,
    );
    const current = screen.getByRole('link', { name: 'Меню' });
    expect(current).toHaveAttribute('aria-current', 'page');
    expect(current).not.toHaveAttribute('aria-pressed');
    expect(screen.getByRole('link', { name: 'Заказы' })).not.toHaveAttribute('aria-current');
  });
});

describe('SectionHeader', () => {
  it('renders an h2 by default and an h3 on request, with description and action', () => {
    render(
      <>
        <h1>Страница</h1>
        <SectionHeader
          id="popular"
          title="Популярное"
          description="Чаще всего заказывают"
          action={<a href="/menu">Всё меню</a>}
        />
        <SectionHeader level={3} title="Пицца" />
      </>,
    );
    const h2 = screen.getByRole('heading', { level: 2, name: 'Популярное' });
    expect(h2).toHaveAttribute('id', 'popular');
    expect(screen.getByRole('heading', { level: 3, name: 'Пицца' })).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByText('Чаще всего заказывают').tagName).toBe('P');
    expect(screen.getByRole('link', { name: 'Всё меню' })).toBeInTheDocument();
  });
});

// ---- Contrast of the colour pairs used by the class strings ----------------

type Fs = { readFileSync(path: string, encoding: 'utf8'): string };
const fsModule = 'node:fs';
const { readFileSync } = (await import(/* @vite-ignore */ fsModule)) as Fs;
const tokensCss = readFileSync('src/styles/tokens.css', 'utf8');
const BRAND = new Map(
  [...tokensCss.matchAll(/(--color-[a-z0-9-]+)\s*:\s*(#[0-9a-f]{6})\s*;/gi)].map((m) => [
    m[1],
    m[2].toLowerCase(),
  ]),
);

const best = (bg: string) =>
  contrastRatio('#ffffff', bg) >= contrastRatio('#000000', bg) ? '#ffffff' : '#000000';
const BACKGROUNDS = [
  '#000000',
  '#121212',
  '#17212b',
  '#1c2733',
  '#212121',
  '#333333',
  '#3e546a',
  '#555555',
  '#777777',
  '#999999',
  '#bbbbbb',
  '#dddddd',
  '#efeff4',
  '#f1f1f1',
  '#ffffff',
];
// Typical themes plus a sweep with rejected secondary/section/hint colours.
const THEMES: Array<[string, TelegramThemeParams]> = [
  ['site (no Telegram theme)', {}],
  [
    'telegram light',
    {
      bg_color: '#ffffff',
      text_color: '#000000',
      hint_color: '#707579',
      secondary_bg_color: '#f4f4f5',
      section_bg_color: '#ffffff',
      section_separator_color: '#e7e7e7',
    },
  ],
  [
    'telegram dark',
    {
      bg_color: '#212121',
      text_color: '#ffffff',
      hint_color: '#aaaaaa',
      secondary_bg_color: '#181818',
      section_bg_color: '#2c2c2c',
      section_separator_color: '#3a3a3a',
    },
  ],
  ...BACKGROUNDS.flatMap((bg): Array<[string, TelegramThemeParams]> => {
    const text = best(bg);
    return [
      [
        `${bg} readable`,
        {
          bg_color: bg,
          text_color: text,
          secondary_bg_color: bg,
          section_bg_color: bg,
          hint_color: text,
        },
      ],
      [
        `${bg} rejected secondary`,
        { bg_color: bg, text_color: text, secondary_bg_color: text, hint_color: bg },
      ],
      [
        `${bg} rejected section`,
        { bg_color: bg, text_color: text, section_bg_color: text, secondary_bg_color: bg },
      ],
    ];
  }),
];

function rgb(hex: string): number[] {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function blend(top: string, under: string, alpha: number): string {
  const [a, b] = [rgb(top), rgb(under)];
  return (
    '#' +
    a
      .map((v, i) =>
        Math.round(v * alpha + b[i] * (1 - alpha))
          .toString(16)
          .padStart(2, '0'),
      )
      .join('')
  );
}

interface Color {
  token: string;
  alpha: number;
}
function colors(classes: string, prefix: 'bg' | 'text', hover: boolean): Color | undefined {
  const re = new RegExp(
    `(?:^|\\s)${hover ? 'hover:' : ''}${prefix}-([a-z0-9-]+?)(?:/(\\d+))?(?=\\s|$)`,
    'g',
  );
  for (const [, name, alpha] of classes.matchAll(re)) {
    if (BRAND.has(`--color-${name}`)) {
      return { token: `--color-${name}`, alpha: alpha ? Number(alpha) / 100 : 1 };
    }
  }
  return undefined;
}

const CONTEXTS = ['--color-cream-50', '--color-surface'];
function failures(label: string, classes: string): string[] {
  const out: string[] = [];
  const text = colors(classes, 'text', false);
  if (!text) {
    return [`${label}: no text colour`];
  }
  const states: Array<[string, Color | undefined, Color]> = [
    ['rest', colors(classes, 'bg', false), text],
  ];
  if (/(?:^|\s)hover:(bg|text)-/.test(classes)) {
    states.push([
      'hover',
      colors(classes, 'bg', true) ?? colors(classes, 'bg', false),
      colors(classes, 'text', true) ?? text,
    ]);
  }
  for (const [themeName, params] of THEMES) {
    const vars = themeVariables(params);
    const value = (token: string) => vars[token] ?? BRAND.get(token) ?? 'missing';
    for (const [state, bg, fg] of states) {
      for (const context of CONTEXTS) {
        const background = bg ? blend(value(bg.token), value(context), bg.alpha) : value(context);
        const ratio = contrastRatio(value(fg.token), background);
        if (ratio < MIN_CONTRAST) {
          out.push(`${label} ${state} on ${context} — ${themeName}: ${ratio.toFixed(2)}`);
        }
      }
    }
  }
  return out;
}

describe('contrast of the component colours in every Telegram theme', () => {
  it('covers readable and rejected theme colours (the sweep is not empty)', () => {
    expect(THEMES.length).toBe(3 + BACKGROUNDS.length * 3);
    expect(BRAND.get('--color-accent-strong')).toBe('#9a3412');
  });

  it.each([
    ...Object.entries(BUTTON_VARIANTS).map(([k, v]) => [`Button ${k}`, v]),
    ...Object.entries(CHIP_STATES).map(([k, v]) => [`Chip ${k}`, v]),
    ...Object.entries(BADGE_TONES).map(([k, v]) => [`Badge ${k}`, v]),
    ['SectionHeader h2', SECTION_HEADER.title2],
    ['SectionHeader h3', SECTION_HEADER.title3],
    ['SectionHeader description', SECTION_HEADER.description],
  ])('%s reaches 4.5:1 at rest and on hover', (label, classes) => {
    expect(failures(label, classes)).toEqual([]);
  });

  it('cards use only surface and border (no text colour of their own)', () => {
    for (const classes of Object.values(CARD_TONES)) {
      expect(colors(classes, 'bg', false)?.token).toBe('--color-surface');
      expect(colors(classes, 'text', false)).toBeUndefined();
    }
  });

  it('why cream-100 and a resting accent-800 text are not used', () => {
    const all = [BUTTON_VARIANTS, CHIP_STATES, BADGE_TONES, CARD_TONES, SECTION_HEADER]
      .flatMap((group) => Object.values(group))
      .join(' ');
    expect(all).not.toMatch(/cream-100/);
    expect(failures('accent-800 text at rest', 'text-accent-800').length).toBeGreaterThan(0);
  });

  // MA-4.6-C: without a readable secondary colour Telegram's cream-100 now
  // takes the surface (theme.ts), so the pair is readable in every theme.
  it('cream-100 under ink-900 is readable in every theme after the fix', () => {
    expect(failures('ink-900 on cream-100', 'bg-cream-100 text-ink-900')).toEqual([]);
  });

  // MA-4.6-B/C pairs: the graphite category chip and the Mini App tabs.
  it.each([
    ['graphite category chip', 'bg-ink-900 text-cream-50'],
    ['idle category chip', 'bg-surface text-ink-900'],
    ['active Mini App tab (pill)', 'bg-accent-50 text-accent-800'],
    ['idle Mini App tab', 'text-ink-600'],
  ])('%s reaches 4.5:1 in every theme', (label, classes) => {
    expect(failures(label, classes)).toEqual([]);
  });
});
