import { act, render, screen, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it } from 'vitest';

import i18n from '../../../shared/i18n';
import {
  BURGER_SUMMARY,
  CATEGORIES,
  MARGHERITA_SUMMARY,
  PEPPERONI_SUMMARY,
  SOLD_OUT_SUMMARY,
} from '../../../test/catalogFixtures';
import type { ProductSummary } from '../../../shared/types/api';
import { DishImage } from './DishImage';
import { DishPlate } from './DishPlate';
import { ProductGrid } from './ProductGrid';

// Catalog cards (MA-4.6.2b): one link per item, a link name without
// repetitions, a decorative image, row/tile classes, and the classic layout
// kept as the default (the home page until MA-4.6.3).

type Layout = 'classic' | 'catalog' | undefined;

function renderGrid(
  products: ProductSummary[],
  {
    layout,
    loading = false,
    basename,
  }: { layout?: Layout; loading?: boolean; basename?: string } = {},
) {
  const element = (
    <ProductGrid
      products={products}
      categories={CATEGORIES}
      loading={loading}
      skeletons={4}
      label="Блюда"
      {...(layout ? { layout } : {})}
    />
  );
  const router = createMemoryRouter([{ path: '*', element }], {
    initialEntries: [basename ? `${basename}/menu` : '/menu'],
    ...(basename ? { basename } : {}),
  });
  return render(<RouterProvider router={router} />);
}

const AVAILABLE_NO_PRICE: ProductSummary = {
  ...MARGHERITA_SUMMARY,
  id: 'p-no-price',
  name: 'Компот',
  price_from: null,
};
const WITH_PHOTO: ProductSummary = {
  ...PEPPERONI_SUMMARY,
  id: 'p-photo',
  image_url: '/media/pepperoni.webp',
};
const CLASSIC_LINK =
  'group flex h-full flex-col overflow-hidden rounded-card border border-border bg-surface shadow-[var(--shadow-card)] transition hover:-translate-y-0.5 hover:border-accent-600 focus-visible:-translate-y-0.5';

describe('catalog layout: semantics and accessible names', () => {
  it('every item is li > one link, without buttons, leading to the dish', async () => {
    renderGrid([MARGHERITA_SUMMARY, PEPPERONI_SUMMARY, SOLD_OUT_SUMMARY], { layout: 'catalog' });
    const list = await screen.findByRole('list', { name: 'Блюда' });
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(3);
    for (const item of items) {
      expect(within(item).getAllByRole('link')).toHaveLength(1);
      expect(within(item).queryAllByRole('button')).toHaveLength(0);
    }
    expect(within(list).getByRole('link', { name: /Маргарита/ })).toHaveAttribute(
      'href',
      '/menu/p-margherita',
    );
  });

  it('the link name is the name and the price or status, without repetitions', async () => {
    renderGrid([MARGHERITA_SUMMARY, PEPPERONI_SUMMARY, SOLD_OUT_SUMMARY, AVAILABLE_NO_PRICE], {
      layout: 'catalog',
    });
    const list = await screen.findByRole('list', { name: 'Блюда' });
    const links = within(list).getAllByRole('link');
    expect(links[0]).toHaveAccessibleName('Маргарита от 550 сом');
    expect(links[1]).toHaveAccessibleName('Пепперони (говяжья) от 650 сом');
    expect(links[2]).toHaveAccessibleName('Чизбургер Нет в наличии');
    expect(links[3]).toHaveAccessibleName('Компот Нет в наличии');
  });

  it('the image is decorative: no img role, hidden drawing, empty alt on a photo', async () => {
    const { container } = renderGrid([MARGHERITA_SUMMARY, WITH_PHOTO], { layout: 'catalog' });
    const list = await screen.findByRole('list', { name: 'Блюда' });
    expect(within(list).queryAllByRole('img')).toHaveLength(0);
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
    expect(container.querySelector('svg')).not.toHaveAttribute('role');
    expect(container.querySelector('img')).toHaveAttribute('alt', '');
    expect(within(list).getAllByRole('link')[1]).toHaveAccessibleName(
      'Пепперони (говяжья) от 650 сом',
    );
  });

  it('the "Choose" / "Details" pill is hidden from the link name', async () => {
    renderGrid([MARGHERITA_SUMMARY, SOLD_OUT_SUMMARY], { layout: 'catalog' });
    const list = await screen.findByRole('list', { name: 'Блюда' });
    const choose = within(list).getByText('Выбрать');
    const details = within(list).getByText('Подробнее');
    expect(choose).toHaveAttribute('aria-hidden', 'true');
    expect(details).toHaveAttribute('aria-hidden', 'true');
    expect(choose).toHaveClass('bg-accent-700', 'min-h-11');
    expect(details).toHaveClass('bg-surface', 'ring-1');
  });
});

describe('catalog layout: rows below 640 px, tiles from 640 px', () => {
  it('uses the row/tile classes on the grid, link, image frame and name', async () => {
    renderGrid([MARGHERITA_SUMMARY], { layout: 'catalog' });
    const list = await screen.findByRole('list', { name: 'Блюда' });
    expect(list).toHaveClass('grid-cols-1', 'sm:grid-cols-2', 'lg:grid-cols-3', 'xl:grid-cols-4');
    const link = within(list).getByRole('link');
    expect(link).toHaveClass('flex', 'sm:flex-col');
    // MA-4.6-B: no card frame; the dark plate carries the shape.
    expect(link.className).not.toMatch(/(^|\s)border(\s|$)|bg-surface|shadow|rounded-card/);
    const frame = link.firstElementChild;
    // Square everywhere: 104x104 in the row, the full tile width from 640 px.
    expect(frame).toHaveClass('aspect-square', 'w-26', 'self-start');
    expect(frame).toHaveClass('sm:w-full', 'sm:self-auto');
    expect(frame?.className).not.toMatch(/4\/3/);
    expect(within(link).getByRole('heading', { level: 3 })).toHaveClass('[overflow-wrap:anywhere]');
  });

  it('marks an unavailable dish in words, with muted image and no cream-100', async () => {
    renderGrid([SOLD_OUT_SUMMARY], { layout: 'catalog' });
    const list = await screen.findByRole('list', { name: 'Блюда' });
    const link = within(list).getByRole('link');
    expect(within(link).getAllByText('Нет в наличии')).toHaveLength(1);
    const frame = link.firstElementChild as HTMLElement;
    // The dark plate stays; only the dish fades to grey (styles/oven.css).
    expect(frame.firstElementChild).toHaveClass('dish-plate', 'dish-plate-muted');
    const outsideImage = [link, ...link.querySelectorAll('*')].filter(
      (element) => !frame.contains(element),
    );
    for (const element of outsideImage) {
      expect(element.getAttribute('class') ?? '').not.toMatch(/cream-100/);
    }
  });

  it('shows a long Uzbek name in full', async () => {
    const long = { ...PEPPERONI_SUMMARY, name: 'Pepperoni (mol goʻshtidan)' };
    renderGrid([long], { layout: 'catalog' });
    expect(
      await screen.findByRole('heading', { level: 3, name: 'Pepperoni (mol goʻshtidan)' }),
    ).toBeInTheDocument();
  });

  it('loading: catalog skeletons, hidden from assistive tech, on a busy list', () => {
    renderGrid([], { layout: 'catalog', loading: true });
    const list = screen.getByRole('list', { name: 'Блюда', hidden: true });
    expect(list).toHaveAttribute('aria-busy', 'true');
    const items = list.querySelectorAll('li');
    expect(items).toHaveLength(4);
    for (const item of items) {
      expect(item).toHaveAttribute('aria-hidden', 'true');
      expect(item).toHaveClass('flex', 'sm:flex-col');
      expect(item.innerHTML).not.toMatch(/cream-100/);
      expect(item.querySelector('.aspect-square')).toHaveClass('dish-plate');
    }
  });

  it('Mini App: card links keep the /tg prefix', async () => {
    renderGrid([MARGHERITA_SUMMARY], { layout: 'catalog', basename: '/tg' });
    const list = await screen.findByRole('list', { name: 'Блюда' });
    expect(within(list).getByRole('link')).toHaveAttribute('href', '/tg/menu/p-margherita');
  });
});

// MA-4.6-B: the image on the "Печь" plate (DEC-161 rev. 47).
describe('catalog layout: the dish image', () => {
  function plateOf(link: HTMLElement): HTMLElement {
    const plate = link.querySelector<HTMLElement>('[data-dish-plate]');
    if (!plate) {
      throw new Error('no plate');
    }
    return plate;
  }

  it('without a photo: the category drawing on the dark plate', async () => {
    renderGrid([MARGHERITA_SUMMARY, BURGER_SUMMARY], { layout: 'catalog' });
    const list = await screen.findByRole('list', { name: 'Блюда' });
    const [pizza, burger] = within(list).getAllByRole('link');
    expect(plateOf(pizza)).toHaveAttribute('data-dish-plate', 'pizza');
    expect(plateOf(pizza)).toHaveClass('dish-plate');
    expect(plateOf(burger)).toHaveAttribute('data-dish-plate', 'burger');
    // The neutral pizza: no topping that a particular dish may not have.
    expect(pizza.querySelector('[data-layer="pepperoni"]')).toBeNull();
  });

  it('a real photo from the API always wins over the drawing', async () => {
    renderGrid([WITH_PHOTO], { layout: 'catalog' });
    const list = await screen.findByRole('list', { name: 'Блюда' });
    const plate = plateOf(within(list).getByRole('link'));
    expect(plate).toHaveAttribute('data-dish-plate', 'photo');
    expect(plate.querySelector('img')).toHaveAttribute('src', '/media/pepperoni.webp');
    expect(plate.querySelector('img')).toHaveClass('object-cover');
    expect(plate.querySelector('svg')).toBeNull();
  });

  it('a dish of an unknown category keeps the older motif', async () => {
    const lost = { ...MARGHERITA_SUMMARY, id: 'p-lost', category_id: 'cat-missing' };
    renderGrid([lost], { layout: 'catalog' });
    const list = await screen.findByRole('list', { name: 'Блюда' });
    const plate = plateOf(within(list).getByRole('link'));
    expect(plate).toHaveAttribute('data-dish-plate', 'motif');
    expect(plate.querySelector('svg[data-dish-art]')).toBeNull();
    expect(plate.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  });

  it.each(['national', 'salads', 'soups', 'desserts', 'drinks'])(
    '%s keeps its older motif on the plate',
    (slug) => {
      const { container } = render(<DishPlate imageUrl={null} categorySlug={slug} />);
      const plate = container.firstElementChild as HTMLElement;
      expect(plate).toHaveAttribute('data-dish-plate', 'motif');
      expect(plate.querySelector('svg[data-dish-art]')).toBeNull();
      expect(plate.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
    },
  );
});

describe('classic layout stays the default (home page until MA-4.6.3)', () => {
  it('without layout: the original card, grid and labelled drawing', async () => {
    renderGrid([MARGHERITA_SUMMARY]);
    const list = await screen.findByRole('list', { name: 'Блюда' });
    expect(list).toHaveClass('grid', 'grid-cols-1', 'gap-5', 'sm:grid-cols-2');
    expect(list).not.toHaveClass('gap-3');
    const link = within(list).getByRole('link');
    expect(link.className).toBe(CLASSIC_LINK);
    expect(within(link).getByRole('img', { name: 'Маргарита' })).toBeInTheDocument();
  });

  it('classic loading keeps the original skeletons', () => {
    renderGrid([], { loading: true });
    const items = screen.getByRole('list', { name: 'Блюда', hidden: true }).querySelectorAll('li');
    expect(items).toHaveLength(4);
    expect(items[0].innerHTML).toMatch(/bg-cream-100/);
  });
});

describe('DishImage default is unchanged (product page, cart, home, admin)', () => {
  it('a drawing keeps role img with its label; a photo keeps its alt', () => {
    const { container } = render(
      <>
        <DishImage imageUrl={null} alt="Маргарита" categorySlug="pizza" />
        <DishImage imageUrl="/media/margherita.webp" alt="Маргарита на тарелке" />
      </>,
    );
    expect(screen.getByRole('img', { name: 'Маргарита' }).tagName.toLowerCase()).toBe('svg');
    expect(container.querySelector('img')).toHaveAttribute('alt', 'Маргарита на тарелке');
  });
});

// MA-4.6.2d: the "Hit" badge, strictly for is_featured === true.
describe('catalog layout: the "Hit" badge', () => {
  const HIT: ProductSummary = { ...MARGHERITA_SUMMARY, is_featured: true };
  const HIT_SOLD_OUT: ProductSummary = { ...SOLD_OUT_SUMMARY, is_featured: true };

  it('is_featured: true shows an accent badge inside the single link', async () => {
    renderGrid([HIT], { layout: 'catalog' });
    const list = await screen.findByRole('list', { name: 'Блюда' });
    const item = within(list).getByRole('listitem');
    const link = within(item).getByRole('link');
    const badge = within(link).getByText('Хит');
    expect(badge.tagName).toBe('SPAN');
    expect(badge).not.toHaveAttribute('role');
    expect(badge).toHaveClass('bg-accent-50', 'text-accent-800');
    expect(link).toHaveAccessibleName('Маргарита Хит от 550 сом');
    expect(within(item).getAllByRole('link')).toHaveLength(1);
    expect(within(item).queryAllByRole('button')).toHaveLength(0);
  });

  it('is_featured: false shows no badge and keeps the link name', async () => {
    renderGrid([{ ...MARGHERITA_SUMMARY, is_featured: false }], { layout: 'catalog' });
    const list = await screen.findByRole('list', { name: 'Блюда' });
    expect(within(list).queryByText('Хит')).toBeNull();
    expect(within(list).getByRole('link')).toHaveAccessibleName('Маргарита от 550 сом');
  });

  it('a missing or non-boolean is_featured shows no badge', async () => {
    const missing = { ...MARGHERITA_SUMMARY, id: 'p-missing' } as Partial<ProductSummary>;
    delete missing.is_featured;
    const wrongType = {
      ...PEPPERONI_SUMMARY,
      is_featured: 'true',
    } as unknown as ProductSummary;
    renderGrid([missing as ProductSummary, wrongType], { layout: 'catalog' });
    const list = await screen.findByRole('list', { name: 'Блюда' });
    expect(within(list).queryByText('Хит')).toBeNull();
    const links = within(list).getAllByRole('link');
    expect(links[0]).toHaveAccessibleName('Маргарита от 550 сом');
    expect(links[1]).toHaveAccessibleName('Пепперони (говяжья) от 650 сом');
  });

  it('featured and unavailable: both badges, availability first, image muted', async () => {
    renderGrid([HIT_SOLD_OUT], { layout: 'catalog' });
    const list = await screen.findByRole('list', { name: 'Блюда' });
    const link = within(list).getByRole('link');
    const unavailable = within(link).getByText('Нет в наличии');
    const hit = within(link).getByText('Хит');
    expect(within(link).getAllByText('Нет в наличии')).toHaveLength(1);
    expect(
      unavailable.compareDocumentPosition(hit) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(unavailable.parentElement).toBe(hit.parentElement);
    expect(link).toHaveAccessibleName('Чизбургер Нет в наличии Хит');
    const frame = link.firstElementChild as HTMLElement;
    expect(frame.firstElementChild).toHaveClass('dish-plate-muted');
    expect(frame.contains(hit)).toBe(false);
    expect(within(list).queryAllByRole('button')).toHaveLength(0);
  });

  it.each([
    ['ky', 'Хит'],
    ['uz', 'Xit'],
  ])('is translated in %s', async (language, text) => {
    renderGrid([HIT], { layout: 'catalog' });
    await screen.findByRole('list', { name: 'Блюда' });
    await act(() => i18n.changeLanguage(language));
    expect(screen.getByText(text)).toHaveClass('bg-accent-50');
  });

  it('the classic home card shows no badge for a featured dish', async () => {
    renderGrid([HIT]);
    const list = await screen.findByRole('list', { name: 'Блюда' });
    expect(within(list).queryByText('Хит')).toBeNull();
    expect(within(list).getByRole('link').className).toBe(CLASSIC_LINK);
  });
});
