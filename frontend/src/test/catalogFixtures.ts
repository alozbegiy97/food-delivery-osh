import type {
  CategoryOut,
  ProductDetail,
  ProductSummary,
  RestaurantOut,
} from '../shared/types/api';

// Shapes copied from real sandbox API answers (demo seed), trimmed for tests.

export const CATEGORIES: CategoryOut[] = [
  {
    id: 'cat-pizza',
    slug: 'pizza',
    name: 'Пицца',
    description: null,
    image_url: null,
    sort_order: 0,
  },
  {
    id: 'cat-burgers',
    slug: 'burgers',
    name: 'Бургеры',
    description: null,
    image_url: null,
    sort_order: 1,
  },
  {
    id: 'cat-shawarma',
    slug: 'shawarma',
    name: 'Шаурма',
    description: null,
    image_url: null,
    sort_order: 3,
  },
];

const summary = (overrides: Partial<ProductSummary>): ProductSummary => ({
  id: 'p',
  slug: 'p',
  category_id: 'cat-pizza',
  name: 'P',
  description: null,
  image_url: null,
  is_available: true,
  is_featured: false,
  price_from: '100.00',
  ...overrides,
});

export const MARGHERITA_SUMMARY = summary({
  id: 'p-margherita',
  slug: 'demo-pizza-margherita',
  name: 'Маргарита',
  price_from: '550.00',
});
export const PEPPERONI_SUMMARY = summary({
  id: 'p-pepperoni',
  slug: 'demo-pizza-pepperoni-beef',
  name: 'Пепперони (говяжья)',
  price_from: '650.00',
});
export const BURGER_SUMMARY = summary({
  id: 'p-burger',
  slug: 'demo-burger-classic',
  category_id: 'cat-burgers',
  name: 'Классический бургер',
  price_from: '280.00',
});
export const SOLD_OUT_SUMMARY = summary({
  id: 'p-sold-out',
  slug: 'demo-sold-out',
  category_id: 'cat-burgers',
  name: 'Чизбургер',
  is_available: false,
  price_from: null,
});

export function productList(items: ProductSummary[], page = 1, pages = 1, total = items.length) {
  return { items, pagination: { page, page_size: 12, total, pages } };
}

export const MARGHERITA: ProductDetail = {
  ...MARGHERITA_SUMMARY,
  images: [],
  variants: [
    { id: 'v-30', name: '30 см', price: '550.00', is_available: true },
    { id: 'v-40', name: '40 см', price: '750.00', is_available: true },
  ],
  modifier_groups: [
    {
      id: 'g-dough',
      name: 'Тесто',
      description: null,
      selection_type: 'single',
      is_required: true,
      min_selections: 1,
      max_selections: 1,
      modifiers: [
        {
          id: 'm-thin',
          name: 'Тонкое тесто',
          description: null,
          price_delta: '0.00',
          max_quantity: 1,
          is_available: true,
          variant_prices: [],
        },
        {
          id: 'm-classic',
          name: 'Традиционное тесто',
          description: null,
          price_delta: '0.00',
          max_quantity: 1,
          is_available: true,
          variant_prices: [],
        },
      ],
    },
    {
      id: 'g-extras',
      name: 'Добавки',
      description: null,
      selection_type: 'multiple',
      is_required: false,
      min_selections: 0,
      max_selections: 3,
      modifiers: [
        {
          id: 'm-cheese',
          name: 'Сыр',
          description: null,
          price_delta: '60.00',
          max_quantity: 2,
          is_available: true,
          variant_prices: [{ variant_id: 'v-40', price_delta: '80.00' }],
        },
        {
          id: 'm-mushrooms',
          name: 'Грибы',
          description: null,
          price_delta: '50.00',
          max_quantity: 1,
          is_available: true,
          variant_prices: [{ variant_id: 'v-40', price_delta: '70.00' }],
        },
        {
          id: 'm-jalapeno',
          name: 'Халапеньо',
          description: null,
          price_delta: '40.00',
          max_quantity: 1,
          is_available: true,
          variant_prices: [{ variant_id: 'v-40', price_delta: '60.00' }],
        },
        {
          id: 'm-olives',
          name: 'Оливки',
          description: null,
          price_delta: '45.00',
          max_quantity: 1,
          is_available: false,
          variant_prices: [],
        },
      ],
    },
  ],
};

export const BURGER: ProductDetail = {
  ...BURGER_SUMMARY,
  images: [],
  variants: [{ id: 'v-std', name: 'Стандарт', price: '280.00', is_available: true }],
  modifier_groups: [],
};

export const SHAWARMA: ProductDetail = {
  ...summary({
    id: 'p-shawarma',
    category_id: 'cat-shawarma',
    name: 'Шаурма с курицей',
    price_from: '220.00',
  }),
  images: [],
  variants: [
    { id: 'v-std-sh', name: 'Стандарт', price: '220.00', is_available: true },
    { id: 'v-big-sh', name: 'Большая', price: '280.00', is_available: true },
  ],
  modifier_groups: [
    {
      id: 'g-sauce',
      name: 'Соус',
      description: null,
      selection_type: 'single',
      is_required: false,
      min_selections: 0,
      max_selections: 1,
      modifiers: [
        {
          id: 'm-garlic',
          name: 'Чесночный соус',
          description: null,
          price_delta: '0.00',
          max_quantity: 1,
          is_available: true,
          variant_prices: [],
        },
        {
          id: 'm-hot',
          name: 'Острый соус',
          description: null,
          price_delta: '0.00',
          max_quantity: 1,
          is_available: true,
          variant_prices: [],
        },
      ],
    },
  ],
};

export const RESTAURANT_OPEN: RestaurantOut = {
  name: 'Demo Restaurant — Osh',
  phone: '+996000000000',
  address: 'Демонстрационный адрес, г. Ош',
  latitude: null,
  longitude: null,
  timezone: 'Asia/Bishkek',
  min_order_amount: '300.00',
  delivery_enabled: true,
  pickup_enabled: true,
  is_open_now: true,
  next_opening_at: null,
  working_hours: Array.from({ length: 7 }, (_, weekday) => ({
    weekday,
    opens_at: '10:00',
    closes_at: '23:00',
    is_closed: false,
  })),
};

export const RESTAURANT_CLOSED: RestaurantOut = {
  ...RESTAURANT_OPEN,
  is_open_now: false,
  // Thursday 2026-11-12 10:00 in Asia/Bishkek (UTC+6).
  next_opening_at: '2026-11-12T10:00:00+06:00',
};
