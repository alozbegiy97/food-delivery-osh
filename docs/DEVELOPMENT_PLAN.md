# DEVELOPMENT_PLAN.md

## Общий принцип

Разрабатывать вертикальными этапами. После каждого этапа --- тесты,
краткий отчёт и подтверждение перед следующим крупным этапом. Не
генерировать весь продукт одним запросом. Все этапы следуют
`docs/DECISIONS.md` (ссылки `DEC-NN`).

## Этап 0 --- аудит документации (выполнен)

Прочитаны все MD, найдены противоречия и открытые решения (checkout
payload, order status transitions, courier assignment states, mock
payment lifecycle, refresh-cookie CSRF, Telegram outbox и др.).
Решения зафиксированы в `docs/DECISIONS.md`, документы приведены в
соответствие. Оставшиеся открытые вопросы перечислены в
`DECISIONS.md` и закрываются до этапа, которому они нужны.

## Этап 1 --- инфраструктура (выполнен, 2026-11-07)

-   Git: `git init`, `.gitignore` (DEC-05).
-   Backend: FastAPI app, settings/env (включая сроки токенов, rate
    limits, таймаут оплаты), DB connection, Alembic, healthcheck,
    logging (без секретов и токенов), request ID, единый error handler
    (DEC-73).
-   Frontend: Vite React TS, Router, Redux store, RTK Query base API,
    Tailwind (design tokens), i18next (RU/KY/UZ).
-   Infra: Dockerfiles, Docker Compose в режимах `dev` (hot reload) и
    `demo` (nginx, production-сборка) (DEC-04); PostgreSQL/PostGIS,
    отдельная тестовая БД с PostGIS (DEC-69), Mailpit, заготовка
    сервиса worker (один экземпляр, DEC-104); API --- один процесс и
    один Uvicorn worker (DEC-95); Vite proxy / nginx для единого origin
    (DEC-68); `.env.example`, README.
-   Зависимости только из согласованного списка (DEC-94); версии
    зафиксированы в lock-файлах backend и frontend; `ruff`, ESLint,
    Prettier настроены.

Done: `docker compose up` в обоих режимах, frontend открывается, backend
healthcheck, migration на чистой БД, тестовые Pytest и Vitest
запускаются, линтеры проходят.

### Итоги этапа 1

Окружение: Docker 29.9.2, Compose v5.6.1; образы
`python:3.14.10-slim-trixie`, `node:24.22.2-alpine`,
`postgis/postgis:16-3.6` (PostgreSQL 16.15, PostGIS 3.6.4),
`nginx:1.30.6-alpine`, `axllent/mailpit:v1.31.6`. Python-зависимости
зафиксированы в `uv.lock` (SQLAlchemy ограничен линейкой 2.0), frontend
--- в `package-lock.json`.

Интеграционные проверки (все пройдены):

| # | Проверка | Результат |
|---|---|---|
| 1 | Запуск `dev` | все сервисы `running`, healthchecks `healthy` |
| 2 | Backend и frontend | health, единый формат ошибок, `X-Request-ID`, Vite proxy (единый origin), Mailpit |
| 3 | Hot reload | backend: StatReload перезапускает приложение; frontend: Vite HMR |
| 4 | PostgreSQL + PostGIS | PostGIS доступен; до миграции не установлен (init-скрипт образа подменён) |
| 5 | Alembic | основная БД --- только `upgrade head`; `db-test` --- цикл `upgrade → downgrade → upgrade` |
| 6 | Тесты на `db-test` | pytest 18 passed; ruff; Vitest 10 passed; lint, Prettier, typecheck, build |
| 7 | Запуск `demo` | prod-образы, `APP_ENV=demo`, non-root, один Uvicorn worker, опубликован только `127.0.0.1:8080` |
| 8 | Demo через nginx | SPA и fallback маршрутов, `/api` через тот же origin, docs выключены, порты 8000/5432 закрыты, security-заголовки, один `Cache-Control` для `/assets/` |
| 9 | Worker и SIGTERM | в `dev` и `demo`: `Worker stopped`, код выхода 0, без SIGKILL |

Дополнительно: утверждены коды ошибок DEC-115; из `uv.lock` убрано
ограничение `exclude-newer`; исправлен двойной `Cache-Control` в nginx.

Ограничения: отрисовка в браузере не проверялась (только HTTP и
тесты; Playwright --- позже по плану); у хоста мало свободной памяти
(около 1 ГБ при ~3 ГБ у Docker Desktop), фоновые сборки могут
прерываться.

## Этап 2 --- БД

SQLAlchemy 2.0 models, Alembic migrations, indexes/constraints (включая
CHECK'и D1–D12 и partial indexes), PostGIS, sequence
`order_number_seq`, таблицы `idempotency_keys` и `telegram_outbox`.
Seed: roles, payment methods, settings, working hours, демонстрационная
зона доставки Оша (DEC-76), демо-каталог (у каждого товара минимум один
вариант). Проверить relationships и delete behavior. Не использовать
`create_all()` вместо Alembic.

Решения этапа: 7 ревизий `0002`–`0008` (DEC-116), seed CLI `base` /
`demo` без пользователей (DEC-117), демо-данные ресторана, зоны и
каталога (DEC-118…DEC-120; значения подтверждены DEC-124, DEC-125),
`lazy="raise"` (DEC-121), CHECK
`ST_IsValid` (DEC-122), номер заказа в БД без обрезания (DEC-123).
CHECK на `notifications.type` и `telegram_outbox.event_type` с тремя
типами v1 из общего `StrEnum` (DEC-126). Seed: идемпотентность и защиты
(DEC-136), принадлежность demo-записей (DEC-137), UUIDv5 и цели
ON CONFLICT (DEC-138), пересечение зон и виды ошибок (DEC-139).
Миграции и `downgrade`-тесты --- только на `db-test`; основная БД ---
только `upgrade`.

Done: чистая БД создаётся миграциями; seed идемпотентен; downgrade/
upgrade проверены на `db-test`; `alembic check` без расхождений; тест
перехода номера заказа `OSH-999999` → `OSH-1000000`.

### Промежуточные итоги этапа 2 (2026-11-08): миграции `0002`–`0008`

Статус: этап 2 закрыт на `db-test` (2026-11-10): модели, 7 ревизий
схемы и seed (DEC-117…DEC-120, DEC-136…DEC-139) готовы и проверены.
Применение миграций и seed к основной БД --- отдельный шаг по
разрешению владельца проекта; основная БД пока на ревизии
`0001_enable_postgis`.

-   Ревизии: `0002_users`, `0003_restaurant_delivery`, `0004_catalog`,
    `0005_carts`, `0006_orders`, `0007_payments_deliveries`,
    `0008_notifications`; на `db-test` --- 40 таблиц предметной
    области.
-   Дополнительные решения по ходу этапа: индексы FK DEC-127, DEC-134,
    DEC-135; CHECK типов уведомлений по DEC-126 (литералы в миграции,
    сверка с `NotificationType` в тестах).
-   `tests/conftest.py` импортирует `app.db.models_registry`: каждый
    тестовый файл проходит и отдельно.
-   `idempotency_keys.response_body` --- `JSONB(none_as_null=True)`:
    Python `None` записывается как SQL `NULL` (без изменения схемы).

Проверки (все на `db-test`; основная БД не изменялась):

| # | Проверка | Результат |
|---|---|---|
| 1 | Полный pytest (после исправления JSONB) | 316 passed, 0 failed, 0 skipped, exit code 0 (848,68 с) |
| 2 | Цепочка `0001 → 0008`, циклы `downgrade → upgrade` по ревизиям | `test_migrations`: 10 passed |
| 3 | `alembic check` | No new upgrade operations detected |
| 4 | `ruff check`, `ruff format --check` | без замечаний |
| 5 | `uv lock --check` | lock-файл актуален |
| 6 | Основная БД `food_delivery` | только `0001_enable_postgis`, доменных таблиц нет |

Ограничения: явный `None` в `notifications.payload` и
`telegram_outbox.payload` через ORM сохраняется как JSON `null` ---
сервисный слой должен всегда передавать объект; `models_registry`
импортирует seed CLI, сервисы приложения начнут использовать его на
этапе 3; полный pytest идёт около 16 минут при малом объёме свободной
памяти хоста.

### Итоги seed и закрытие этапа 2 (2026-11-10)

-   Модули `backend/app/seeds/`: `common.py` (advisory lock, проверка
    ревизии, UUIDv5, вставки с явными целями ON CONFLICT), `base.py`,
    `demo_data.py`, `demo.py`, CLI `__main__.py`
    (`python -m app.seeds base|demo`; коды выхода 0, 1, 2, 130).
-   Тесты: `test_seeds_common.py`, `test_seeds_base.py`,
    `test_seeds_demo.py`, `test_seeds_cli.py`,
    `test_seeds_cli_smoke.py` (smoke-тест CLI с очисткой только своих
    записей).

Проверки закрытия (тесты и Alembic --- только на `db-test`):

| # | Проверка | Результат |
|---|---|---|
| 1 | Сборка тестов | 454 tests collected |
| 2 | Полный pytest | 454 passed, 0 failed, 0 skipped, exit code 0 (947,84 с; 122 предупреждения `DeprecationWarning` от `alembic.ini`) |
| 3 | `alembic check` на `db-test` | No new upgrade operations detected |
| 4 | `ruff check`, `ruff format --check` | без замечаний (76 файлов) |
| 5 | `uv lock --check` | lock-файл актуален |
| 6 | Основная БД `food_delivery` (только чтение) | ревизия `0001_enable_postgis`; расширения `plpgsql`, `postgis` 3.6.4; объекты только `alembic_version`, `spatial_ref_sys`, `geometry_columns`, `geography_columns` |
| 7 | `db-test` после прогона | 19 таблиц seed и пользователей пусты |
| 8 | Volume `food-delivery_db-data` | не удалён и не пересоздан |

Ограничения seed: цены демо-каталога --- предложения, а не утверждённые
цены ресторана; переводы KY/UZ --- черновики, нужна проверка носителем
языка; seed на основной БД не запускался; известное ограничение
пересечения зон без общей блокировки сервиса зон (DEC-139).

## Этап 3 --- auth/RBAC

Register (роль `customer`)/login/refresh/logout/me, Argon2id, политика
паролей (DEC-96), нормализация телефона (DEC-89), JWT (15 мин), refresh
rotation с `family_id` и строгим отзывом семьи при повторном
использовании без льготного окна (30 дней, DEC-110), password reset
через email (Mailpit, токен 30 мин, одинаковый ответ `202`, отзыв всех
семей после сброса, DEC-108), смена пароля и `must_change_password`
(DEC-28), проверка ролей и `is_active` по БД (DEC-66), CSRF с
`CSRF_FAILED` (DEC-68), rate limits (DEC-80). CLI-команда
`python -m app.cli create-admin` с защитой от параллельного запуска
(DEC-88). Frontend: каркас публичного layout, auth forms, маска
телефона, обязательная смена пароля, protected routes, session refresh
с mutex и `navigator.locks` (DEC-110).

Tests: invalid credentials (одинаковый ответ для неактивного аккаунта),
expired/revoked refresh, reuse detection, role denial, ownership,
`PASSWORD_CHANGE_REQUIRED`, CSRF, rate limit, политика паролей,
нормализация телефона, сброс пароля без раскрытия email,
`create-admin` (повторный и параллельный запуск, создаётся только роль
`admin`).

### Состояние этапа 3 (2026-11-11)

Выполнено и принято: DB-A (READ COMMITTED), DB-B (refresh-сессии),
S3-A (зависимости, настройки, Argon2id, JWT, телефон), S3-B (register,
login, refresh, logout, me, password/change, CSRF, cookie, роли;
DEC-140, DEC-141, DEC-143).

Реализовано 2026-11-11 (ожидает приёмки): S3-C, S3-D и этап 4A ---
состав ниже. Основная БД по-прежнему на ревизии `0001`, поэтому в
запущенном dev-стеке эти функции заработают только после применения
миграций и seed к основной БД (отдельное разрешение).

Состав пакетов:

-   **S3-C** (зависит от S3-B): `python -m app.cli create-admin` с
    собственной advisory-блокировкой (DEC-88); rate limits через
    `slowapi` (DEC-80, DEC-95); password forgot/reset через `smtplib` в
    `BackgroundTasks` и Mailpit (DEC-108, DEC-140); настройки SMTP и
    `FRONTEND_BASE_URL`.
-   **S3-D** (зависит от S3-B; экран сброса пароля --- от S3-C):
    frontend входа и регистрации, обязательная смена пароля, protected
    routes, обновление сессии с `navigator.locks` (DEC-110), README
    (включая `JWT_SECRET_KEY`).

S3-C и S3-D завершаются до начала этапа 4B (DEC-144): без
`create-admin` и входа через frontend каталогом управлять некому.
Этап 4A требует только S3-B и может идти параллельно с ними.

## Порядок этапов 4--11 и параллельность (DEC-144, 2026-11-11)

Два клиентских интерфейса одного продукта:

-   **сайт** --- полноценный клиентский интерфейс в браузере без
    Telegram (DEC-140: вход по email и паролю, refresh-cookie);
-   **Telegram Mini App** --- второй клиентский интерфейс с тем же
    покупательским функционалом (DEC-142: вход по `initData`, без
    cookie).

Оба используют общий backend, API `/api/v1` и бизнес-логику; цены,
зоны, статусы и права frontend не вычисляет. Готовность одного
интерфейса не доказывает готовность другого: у каждого этапа с
клиентским UI отдельные критерии приёмки сайта и Mini App.

Карты --- Leaflet + OpenStreetMap по DEC-01 (вопрос Q-18 решён в
пользу варианта A, DEC-144). Интеграция 2GIS рассматривается
отдельно после проверки условий, стоимости и качества
геокодирования в Оше; DEC-01 не меняется.

Граф зависимостей (DEC-144) по уровням. `←` --- «требует завершения»;
этапы одного уровня, разделённые `‖`, можно вести параллельно:

```
Уровень 0:  S3-B (выполнен)
Уровень 1:  S3-C  ‖  S3-D  ‖  4A                 ← каждый требует только S3-B
Уровень 2:  4B админский CRUD каталога           ← 4A + S3-C + S3-D
            ‖ 4C клиентский frontend каталога    ← 4A + S3-D
Уровень 3:  4C админ-формы каталога              ← 4B
Уровень 4:  5 корзина                            ← этап 4 целиком
Уровень 5:  6 оформление и заказы                ← 5
Уровень 6:  7 оплата                             ← 6
Уровень 7:  8 admin/staff  ‖  MA Telegram Mini App   ← 7
Уровень 8:  9 courier                            ← 8   (MA продолжается параллельно)
            ‖ 10 notifications/Telegram          ← 6 + MA
Уровень 9:  11 QA and demo                       ← все этапы
```

Зависимости списком (совпадают с графом и с разделами этапов):

| Этап | Требует | Можно параллельно с |
|---|---|---|
| S3-C | S3-B | S3-D, 4A |
| S3-D | S3-B | S3-C, 4A |
| 4A публичный каталог | S3-B | S3-C, S3-D |
| 4B админский CRUD каталога | 4A, S3-C, S3-D | клиентская часть 4C |
| 4C frontend каталога | 4A, S3-D; админ-формы --- также 4B | клиентская часть 4C --- с 4B |
| 5 корзина | 4 (4A, 4B, 4C) | --- |
| 6 оформление и заказы | 5 | --- |
| 7 оплата | 6 | --- |
| 8 admin/staff | 7 | MA |
| 9 courier | 8 | MA |
| MA Telegram Mini App | 7 | 8, 9 |
| 10 notifications/Telegram | 6, MA | 9 (после MA) |
| 11 QA and demo | все этапы | --- |

Этап MA можно вести параллельно с этапами 8 и 9: он затрагивает
только клиентские сценарии и вход, а этапы 8--9 --- рабочие экраны
персонала.

## Этап 4 --- catalog/admin CRUD

Categories/translations (деактивация вместо удаления), products/
translations/images (Pillow, JPEG/PNG/WebP ≤ 5 МБ), variants (минимум
один), modifier groups/options (`max_quantity`), variant price
override, validation, `GET /restaurant`. Генерация типов
`openapi-typescript` (DEC-71).

Frontend: home/menu/product detail (степпер модификаторов), каркас
админки с навигацией по ролям (DEC-77), admin forms каталога.

Tests: language fallback, inactive products, min/max (по числу разных
модификаторов), `max_quantity`, variant-product relation, modifier
availability and price override, проверка файлов.

Пицца: размер --- вариант товара; тесто --- обязательная
`single`-группа модификаторов (DEC-128, DEC-144; в demo-seed ---
`pizza-dough`); дополнительные ингредиенты --- `multiple`-группа с
`max_quantity`; цена добавки по размеру --- `variant_modifier_prices`.
Схема БД и demo-seed не меняются.

Подэтапы (зависимости --- DEC-144):

-   4A --- публичное API каталога и `GET /restaurant`; после 4A ---
    генерация `openapi-typescript` типов публичных эндпоинтов
    (DEC-71), на которых строится клиентская часть 4C; требует S3-B,
    можно вести параллельно с S3-C и S3-D;
-   4B --- админский CRUD, изображения, цены по вариантам; после
    появления админских эндпоинтов 4B --- повторная генерация
    `openapi-typescript` типов, включающая их (для админ-форм 4C);
    требует 4A, S3-C и S3-D;
-   4C --- frontend меню и карточки товара (требует 4A и S3-D) и
    админ-формы каталога (дополнительно требуют 4B).

Приёмка сайта: меню и карточка товара работают в браузере без
Telegram на ru/ky/uz; выбор размера, теста и добавок соблюдает
ограничения, цены берутся из API.

### Состояние этапа 4 (2026-11-11)

-   **4A** (публичное API каталога и `GET /restaurant`) --- реализован
    вместе с S3-C и S3-D; ожидает приёмки.
-   **4C, клиентская часть** --- реализована: главная страница, меню
    (категории, поиск, пагинация, состояния загрузки, пустого результата
    и ошибки), страница блюда (размер, обязательное тесто по DEC-128,
    добавки с лимитами и ценами по размеру, предварительная цена), шапка
    и footer с данными ресторана; ru/ky/uz. Данные --- только из API
    через RTK Query и сгенерированные OpenAPI-типы.
-   Проверки 4C пройдены: Vitest 65/65, `tsc`, ESLint, Prettier,
    `npm run build`.
-   Визуальная проверка в браузере ещё не проведена.
-   **4B** (админский CRUD каталога, изображения, цены добавок по
    размерам) и админ-формы 4C --- реализованы 2026-11-11, ожидают
    приёмки (DEC-145): API `/api/v1/admin/...` только для роли `admin`;
    разделы `/admin/categories`, `/admin/products`,
    `/admin/products/new`, `/admin/products/:id`, `/admin/modifiers`.
    Проверено в sandbox-БД; основная БД не изменялась.
-   Корзина и оформление заказа --- этапы 5 и 6: кнопка «В корзину»
    неактивна и не имитирует добавление.

**Приёмка этапа 4 (2026-11-12).** Пользователь вручную проверил в
браузере административную панель 4B (sandbox-БД) и клиентскую часть 4C:
**4B и 4C приняты**. Записи выше сохранены как история состояния на
2026-11-11. Этап 4 завершён; следующий --- этап 5 (корзина).

## Этап 5 --- cart

Единый модуль расчёта цены (DEC-08), server cart, add/update/delete,
объединение позиций (DEC-11), изменение только количества и пожеланий
(DEC-12), UI cart/empty states, переход на вход для гостя (DEC-13).

Tests: persistence after reload, no client price trust, unavailable
modifier rejection, modifier quantity limits, merge, cart ownership.

Приёмка сайта: корзина сохраняется после перезагрузки браузера,
суммы совпадают с ответом API, гость перенаправляется на вход.

### Состояние этапа 5 (2026-11-12)

-   **Реализован и принят (2026-11-12).** Ограничения корзины ---
    DEC-146, правило `subtotal` --- DEC-147. Проверки при приёмке: полный
    pytest на db-test --- 746 passed, 0 failed, 1 skipped (Mailpit не
    успел ответить за 2 с; таймаут проверки доступности увеличен до 5 с,
    тест проходит), EXIT 0; Vitest 77/77, `tsc`, ESLint, Prettier, build;
    проверка в sandbox-БД.
-   Backend: единый модуль расчёта цены и проверки выбора
    `app/modules/pricing` (DEC-08); сервис `app/modules/cart/service.py`
    (блокировка строки корзины на время изменения, объединение по
    DEC-11/DEC-12, пересчёт и перепроверка при каждом чтении); API
    `/api/v1/cart` только для роли `customer`. Миграции не менялись
    (таблицы корзины --- ревизия `0005`).
-   Frontend: количество, пожелания и «В корзину» на странице блюда
    (гость --- на вход с возвратом, DEC-13; сотрудник --- пояснение),
    ссылка «Корзина» с количеством в шапке, страница `/cart` (позиции,
    добавки, пожелания, количество, удаление, очистка, серверные суммы,
    предупреждения о недоступных позициях, пустое состояние). Кнопка
    «Оформить заказ» неактивна до этапа 6.
-   Не входит: quote, оформление, оплата (этапы 6--7), Telegram Mini App
    (этап MA).

## Этап 6 --- checkout/orders

Quote, delivery/pickup, рабочие часы и ночные интервалы, флаги
доставки/самовывоза, zone/minimum checks, `expected_total` и
`PRICE_CHANGED`, транзакция, snapshots на языке клиента, номер заказа,
idempotency (24 часа), платёж `pending` (DEC-78), status history,
state machine статусов с доменными событиями (DEC-79), cancellation
request. Frontend: checkout с картой Leaflet/OSM, order history/detail с
polling 20 секунд.

Tests: in-zone/out-of-zone, pickup without address, min order (зона/
глобальный), closed restaurant, overnight hours, disabled delivery/
pickup, price changed, idempotency replay/conflict/in-progress,
immutable snapshots, no direct customer cancellation, cancellation
request statuses.

Карта на checkout --- Leaflet + OpenStreetMap (DEC-01; Q-18 вариант A,
DEC-144).

Приёмка сайта: полный путь «корзина → адрес на карте → quote → заказ
→ история заказа» в браузере; `PRICE_CHANGED` и вне-зоны показаны
понятно; успех заказа --- только после ответа backend.

### Состояние этапа 6 (2026-11-12)

-   **Реализован, ожидает приёмки.** Решения этапа --- DEC-148 (оплата
    только наличными до этапа 7, адресная книга, лимиты, quote `200` с
    `problems`, idempotency до фоновой очистки, объём сервиса статусов).
-   Backend: адресная книга `/users/me/addresses`; поиск зоны PostGIS
    (`ST_Covers`, DEC-102); общий расчёт quote и заказа
    (`app/modules/orders/checkout.py`) на едином модуле цены (DEC-08);
    `POST /checkout/quote`; `POST /orders` одной транзакцией по §14.1 с
    `Idempotency-Key`; `GET /orders`, `GET /orders/{id}`, запрос отмены;
    сервис статусов (таблица §7.1, история, доменное событие DEC-79 без
    обработчиков). Миграции не менялись.
-   Frontend: `/checkout` с картой Leaflet + OpenStreetMap (`leaflet`
    1.9.4, `react-leaflet` 5.0.0, `@types/leaflet`), выбор сохранённого
    или нового адреса, quote, объяснение проблем, `PRICE_CHANGED` с
    повторным подтверждением, один `Idempotency-Key` на попытку;
    `/orders`, `/orders/:id` (опрос 20 с), запрос отмены; ru/ky/uz.
-   Перенесено: очистка просроченных `idempotency_keys` worker-ом ---
    этап 10; `mock_card` --- этап 7; переходы статусов персоналом ---
    этапы 8--9.

## Этап 7 --- payments

Cash lifecycle (`succeeded` при завершении), mock card lifecycle
(успех/ошибка/повтор), блокировка подтверждения неоплаченного
mock-заказа, фоновая задача таймаута оплаты 30 минут с причиной
`payment_timeout` (DEC-84), refund-имитация при отмене, payment status
UI и экран демо-оплаты.

Tests: mock always simulated, no card data, no false success, retry,
timeout cancellation, unpaid order hidden from queue, one succeeded
payment per order.

Приёмка сайта: наличные и mock card (ошибка → повтор → успех) в
браузере; данные карты не отправляются и не хранятся.

### Состояние этапа 7 (2026-11-12)

-   **Реализован, ожидает приёмки.** Решения этапа --- DEC-149 (снимает
    ограничение DEC-148 п. 1).
-   Backend: `GET /payment-methods`; заказ с `mock_card` (попытка
    `pending`, `is_simulated`, `MOCK-…`, `payment_due_at` + 30 минут);
    `POST /payments/mock/confirm` по `attempt_id` (успех, неудача с новой
    попыткой, повтор с сохранённым результатом, `PAYMENT_NOT_ALLOWED`,
    блокировка заказа); ядро единой операции отмены §14.3
    (`app/modules/orders/cancel.py`); worker: каркас фоновых задач и
    задача таймаута (60 с, пачки по 50, `SKIP LOCKED`, отдельная
    транзакция на заказ). Миграции не менялись.
-   Frontend: выбор способа оплаты на checkout из `GET /payment-methods`;
    экран демо-оплаты `/orders/:id/pay` (предупреждение, без полей карты,
    успех/ошибка, повтор новой попыткой, таймер, истёкший срок, отмена по
    таймауту); попытки оплаты и кнопка «Оплатить» в деталях заказа;
    ru/ky/uz.
-   Перенесено: `cash → succeeded` при завершении --- этапы 8–9;
    прямая отмена, одобрение/отклонение запросов, `rejected` и скрытие
    неоплаченных заказов из очереди --- этап 8; очистка
    `idempotency_keys` --- этап 10.

## Этап MA --- Telegram Mini App (DEC-142, DEC-144, DEC-152)

Требует этапа 7 (каталог, корзина, оформление и оплата готовы);
может выполняться параллельно с этапами 8 и 9. Каждый подэтап --- после
отдельного разрешения, с отчётом.

Состояние: MA-0 (согласование решений, DEC-152) выполнен 2026-11-13;
MA-1 (аккаунты и профиль, DEC-153) реализован 2026-11-13; MA-2 (вход,
регистрация и привязка, DEC-154, DEC-155) реализован 2026-11-14;
MA-3 (ядро Telegram во frontend, DEC-156) реализован 2026-11-14;
MA-4.0 (маршрутизация Mini App, DEC-157) и MA-4.1 (вход и выбор
аккаунта) реализованы 2026-11-14; MA-4.2 (каталог, товар, корзина)
реализован 2026-11-19, сборка frontend опубликована в sandbox;
MA-4.3 (оформление и оплата) реализован 2026-11-19; реализация MA-4.4
(заказы и профиль, DEC-160) завершена 2026-11-21; локальная техническая
приёмка MA-4.5 (автоматические проверки и production build) завершена
2026-11-21; сборка MA-4.4 опубликована в sandbox 2026-11-20 UTC
(MA-4.5.7, DEC-159); ручные
проверки общей приёмки Mini App открыты. MA-4.6.0 (решения по дизайну,
DEC-161) утверждён 2026-11-21; MA-4.6.1 в работе. MA-5, MA-6 не
начаты.

Объём (DEC-152 п. 6): K2-B, `GET/PATCH /users/me`, вход, регистрация и
привязка из Mini App, настройки Telegram, frontend `/tg/*`, nginx.
Процесса бота в MA нет: кнопку Mini App в BotFather настраивает
владелец бота вручную. Бот (long polling, `/start`), `POST
/telegram/link-token`, `GET`/`DELETE /telegram/link`, outbox,
уведомления и `requestWriteAccess` --- этап 10.

Окружение (DEC-152 п. 12): автотесты, включая ревизию `0009`, --- только
на БД `food_delivery_ma_test` в `db-sandbox` (создаётся по отдельному
разрешению; `TEST_DATABASE_URL` только для процесса pytest; проверка
`current_database()`). `food_delivery`, `food_delivery_test`,
`food_delivery_sandbox` и БД прежних этапов не используются. `0009` в
основной БД --- этап 11; в sandbox --- по отдельному разрешению.
Автотесты MA-2 --- только на отдельной БД `food_delivery_ma2_test` в
`db-sandbox` (DEC-154 п. 9); она создаётся по отдельному разрешению, до
этого тесты MA-2 не запускаются.

-   **MA-1. Аккаунты и профиль (backend).** Ревизия `0009`
    (`email`/`password_hash` NULL, CHECK `ck_users_credentials_pair`),
    модель `User`; `POST /auth/credentials`; `409 PASSWORD_NOT_SET`;
    вход и сброс пароля для аккаунта без email; `GET/PATCH /users/me`
    строго по API §4 (DEC-152 п. 9; ответ как у `/auth/me`, `phone:
    null` и пустое тело --- DEC-153); откат `0009` отказывает при
    аккаунтах только с Telegram (DEC-153 п. 3).
    Tests: миграции вверх/вниз и сверка моделей; отказ отката `0009`
    при аккаунте только с Telegram; CHECK пары;
    `/auth/credentials` (занятый email, повтор, одновременные запросы);
    `PASSWORD_NOT_SET`; login/forgot для аккаунта без email;
    `PATCH /users/me` (нормализация телефона, язык, запрет изменения
    email и ролей); регрессия auth сайта.
-   **MA-2. Вход, регистрация и привязка (backend).** Настройки
    `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS`,
    `TELEGRAM_WEBAPP_INIT_DATA_MAX_LENGTH` (4096),
    `TELEGRAM_WEBAPP_CLOCK_SKEW_SECONDS` (60),
    `RATE_LIMIT_TELEGRAM_WEBAPP` (`5/minute`); в `.env.example` и
    `compose.yaml` --- только имена переменных (DEC-154 п. 8). Проверка
    `init_data` по официальному алгоритму HMAC-SHA256 (DEC-154 п. 2);
    `POST /auth/telegram/webapp`, `…/register`, `…/link` (API §2.3,
    DEC-152 пп. 2--4, DEC-154); advisory-блокировка в двухключевой
    форме; `is_active` и `telegram_username` по DEC-154 пп. 3, 4;
    повторная проверка роли в `link` (DEC-154 п. 5); лимиты (общий
    счётчик `/link` и `/auth/login`; `RATE_LIMIT_TELEGRAM_WEBAPP` для
    входа и регистрации). `lock_timeout` 5 секунд в `register` и `link`,
    `409 TELEGRAM_BUSY`; `telegram_username` и длина `init_data` по
    DEC-155. Dockerfile и настройки прокси не меняются. Код:
    `app/modules/telegram_auth/` (`init_data.py`, `locks.py`,
    `service.py`, `schemas.py`, `errors.py`), `app/api/v1/telegram_auth.py`.
    Тесты: `test_telegram_init_data.py` (без БД, эталон HMAC от
    `openssl`), `test_telegram_links_constraints.py`,
    `test_telegram_webapp_api.py`, `test_telegram_webapp_concurrency.py`,
    лимиты --- в `test_rate_limit.py`.
    Tests (БД `food_delivery_ma2_test`): эталонные `init_data` (верная
    подпись, подмена поля, чужой токен бота, просроченный `auth_date`,
    будущий `auth_date` в пределах 60 секунд и сверх них, длина 4096 и
    4097, нет `hash`/`auth_date`/`user`, повторяющиеся ключи, поле
    `signature` входит в строку проверки, `is_bot`, неверный `user`);
    вход без связи --- `409 TELEGRAM_NOT_LINKED` и БД без изменений;
    неактивный пользователь; сотрудник (`403`); бот не настроен;
    `is_active` при создании связи, входе и повторной привязке при
    `allows_write_to_pm` true/false/нет поля; `telegram_username` не
    меняется при входе и повторной привязке; язык (`ru`/`ky`/`uz`,
    `ru-RU`, `en`, нет поля); одновременные запросы --- конкурентные
    тесты MA-2 ниже; `link` с неверным паролем, неизвестным email,
    аккаунтом без email и неактивным аккаунтом --- одинаковый `401`; оба `409` без изменений в БД; повтор
    `link` --- `200` без изменений связи; после `link` имя, телефон,
    язык и заказы не изменились; общий лимит `/link` и `/auth/login`,
    отдельный лимит входа и регистрации; `init_data` и пароль не
    попадают в логи и ответы `422`; без взаимоблокировок; совместимость
    с MA-1 (`/auth/credentials`, `/users/me`, `PASSWORD_NOT_SET`).

    Конкурентные тесты MA-2 (реальные COMMIT; одновременность
    обеспечивается внешней блокировкой и ожиданием ожидающих сессий;
    состояние проверяется отдельным соединением; без взаимоблокировок,
    `lock_timeout`):

    1.  `register` + `register` с одним Telegram ID: оба `200`, токены
        одного пользователя; в БД ровно один новый пользователь, одна
        роль `customer`, одна строка `telegram_links`.
    2.  `register` + `link` (аккаунт сайта A) с одним Telegram ID; порядок
        задаётся явно, а не очередью advisory-блокировки. Первым
        `register` (он держит advisory и ждёт `telegram_links`, `link`
        ждёт advisory): `register` --- `200` (новый пользователь со
        связью), `link` --- `409 TELEGRAM_ALREADY_LINKED`, у A связи нет.
        Первым `link` (он держит advisory и ждёт строку `users`,
        `register` ждёт advisory): `link` --- `200` (связь A), `register`
        --- `200` с токеном A, новый пользователь не создаётся. В обоих
        случаях ровно одна связь этого Telegram ID, не более одного
        нового пользователя, данные A не изменены.
    3.  Два `link` к одному аккаунту A с разными Telegram ID: один `200`,
        другой `409 ACCOUNT_ALREADY_LINKED` (очерёдность --- блокировка
        `users`); у A ровно одна связь, Telegram проигравшего запроса не
        связан ни с кем.
    4.  `link` против деактивации A (деактивация держит строку `users` и
        фиксируется первой): `401 INVALID_CREDENTIALS`, связи нет, A
        неактивен.
    5.  `link` против смены пароля A (смена держит строку `users` и
        фиксируется первой): `401 INVALID_CREDENTIALS`, связи нет,
        сохранён новый хеш.
    6.  `link` против снятия роли `customer` у A (снятие под блокировкой
        `users` фиксируется первым): `403 FORBIDDEN`, полный откат, связи
        нет, роли A не восстановлены и не изменены сверх снятия.
        Для 4--6 также откат конкурента: `link` дожидается его и
        получает `200`.
    7.  Два `link` одной пары одновременно: оба `200`, одна связь,
        username записан один раз; профиль A не изменён.
    8.  Два Telegram ID с одинаковой свёрткой advisory-ключа: запросы
        ждут друг друга, оба `200`, два пользователя и две связи.
    9.  Вход и повторный `link` той же пары одновременно повышают
        `is_active`: оба `200`, одна строка, `TRUE`, username и
        `linked_at` прежние.
    10. `lock_timeout` (DEC-155 п. 1): `register` против удерживаемой
        advisory-блокировки и `link` против удерживаемой строки `users`
        --- `409 TELEGRAM_BUSY` через 5 секунд, БД без изменений,
        следующий запрос того же приложения успешен.
-   **MA-3. Ядро Telegram (frontend).** `features/telegram/`
    (минимальные типы, загрузка официального скрипта SDK только на
    `/tg/*` --- K5-A, `TelegramProvider`, обмен `init_data` с общим
    ожиданием для одновременных `401`); режим Mini App в `baseApi` и
    восстановлении сессии без изменения поведения сайта; макет Mini App;
    тема `themeParams`, `BackButton`, язык (DEC-152 п. 10); экраны
    «перезапустите Mini App» и «только для клиентов».
    Tests: Vitest с подставным `window.Telegram`; все прежние тесты
    сайта проходят без изменений.
    Реализовано (DEC-156): `features/telegram/` (`types`, `sdk`,
    `telegramSlice`, `telegramSession`, `theme`, `useTelegramBackButton`,
    `useMiniAppLanguage`, компоненты `TelegramBootstrap`,
    `TelegramLayout`, `RequireTelegramSession`, `TelegramScreens`,
    `TelegramLanguageSwitcher`), `features/profile/profileApi.ts`,
    `shared/lib/miniAppMode.ts`, `pages/telegram/TelegramEntryPage.tsx`,
    маршрут `/tg`; изменены `baseApi`, `AppProviders`, `store`, i18n
    (без `localStorage` в Mini App), `LanguageSwitcher` (необязательный
    обработчик выбора), переводы ru/ky/uz (ky/uz — черновики для
    проверки носителями), OpenAPI-типы. Тесты:
    `features/telegram/{foundation,session,ui}.test.ts(x)`.
-   **MA-4. Покупательский сценарий (frontend, DEC-157).** Те же
    компоненты страниц сайта под `/tg/*`; подэтапы по порядку:
    -   **MA-4.0. Маршрутизация** --- *реализован 2026-11-14.* Один
        роутер на загрузку страницы: сайт или Mini App с `basename:
        '/tg'` (`app/router/createAppRouter.ts`, `miniAppRoutes.tsx`);
        `/` → `/menu`; временный `/account`; «Раздел недоступен» для
        прочих путей; нижняя панель `MiniAppNav` (Меню, Корзина со
        счётчиком, Заказы, Профиль); проверка обычных ссылок
        (`linkGuard.ts`: пути сайта блокируются, внешние --- `openLink`);
        `BackButton` по путям роутера Mini App; гость в
        `ProductConfigurator` не уходит на `/login`. Tests:
        `features/telegram/routing.test.tsx`; тесты MA-3 переведены на
        роутер Mini App; тесты сайта без изменений.
    -   **MA-4.1. Вход и выбор аккаунта** --- *реализован 2026-11-14.*
        При `409 TELEGRAM_NOT_LINKED` вместо экрана «Аккаунт ещё не
        выбран» --- экран выбора «Я новый клиент» / «У меня уже есть
        аккаунт» с предупреждением
        (`features/telegram/components/TelegramOnboarding.tsx`).
        `register` и `link` --- мутации RTK Query
        (`telegramAuthApi.ts`) без cookie и CSRF; `init_data` читается
        при отправке и не хранится в аргументах мутации, запрос
        удаляется из store сразу после ответа. Форма привязки --- React
        Hook Form + Zod (схема входа сайта). После успеха --- access-токен
        в памяти и переход на `/tg/menu`. Ошибки
        (`onboardingErrors.ts`): `401 INVALID_TELEGRAM_AUTH` --- экран
        «перезапустите Mini App»; `409 TELEGRAM_DISABLED` --- экран
        недоступности; `401` формы привязки --- общее «Неверный email или
        пароль», пароль очищается; `403` --- в форме привязки сообщение
        «доступен только клиентам» (Telegram остаётся без связи), при
        регистрации --- экран `403`; `TELEGRAM_ALREADY_LINKED`,
        `ACCOUNT_ALREADY_LINKED`, `TELEGRAM_BUSY`, `429`, `422`, `5xx`,
        сеть --- текст по коду, повтор возможен. Ответы `401` форм не
        запускают повторный обмен `init_data` (`NO_REAUTH`). «Забыли
        пароль?» --- `openLink` на `/forgot-password` сайта (без
        `openLink` --- новая вкладка). До входа язык --- русский (язык
        профиля ещё не известен). Tests:
        `features/telegram/onboarding.test.tsx`.
    -   **MA-4.2. Каталог, товар, корзина** в режиме Mini App: категории,
        поиск, размер, тесто, добавки, количество; итоги только от
        сервера. --- *реализован 2026-11-19.* Объём покрыт общими
        страницами сайта под `/tg/*`; меню запрашивает товары страницами
        по 12. Исправлено: в Mini App закреплённый блок «Итог выбора»
        (цена и кнопка «В корзину») располагается над нижней панелью с
        учётом нижней safe area (CSS-переменная `--mini-app-nav-space`,
        `features/telegram/miniAppLayout.ts`); вёрстка сайта не
        изменилась. Tests: `features/telegram/shopping.test.tsx` (11:
        меню, категория и поиск, вторая страница, `BackButton`,
        добавление без цен и счётчик после ответа сервера, ошибки
        добавления, количество и удаление в корзине, ошибки корзины,
        положение итога над панелью, сайт без изменений); весь Vitest ---
        263 passed; typecheck, lint, format:check и build --- успешно.
        Сборка frontend опубликована в sandbox; ручная проверка Mini App
        в Telegram пройдена 2026-11-19.
    -   **MA-4.3. Оформление и оплата.** Доставка или самовывоз; выбор
        сохранённого адреса или добавление нового адреса с картой
        (`disableVerticalSwipes`) --- новый адрес добавляется именно здесь
        (DEC-157 п. 3); телефон, способ оплаты, quote, `PRICE_CHANGED`;
        mock-оплата. На оформлении и оплате ---
        `enableClosingConfirmation` (DEC-157 п. 4). `sessionStorage` для
        `Idempotency-Key` пока не используется: ключ живёт в памяти
        страницы, повтор с этой страницы --- с тем же ключом; незавершённая
        отправка после повторного открытия не восстанавливается. Tests:
        `enableClosingConfirmation` включается на оформлении и оплате и
        выключается при уходе с них; повтор отправки с той же страницы ---
        тот же `Idempotency-Key`. --- *реализован 2026-11-19* подэтапами:
        -   MA-4.3.1 --- оформление и mock-оплата в `/tg` на общих
            страницах сайта: `Idempotency-Key` и повтор с тем же ключом,
            `PRICE_CHANGED`, адрес и карта, `mock_card` →
            `/tg/orders/:id/pay`. Tests:
            `features/telegram/checkout.test.tsx`.
        -   MA-4.3.2 --- `enableClosingConfirmation` на оформлении
            (непустая корзина клиента) и на оплате `mock_card`
            (`features/telegram/useTelegramClosingConfirmation.ts`,
            `CheckoutPage`, `PayPage`). Tests:
            `features/telegram/closing.test.tsx`.
        -   MA-4.3.3 --- `disableVerticalSwipes`, пока смонтирована карта
            доставки (`features/telegram/useTelegramVerticalSwipesDisabled.ts`,
            `DeliveryMap`); исправлен тестовый мок `test/telegramMock.ts`.
            Tests: `features/telegram/swipes.test.tsx` (11/11).
        Весь Vitest --- 301 passed; typecheck, lint и format:check ---
        успешно (2026-11-19). 2026-11-20 исправлена адаптивность строки
        добавки на узких экранах (`OptionPickers.tsx`). Build и публикация
        в sandbox после MA-4.3 не выполнялись.
    -   **MA-4.4. Заказы и профиль (DEC-160).** История, детали, статусы,
        запрос отмены; отдельная страница профиля Mini App `/tg/account`
        (не страница профиля сайта, DEC-160 п. 1): имя, телефон, язык,
        список сохранённых адресов (DEC-157 п. 3: новый адрес добавляется
        при оформлении в MA-4.3, отдельной формы добавления адреса с
        картой в профиле нет), «Добавить email и пароль» для аккаунта
        только с Telegram. --- *реализация завершена 2026-11-21*
        подэтапами:
        -   MA-4.4.1 --- заказы на общих страницах сайта без изменения
            бизнес-поведения (DEC-160 п. 7). Tests:
            `features/telegram/orders.test.tsx` (10/10).
        -   MA-4.4.2 --- `pages/telegram/TelegramProfilePage.tsx`: имя,
            телефон, email только для чтения, язык (меняется в шапке),
            список адресов
            (`features/profile/components/SavedAddressList.tsx`); без
            ссылок на сайт, вход, смену пароля и выход. Tests:
            `features/telegram/profile.test.tsx`; весь Vitest --- 321
            passed; typecheck и lint --- успешно; format:check --- успешно
            после форматирования `orders.test.tsx`.
        -   MA-4.4.3 --- имя и телефон через `PATCH /users/me` (DEC-160
            п. 2): встроенная форма
            `features/profile/components/ProfileDetailsForm.tsx`;
            отправляются только изменённые поля, `phone: null` и
            `preferred_language` не отправляются, существующий телефон
            нельзя удалить; `ErrorState` --- только если профиль не
            загружен ни разу. Tests: `profile.test.tsx` (24/24);
            typecheck и lint --- успешно; format:check --- успешно после
            форматирования `profile.test.tsx`.
        -   MA-4.4.4 (адреса) закрыт в рамках MA-4.4.2: по DEC-160 п. 4
            адреса только показываются списком; новой реализации нет.
        -   MA-4.4.5 --- «Вход на сайте»: email и пароль через `POST
            /auth/credentials` для аккаунта только с Telegram (DEC-160
            п. 5): `features/profile/components/AddCredentialsForm.tsx`,
            мутация `addCredentials` в `features/auth/authApi.ts` (тег
            `Me` инвалидируется мутацией только при успешном ответе
            `204`; при `409 CREDENTIALS_ALREADY_SET` форма отдельно
            инвалидирует `Me`, чтобы обновить профиль; остальные ошибки
            инвалидацию не вызывают), `credentialsSchema` в
            `features/profile/validation.ts` (правила регистрации не
            изменены); после каждой попытки --- `request.reset()` и
            очистка поля пароля; сообщения об успехе и о
            `CREDENTIALS_ALREADY_SET` остаются на странице. Tests:
            `features/telegram/credentials.test.tsx` (13/13),
            `profile.test.tsx` (24/24); typecheck --- успешно; lint ---
            успешно после исправления `react-hooks/refs` в
            `AddCredentialsForm.tsx`. После этого последнего изменения
            повторно пройдены lint, `credentials.test.tsx` (13/13) и
            format:check; typecheck и весь Vitest повторно не
            запускались.
        Известные ограничения MA-4.4 (не выполнено или отложено):
        -   весь Vitest и typecheck после MA-4.4.3 и MA-4.4.5 в рамках
            MA-4.4 не запускались --- выполнены позже в MA-4.5.3;
        -   production build выполнен локально в MA-4.5.4; публикация в
            sandbox не выполнялась; ручная проверка Mini App в Telegram
            не выполнялась;
        -   вёрстка `OrdersPage` и `OrderDetailPage` на ширине 320, 360 и
            390 px (DEC-160 п. 7) и страницы профиля не проверялась;
        -   дефект, возникший до MA-4.4: после успешного переключения
            языка на ky и неудачного фонового `GET /users/me` интерфейс
            возвращается на ru (`useProfileLanguage` в
            `features/telegram/useMiniAppLanguage.ts`); причина
            установлена, исправление отложено;
        -   список адресов запрашивается одной страницей
            (`page_size=100`): адреса после сотого не показываются;
        -   текст пустого списка адресов «Адрес сохраняется при
            оформлении заказа с доставкой» не упоминает флажок
            `save_address`; оставлен до общей редакторской проверки;
        -   во время выполнения запроса `POST /auth/credentials` пароль
            кратковременно находится в аргументах мутации RTK Query в
            store (принятое исключение); после завершения запроса его там
            нет, что проверено тестами;
        -   переводы новых текстов на ky и uz не проверены носителями.
    -   **MA-4.5. Приёмка** --- весь Vitest, typecheck, lint, format,
        build; документация. --- *локальная техническая приёмка
        завершена 2026-11-21* (общая приёмка Mini App и сайта не
        завершена):
        -   MA-4.5.1 --- аудит покрытия тестами по критериям приёмки
            Mini App: критических пробелов нет, новые тесты не
            добавлялись.
        -   MA-4.5.2 --- статический аудит вёрстки на 320, 360 и 390 px;
            исправлено: перенос длинных строк без пробелов в блоках
            `OrderDetailPage` (`[overflow-wrap:anywhere]` в общем стиле
            блоков) и высота 44 px (`min-h-11`) кнопок «Изменить» и
            «Отмена» профиля. Кнопки на общем `SubmitButton` («Сохранить»,
            «Добавить email и пароль») не изменялись; риски, которые
            проверяются только в браузере (подписи нижней панели в uz на
            320 px, перекрытие полей панелью при открытой клавиатуре,
            длинные подписи кнопок в ky/uz, пагинация на 320 px), открыты.
        -   MA-4.5.3 --- весь Vitest --- 28/28 файлов, 348/348 тестов;
            typecheck --- успешно; lint --- успешно, без предупреждений;
            format:check --- успешно.
        -   MA-4.5.4 --- production build (`tsc -b` и `vite build`, Vite
            8.3.5, 402 модуля) --- успешно; сборка выполнена во временный
            каталог контейнера, `frontend/dist` не изменён, временные
            артефакты удалены; source maps, маркеры секретов и адреса
            dev-backend в сборке отсутствуют. Предупреждение: JS-чанк
            больше 500 kB после минификации (около 1,38 MB, gzip около
            393 kB); оптимизация (разбиение кода) отложена.
        -   MA-4.5.5 (исправления) не потребовался: блокирующих ошибок
            нет.
        Локальная приёмка не заменяет и не включает: ручную проверку
        Mini App в Telegram на устройстве (DEC-159), визуальную проверку
        на 320, 360 и 390 px в браузере, проверку реальной карты
        (Leaflet), проверку во фрейме Telegram Web (после MA-5) и E2E
        сайта (MA-6). Эти проверки и известные ограничения MA-4.4
        остаются открытыми.
    -   **MA-4.6. Дизайн сайта и Mini App (DEC-161).** Доводка внешнего
        вида внутри UI_UX_GUIDELINES §1; API, RTK Query, бизнес-логика,
        маршруты, авторизация и оформление заказа не меняются;
        административный интерфейс исключён.
        -   MA-4.6.0 --- решения: шрифт Manrope Variable локально,
            SVG-заглушки до фотографий, inline SVG-иконки, админка вне
            объёма, порядок подэтапов, требования к Mini App (темы, safe
            areas, 320/360/390 px, ru/ky/uz). --- *утверждён 2026-11-21.*
            Шрифт уточнён DEC-161 ред. 46: Inter 4.1 вместо Manrope.
        -   MA-4.6.1 --- дизайн-система: токены, шрифт, общие компоненты
            Button, Card, Badge, Chip, SectionHeader. --- *в работе:*
            1a (токены) и 1b (контраст в тёмной теме Telegram) выполнены;
            1c --- шрифт Inter 4.1; 1d --- компоненты.
        -   Далее --- каталог и остальные подэтапы, каждый с отдельным
            разрешением; публикация сборки --- отдельным этапом (DEC-159).
    Tests: Vitest --- меню → карточка → корзина → оформление → оплата →
    заказы в режиме Mini App; регистрация и привязка; конфликты.
-   **MA-5. nginx и разработка.** `frame-ancestors
    https://web.telegram.org` без `X-Frame-Options` для `/tg` и `/tg/*`,
    `DENY` для остальных адресов (K4-B, DEC-152 п. 1); подставной
    `window.Telegram` только в режиме разработки (K3-A). Сборка
    demo-контейнера --- только с отдельного разрешения.
-   **MA-6. E2E и приёмка.** `@playwright/test` (dev-зависимость
    frontend, Fixed stack); стенд E2E согласуется отдельно; сценарии
    E2E №8--11 этапа 11; регрессия сайта.
-   **Проверка на устройствах** через туннель (K3-C) --- только после
    отдельного согласования; порядок --- DEC-159.

Приёмка Mini App (отдельно от сайта):

1.  Вход по `init_data` без email и пароля для связанного Telegram;
    повторный вход после истечения access-токена без cookie; без связи
    --- экран выбора, аккаунт автоматически не создаётся.
2.  Регистрация нового клиента и привязка существующего аккаунта сайта
    по email и паролю: один аккаунт, общая история заказов, имя, телефон
    и язык сохраняются; дубликат не создаётся; конфликты ---
    `TELEGRAM_ALREADY_LINKED` / `ACCOUNT_ALREADY_LINKED` с понятным
    текстом, связь не переносится, данные не меняются.
3.  Тот же покупательский сценарий, что на сайте: меню → карточка →
    корзина → адрес на карте → quote → заказ → оплата → история и
    запрос отмены --- на том же API.
4.  Тема Telegram, `BackButton`, язык по DEC-152 п. 10; закрытие и
    повторное открытие не теряют корзину и заказы.
5.  Работа в Telegram Web во фрейме на `/tg/*` и отказ встраивания для
    остальных адресов.
6.  Сайт работает как прежде: вход по email, refresh-cookie, его
    тесты и E2E №1--7.

## Этап 8 --- admin/staff

Dashboard (метрики DEC-90, DEC-111; период по умолчанию 7 дней для
сводки, графика и топ-10, DEC-114),
order filters/status transitions, единая
идемпотентная отмена (DEC-82), cancellation review, staff/roles с
временным паролем, автосоздание `courier_profiles`, запрет снятия роли
courier при активных назначениях, settings, working hours (один
интервал в день, ночные интервалы, DEC-107), delivery zone editor на
Leaflet + Geoman с проверкой геометрии и пересечений на backend
(DEC-53, DEC-102), кухонная очередь для повара (DEC-106), polling 10 с
(DEC-93).

Уточнения DEC-150 (2026-11-12): завершение самовывоза с наличным
платежом → `succeeded`; отклонение заказа с автоматическим закрытием
ожидающего запроса отмены; сотрудники --- только роли `cook`/`courier`,
защита последнего активного администратора, деактивация с отзывом
сессий и повторная активация (`POST /admin/staff/{user_id}/deactivate`,
`…/reactivate`; аккаунты с ролью `admin` --- `409
ADMIN_ACCOUNT_PROTECTED`); зоны --- `Polygon`/`MultiPolygon`, `DELETE` = деактивация,
Geoman; координаты ресторана на карте, часовой пояс не меняется;
графики дашборда на SVG; отдельный интерфейс «Кухня»; в sandbox ---
один тестовый `cook`. Курьерские API и назначения перенесены в этап 9.

Tests: cook restrictions (нет персональных данных и комментария
клиента), invalid transitions rejected, status history atomic,
cancellation idempotency, zone overlap vs touching, выбор зоны на общей
границе, role removal conflict, метрики dashboard (исключение только
`payment_timeout`, ожидающие оплаты учитываются, средний чек 0, активные
заказы не зависят от периода, границы дней в `Asia/Bishkek`, топ-10),
рабочие часы, `special_instructions` видны повару, а `customer_comment`
--- нет.

### Состояние этапа 8 (2026-11-12)

-   **Реализован, ожидает приёмки.** Решения этапа --- DEC-150. Миграции
    не менялись, новых зависимостей, кроме согласованного Geoman (DEC-94),
    нет.
-   Backend: `/admin/dashboard/*`, `/admin/orders` (рабочая очередь без
    неоплаченных `mock_card`, отдельный фильтр `awaiting_payment`, смена
    статуса через сервис статусов и ядро отмены §14.3),
    `/admin/cancellation-requests` (approve/reject, идемпотентно),
    `/staff/kitchen/orders` (узкая схема без данных покупателя и оплаты),
    `/admin/staff` (create/roles/deactivate/reactivate), `/admin/settings`,
    `/admin/working-hours`, `/admin/delivery-zones`.
-   Frontend: разделы «Дашборд», «Заказы», «Запросы отмены», «Кухня»,
    «Сотрудники», «Зоны доставки», «Настройки»; повар видит только
    «Кухню»; RU/KY/UZ.
-   Перенесено в этап 9: передача курьеру (`out_for_delivery`),
    завершение доставки, курьерские API.

## Этап 9 --- courier

Сюда перенесены из API §9 (DEC-150): `POST
/admin/orders/{id}/assign-courier`, `POST
/admin/orders/{id}/auto-assign-courier`, `GET /admin/couriers`,
`PATCH /admin/couriers/{user_id}/availability`, а также завершение
доставки (наличный платёж → `succeeded`) и проверка правила DEC-150:
деактивация курьера с активными назначениями → `409
COURIER_HAS_ACTIVE_ASSIGNMENTS` без деактивации и отзыва сессий (с
тестами).

Courier profile, availability, manual/auto assignment с `SELECT … FOR
UPDATE` (DEC-67), переназначение, `NO_COURIER_AVAILABLE`, active order
limit, принятие назначения (`accepted_at`) до выезда (DEC-83), отказ до
принятия (`declined`, DEC-92), административное вмешательство в
курьерские переходы (`is_admin_override`, DEC-91), видимость данных
курьера (DEC-106), courier UI с polling 10 с.

Tests: only assigned orders visible, courier role/profile required,
assignment limit под конкурентной нагрузкой, one active assignment per
order, picked-up без принятия запрещён, decline только до принятия
и до `out_for_delivery` (DEC-151),
отказавшийся курьер исключён из автоназначения, вмешательство
администратора требует комментарий и активное назначение и не
записывает `accepted_at`, потеря доступа после переназначения, cash
`succeeded` при доставке.

Уточнения DEC-151 (2026-11-13): неудачная доставка в v1 без отдельного
статуса (решается вне системы, миграции нет); администратор меняет
`max_active_orders` (1–10) через `PATCH
/admin/couriers/{user_id}/availability`; детерминированное
автоназначение (активные назначения → самое раннее последнее назначение,
`NULLS FIRST` → `user_id`); повторы: `accept` и `delivered` --- `200`,
`picked-up` --- `409 INVALID_STATUS_TRANSITION`, назначение того же
курьера --- `200` без изменений; отказ запрещён и после
`out_for_delivery`; единый порядок блокировок `orders → users (FOR
SHARE) → courier_profiles → courier_assignments` (совместим с `users →
refresh_tokens` DEC-140); блокировка `users` в операциях сотрудников
этапа 8 приводится к `FOR NO KEY UPDATE` (DEC-140); данные курьера
клиенту не показываются; в sandbox --- ровно один тестовый `courier`;
кабинет курьера --- отдельный мобильный маршрут `/courier`. Q-19 закрыт
(DEC-151 п. 4): автоназначение заказа с активным назначением --- `200`
с текущим назначением без изменений; повторный отказ по своему
отклонённому назначению --- `200` без побочных эффектов; заменить
курьера можно только ручным переназначением.

Дополнительные тесты DEC-151: детерминированный выбор при равной
нагрузке, лимит 1–10 и его уменьшение, повторы `accept`/`delivered`/
`picked-up`/назначения того же курьера, автоназначение заказа с
активным назначением (`200`, БД не меняется), повторный отказ (`200`,
`declined_at` не перезаписывается), отказ после вмешательства
администратора; конкурентные сценарии без `deadlock detected`: два
назначения на лимит 1, два автоназначения разных заказов, назначение
против деактивации и против снятия роли `courier`, принятие и отказ
против переназначения, «доставлен» против отмены.

### Состояние этапа 9 (2026-11-13)

-   **Реализован, ожидает приёмки.** Решения этапа --- DEC-151. Миграций
    и новых зависимостей нет.
-   Backend: модуль `app/modules/courier/` (назначение и переназначение,
    автоназначение по DEC-151 п. 3, лимит и доступность, профиль,
    списки, принятие, отказ, «забрал», «доставлен»); `/courier/*`;
    `/admin/orders/{id}/assign-courier`, `…/auto-assign-courier`,
    `/admin/couriers`, `/admin/couriers/{user_id}/availability`; сервис
    статусов применяет курьерские переходы и вмешательство администратора
    (`delivered_at`, назначение `completed`, наличные `succeeded`);
    блокировка `users` в операциях сотрудников --- `FOR NO KEY UPDATE`.
-   Frontend: кабинет `/courier` (заказы, карточка, история); раздел
    «Курьеры», блок «Курьер» и вмешательство в карточке заказа, отметка
    «Нужен курьер» в списке заказов; RU/KY/UZ.

## Этап 10 --- notifications/Telegram

Требует этапов 6 и MA. На этапе MA реализованы вход, регистрация и
привязка из Mini App (связи `telegram_links`); бот, `/start`, `POST
/telegram/link-token`, `GET`/`DELETE /telegram/link` (отвязка с
`current_password`), outbox и `requestWriteAccess` --- этот этап
(DEC-152 пп. 5, 6, 8).

Сюда же перенесена (DEC-148) фоновая задача очистки просроченных
`idempotency_keys` (DATABASE_SCHEMA.md §14.5) вместе с другими задачами
worker.

In-app notifications клиентам (`type` + `payload`, i18next), read/
read-all, one-time Telegram linking (10 минут, DEC-87), Telegram long
polling (DEC-03), transactional outbox и worker отправки с повторами
(DEC-75, DEC-104, DEC-105), язык сообщения фиксируется в событии,
`TELEGRAM_DISABLED` без настроенного бота. Подключение к доменным
событиям этапа 6.

Tests: token single-use/expiry, повторный `/start` с тем же токеном,
чат другого аккаунта, аккаунт с другой связью, порядок блокировок
(DEC-152 п. 3), отвязка (неверный `current_password`, аккаунт без email
и пароля, отсутствие связи), outbox после отвязки, Telegram failure
doesn't roll back order, outbox
retry/429/403, язык события не меняется после смены языка
пользователем, notification ownership, сотрудники не получают
уведомления.

## Этап 11 --- QA and demo

Pytest, Vitest/RTL, Playwright, responsive QA, accessibility, security
review, Docker clean install в режимах `dev` и `demo`, demo seed,
README and `.env.example`.

Critical E2E:

1. Register → menu → configure product → cart → checkout → order.
2. Admin confirms → cook prepares/marks ready → courier assigned →
   accepts → picked up → delivered.
3. Customer requests cancellation → admin approves/rejects.
4. Language switch updates UI/catalog.
5. Telegram links through one-time token.
6. Mock card: failure → retry → success → order in admin queue.
7. Courier declines → admin assigns another courier → delivered.

Critical E2E Telegram Mini App (выполняются отдельно; прохождение
сценариев сайта их не заменяет):

8. `/tg` вход по `initData` → `/tg/menu` → configure product → cart →
   checkout → mock card → order in admin queue.
9. Истечение access-токена в Mini App → повторный обмен `initData` →
   работа продолжается.
10. Mini App: запрос отмены → admin approves/rejects → статус виден в
    Mini App.
11. Mini App: первый запуск без связи → «У меня есть аккаунт на сайте»
    → привязка по email и паролю → прежние заказы видны; повторный
    запуск входит без экрана выбора.

## Quality rules

-   No giant files/components.
-   No duplicate price calculation.
-   No trusting client roles, user IDs or monetary totals.
-   No broad swallowed exceptions.
-   No dependency without reason.
-   No TODO in critical business logic.
-   Do not claim tests passed unless executed.
-   Do not silently delete existing code.

## Report after each stage

List implemented behavior, changed files, migrations, test
commands/results, known issues, and next proposed step. Wait for user
approval before next major stage.
