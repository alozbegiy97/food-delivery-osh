// MA-4.4.2: the profile page of the Mini App `/tg/account` (DEC-160 пп. 1–4,
// 6): read only — name, phone, email, language and the saved addresses.
// Only the mocked API is used; nothing is changed anywhere.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AppProviders } from '../../app/providers/AppProviders';
import { miniAppRoutes } from '../../app/router/miniAppRoutes';
import { makeStore } from '../../app/store/store';
import i18n from '../../shared/i18n';
import type { AddressOut } from '../../shared/types/api';
import { mockFetchRoutes, type RecordedRequest } from '../../test/fetchRoutes';
import { BASE } from '../../test/orderFixtures';
import { apiError, jsonResponse } from '../../test/renderWithProviders';
import { installTelegram, openAt, uninstallTelegram } from '../../test/telegramMock';
import { profileApi } from '../profile/profileApi';

type Routes = Parameters<typeof mockFetchRoutes>[0];

const PROFILE = 'GET /api/v1/users/me';
const ADDRESSES = 'GET /api/v1/users/me/addresses';

function me(extra: Record<string, unknown> = {}) {
  return () =>
    jsonResponse({
      id: 'u-1',
      email: 'buyer@example.com',
      full_name: 'Айбек Токтогулов',
      phone: '+996700123456',
      preferred_language: 'ru',
      roles: ['customer'],
      must_change_password: false,
      has_password: true,
      ...extra,
    });
}

function address(extra: Partial<AddressOut> = {}): AddressOut {
  return {
    id: 'a-1',
    label: 'Дом',
    address_text: 'ул. Ленина, 1',
    latitude: '40.5283',
    longitude: '72.7985',
    entrance: '2',
    floor: '3',
    apartment: '15',
    comment: 'Домофон не работает',
    is_default: true,
    created_at: '2026-11-12T06:00:00Z',
    updated_at: '2026-11-12T06:00:00Z',
    ...extra,
  };
}

function addressList(items: AddressOut[]) {
  return () =>
    jsonResponse({
      items,
      pagination: { page: 1, page_size: 100, total: items.length, pages: items.length ? 1 : 0 },
    });
}

function signedIn(routes: Routes = {}): Routes {
  return {
    ...BASE,
    'POST /api/v1/auth/telegram/webapp': () =>
      jsonResponse({ access_token: 'mini', token_type: 'bearer', expires_in: 900 }),
    [PROFILE]: me(),
    [ADDRESSES]: addressList([]),
    ...routes,
  };
}

function launch(path = '/tg/account', store = makeStore()) {
  openAt(path);
  const router = createMemoryRouter(miniAppRoutes, { initialEntries: [path], basename: '/tg' });
  render(
    <AppProviders store={store}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}

function details() {
  return screen.getByRole('region', { name: 'Личные данные' });
}

function addresses() {
  return screen.getByRole('region', { name: 'Сохранённые адреса' });
}

/** The value (the first dd) that follows the term (dt) with this text. */
function valueOf(term: string): string {
  const dt = within(details()).getByText(term, { selector: 'dt' });
  return dt.nextElementSibling?.textContent ?? '';
}

function profileCalls(calls: RecordedRequest[]) {
  return calls.filter((c) => c.path === '/api/v1/users/me');
}

function addressCalls(calls: RecordedRequest[]) {
  return calls.filter((c) => c.path === '/api/v1/users/me/addresses');
}

beforeEach(() => {
  installTelegram();
});

afterEach(() => {
  uninstallTelegram();
  openAt('/');
});

describe('the profile page', () => {
  it('shows name, formatted phone, read-only email and language; only "Изменить", no forms or site links', async () => {
    mockFetchRoutes(signedIn());
    const router = launch();
    expect(await screen.findByRole('heading', { level: 1, name: 'Профиль' })).toBeInTheDocument();
    await waitFor(() => expect(valueOf('Имя')).toBe('Айбек Токтогулов'));
    expect(valueOf('Телефон')).toBe('+996 700 12 34 56');
    expect(valueOf('Email')).toBe('buyer@example.com');
    expect(valueOf('Язык интерфейса')).toBe('Русский');
    expect(within(details()).getByText('Язык меняется вверху экрана.')).toBeInTheDocument();

    const main = document.getElementById('main')!;
    expect(main.querySelectorAll('input, textarea, select, form')).toHaveLength(0);
    expect(
      within(main)
        .getAllByRole('button')
        .map((b) => b.textContent),
    ).toEqual(['Изменить']);
    expect(within(main).queryAllByRole('link')).toHaveLength(0);
    expect(
      screen.queryByRole('link', { name: /пароль|выйти|войти|регистрац/i }),
    ).not.toBeInTheDocument();
    for (const a of document.querySelectorAll('a[href]')) {
      expect(a.getAttribute('href')).toMatch(/^\/tg\//); // only the Mini App tabs
    }
    expect(router.state.location.pathname).toBe('/tg/account');
  });

  it('a Telegram-only account: no phone and no email yet', async () => {
    mockFetchRoutes(signedIn({ [PROFILE]: me({ email: null, phone: null, has_password: false }) }));
    launch();
    await screen.findByRole('region', { name: 'Личные данные' });
    expect(valueOf('Имя')).toBe('Айбек Токтогулов');
    expect(valueOf('Телефон')).toBe('Не указан');
    expect(valueOf('Email')).toBe('Не добавлен');
  });

  it('shows the profile language; the only switcher is the one in the header', async () => {
    mockFetchRoutes(signedIn({ [PROFILE]: me({ preferred_language: 'ky' }) }));
    try {
      launch();
      await waitFor(() => expect(i18n.language).toBe('ky'));
      const region = await screen.findByRole('region', { name: 'Жеке маалыматтар' });
      expect(screen.getByRole('heading', { level: 1, name: 'Профиль' })).toBeInTheDocument();
      expect(within(region).getByText('Кыргызча')).toBeInTheDocument();
      expect(
        within(region).getByText('Тил экрандын жогору жагында өзгөртүлөт.'),
      ).toBeInTheDocument();
      expect(screen.getAllByRole('group', { name: 'Интерфейстин тили' })).toHaveLength(1);
      // The only button of the section is "Изменить", not a language switcher.
      expect(
        within(region)
          .getAllByRole('button')
          .map((b) => b.textContent),
      ).toEqual(['Өзгөртүү']);
    } finally {
      await i18n.changeLanguage('ru');
    }
  });

  it('only GET requests of the profile and the addresses on opening', async () => {
    const { calls } = mockFetchRoutes(signedIn({ [ADDRESSES]: addressList([address()]) }));
    launch();
    await screen.findByRole('list', { name: 'Список сохранённых адресов' });
    expect(profileCalls(calls).length).toBeGreaterThan(0);
    expect(addressCalls(calls).length).toBeGreaterThan(0);
    // The only write is the sign-in exchange of initData.
    const writes = calls.filter((c) => c.method !== 'GET');
    expect(writes.map((c) => c.path)).toEqual(['/api/v1/auth/telegram/webapp']);
  });
});

describe('saved addresses', () => {
  it('are listed read only, with the default one marked in words', async () => {
    mockFetchRoutes(
      signedIn({
        [ADDRESSES]: addressList([
          address(),
          address({
            id: 'a-2',
            label: null,
            address_text: 'ул. Курманжан Датка, 200',
            entrance: null,
            floor: null,
            apartment: null,
            comment: null,
            is_default: false,
          }),
        ]),
      }),
    );
    launch();
    const list = await screen.findByRole('list', { name: 'Список сохранённых адресов' });
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(2);

    expect(within(items[0]).getByText('Дом')).toBeInTheDocument();
    expect(within(items[0]).getByText('Основной')).toBeInTheDocument();
    expect(within(items[0]).getByText('ул. Ленина, 1')).toBeInTheDocument();
    expect(within(items[0]).getByText('подъезд 2, этаж 3, кв. 15')).toBeInTheDocument();
    expect(within(items[0]).getByText('Домофон не работает')).toBeInTheDocument();

    expect(within(items[1]).getByText('ул. Курманжан Датка, 200')).toBeInTheDocument();
    expect(within(items[1]).queryByText('Основной')).not.toBeInTheDocument();

    expect(within(addresses()).queryAllByRole('button')).toHaveLength(0);
    expect(within(addresses()).queryAllByRole('link')).toHaveLength(0);
    expect(screen.queryByText('40.5283')).not.toBeInTheDocument(); // no coordinates
  });

  it('an empty list explains where an address comes from', async () => {
    mockFetchRoutes(signedIn());
    launch();
    expect(await screen.findByText('Сохранённых адресов нет')).toBeInTheDocument();
    expect(
      screen.getByText('Адрес сохраняется при оформлении заказа с доставкой.'),
    ).toBeInTheDocument();
  });

  it('a loading error keeps the details; "Повторить" reloads only the addresses', async () => {
    const { calls } = mockFetchRoutes(
      signedIn({
        [ADDRESSES]: [() => apiError('INTERNAL_ERROR', 500), addressList([address()])],
      }),
    );
    launch();
    const region = await screen.findByRole('region', { name: 'Сохранённые адреса' });
    const alert = await within(region).findByRole('alert');
    expect(alert).toHaveTextContent('Не удалось загрузить адреса');
    expect(valueOf('Имя')).toBe('Айбек Токтогулов');
    const profileBefore = profileCalls(calls).length;

    fireEvent.click(within(alert).getByRole('button', { name: 'Повторить' }));
    expect(
      await screen.findByRole('list', { name: 'Список сохранённых адресов' }),
    ).toBeInTheDocument();
    expect(addressCalls(calls)).toHaveLength(2);
    expect(profileCalls(calls)).toHaveLength(profileBefore);
    expect(valueOf('Имя')).toBe('Айбек Токтогулов');
  });
});

describe('profile errors', () => {
  it('a profile error shows only that error, no addresses; "Повторить" loads the page', async () => {
    const { calls } = mockFetchRoutes(
      signedIn({ [PROFILE]: [() => apiError('INTERNAL_ERROR', 500), me()] }),
    );
    launch();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Не удалось загрузить профиль');
    expect(screen.getByRole('heading', { level: 1, name: 'Профиль' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Сохранённые адреса' })).not.toBeInTheDocument();
    expect(addressCalls(calls)).toHaveLength(0);

    fireEvent.click(within(alert).getByRole('button', { name: 'Повторить' }));
    await waitFor(() => expect(valueOf('Имя')).toBe('Айбек Токтогулов'));
    expect(await screen.findByText('Сохранённых адресов нет')).toBeInTheDocument();
    expect(addressCalls(calls)).toHaveLength(1);
  });
});

const PATCH = 'PATCH /api/v1/users/me';
type Handler = (request: RecordedRequest) => Response | Promise<Response>;

/** GET /users/me answers the latest saved profile; PATCH merges its body. */
function editable(initial: Record<string, unknown> = {}): Routes & { [PATCH]: Handler } {
  let state = { ...initial };
  return {
    [PROFILE]: () => me(state)(),
    [PATCH]: (request) => {
      state = { ...state, ...(request.body as Record<string, unknown>) };
      return me(state)();
    },
  };
}

function patchBodies(calls: RecordedRequest[]) {
  return calls
    .filter((c) => c.method === 'PATCH' && c.path === '/api/v1/users/me')
    .map((c) => c.body);
}

async function openForm(edit = 'Изменить') {
  fireEvent.click(await screen.findByRole('button', { name: edit }));
}

function nameInput() {
  return screen.getByLabelText('Имя');
}

function phoneInput() {
  return screen.getByLabelText('Телефон');
}

function type(input: HTMLElement, value: string) {
  fireEvent.change(input, { target: { value } });
}

function save(name = 'Сохранить') {
  fireEvent.click(screen.getByRole('button', { name }));
}

describe('editing the name and the phone', () => {
  it('"Изменить" opens the form with the current values; email and language stay read only', async () => {
    mockFetchRoutes(signedIn());
    launch();
    await openForm();
    expect(nameInput()).toHaveValue('Айбек Токтогулов');
    expect(phoneInput()).toHaveValue('+996 700 12 34 56');
    expect(screen.getByRole('button', { name: 'Отмена' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Изменить' })).not.toBeInTheDocument();
    expect(valueOf('Email')).toBe('buyer@example.com');
    expect(valueOf('Язык интерфейса')).toBe('Русский');
    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument();
  });

  it('only the changed name is sent; success is shown after the answer', async () => {
    const { calls } = mockFetchRoutes(signedIn(editable()));
    launch();
    await openForm();
    type(nameInput(), '  Нурлан Асанов  ');
    save();
    expect(await within(details()).findByRole('status')).toHaveTextContent('Данные сохранены');
    expect(patchBodies(calls)).toEqual([{ full_name: 'Нурлан Асанов' }]);
    await waitFor(() => expect(valueOf('Имя')).toBe('Нурлан Асанов'));
    expect(valueOf('Телефон')).toBe('+996 700 12 34 56');
    expect(screen.getByRole('button', { name: 'Изменить' })).toHaveFocus();
  });

  it('a new phone replaces the old one; only the phone is sent', async () => {
    const { calls } = mockFetchRoutes(signedIn(editable()));
    launch();
    await openForm();
    type(phoneInput(), '0555 99 88 77');
    expect(phoneInput()).toHaveValue('+996 555 99 88 77');
    save();
    await within(details()).findByRole('status');
    expect(patchBodies(calls)).toEqual([{ phone: '+996 555 99 88 77' }]);
    await waitFor(() => expect(valueOf('Телефон')).toBe('+996 555 99 88 77'));
  });

  it('no phone yet: an empty field means "do not change", the phone is not sent', async () => {
    const { calls } = mockFetchRoutes(
      signedIn(editable({ email: null, phone: null, has_password: false })),
    );
    launch();
    await openForm();
    expect(phoneInput()).toHaveValue('');
    type(nameInput(), 'Нурлан');
    save();
    await within(details()).findByRole('status');
    const bodies = patchBodies(calls);
    expect(bodies).toEqual([{ full_name: 'Нурлан' }]);
    expect(bodies[0]).not.toHaveProperty('phone');
    expect(valueOf('Телефон')).toBe('Не указан');
  });

  it('no phone yet: a typed phone is added', async () => {
    const { calls } = mockFetchRoutes(signedIn(editable({ phone: null })));
    launch();
    await openForm();
    type(phoneInput(), '700112233');
    save();
    await within(details()).findByRole('status');
    expect(patchBodies(calls)).toEqual([{ phone: '+996 700 11 22 33' }]);
    await waitFor(() => expect(valueOf('Телефон')).toBe('+996 700 11 22 33'));
  });

  it('an existing phone cannot be removed: error, no request, the form stays open', async () => {
    const { calls } = mockFetchRoutes(signedIn(editable()));
    launch();
    await openForm();
    type(phoneInput(), '');
    save();
    expect(
      await screen.findByText('Телефон можно заменить, но нельзя удалить'),
    ).toBeInTheDocument();
    expect(phoneInput()).toHaveAttribute('aria-invalid', 'true');
    expect(patchBodies(calls)).toEqual([]);
    expect(calls.some((c) => (c.body as { phone?: unknown } | undefined)?.phone === null)).toBe(
      false,
    );
  });

  it('client rules of DEC-141: empty or too long name, incomplete phone; nothing is sent', async () => {
    const { calls } = mockFetchRoutes(signedIn(editable()));
    launch();
    await openForm();
    type(nameInput(), '   ');
    type(phoneInput(), '700 12');
    save();
    expect(await screen.findByText('Заполните поле')).toBeInTheDocument();
    expect(screen.getByText('Введите номер полностью: +996 и 9 цифр')).toBeInTheDocument();

    type(nameInput(), 'а'.repeat(151));
    save();
    expect(await screen.findByText('Имя должно быть не длиннее 150 символов')).toBeInTheDocument();
    expect(patchBodies(calls)).toEqual([]);
  });

  it('nothing changed: the form closes without a request and without a message', async () => {
    const { calls } = mockFetchRoutes(signedIn(editable()));
    launch();
    await openForm();
    save();
    expect(await screen.findByRole('button', { name: 'Изменить' })).toHaveFocus();
    expect(patchBodies(calls)).toEqual([]);
    expect(within(details()).queryByRole('status')).not.toBeInTheDocument();
  });

  it('a 422 with field details is shown under the field; typed values are kept', async () => {
    mockFetchRoutes(
      signedIn({
        ...editable(),
        [PATCH]: () => apiError('VALIDATION_ERROR', 422, [{ field: 'phone', message: 'x' }]),
      }),
    );
    launch();
    await openForm();
    type(nameInput(), 'Нурлан');
    type(phoneInput(), '700 99 99 99');
    save();
    expect(await screen.findByText('Введите номер полностью: +996 и 9 цифр')).toBeInTheDocument();
    expect(within(details()).queryByRole('alert')).not.toBeInTheDocument();
    expect(within(details()).queryByRole('status')).not.toBeInTheDocument();
    expect(nameInput()).toHaveValue('Нурлан');
    expect(phoneInput()).toHaveValue('+996 700 99 99 99');
  });

  it('a server error keeps the form open with the values; saving again works', async () => {
    const routes = editable();
    const { calls } = mockFetchRoutes(
      signedIn({ ...routes, [PATCH]: [() => apiError('INTERNAL_ERROR', 500), routes[PATCH]] }),
    );
    launch();
    await openForm();
    type(nameInput(), 'Нурлан');
    save();
    expect(await within(details()).findByRole('alert')).toBeInTheDocument();
    expect(within(details()).queryByRole('status')).not.toBeInTheDocument();
    expect(nameInput()).toHaveValue('Нурлан');

    save();
    expect(await within(details()).findByRole('status')).toHaveTextContent('Данные сохранены');
    expect(patchBodies(calls)).toEqual([{ full_name: 'Нурлан' }, { full_name: 'Нурлан' }]);
    await waitFor(() => expect(valueOf('Имя')).toBe('Нурлан'));
  });

  it('"Отмена" closes the form without a request and keeps the data', async () => {
    const { calls } = mockFetchRoutes(signedIn(editable()));
    launch();
    await openForm();
    type(nameInput(), 'Нурлан');
    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));
    expect(await screen.findByRole('button', { name: 'Изменить' })).toHaveFocus();
    expect(valueOf('Имя')).toBe('Айбек Токтогулов');
    expect(patchBodies(calls)).toEqual([]);

    await openForm(); // opens again with the saved values, not the typed ones
    expect(nameInput()).toHaveValue('Айбек Токтогулов');
  });

  it('while saving the buttons are disabled and no success is shown', async () => {
    const routes = editable();
    let release!: () => void;
    mockFetchRoutes(
      signedIn({
        ...routes,
        [PATCH]: (request) =>
          new Promise<Response>((resolve) => {
            release = () => resolve(routes[PATCH](request));
          }),
      }),
    );
    launch();
    await openForm();
    type(nameInput(), 'Нурлан');
    save();
    expect(await screen.findByRole('button', { name: 'Сохраняем…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Отмена' })).toBeDisabled();
    expect(screen.queryByText('Данные сохранены')).not.toBeInTheDocument();

    release();
    expect(await screen.findByText('Данные сохранены')).toBeInTheDocument();
  });

  it('a profile reload (language change in the header) keeps the typed values; the language is never sent by the form', async () => {
    const { calls } = mockFetchRoutes(signedIn(editable()));
    try {
      launch();
      await openForm();
      type(nameInput(), 'Нурлан');
      type(phoneInput(), '555 11 22 33');
      const switcher = screen.getByRole('group', { name: 'Язык интерфейса' });
      fireEvent.click(within(switcher).getByRole('button', { name: 'Кыргызча' }));
      await waitFor(() => expect(i18n.language).toBe('ky'));
      expect(patchBodies(calls)).toEqual([{ preferred_language: 'ky' }]);

      expect(screen.getByLabelText('Аты')).toHaveValue('Нурлан');
      expect(screen.getByLabelText('Телефон')).toHaveValue('+996 555 11 22 33');
      save('Сактоо');
      const region = screen.getByRole('region', { name: 'Жеке маалыматтар' });
      expect(await within(region).findByRole('status')).toHaveTextContent('Маалыматтар сакталды');
      expect(patchBodies(calls)).toEqual([
        { preferred_language: 'ky' },
        { full_name: 'Нурлан', phone: '+996 555 11 22 33' },
      ]);
    } finally {
      await i18n.changeLanguage('ru');
    }
  });

  it('a failed background profile reload keeps the page and the open form with the typed values', async () => {
    // The first GET /users/me succeeds; any reload fails. RTK Query keeps the
    // last data with isError, so the page must not switch to ErrorState.
    let loaded = false;
    mockFetchRoutes(
      signedIn({
        [PROFILE]: () => {
          if (loaded) {
            return apiError('INTERNAL_ERROR', 500);
          }
          loaded = true;
          return me()();
        },
      }),
    );
    const store = makeStore();
    launch('/tg/account', store);
    await openForm();
    type(nameInput(), 'Нурлан');
    type(phoneInput(), '555 11 22 33');

    // A background reload of the profile, as after any change of `Me`.
    store.dispatch(profileApi.util.invalidateTags(['Me']));
    await waitFor(() =>
      expect(profileApi.endpoints.getProfile.select()(store.getState()).isError).toBe(true),
    );

    expect(screen.queryByRole('alert')).not.toBeInTheDocument(); // no ErrorState
    expect(details()).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Отмена' })).toBeInTheDocument(); // form open
    expect(nameInput()).toHaveValue('Нурлан');
    expect(phoneInput()).toHaveValue('+996 555 11 22 33');
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeInTheDocument();
  });
});

describe('translations', () => {
  it.each([
    [
      'uz',
      'Profil',
      'Shaxsiy maʼlumotlar',
      'Saqlangan manzillar',
      ['Oʻzgartirish', 'Saqlash', 'Bekor qilish'],
    ],
    [
      'ky',
      'Профиль',
      'Жеке маалыматтар',
      'Сакталган даректер',
      ['Өзгөртүү', 'Сактоо', 'Жокко чыгаруу'],
    ],
  ])(
    '%s: title, sections and the form buttons',
    async (language, title, detailsTitle, addressesTitle, [edit, saveLabel, cancel]) => {
      mockFetchRoutes(signedIn({ [PROFILE]: me({ preferred_language: language }) }));
      try {
        launch();
        await waitFor(() => expect(i18n.language).toBe(language));
        expect(await screen.findByRole('heading', { level: 1, name: title })).toBeInTheDocument();
        expect(
          await screen.findByRole('heading', { level: 2, name: detailsTitle }),
        ).toBeInTheDocument();
        expect(screen.getByRole('heading', { level: 2, name: addressesTitle })).toBeInTheDocument();
        await openForm(edit);
        expect(screen.getByRole('button', { name: saveLabel })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: cancel })).toBeInTheDocument();
      } finally {
        await i18n.changeLanguage('ru');
      }
    },
  );
});
