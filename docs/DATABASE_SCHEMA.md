# DATABASE_SCHEMA.md

## 1. Назначение документа

Документ описывает схему PostgreSQL для демонстрационного веб-приложения
доставки еды одного ресторана и одного филиала в городе Ош, Кыргызстан.

Схема рассчитана на дальнейшую адаптацию под реального ресторанного
клиента. Архитектура --- модульный монолит: один backend на FastAPI и
одна база PostgreSQL.

Утверждённые решения перечислены в `docs/DECISIONS.md` (ссылки вида
`DEC-NN`). При расхождении приоритет имеет `DECISIONS.md`.

### Основные правила

-   Первичные ключи всех основных сущностей --- UUID.
-   Денежные значения хранятся в `NUMERIC(12,2)`, не в `FLOAT` и не в
    `REAL`.
-   Валюта проекта --- KGS.
-   Время хранится в `TIMESTAMPTZ` в UTC. Часовой пояс ресторана для
    расписания и отображения --- `Asia/Bishkek`.
-   Язык интерфейса и переводов: `ru`, `ky`, `uz`.
-   Пароли хранятся только в виде хешей Argon2id.
-   Refresh-токены и одноразовые токены хранятся только в виде
    криптографических хешей.
-   Исторические заказы не должны изменяться вслед за изменением
    каталога.
-   Удаление товара или пользователя не должно разрушать историю
    заказов.
-   Все проверки доступа и бизнес-ограничения обязательно выполняются
    backend-ом. Frontend не является доверенной стороной.

## 2. Общие соглашения

### 2.1 Идентификаторы и временные поля

Для большинства таблиц используются:

-   `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`;
-   `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`;
-   `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` --- для изменяемых
    сущностей.

Для таблиц-связок с естественным составным ключом допускается составной
`PRIMARY KEY`, например `(user_id, role_id)`.

Принятый подход (DEC-63): UUID по умолчанию генерирует PostgreSQL
(`gen_random_uuid()`); `updated_at` обновляется через SQLAlchemy
(`onupdate=func.now()`). Подход применяется ко всем таблицам
единообразно.

### 2.2 Языки

Коды языков: `ru`, `ky`, `uz`.

Переводимые названия и описания хранятся в отдельных
translation-таблицах. Не следует добавлять отдельные колонки `name_ru`,
`name_ky`, `name_uz`.

Если перевод для выбранного языка отсутствует, backend использует
fallback в порядке:

1. язык, явно запрошенный клиентом (параметр `language`);
2. язык пользователя (`users.preferred_language`), если пользователь
   авторизован;
3. русский (`ru`);
4. первый доступный перевод.

### 2.3 Денежные значения

-   Все суммы --- `NUMERIC(12,2)`.
-   Все суммы в заказе и платеже имеют валюту `KGS`.
-   Не использовать вычисления денежных сумм через Python `float` или
    JavaScript floating-point как источник истины.
-   Backend рассчитывает цену, скидки (если появятся), доставку и
    итоговую сумму в едином модуле расчёта цены (DEC-08). Клиент
    передаёт только идентификаторы, количество и выбранные опции.
-   `expected_total`, присланный клиентом, используется только для
    сравнения и никогда не сохраняется как сумма заказа (DEC-09, DEC-10).
-   В версии 1 промокодов нет.

### 2.4 Удаление данных

-   Категории деактивируются (`is_active = FALSE`), товары деактивируются
    или помечаются `deleted_at`; физическое удаление не используется
    (DEC-26).
-   Пользователи с историей заказов физически не удаляются, а
    деактивируются (`is_active = FALSE`) (DEC-62).
-   Исторические `order_items` и `order_item_modifiers` сохраняют снимки
    названий и цен.
-   Для ссылок из исторических заказов использовать `ON DELETE SET NULL`
    либо запрет физического удаления, но не каскадное удаление истории.
-   Для временных и зависимых сущностей (например, содержимое корзины)
    допустим `ON DELETE CASCADE`.

## 3. Пользователи, роли и авторизация

### 3.1 `users`

Хранит учётные записи всех пользователей.

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| email | VARCHAR(255) | NULL только у аккаунта только с Telegram (DEC-142); уникальный без учёта регистра |
| password_hash | TEXT | NULL только у аккаунта только с Telegram (DEC-142); Argon2id |
| full_name | VARCHAR(150) | NOT NULL |
| phone | VARCHAR(30) | NULL; нормализованный `+996XXXXXXXXX`, CHECK `phone ~ '^\+996[0-9]{9}$'` (DEC-89) |
| preferred_language | VARCHAR(2) | NOT NULL, DEFAULT `ru`; CHECK IN (`ru`,`ky`,`uz`) |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE |
| is_verified | BOOLEAN | NOT NULL, DEFAULT FALSE; в v1 не используется (DEC-64) |
| must_change_password | BOOLEAN | NOT NULL, DEFAULT FALSE (DEC-28) |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |

Email нормализуется в lowercase на backend-е. На уровне PostgreSQL
создать уникальный индекс по `lower(email)`.

Аккаунт только с Telegram (DEC-142) создаётся только явной
регистрацией из Telegram Mini App (`POST /auth/telegram/webapp/register`,
DEC-152; при входе без связи аккаунт не создаётся): `email` и
`password_hash` равны NULL. CHECK
`ck_users_credentials_pair`: `(email IS NULL) = (password_hash IS
NULL)` --- оба поля заполнены или оба пусты. NULL в уникальном индексе
по `lower(email)` не конфликтуют, поэтому таких аккаунтов может быть
несколько. Email и пароль добавляются позже одним `UPDATE`
(`POST /auth/credentials`). Такой аккаунт не находится по email при
входе и сбросе пароля; роль сотрудника ему не назначается.

Ревизия `0009` (DEC-142, DEC-153) снимает NOT NULL с `email` и
`password_hash` и добавляет `ck_users_credentials_pair`. Её откат
останавливается с ошибкой до любых изменений, если есть хотя бы один
аккаунт только с Telegram (`email IS NULL`): данные пользователей не
удаляются и не изменяются. Без таких аккаунтов откат удаляет CHECK и
восстанавливает NOT NULL.

Телефон не обязателен для регистрации. При оформлении заказа телефон
клиента обязателен и сохраняется в снимке заказа. Backend нормализует
телефон (DEC-89): принимает `+996 700 12 34 56`, `996700123456`,
`0700123456`, `700123456` и хранит только `+996700123456` (`+996` и 9
цифр).

Политика паролей (DEC-96) — общая для регистрации, смены, сброса и
CLI-команды создания администратора: от 8 до 128 символов, минимум
одна буква и одна цифра; хранится только Argon2id-хеш.

Первый администратор создаётся только CLI-командой
`python -m app.cli create-admin` (DEC-88); стандартных учётных данных
нет.

`must_change_password = TRUE` выставляется, когда администратор создаёт
сотрудника с временным паролем. Пока флаг установлен, из маршрутов,
требующих авторизации, пользователю доступны только `/auth/me`,
`/auth/password/change`, `/auth/logout` и `/auth/refresh` (DEC-28,
DEC-140).

Пользователь с `is_active = FALSE` не может войти (ответ login
неотличим от неверного пароля, DEC-103); при деактивации его
refresh-токены отзываются. Роли и `is_active` проверяются по БД на
каждом аутентифицированном запросе (DEC-66); запрос деактивированного
пользователя получает `401`.

### 3.2 `roles`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| name | VARCHAR(30) | NOT NULL, UNIQUE; `customer`, `admin`, `cook`, `courier` |
| description | VARCHAR(255) | NULL |
| created_at | TIMESTAMPTZ | NOT NULL |

### 3.3 `user_roles`

Связь пользователей и ролей. Один пользователь может иметь несколько
ролей; роли сочетаются (DEC-23). Роль `customer` выдаётся при
регистрации (DEC-24).

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| user_id | UUID | FK → users.id, ON DELETE CASCADE |
| role_id | UUID | FK → roles.id, ON DELETE RESTRICT |
| assigned_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() |

Составной PK: `(user_id, role_id)`.

Роль `courier` нельзя снять, пока у пользователя есть назначения со
статусом `active` (DEC-29).

### 3.4 `courier_profiles`

Отдельный профиль курьера. Не добавлять поля доступности курьера
непосредственно в `users`.

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| user_id | UUID | PK и FK → users.id, ON DELETE CASCADE |
| is_available | BOOLEAN | NOT NULL, DEFAULT FALSE |
| max_active_orders | SMALLINT | NOT NULL, DEFAULT 1, CHECK > 0 |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |

Профиль создаётся автоматически при выдаче роли `courier` (DEC-27).
Наличие профиля и роли `courier` проверяется backend-ом.
`is_available = TRUE` не означает, что курьер автоматически может
получить заказ: также учитывается число его активных назначений.
`max_active_orders` меняет администратор; API принимает 1–10, в БД
остаётся CHECK `> 0`; уменьшение ниже числа активных назначений их не
снимает (DEC-151 п. 2).

### 3.5 `addresses`

Сохранённые адреса пользователя. У пользователя может быть несколько
адресов.

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| user_id | UUID | FK → users.id, ON DELETE CASCADE |
| label | VARCHAR(80) | NULL; например, «Дом» или «Работа» |
| address_text | TEXT | NOT NULL |
| latitude | NUMERIC(10,7) | NULL; CHECK BETWEEN -90 AND 90 |
| longitude | NUMERIC(10,7) | NULL; CHECK BETWEEN -180 AND 180 |
| entrance | VARCHAR(30) | NULL |
| floor | VARCHAR(20) | NULL |
| apartment | VARCHAR(30) | NULL |
| comment | TEXT | NULL |
| is_default | BOOLEAN | NOT NULL, DEFAULT FALSE |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |

Создать индекс по `user_id`. Частичный уникальный индекс должен
обеспечивать не более одного адреса `is_default = TRUE` на пользователя.

Координаты проверяются на допустимый диапазон. Для доставки координаты
обязательны: клиент ставит точку на карте Leaflet/OpenStreetMap, а
текстовый адрес вводит дополнительно (DEC-01). Адрес без координат
нельзя использовать для доставки.

### 3.6 `refresh_tokens`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| user_id | UUID | FK → users.id, ON DELETE CASCADE |
| family_id | UUID | NOT NULL; общая для цепочки ротаций (DEC-65) |
| token_hash | TEXT | NOT NULL, UNIQUE |
| replaced_by_id | UUID | NULL; FK → refresh_tokens.id, ON DELETE SET NULL |
| expires_at | TIMESTAMPTZ | NOT NULL |
| revoked_at | TIMESTAMPTZ | NULL |
| created_at | TIMESTAMPTZ | NOT NULL |

Индексы: `(user_id, expires_at)`, `(family_id)`. В cookie браузера
хранится исходный refresh token; в БД --- только его хеш. Access token
короткоживущий и не обязан храниться в БД.

Ротация: при каждом refresh создаётся новый токен той же семьи, старому
выставляются `revoked_at` и `replaced_by_id`. Предъявление уже
ротированного или отозванного токена считается повторным использованием:
отзываются все токены семьи — **без льготного окна** (DEC-110).
Конкурентный refresh из нескольких вкладок предотвращается на frontend
(`navigator.locks`). На backend ротация атомарна: в одной транзакции
(READ COMMITTED) сначала блокируется строка `users`
(`FOR NO KEY UPDATE`), затем строка токена (`FOR UPDATE`); состояние
токена проверяется после получения блокировок. Значение `is_active`
берётся из блокирующего чтения строки `users`. Отзыв фиксируется
(COMMIT) до ответа `401`; без подтверждения успешного COMMIT
возвращается `500`, и результат отзыва считается неизвестным
(DEC-140). Тот же порядок блокировок соблюдают logout, смена и сброс
пароля, деактивация пользователя и административный отзыв его сессий
(DEC-140). Logout отзывает семью текущего токена; успешный сброс
пароля отзывает все семьи пользователя (DEC-108).
Сроки жизни (DEC-80): access JWT --- 15 минут, refresh --- 30 дней;
значения задаются в конфигурации.

### 3.7 `password_reset_tokens`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| user_id | UUID | FK → users.id, ON DELETE CASCADE |
| token_hash | TEXT | NOT NULL, UNIQUE |
| expires_at | TIMESTAMPTZ | NOT NULL |
| used_at | TIMESTAMPTZ | NULL |
| created_at | TIMESTAMPTZ | NOT NULL |

Одноразовый токен (32 случайных байта, в БД — SHA-256 хеш) становится
недействительным после использования или истечения срока (30 минут,
DEC-80). При выдаче нового токена прежние неиспользованные токены
пользователя помечаются использованными. Не хранить исходный токен.
Ссылка сброса отправляется по email (в dev/demo --- перехватывается
Mailpit) и никогда не пишется в лог (DEC-108).

Индекс `ix_password_reset_tokens_user_id` по `(user_id)` (DEC-127)
ускоряет поиск и аннулирование токенов пользователя (пометку прежних
неиспользованных токенов при новом запросе сброса) и проверки внешнего
ключа при каскадном удалении. Сам токен ищется по уникальному индексу
`token_hash`.

## 4. Каталог товаров

### 4.1 `categories`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| slug | VARCHAR(100) | NOT NULL, UNIQUE |
| image_path | TEXT | NULL |
| sort_order | INTEGER | NOT NULL, DEFAULT 0 |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |

«Удаление» категории --- это деактивация (`is_active = FALSE`), не
физическое удаление (DEC-26). Товары неактивной категории не
показываются в публичном каталоге и не могут быть заказаны.

### 4.2 `category_translations`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| category_id | UUID | FK → categories.id, ON DELETE CASCADE |
| language_code | VARCHAR(2) | NOT NULL, CHECK IN (`ru`,`ky`,`uz`) |
| name | VARCHAR(120) | NOT NULL |
| description | TEXT | NULL |

UNIQUE `(category_id, language_code)`.

### 4.3 `products`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| category_id | UUID | FK → categories.id, ON DELETE RESTRICT |
| slug | VARCHAR(150) | NOT NULL, UNIQUE |
| is_available | BOOLEAN | NOT NULL, DEFAULT TRUE |
| is_featured | BOOLEAN | NOT NULL, DEFAULT FALSE |
| sort_order | INTEGER | NOT NULL, DEFAULT 0 |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |
| deleted_at | TIMESTAMPTZ | NULL |

Поле `base_price` отсутствует (DEC-06). Цена товара всегда берётся из
выбранного `product_variant`. Каждый товар обязан иметь минимум один
вариант; для простых товаров создаётся вариант «Стандарт». Это
инвариант сервисного слоя: товар создаётся вместе как минимум с одним
вариантом.

Товар доступен к заказу, если: `deleted_at IS NULL`,
`is_available = TRUE`, его категория активна и у него есть хотя бы один
доступный вариант. Цена «от» в каталоге = минимальная цена доступного
варианта.

### 4.4 `product_translations`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| product_id | UUID | FK → products.id, ON DELETE CASCADE |
| language_code | VARCHAR(2) | NOT NULL, CHECK IN (`ru`,`ky`,`uz`) |
| name | VARCHAR(180) | NOT NULL |
| description | TEXT | NULL |

UNIQUE `(product_id, language_code)`.

### 4.5 `product_images`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| product_id | UUID | FK → products.id, ON DELETE CASCADE |
| image_path | TEXT | NOT NULL |
| alt_text | VARCHAR(255) | NULL |
| sort_order | INTEGER | NOT NULL, DEFAULT 0 |
| is_primary | BOOLEAN | NOT NULL, DEFAULT FALSE |
| created_at | TIMESTAMPTZ | NOT NULL |

Индекс по `(product_id, sort_order)`. Частичный уникальный индекс
`(product_id) WHERE is_primary = TRUE` --- не более одного основного
изображения на товар.

Файлы изображений хранятся в локальном хранилище / Docker volume, в БД
хранится путь или относительный storage key. Разрешены JPEG, PNG, WebP
до 5 МБ (DEC-70). Проверять MIME-тип, расширение, размер и фактическое
содержимое файла (Pillow). Имя файла генерирует сервер; не доверять
имени файла, присланному клиентом. Те же правила действуют для
изображений категорий.

### 4.6 `product_variants`

Варианты товара, например маленькая и большая пицца или «Стандарт» для
простого товара.

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| product_id | UUID | FK → products.id, ON DELETE CASCADE |
| sku | VARCHAR(100) | NOT NULL, UNIQUE |
| price | NUMERIC(12,2) | NOT NULL, CHECK >= 0 |
| is_available | BOOLEAN | NOT NULL, DEFAULT TRUE |
| sort_order | INTEGER | NOT NULL, DEFAULT 0 |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |

Индекс по `product_id`.

### 4.7 `product_variant_translations`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| variant_id | UUID | FK → product_variants.id, ON DELETE CASCADE |
| language_code | VARCHAR(2) | NOT NULL, CHECK IN (`ru`,`ky`,`uz`) |
| name | VARCHAR(100) | NOT NULL |

UNIQUE `(variant_id, language_code)`.

## 5. Модификаторы и дополнительные ингредиенты

Модификаторы нужны для выбора теста, сыра, соусов, добавок и других
опций. Группы могут быть обязательными или необязательными. Модификатор
может быть выбран в количестве больше 1 (например, двойной сыр) в
пределах `max_quantity` (DEC-07, DEC-81).

### 5.1 `modifier_groups`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| selection_type | VARCHAR(20) | NOT NULL, CHECK IN (`single`,`multiple`) |
| is_required | BOOLEAN | NOT NULL, DEFAULT FALSE |
| min_selections | SMALLINT | NOT NULL, DEFAULT 0, CHECK >= 0 |
| max_selections | SMALLINT | NULL, CHECK > 0; NULL = без ограничения |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE |
| sort_order | INTEGER | NOT NULL, DEFAULT 0 |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |

CHECK constraints (DEC-58, D1):

-   `max_selections IS NULL OR min_selections <= max_selections`;
-   `selection_type <> 'single' OR max_selections IS NOT DISTINCT FROM 1`
    (DEC-128: строгая форма — `single` с `max_selections IS NULL`
    отклоняется);
-   `is_required = (min_selections >= 1)`.

`min_selections` и `max_selections` считают **количество разных
выбранных модификаторов** группы, а не сумму их количеств (DEC-81).
Backend дополнительно проверяет ограничения с учётом доступных опций:
если доступных модификаторов меньше `min_selections`, товар с этой
группой не может быть заказан.

### 5.2 `modifier_group_translations`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| group_id | UUID | FK → modifier_groups.id, ON DELETE CASCADE |
| language_code | VARCHAR(2) | NOT NULL, CHECK IN (`ru`,`ky`,`uz`) |
| name | VARCHAR(120) | NOT NULL |
| description | TEXT | NULL |

UNIQUE `(group_id, language_code)`.

### 5.3 `modifiers`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| group_id | UUID | FK → modifier_groups.id, ON DELETE CASCADE |
| price_delta | NUMERIC(12,2) | NOT NULL, DEFAULT 0, CHECK >= 0 |
| max_quantity | SMALLINT | NOT NULL, DEFAULT 1, CHECK > 0 (DEC-81) |
| is_available | BOOLEAN | NOT NULL, DEFAULT TRUE |
| sort_order | INTEGER | NOT NULL, DEFAULT 0 |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |

Индекс по `group_id`. `price_delta` --- стандартная доплата за одну
единицу модификатора. `max_quantity` --- максимальное количество этого
модификатора в одной позиции; если администратор не задал значение,
используется 1.

### 5.4 `modifier_translations`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| modifier_id | UUID | FK → modifiers.id, ON DELETE CASCADE |
| language_code | VARCHAR(2) | NOT NULL, CHECK IN (`ru`,`ky`,`uz`) |
| name | VARCHAR(120) | NOT NULL |
| description | TEXT | NULL |

UNIQUE `(modifier_id, language_code)`.

### 5.5 `product_modifier_groups`

Связывает товар с доступными ему группами модификаторов.

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| product_id | UUID | FK → products.id, ON DELETE CASCADE |
| group_id | UUID | FK → modifier_groups.id, ON DELETE RESTRICT |
| sort_order | INTEGER | NOT NULL, DEFAULT 0 |

Составной PK `(product_id, group_id)`. Индекс
`ix_product_modifier_groups_group_id` по `(group_id)` (DEC-129).

Для первой версии правила выбора (`is_required`, `min_selections`,
`max_selections`) задаются на самой группе и одинаковы для всех товаров,
к которым группа подключена.

### 5.6 `variant_modifier_prices`

Переопределяет стоимость модификатора для конкретного варианта товара.

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| variant_id | UUID | FK → product_variants.id, ON DELETE CASCADE |
| modifier_id | UUID | FK → modifiers.id, ON DELETE CASCADE |
| price_delta | NUMERIC(12,2) | NOT NULL, CHECK >= 0 |

Составной PK `(variant_id, modifier_id)`. Индекс
`ix_variant_modifier_prices_modifier_id` по `(modifier_id)` (DEC-129).

Семантика цены:

-   если строка для пары `(variant_id, modifier_id)` существует,
    использовать её `price_delta`;
-   иначе использовать `modifiers.price_delta`.

Backend обязан проверять, что модификатор принадлежит группе,
подключённой к товару данного варианта. Одних внешних ключей
недостаточно для этой межтабличной проверки.

### 5.7 Правила валидации выбора модификаторов

При добавлении в корзину, в quote и при создании заказа backend
проверяет одновременно (DEC-81):

1. модификатор существует, доступен, его группа активна и подключена к
   товару;
2. количество каждого модификатора: `1 <= quantity <= max_quantity`;
3. число разных выбранных модификаторов группы:
   `min_selections <= n <= max_selections` (если max не NULL);
4. обязательные группы (`is_required`) не пропущены;
5. для `single` выбран не более чем один модификатор.

## 6. Корзина

### 6.1 `carts`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| user_id | UUID | FK → users.id, ON DELETE CASCADE, NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |

UNIQUE `(user_id)` --- у пользователя одна активная корзина. Корзина
есть только у авторизованных пользователей с ролью `customer`; гостевой
корзины нет (DEC-13, DEC-23). После успешного оформления заказа
содержимое корзины очищается в той же транзакции, в которой создаётся
заказ. Строка корзины остаётся и используется повторно.

### 6.2 `cart_items`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| cart_id | UUID | NOT NULL; FK → carts.id, ON DELETE CASCADE |
| product_id | UUID | NOT NULL; FK → products.id, ON DELETE RESTRICT |
| variant_id | UUID | NOT NULL; FK → product_variants.id, ON DELETE RESTRICT (DEC-06) |
| quantity | INTEGER | NOT NULL, CHECK > 0 |
| special_instructions | TEXT | NULL |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |

Индексы: `(cart_id)`; `(product_id)` и `(variant_id)` (DEC-130). Backend
проверяет, что `variant_id` принадлежит
`product_id`. Цена в корзине не хранится и не считается доверенной: она
пересчитывается сервером при каждом чтении корзины, quote и оформлении.

Объединение позиций (DEC-11): если добавляемая позиция совпадает с
существующей по товару, варианту, набору модификаторов с количествами и
пожеланиям (после нормализации пробелов), увеличивается `quantity`
существующей позиции. Изменение позиции через API ограничено
`quantity` и `special_instructions` (DEC-12); если после изменения
пожеланий позиция совпала с другой, они объединяются.

### 6.3 `cart_item_modifiers`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| cart_item_id | UUID | NOT NULL; FK → cart_items.id, ON DELETE CASCADE |
| modifier_id | UUID | NOT NULL; FK → modifiers.id, ON DELETE RESTRICT |
| quantity | SMALLINT | NOT NULL, DEFAULT 1, CHECK > 0 |

UNIQUE `(cart_item_id, modifier_id)`. Индекс `(modifier_id)` (DEC-130).
Backend проверяет доступность
модификатора для товара, `quantity <= modifiers.max_quantity` и
ограничения группы (раздел 5.7).

## 7. Заказы

### 7.1 Статусы заказа и переходы

Допустимые статусы заказа версии 1:

-   `pending` --- создан, ожидает подтверждения (для `mock_card` ---
    также ожидает успешной оплаты);
-   `confirmed` --- подтверждён рестораном;
-   `preparing` --- готовится;
-   `ready_for_pickup` --- готов к выдаче клиенту или передаче курьеру;
-   `out_for_delivery` --- передан курьеру;
-   `completed` --- завершён;
-   `rejected` --- отклонён рестораном;
-   `cancelled` --- отменён (одобренный запрос клиента, решение
    администратора или истечение срока оплаты).

Статусы хранятся как `VARCHAR` с `CHECK`, а допустимые переходы
проверяются в сервисном слое. Клиент не может напрямую менять статус
заказа.

Цепочки (DEC-30, DEC-31):

-   доставка: `pending → confirmed → preparing → ready_for_pickup →
    out_for_delivery → completed`;
-   самовывоз: `pending → confirmed → preparing → ready_for_pickup →
    completed`.

Таблица переходов:

| Из | В | Кто | Условия |
|---|---|---|---|
| `pending` | `confirmed` | admin | для `mock_card` --- только при успешном платеже (DEC-45) |
| `pending` | `rejected` | admin | только из `pending` (DEC-32) |
| `confirmed` | `preparing` | cook, admin | DEC-35 |
| `preparing` | `ready_for_pickup` | cook, admin | DEC-35 |
| `ready_for_pickup` | `out_for_delivery` | courier | только `delivery`; активное назначение этого курьера с заполненным `accepted_at` (DEC-36, DEC-83) |
| `out_for_delivery` | `completed` | courier | только `delivery`; активное назначение этого курьера (DEC-36) |
| `ready_for_pickup` | `out_for_delivery` | admin (вмешательство) | только `delivery`; обязательно активное назначение курьера; `accepted_at` не требуется и не заполняется; обязательный комментарий; `is_admin_override = TRUE` (DEC-91) |
| `out_for_delivery` | `completed` | admin (вмешательство) | только `delivery`; обязательный комментарий; `is_admin_override = TRUE` (DEC-91) |
| `ready_for_pickup` | `completed` | admin | только `pickup` (DEC-37) |
| `pending`, `confirmed`, `preparing`, `ready_for_pickup` | `cancelled` | admin | прямая отмена или одобрение запроса клиента (DEC-33, DEC-82) |
| `pending` | `cancelled` | система | `mock_card`, срок оплаты истёк (`payment_timeout`, DEC-84) |

Из `out_for_delivery`, `completed`, `rejected`, `cancelled` отмена
невозможна.

Административное вмешательство (DEC-91): администратор может выполнить
курьерские переходы, но только по правилам state machine (те же
исходные статусы и тип заказа). Побочные эффекты те же, что у курьера:
при `completed` — `deliveries.delivered_at`, назначение `completed`,
наличный платёж `succeeded`. Фиктивный `accepted_at` не записывается;
факт вмешательства фиксируется в `order_status_history`
(`is_admin_override`, `changed_by`, `created_at`, `comment`).

### 7.2 `orders`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| order_number | VARCHAR(40) | NOT NULL, UNIQUE, публичный номер `OSH-000123` |
| user_id | UUID | NOT NULL; FK → users.id, ON DELETE RESTRICT |
| language_code | VARCHAR(2) | NOT NULL, CHECK IN (`ru`,`ky`,`uz`); язык оформления и snapshot'ов (DEC-15) |
| delivery_type | VARCHAR(20) | NOT NULL, CHECK IN (`delivery`,`pickup`) |
| status | VARCHAR(30) | NOT NULL, DEFAULT `pending`, CHECK по списку статусов |
| payment_method_code | VARCHAR(30) | NOT NULL, например `cash`, `mock_card`; снимок выбранного способа |
| subtotal | NUMERIC(12,2) | NOT NULL, CHECK >= 0 |
| delivery_fee | NUMERIC(12,2) | NOT NULL, DEFAULT 0, CHECK >= 0; снимок |
| total_amount | NUMERIC(12,2) | NOT NULL, CHECK >= 0 |
| currency | VARCHAR(3) | NOT NULL, DEFAULT `KGS`, CHECK = `KGS` |
| customer_name | VARCHAR(150) | NOT NULL, снимок |
| customer_phone | VARCHAR(30) | NOT NULL, снимок; CHECK `customer_phone ~ '^\+996[0-9]{9}$'` (DEC-89) |
| delivery_address_text | TEXT | NULL, снимок адреса для доставки |
| delivery_latitude | NUMERIC(10,7) | NULL, снимок |
| delivery_longitude | NUMERIC(10,7) | NULL, снимок |
| delivery_entrance | VARCHAR(30) | NULL, снимок |
| delivery_floor | VARCHAR(20) | NULL, снимок |
| delivery_apartment | VARCHAR(30) | NULL, снимок |
| customer_comment | TEXT | NULL |
| payment_due_at | TIMESTAMPTZ | NULL; срок онлайн-оплаты, см. ниже (DEC-84) |
| cancellation_reason_code | VARCHAR(30) | NULL; CHECK IN (`customer_request`,`admin_decision`,`payment_timeout`) (DEC-82, DEC-84) |
| cancelled_at | TIMESTAMPTZ | NULL |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |
| completed_at | TIMESTAMPTZ | NULL |

Индексы:

-   `(user_id, created_at DESC)`;
-   `(status, created_at)`;
-   уникальный `order_number`;
-   частичный `(payment_due_at) WHERE status = 'pending' AND
    payment_due_at IS NOT NULL` --- для фоновой задачи таймаута оплаты.

Номер заказа (DEC-14, DEC-123) генерирует БД: `server_default` колонки
`order_number` вызывает SQL-функцию (например, `next_order_number()`),
которая один раз берёт `nextval('order_number_seq')` и форматирует его
как `'OSH-' || lpad(n::text, greatest(6, length(n::text)), '0')`:
минимум 6 цифр, без обрезания (`OSH-000001`, `OSH-999999`,
`OSH-1000000`). Простое `lpad(..., 6, '0')` недопустимо: PostgreSQL
обрезает длинную строку (`1000000` → `100000`), что даёт повторный номер.
Sequence и функция создаются миграцией `0006`. Пропуски номеров после
откатившихся транзакций допустимы.

Snapshot адреса и стоимости доставки хранится **только** в `orders`
(DEC-16) и не меняется при изменении адреса пользователя или зоны.

`payment_due_at` (DEC-84): для `mock_card` при создании заказа
устанавливается `created_at + 30 минут` (значение из конфигурации);
при успешной mock-оплате сбрасывается в NULL. Для `cash` всегда NULL.
Заказ `pending` с `payment_due_at IS NOT NULL` считается «ожидающим
оплаты» и не попадает в рабочую очередь ресторана.

CHECK constraints:

-   `delivery_type = 'pickup'` → все поля `delivery_*` NULL и
    `delivery_fee = 0`;
-   `delivery_type = 'delivery'` → `delivery_address_text`,
    `delivery_latitude`, `delivery_longitude` NOT NULL;
-   `total_amount = subtotal + delivery_fee` (в версии 1);
-   `(status = 'cancelled') = (cancellation_reason_code IS NOT NULL)`;
-   `(status = 'cancelled') = (cancelled_at IS NOT NULL)`.

### 7.3 `order_items`

Содержит позиции заказа и снимки данных на момент оформления. Снимки
названий сохраняются на языке `orders.language_code` (DEC-15).

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| order_id | UUID | NOT NULL; FK → orders.id, ON DELETE CASCADE |
| product_id | UUID | NULL; FK → products.id, ON DELETE SET NULL |
| variant_id | UUID | NULL; FK → product_variants.id, ON DELETE SET NULL; при создании заказа всегда заполнен |
| product_name | VARCHAR(180) | NOT NULL, снимок |
| variant_name | VARCHAR(100) | NOT NULL, снимок |
| sku | VARCHAR(100) | NOT NULL, снимок |
| unit_price | NUMERIC(12,2) | NOT NULL, CHECK >= 0 |
| quantity | INTEGER | NOT NULL, CHECK > 0 |
| total_price | NUMERIC(12,2) | NOT NULL, CHECK >= 0 |
| special_instructions | TEXT | NULL |

Индексы: `(order_id)`; `(product_id)`, `(variant_id)` (DEC-133).

`unit_price` --- цена единицы варианта без модификаторов. Формула
(DEC-61):

```text
order_items.total_price = (unit_price + Σ(order_item_modifiers.unit_price × order_item_modifiers.quantity)) × order_items.quantity
```

Все снимки создаются backend-ом в момент оформления.

### 7.4 `order_item_modifiers`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| order_item_id | UUID | NOT NULL; FK → order_items.id, ON DELETE CASCADE |
| modifier_id | UUID | NULL; FK → modifiers.id, ON DELETE SET NULL |
| group_name | VARCHAR(120) | NOT NULL, снимок названия группы (DEC-60) |
| modifier_name | VARCHAR(120) | NOT NULL, снимок |
| quantity | SMALLINT | NOT NULL, CHECK > 0 |
| unit_price | NUMERIC(12,2) | NOT NULL, CHECK >= 0; доплата за 1 единицу с учётом override варианта |
| total_price | NUMERIC(12,2) | NOT NULL, CHECK >= 0; `unit_price × quantity` на **одну** единицу позиции |

Снимки названия группы, названия и цены обязательны, даже если исходный
модификатор впоследствии будет удалён или изменён. Индексы:
`(order_item_id)`, `(modifier_id)` (DEC-133).

### 7.5 `order_status_history`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| order_id | UUID | NOT NULL; FK → orders.id, ON DELETE CASCADE |
| old_status | VARCHAR(30) | NULL для первого статуса; CHECK по списку статусов |
| new_status | VARCHAR(30) | NOT NULL; CHECK по списку статусов |
| changed_by | UUID | NULL; FK → users.id, ON DELETE SET NULL; NULL для системных переходов |
| comment | TEXT | NULL; для `rejected`/`cancelled` и административного вмешательства --- обязателен |
| is_admin_override | BOOLEAN | NOT NULL, DEFAULT FALSE; TRUE --- администратор выполнил курьерский переход (DEC-91) |
| created_at | TIMESTAMPTZ | NOT NULL |

Индексы `(order_id, created_at)`, `(changed_by)` (DEC-133). CHECK:
`NOT is_admin_override OR (changed_by IS NOT NULL AND comment IS NOT NULL
AND length(trim(comment)) > 0)`; при этом `changed_by ON DELETE SET
NULL`, поэтому удаление пользователя, на которого ссылается запись
вмешательства, отклоняется БД и аудит сохраняется (DEC-131). CHECK
(DEC-132): `new_status NOT IN ('rejected', 'cancelled') OR (comment IS NOT
NULL AND length(trim(comment)) > 0)`. Создавать запись при каждом изменении статуса, включая
первоначальный статус. История используется для отображения клиенту и
аудита действий персонала.

### 7.6 `cancellation_requests`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| order_id | UUID | NOT NULL; FK → orders.id, ON DELETE CASCADE |
| user_id | UUID | NOT NULL; FK → users.id, ON DELETE RESTRICT |
| reason | TEXT | NOT NULL |
| status | VARCHAR(20) | NOT NULL, DEFAULT `pending`, CHECK IN (`pending`,`approved`,`rejected`) |
| reviewed_by | UUID | NULL; FK → users.id, ON DELETE SET NULL |
| admin_comment | TEXT | NULL |
| created_at | TIMESTAMPTZ | NOT NULL |
| reviewed_at | TIMESTAMPTZ | NULL |

Частичный уникальный индекс по `order_id` для строк со статусом
`pending`: у заказа может быть не более одного ожидающего запроса
отмены. Индексы `(order_id)`, `(user_id)`, `(reviewed_by)` (DEC-133). Клиент создаёт запрос, но не отменяет заказ самостоятельно.
Backend проверяет, что заказ принадлежит клиенту и находится в статусе
`pending`, `confirmed` или `preparing` (DEC-38). После отклонения клиент
может создать новый запрос (DEC-42).

Одобрение запроса выполняет единую операцию отмены (раздел 14.3). Если
администратор отменяет заказ напрямую при наличии `pending`-запроса,
запрос помечается `approved` тем же администратором. Если заказ перешёл
в статус, из которого отмена невозможна, `pending`-запрос
автоматически отклоняется с комментарием.

## 8. Способы оплаты и платежи

### 8.1 `payment_methods`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| code | VARCHAR(30) | NOT NULL, UNIQUE; `cash`, `mock_card` |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE |
| sort_order | INTEGER | NOT NULL, DEFAULT 0 |
| created_at | TIMESTAMPTZ | NOT NULL |

### 8.2 `payments`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| order_id | UUID | NOT NULL, FK → orders.id, ON DELETE RESTRICT |
| payment_method_id | UUID | NOT NULL, FK → payment_methods.id, ON DELETE RESTRICT |
| amount | NUMERIC(12,2) | NOT NULL, CHECK >= 0; равна `orders.total_amount` |
| currency | VARCHAR(3) | NOT NULL, DEFAULT `KGS`, CHECK = `KGS` |
| status | VARCHAR(20) | NOT NULL, CHECK IN (`pending`,`succeeded`,`failed`,`refunded`,`cancelled`) |
| transaction_reference | VARCHAR(120) | NULL; для mock --- сгенерированный идентификатор |
| is_simulated | BOOLEAN | NOT NULL, DEFAULT FALSE |
| paid_at | TIMESTAMPTZ | NULL |
| refunded_at | TIMESTAMPTZ | NULL |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |

Индексы: `(order_id, created_at)`; partial UNIQUE `(order_id) WHERE
status = 'succeeded'`; partial UNIQUE `(order_id) WHERE status =
'pending'` --- не более одной незавершённой попытки; `(payment_method_id)`
(DEC-134).

Для `mock_card` всегда устанавливать `is_simulated = TRUE`. Никакие
реальные деньги не списываются и реальные карточные данные не
собираются. Не сохранять номер карты, CVV или срок действия.

Жизненный цикл:

-   **cash** (DEC-43): при создании заказа --- платёж `pending`; при
    завершении заказа (курьер `completed` или администратор завершает
    самовывоз) --- `succeeded` и `paid_at` в той же транзакции. При
    отмене или отклонении заказа --- `cancelled`.
-   **mock_card** (DEC-44–DEC-47): при создании заказа --- платёж
    `pending`. Имитация оплаты: успех → `succeeded`, `paid_at`,
    `orders.payment_due_at = NULL`; неудача → `failed` и в той же
    транзакции создаётся новая попытка `pending` (повтор разрешён, пока
    не истёк `payment_due_at`). При истечении срока --- `pending` →
    `cancelled`, заказ → `cancelled` (`payment_timeout`). При отмене или
    отклонении заказа: `succeeded` → `refunded` (`refunded_at`, только
    имитация), `pending` → `cancelled`.

Backend проверяет, что сумма платежа соответствует заказу и что
состояние оплаты не переводится в недопустимое состояние. Повторная
операция возврата не создаёт повторных побочных эффектов.

## 9. Доставка и курьеры

### 9.1 `delivery_zones`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| name | VARCHAR(120) | NOT NULL |
| description | TEXT | NULL |
| delivery_fee | NUMERIC(12,2) | NOT NULL, CHECK >= 0 |
| min_order_amount | NUMERIC(12,2) | NOT NULL, DEFAULT 0, CHECK >= 0 |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE |
| boundary | geometry(MultiPolygon, 4326) | NULL до настройки зоны |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |

CHECK: `NOT is_active OR boundary IS NOT NULL` (D5);
`boundary IS NULL OR ST_IsValid(boundary)` (DEC-122; NULL допустим, пока
зона не настроена).

Использовать PostGIS. В PostgreSQL включить расширение `postgis`, а
Docker-образ базы выбрать с поддержкой PostGIS. Для `boundary` создать
GIST-индекс. При сохранении геометрии проверять валидность
(`ST_IsValid`) и SRID 4326.

Пересечение активных зон по площади запрещено; касание только
границами допускается (DEC-53). Проверка выполняется сервисом при
создании/изменении/активации зоны по пересечению внутренних областей,
например `ST_Relate(a, b, 'T********')`, а не `ST_Intersects`. Зона
принадлежности точки определяется `ST_Covers(boundary, point)`; при
попадании точки на общую границу нескольких зон выбирается зона с
меньшим `delivery_fee`, при равной стоимости --- с меньшим `id` (UUID),
чтобы результат был стабильным (DEC-102). Вся проверка геометрии и
пересечений выполняется на backend через PostGIS; данным frontend не
доверяем (DEC-94).

Backend определяет зону по координатам адреса, затем получает стоимость
доставки и минимальную сумму заказа (раздел 10.1). Если точка не входит
ни в одну активную зону, доставка недоступна; интерфейс предлагает
самовывоз.

### 9.2 `deliveries`

Операционные данные доставки (DEC-16). Адрес, координаты и стоимость
хранятся только в snapshot `orders`.

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| order_id | UUID | NOT NULL, FK → orders.id, ON DELETE RESTRICT, UNIQUE |
| delivery_zone_id | UUID | NULL; FK → delivery_zones.id, ON DELETE SET NULL |
| delivery_comment | TEXT | NULL; комментарий для курьера (снимок комментария адреса) |
| delivered_at | TIMESTAMPTZ | NULL |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |

Индекс: `(delivery_zone_id)` (DEC-134).

Создаётся только для заказов типа `delivery`, в транзакции оформления.
`delivered_at` заполняется при переходе заказа в `completed` курьером.

### 9.3 `courier_assignments`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| order_id | UUID | NOT NULL, FK → orders.id, ON DELETE RESTRICT |
| courier_id | UUID | NOT NULL, FK → users.id, ON DELETE RESTRICT |
| assigned_by | UUID | NULL; FK → users.id, ON DELETE SET NULL |
| assignment_type | VARCHAR(20) | NOT NULL, CHECK IN (`manual`,`automatic`) |
| status | VARCHAR(20) | NOT NULL, DEFAULT `active`, CHECK IN (`active`,`completed`,`cancelled`,`declined`) |
| assigned_at | TIMESTAMPTZ | NOT NULL |
| accepted_at | TIMESTAMPTZ | NULL; заполняется только при фактическом принятии курьером (DEC-52, DEC-83) |
| declined_at | TIMESTAMPTZ | NULL; время отказа курьера (DEC-92) |
| decline_reason | TEXT | NULL; необязательная причина отказа (DEC-92) |
| completed_at | TIMESTAMPTZ | NULL |

CHECK: `(status = 'declined') = (declined_at IS NOT NULL)`;
`status <> 'declined' OR accepted_at IS NULL`.

Создать частичный уникальный индекс по `order_id` для
`status = 'active'`: у одного заказа не может быть двух активных
назначений курьера. Создать индексы `(courier_id, status)` и
`(order_id, courier_id)` (для исключения отказавшихся курьеров при
автоназначении), а также `(assigned_by)` (DEC-134).

Правила:

-   назначение возможно только для заказов `delivery` в статусах
    `confirmed`, `preparing`, `ready_for_pickup` (DEC-48);
-   backend проверяет роль `courier`, наличие `courier_profiles`,
    доступность курьера и лимит активных заказов;
-   ручное и автоматическое назначение выполняются с `SELECT … FOR
    UPDATE` на строку `courier_profiles` выбранного курьера (DEC-67);
    единый порядок блокировок: `orders` (`FOR UPDATE`) → `users`
    курьера (`FOR SHARE`) → `courier_profiles` (`FOR UPDATE`) → строки
    `courier_assignments`; автоназначение блокирует строки всех
    кандидатов одним запросом `ORDER BY user_id`; принятие, отказ и
    курьерские переходы блокируют `orders`, затем назначение;
    деактивация курьера и снятие роли блокируют `users` (`FOR NO KEY
    UPDATE`, DEC-140) и сериализуются с назначением через `users`;
    удерживая `users` или `courier_profiles`, нельзя блокировать
    `orders` (DEC-151 п. 6);
-   автоматическое назначение запускается кнопкой администратора и
    выбирает доступного курьера с наименьшим количеством активных
    назначений, меньшим `max_active_orders` (DEC-49), исключая курьеров,
    отказавшихся от этого заказа (`declined`, DEC-92); при равенстве ---
    курьер с наиболее ранним `max(assigned_at)` по всем его назначениям
    (курьер без назначений первым), затем меньший `user_id` (DEC-151
    п. 3); если таких нет ---
    `409 NO_COURIER_AVAILABLE` (DEC-50); ручное назначение отказавшегося
    курьера администратором допускается;
-   курьер может отказаться от назначения только до принятия
    (`accepted_at IS NULL`) и пока заказ не перешёл в `out_for_delivery`
    (DEC-151 п. 5): назначение → `declined`, `declined_at`,
    необязательная `decline_reason`; статус заказа не меняется;
    администратор назначает другого курьера (DEC-92); после принятия
    отказ недоступен, переназначение выполняет только администратор;
-   переназначение: текущее активное назначение → `cancelled`,
    создаётся новое, в одной транзакции (DEC-51); назначение того же
    курьера, у которого уже есть активное назначение, ничего не меняет
    (DEC-151 п. 4);
-   неудачная доставка в v1 не отражается отдельным статусом
    назначения или заказа; после `out_for_delivery` назначение не
    меняется до `completed` (DEC-151 п. 1);
-   курьер обязан принять назначение (`accepted_at`) до перевода заказа
    в `out_for_delivery` (DEC-83); исключение --- административное
    вмешательство (DEC-91), которое требует активного назначения, но не
    `accepted_at`;
-   при `completed` заказа назначение → `completed`; при отмене заказа →
    `cancelled` (DEC-41);
-   исторические назначения сохраняются.

## 10. Настройки ресторана и рабочее время

### 10.1 `restaurant_settings`

Одна строка с настройками единственного филиала.

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | SMALLINT | PK, CHECK = 1 --- обеспечивает singleton |
| restaurant_name | VARCHAR(180) | NOT NULL |
| phone | VARCHAR(30) | NULL |
| address | TEXT | NULL |
| latitude | NUMERIC(10,7) | NULL |
| longitude | NUMERIC(10,7) | NULL |
| min_order_amount | NUMERIC(12,2) | NOT NULL, DEFAULT 0, CHECK >= 0 |
| delivery_enabled | BOOLEAN | NOT NULL, DEFAULT TRUE |
| pickup_enabled | BOOLEAN | NOT NULL, DEFAULT TRUE |
| timezone | VARCHAR(64) | NOT NULL, DEFAULT `Asia/Bishkek` |
| updated_at | TIMESTAMPTZ | NOT NULL |

`id = 1` --- единственная допустимая строка.

Правило минимальной суммы (DEC-17–DEC-19), реализуется в едином
сервисе расчёта заказа:

-   доставка: `delivery_zones.min_order_amount`, если он больше 0, иначе
    `restaurant_settings.min_order_amount`;
-   самовывоз: `restaurant_settings.min_order_amount`;
-   сравнивается с `subtotal` без стоимости доставки.

`delivery_enabled` и `pickup_enabled` проверяются при quote и создании
заказа (DEC-22).

### 10.2 `restaurant_working_hours`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| weekday | SMALLINT | NOT NULL, CHECK BETWEEN 0 AND 6 |
| opens_at | TIME | NULL |
| closes_at | TIME | NULL |
| is_closed | BOOLEAN | NOT NULL, DEFAULT FALSE |

UNIQUE `(weekday)` --- ровно один интервал работы на день недели;
несколько интервалов в день и круглосуточный режим в v1 не
поддерживаются (DEC-107). Соглашение: `0 = Monday`, `6 = Sunday`.
CHECK: `is_closed OR (opens_at IS NOT NULL AND closes_at IS NOT NULL AND
opens_at <> closes_at)`. Если `is_closed = TRUE`, `opens_at` и
`closes_at` могут быть NULL.

Ночные интервалы (DEC-21): если `closes_at < opens_at`, интервал
продолжается после полуночи; время после полуночи относится к интервалу
дня `weekday`, в который ресторан открылся. Время сравнивается в
`restaurant_settings.timezone`. Заказы вне рабочих часов не принимаются
(DEC-20); решающий момент --- время создания заказа, буфера перед
закрытием нет. Ночной «хвост» не должен пересекаться с интервалом
следующего дня (проверка сервисом, `422 INVALID_WORKING_HOURS`). Для
первой версии специальные праздничные расписания не требуются.

## 11. Уведомления и Telegram

Уведомления (внутренние и Telegram) в v1 предназначены только клиентам
(DEC-57, DEC-85). Рабочие экраны персонала получают данные через API и
polling.

### 11.1 `notifications`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| user_id | UUID | NOT NULL, FK → users.id, ON DELETE CASCADE |
| order_id | UUID | NULL; FK → orders.id, ON DELETE SET NULL |
| type | VARCHAR(50) | NOT NULL; см. список типов |
| payload | JSONB | NOT NULL, DEFAULT `'{}'` |
| is_read | BOOLEAN | NOT NULL, DEFAULT FALSE |
| created_at | TIMESTAMPTZ | NOT NULL |
| read_at | TIMESTAMPTZ | NULL |

Колонок `title`/`message` нет (DEC-55): текст формируется на frontend
через i18next по `type` и `payload`.

Типы v1: `order_status_changed`
(`{order_number, old_status, new_status}`),
`cancellation_request_approved`, `cancellation_request_rejected`
(`{order_number, admin_comment?}`). Отмена по таймауту оплаты
порождает `order_status_changed` с `new_status = cancelled`.

CHECK (DEC-126): `type IN ('order_status_changed',
'cancellation_request_approved', 'cancellation_request_rejected')`.
Тот же CHECK действует для `telegram_outbox.event_type`. Значения берутся
из одного Python `StrEnum`; новый тип добавляется только отдельным
решением и миграцией, изменяющей CHECK.

Индексы: `(user_id, is_read, created_at DESC)`; `(order_id)` (DEC-135).
Уведомления внутри сайта
сохраняются в БД. Telegram --- дополнительный канал, а не единственный
источник информации о заказе.

### 11.2 `telegram_links`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| user_id | UUID | NOT NULL, FK → users.id, ON DELETE CASCADE, UNIQUE |
| telegram_chat_id | BIGINT | NOT NULL, UNIQUE |
| telegram_username | VARCHAR(100) | NULL |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE; разрешение боту писать пользователю, не признак привязки (DEC-152 п. 8) |
| linked_at | TIMESTAMPTZ | NOT NULL |

Привязка определяется наличием строки. Отвязка (`DELETE /telegram/link`
с подтверждением текущим паролем, DEC-152 п. 5) удаляет строку, чтобы
тот же чат можно было привязать снова. Чат, уже привязанный к другому
аккаунту, не может быть привязан повторно, и аккаунт, уже связанный с
другим чатом, не привязывается к новому (DEC-105, DEC-152); переноса
связи и слияния аккаунтов нет.

`is_active` --- разрешение боту писать пользователю (DEC-152 п. 8);
используется только при отправке сообщений (этап 10). Вход в Mini App и
поиск связи `is_active` не учитывают. Значения:

-   `FALSE` --- связь создана из Mini App при `allows_write_to_pm ≠ true`
    в проверенном `init_data`; Telegram ответил 403 (бот заблокирован
    пользователем). Пока `FALSE`, новые события в очередь не ставятся;
-   `TRUE` --- успешный вход, регистрация или привязка из Mini App с
    проверенным `allows_write_to_pm = true`; привязка через `/start`
    (этап 10).

`telegram_chat_id` хранит Telegram `user.id`; для личного чата с ботом
он совпадает с `chat_id`. Поэтому UNIQUE по `telegram_chat_id` означает
«один Telegram-аккаунт --- не более одного пользователя» (DEC-142), а
UNIQUE по `user_id` --- «не более одного Telegram-аккаунта у
пользователя». Строка создаётся регистрацией или привязкой из Mini App
(DEC-152 п. 2) либо `/start` бота (этап 10) в порядке блокировок
advisory(Telegram `user.id`) → `users` → `telegram_links` (DEC-152 п. 3).
Для аккаунта без email и пароля строка не удаляется (`DELETE
/telegram/link` отклоняется), иначе аккаунт останется без способа входа.

### 11.3 `telegram_link_tokens`

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| user_id | UUID | NOT NULL, FK → users.id, ON DELETE CASCADE |
| token_hash | TEXT | NOT NULL, UNIQUE |
| expires_at | TIMESTAMPTZ | NOT NULL |
| used_at | TIMESTAMPTZ | NULL |
| created_at | TIMESTAMPTZ | NOT NULL |

Пользователь связывает Telegram через одноразовый токен / deep link
`https://t.me/<bot>?start=<token>`. Токен (32 случайных байта) живёт 10
минут (DEC-87, значение в конфигурации), хранится в БД только в виде
SHA-256 хеша и может быть использован один раз; после успешной привязки
повторно не принимается. Выдача нового токена помечает прежние
неиспользованные токены пользователя использованными. Индекс
`(user_id)` (DEC-135). Бот получает
команду `/start <token>` через long polling (DEC-03, DEC-105).

### 11.4 `telegram_outbox`

Очередь надёжной отправки Telegram-сообщений (DEC-75).

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| user_id | UUID | NOT NULL, FK → users.id, ON DELETE CASCADE |
| order_id | UUID | NULL; FK → orders.id, ON DELETE SET NULL |
| event_type | VARCHAR(50) | NOT NULL; те же типы, что в `notifications`; CHECK по тому же списку (DEC-126) |
| payload | JSONB | NOT NULL; без адреса, телефона, сумм и токенов |
| language_code | VARCHAR(2) | NOT NULL, CHECK IN (`ru`,`ky`,`uz`); язык на момент создания события (DEC-105) |
| status | VARCHAR(20) | NOT NULL, DEFAULT `pending`, CHECK IN (`pending`,`sent`,`failed`,`skipped`) |
| attempts | SMALLINT | NOT NULL, DEFAULT 0, CHECK >= 0 |
| next_attempt_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() |
| sent_at | TIMESTAMPTZ | NULL |
| last_error | TEXT | NULL; без токенов и секретов |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |

Индексы: `(status, next_attempt_at)`; `(user_id)`, `(order_id)`
(DEC-135). Запись создаётся в той же
транзакции, что и изменение заказа, только если у пользователя есть
активная `telegram_links` и Telegram включён в конфигурации;
`language_code` = `users.preferred_language` в этот момент, и
последующая смена языка пользователем на уже созданное событие не
влияет (DEC-105).

Отправку выполняет фоновый worker (DEC-104, DEC-105):

-   максимум 5 попыток; задержка `30 с × 2^(attempt-1)`, не более 1 часа;
    после последней неудачи --- `failed`;
-   ответ Telegram 429 --- ожидание `retry_after`, попытка не
    засчитывается;
-   ответ 403 --- привязка `is_active = FALSE`, запись `skipped`;
-   привязка исчезла до отправки --- `skipped`;
-   токен бота не попадает в логи (URL с токеном маскируется).

Ошибка Telegram не откатывает заказ.

## 12. Основные связи

-   `users` M:N `roles` через `user_roles`.
-   `users` 1:N `addresses`.
-   `users` 1:1 `courier_profiles` для пользователей-курьеров.
-   `users` 1:N `refresh_tokens`, `password_reset_tokens`,
    `notifications`, `telegram_link_tokens`, `telegram_outbox`,
    `idempotency_keys`.
-   `users` 1:0..1 `telegram_links`.
-   `refresh_tokens` образуют семьи по `family_id`; `replaced_by_id`
    ссылается на следующий токен цепочки.
-   `categories` 1:N `products`.
-   `categories` 1:N `category_translations`.
-   `products` 1:N `product_translations`, `product_images`,
    `product_variants` (минимум один вариант).
-   `products` M:N `modifier_groups` через `product_modifier_groups`.
-   `modifier_groups` 1:N `modifiers`.
-   `modifier_groups`, `modifiers` имеют собственные
    translation-таблицы.
-   `product_variants` M:N `modifiers` через `variant_modifier_prices`
    для переопределения цены.
-   `users` 1:1 `carts`; `carts` 1:N `cart_items`; `cart_items` 1:N
    `cart_item_modifiers`.
-   `users` 1:N `orders`; `orders` 1:N `order_items`,
    `order_status_history`, `payments`, `cancellation_requests`.
-   `order_items` 1:N `order_item_modifiers`.
-   `orders` 1:0..1 `deliveries`; `orders` 1:N `courier_assignments`.
-   `delivery_zones` 1:N `deliveries`.
-   `users` 1:N `courier_assignments` в качестве курьера и отдельно в
    качестве назначившего сотрудника.

## 13. Индексы и ограничения --- сводный список

Помимо PK и UNIQUE, создать индексы для частых запросов:

-   `users`: UNIQUE INDEX по `lower(email)`; CHECK
    `ck_users_credentials_pair` (DEC-142).
-   `addresses`: индекс по `user_id`; partial UNIQUE по
    `user_id WHERE is_default = TRUE`.
-   `refresh_tokens`: `(user_id, expires_at)`, `(family_id)`.
-   `password_reset_tokens`: `(user_id)` (DEC-127).
-   `products`: `(category_id, is_available, sort_order) WHERE deleted_at
    IS NULL` (D6).
-   Все translation-таблицы: UNIQUE по `(entity_id, language_code)`.
-   `product_images`: `(product_id, sort_order)` и partial UNIQUE по
    `product_id WHERE is_primary = TRUE`.
-   `product_variants`: индекс по `product_id`.
-   `modifiers`: индекс по `group_id`.
-   `product_modifier_groups`: индекс по `group_id` (DEC-129).
-   `variant_modifier_prices`: индекс по `modifier_id` (DEC-129).
-   `cart_items`: индекс по `cart_id`; `(product_id)`, `(variant_id)` (DEC-130).
-   `cart_item_modifiers`: индекс по `modifier_id` (DEC-130).
-   `orders`: `(user_id, created_at DESC)`, `(status, created_at)`,
    partial `(payment_due_at) WHERE status = 'pending' AND payment_due_at
    IS NOT NULL`.
-   `order_items`: индекс по `order_id`; `(product_id)`, `(variant_id)` (DEC-133).
-   `order_item_modifiers`: `(order_item_id)`, `(modifier_id)` (DEC-133).
-   `order_status_history`: `(order_id, created_at)`; `(changed_by)` (DEC-133).
-   `cancellation_requests`: partial UNIQUE по
    `order_id WHERE status = 'pending'`; `(order_id)`, `(user_id)`,
    `(reviewed_by)` (DEC-133).
-   `payments`: `(order_id, created_at)`; partial UNIQUE по `order_id
    WHERE status = 'succeeded'`; partial UNIQUE по `order_id WHERE status
    = 'pending'`; `(payment_method_id)` (DEC-134).
-   `delivery_zones`: GIST по `boundary`.
-   `deliveries`: UNIQUE по `order_id`; `(delivery_zone_id)` (DEC-134).
-   `courier_assignments`: `(courier_id, status)`, `(order_id,
    courier_id)` и partial UNIQUE по `order_id WHERE status = 'active'`;
    `(assigned_by)` (DEC-134).
-   `notifications`: `(user_id, is_read, created_at DESC)`; `(order_id)` (DEC-135).
-   `telegram_links`: UNIQUE по `user_id` и `telegram_chat_id`.
-   `telegram_link_tokens`: UNIQUE по `token_hash`; `(user_id)` (DEC-135).
-   `telegram_outbox`: `(status, next_attempt_at)`; `(user_id)`, `(order_id)` (DEC-135).
-   `idempotency_keys`: UNIQUE `(user_id, scope, key)`; индекс по
    `expires_at`.

Также использовать CHECK constraints для положительных количеств,
неотрицательных цен и сумм, допустимых статусов (включая
`order_status_history`), типов доставки, языков, причин отмены, формата
телефона и времени, а также CHECK'и из разделов 3.1, 5.1, 7.2, 7.5, 9.1,
9.3, 10.2, 11.4.

Sequence: `order_number_seq`.

## 14. Транзакции и бизнес-инварианты

### 14.1 Оформление заказа

Создание заказа должно выполняться одной транзакцией:

1.  Зарегистрировать `Idempotency-Key` (раздел 14.2).
2.  Заблокировать (`SELECT … FOR UPDATE`) корзину пользователя; пустая
    корзина --- ошибка.
3.  Проверить рабочие часы и флаг `delivery_enabled`/`pickup_enabled`.
4.  Заново получить товары, варианты и модификаторы из БД.
5.  Проверить доступность каждого элемента и корректность выбранных
    модификаторов (раздел 5.7).
6.  Пересчитать цены на backend-е единым модулем расчёта; не доверять
    суммам, присланным frontend-ом.
7.  Для доставки определить активную зону по координатам и рассчитать
    стоимость доставки.
8.  Проверить минимальную сумму заказа (раздел 10.1).
9.  Сравнить итог с `expected_total`; при расхождении --- откат и
    `409 PRICE_CHANGED` с актуальным расчётом.
10. Создать `orders` (номер из sequence, `language_code`,
    `payment_due_at` для `mock_card`), `order_items`,
    `order_item_modifiers`.
11. Создать `deliveries`, если тип заказа --- доставка; сохранить новый
    адрес в `addresses`, если клиент попросил.
12. Создать запись `payments` в статусе `pending`.
13. Создать начальную запись `order_status_history`.
14. Очистить `cart_items` пользователя.
15. Сохранить результат в `idempotency_keys`.
16. Зафиксировать транзакцию.

Если любой шаг завершается ошибкой, транзакция откатывается полностью.

### 14.2 Защита от повторной отправки

Frontend может повторить запрос из-за сетевой ошибки. Idempotency для
создания заказа обязательна (DEC-59). Таблица `idempotency_keys`:

| Поле | Тип | Ограничения / назначение |
|---|---|---|
| id | UUID | PK |
| user_id | UUID | NOT NULL; FK → users.id, ON DELETE CASCADE |
| scope | VARCHAR(50) | NOT NULL; например `create_order` |
| key | VARCHAR(128) | NOT NULL |
| request_hash | VARCHAR(64) | NOT NULL; SHA-256 нормализованного payload |
| response_status | SMALLINT | NULL; NULL --- запрос ещё выполняется |
| response_body | JSONB | NULL |
| created_at | TIMESTAMPTZ | NOT NULL |
| expires_at | TIMESTAMPTZ | NOT NULL; `created_at + 24 часа` |

UNIQUE `(user_id, scope, key)`. Алгоритм (DEC-109):

1.  `request_hash` --- SHA-256 канонического JSON тела (ключи
    отсортированы, суммы --- строки с 2 знаками, отсутствующие
    необязательные поля = `null`).
2.  В начале транзакции заказа --- `INSERT` ключа с `response_status =
    NULL` при `lock_timeout = 5 s`.
3.  Вставка прошла → заказ создаётся, в той же транзакции сохраняются
    `response_status` и `response_body`, commit.
4.  Тот же ключ обрабатывается параллельно → PostgreSQL ждёт на
    уникальном индексе: после commit первой транзакции --- п. 5; после
    её rollback --- вставка проходит (п. 3); ожидание дольше
    `lock_timeout` → `409 IDEMPOTENCY_IN_PROGRESS`.
5.  Запись существует: тот же `request_hash` → вернуть сохранённый
    ответ (`201`, заголовок `Idempotent-Replayed: true`), второй заказ не
    создаётся; другой хеш → `409 IDEMPOTENCY_KEY_CONFLICT`.
6.  Любая ошибка (включая `PRICE_CHANGED`) откатывает транзакцию вместе
    с записью ключа: ошибки не сохраняются как результат, повтор с тем
    же ключом разрешён.
7.  `expires_at = created_at + 24 часа`; просроченные ключи удаляет
    worker, после этого ключ можно использовать снова. Ключи разных
    пользователей не конфликтуют.

### 14.3 Изменение статуса заказа

-   Изменять статус только через сервис статусов заказа (state machine).
-   Блокировать строку заказа `SELECT … FOR UPDATE`.
-   Проверять разрешённый переход из текущего статуса (раздел 7.1).
-   Проверять роль пользователя и его полномочия (для курьера ---
    принадлежность активного назначения).
-   В той же транзакции обновлять `orders.status` и добавлять
    `order_status_history`.
-   Изменения статуса, связанные с доставкой, синхронизировать с
    `deliveries`, `courier_assignments` и `payments`.
-   Публиковать доменное событие изменения статуса (DEC-79); обработчики
    в той же транзакции создают `notifications` и `telegram_outbox` для
    клиента.
-   Не позволять клиенту изменять статус заказа напрямую.

**Единая операция отмены** (DEC-39–DEC-41, DEC-82), используется при
одобрении запроса клиента, прямой отмене администратором и таймауте
оплаты:

1. заблокировать заказ; если он уже `cancelled` --- вернуть текущее
   состояние без побочных эффектов (идемпотентность);
2. проверить, что отмена допустима из текущего статуса;
3. `status = cancelled`, `cancelled_at`, `cancellation_reason_code`;
   запись истории с причиной;
4. платежи: `succeeded` mock → `refunded` (`refunded_at`), `pending` →
   `cancelled`; уже `refunded` не изменяется;
5. активное назначение курьера → `cancelled`;
6. `pending`-запрос отмены → `approved` (или остаётся `approved`);
7. доменное событие → уведомление клиенту.

Отклонение заказа (`rejected`) применяет те же правила к платежам.

### 14.4 Снимки данных

После создания заказа не пересчитывать его историю на основе текущего
каталога. Изменение цены товара, названия, перевода, состава
модификатора или стоимости доставки не должно изменять уже созданный
заказ.

### 14.5 Фоновые задачи

Выполняются отдельным процессом worker (DEC-104): один экземпляр в v1,
`asyncio`, без Celery/APScheduler/брокеров; worker вызывает те же
сервисы, что и API; каждая задача --- в отдельной транзакции; ошибка
одной задачи не останавливает worker; graceful shutdown.

| Задача | Интервал (конфигурация) | Правило |
|---|---|---|
| Таймаут mock-оплаты | 60 с | заказы `pending` с `payment_due_at < now()`, пачками по 50, `FOR UPDATE SKIP LOCKED`; единая операция отмены с `payment_timeout`, `changed_by = NULL` (DEC-84) |
| Отправка `telegram_outbox` | 5 с | `pending` с `next_attempt_at <= now()`, пачками по 50, `SKIP LOCKED`; правила --- §11.4 |
| Telegram long polling | непрерывно | `getUpdates`, timeout 30 с; повторные апдейты обрабатываются идемпотентно (DEC-03) |
| Очистка | 1 час | просроченные `idempotency_keys`; refresh-, reset- и Telegram-токены, истёкшие более 7 дней назад; `telegram_outbox` в `sent`/`skipped`/`failed` старше 30 дней |

## 15. Миграции и начальные данные

Использовать Alembic. Все изменения схемы проводить через миграции; не
использовать `Base.metadata.create_all()` как механизм
production-миграций. Миграции также создают расширение `postgis`,
sequence `order_number_seq` и функцию номера заказа (DEC-123).

Схема создаётся семью ревизиями `0002`–`0008` по доменам (DEC-116).
Миграции и `downgrade`-проверки выполняются только на изолированной
`db-test`; основная БД мигрируется только вперёд.

Seed-данные первой версии --- CLI `python -m app.seeds <режим>` (DEC-117):

-   `base` (обязательные системные данные):
    -   ровно 4 роли: `customer`, `admin`, `cook`, `courier`;
    -   способы оплаты `cash`, `mock_card` (`mock_card` ---
        исключительно демонстрационный, без реального списания денег,
        DEC-47; названия --- в переводах frontend по `code`);
    -   одна строка `restaurant_settings` с `id = 1`: `Demo Restaurant —
        Osh`, глобальный минимум `300.00` KGS, фиктивные
        демонстрационные контакты `+996000000000` и
        `Демонстрационный адрес, г. Ош`, явно обозначенные как
        демонстрационные (DEC-118, DEC-125); координаты ресторана не
        заполняются (DEC-136);
    -   рабочие часы ресторана: ежедневно `10:00–23:00` (DEC-119,
        DEC-124);
-   `demo` (демонстрационные данные; требует выполненного `base`,
    DEC-136):
    -   демонстрационная зона доставки в Оше, явно помеченная как
        демонстрационная: доставка `100.00` KGS, минимум `500.00` KGS
        (DEC-76, DEC-119, DEC-124); граница --- прямоугольник широта
        `40.49–40.57`, долгота `72.74–72.86`; при пересечении с
        активной зоной seed завершается ошибкой (DEC-53, DEC-136);
    -   8 категорий и 21 тестовый товар (у каждого минимум один
        вариант; у простых --- «Стандарт») и модификаторы, без
        изображений; переводы категорий, товаров, вариантов, групп
        модификаторов и модификаторов на `ru`, `ky`, `uz` (DEC-120,
        состав --- DEC-136).

Seed-скрипты идемпотентны: повторный запуск не создаёт дубликаты,
существующие данные не перезаписываются и не удаляются --- создаются
только отсутствующие записи (DEC-136). Все операции режима
выполняются в одной транзакции под advisory lock и только на БД с
ревизией head. Seed не создаёт пользователей и стандартных учётных
данных. Основная БД для seed пока не используется: тесты seed
выполняются только на `db-test` (DEC-136). Принадлежность демо-записи
seed определяется только её детерминированным UUIDv5. Если
естественный ключ демо-записи занят записью с другим `id`, режим
завершается ошибкой с кодом 1 и полным rollback (DEC-137).

Первый администратор (DEC-88) создаётся командой
`python -m app.cli create-admin` (в Docker: `docker compose exec backend
python -m app.cli create-admin`):

-   команда интерактивно запрашивает имя и email (логин), пароль --- дважды
    и без отображения в терминале; пароль проверяется политикой DEC-96;
-   работает, только если в системе ещё нет пользователя с ролью
    `admin`;
-   защита от параллельного запуска: одна транзакция с
    `pg_advisory_xact_lock(<константа>)`, затем проверка отсутствия
    администратора и создание пользователя **только с ролью `admin`**;
    роль `customer` автоматически не добавляется и при необходимости
    назначается отдельно (DEC-113);
-   `must_change_password = FALSE`; хранится только Argon2id-хеш;
    пароль не попадает в исходный код, env-файлы и логи.

## 16. PostGIS и Docker

Так как `delivery_zones.boundary` использует
`geometry(MultiPolygon, 4326)`, PostgreSQL должен запускаться из образа
с установленным PostGIS. В миграции включить:

``` sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

Проверить, что выбранный Docker image содержит совместимую версию
PostGIS. Обычный образ PostgreSQL без PostGIS не подходит. Тестовая БД
также использует образ с PostGIS (DEC-69).

Используется `postgis/postgis:16-3.6` (PostgreSQL 16, PostGIS 3.6).
Собственный init-скрипт образа отключён: каталог
`/docker-entrypoint-initdb.d` заменён пустым `infra/postgres/initdb.d`,
поэтому расширение `postgis` устанавливает только миграция Alembic
`0001_enable_postgis`, а её `downgrade` его удаляет.

## 17. Что не входит в первую версию

Не реализовывать без отдельного согласования:

-   реальные карточные платежи и хранение карточных данных;
-   промокоды, купоны и бонусные баллы;
-   live GPS-карту курьера;
-   несколько филиалов ресторана;
-   сложный складской учёт и списание ингредиентов;
-   праздничные исключения в расписании;
-   микросервисную архитектуру;
-   подтверждение email;
-   уведомления сотрудникам;
-   Telegram webhook.

## 18. Требования к реализации SQLAlchemy

-   Использовать SQLAlchemy 2.0 style (`Mapped`, `mapped_column`,
    `relationship`).
-   Типы UUID, `Numeric(12, 2)`, `DateTime(timezone=True)`, `JSONB` для
    idempotency response, notifications и outbox payload.
-   Явно задавать `ForeignKey` и `ondelete`.
-   Отношения объявляются с `lazy="raise"`; нужные связи загружаются
    явно через `selectinload` / `joinedload` (DEC-121).
-   Для partial indexes и PostGIS типов использовать возможности
    PostgreSQL dialect (PostGIS --- через `GeoAlchemy2`, DEC-94).
-   Не помещать всю бизнес-логику в ORM-модели. Межтабличные проверки,
    переходы статусов, расчёты и права доступа находятся в сервисном
    слое.
-   Для критичных операций использовать транзакции и подходящие
    блокировки (`FOR UPDATE` для корзины при checkout, заказа при смене
    статуса, `courier_profiles` при назначении).
-   Все миграции должны быть проверены на чистой БД и на БД с предыдущей
    миграцией.

------------------------------------------------------------------------

**Инструкция Claude Code:** перед созданием моделей проверь
согласованность этой схемы с `DECISIONS.md`, `TECHNICAL_SPECIFICATION.md`
и `API_SPECIFICATION.md`. Если найдёшь конфликт, не выбирай решение
молча: перечисли конфликт и предложи вариант. Затем реализуй модели,
связи, индексы, ограничения и Alembic-миграции. Не пропускай
бизнес-инварианты, которые нельзя выразить простыми SQL constraints.
