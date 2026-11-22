# API_SPECIFICATION.md

Утверждённые решения --- в `docs/DECISIONS.md` (ссылки `DEC-NN`). При
расхождении приоритет имеет `DECISIONS.md`. Схема данных ---
`DATABASE_SCHEMA.md`.

## 1. Общий контракт

Base path: `/api/v1`. JSON по умолчанию; загрузки изображений ---
multipart (`python-multipart`). Даты --- ISO 8601 с timezone. Деньги
возвращать decimal-строками, например `"450.00"`. Списки имеют `items`
и `pagination` (`page`, `page_size`, `total`, `pages`).

Формат ошибки (единый для всех ошибок, включая ошибки валидации
FastAPI/Pydantic и `HTTPException`, DEC-73, DEC-103):

``` json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Проверьте данные",
    "details": [{"field": "email", "message": "Некорректный email"}],
    "request_id": "..."
  }
}
```

Правила (DEC-103):

-   `code` --- стабильный машинный код; frontend показывает
    локализованный текст по `code` через i18next.
-   `message` --- запасной текст на русском для разработчика.
-   `details` --- список ошибок полей `[{field, message}]` или объект с
    данными (например, quote для `PRICE_CHANGED`).
-   `request_id` совпадает с заголовком ответа `X-Request-ID` и записью в
    логе.
-   Stack trace, SQL, пути файлов и секреты в ответ не попадают никогда.
    Подробности непредвиденных ошибок --- только в логах; клиенту ---
    `500 INTERNAL_ERROR`.

HTTP: 200/201/202/204, 400, 401, 403, 404, 409, 422, 429, 500.

### 1.1 Каталог кодов ошибок

| HTTP | code | Где | Условие |
|---|---|---|---|
| 422 | `VALIDATION_ERROR` | любой | неверное тело, параметры, заголовки (включая ошибки Pydantic, формат телефона, политику паролей, `Idempotency-Key`) |
| 401 | `UNAUTHORIZED` | защищённые | нет/истёк/невалиден access token; пользователь деактивирован |
| 401 | `INVALID_CREDENTIALS` | `/auth/login`, `/auth/telegram/webapp/link` | неверный email или пароль, аккаунт без email **или** аккаунт неактивен --- ответ одинаковый (DEC-152) |
| 401 | `INVALID_REFRESH_TOKEN` | `/auth/refresh` | токен отсутствует, истёк, отозван или использован повторно |
| 401 | `INVALID_TELEGRAM_AUTH` | `/auth/telegram/webapp`, `…/register`, `…/link` | `init_data` не прошёл проверку (в том числе длина больше 4096) **или** (при входе) пользователь неактивен --- ответ одинаковый, причина не раскрывается (DEC-142, DEC-152, DEC-155) |
| 403 | `FORBIDDEN` | любой | нет нужной роли |
| 403 | `CSRF_FAILED` | cookie-операции | не прошла проверка `Origin` или заголовка `X-CSRF-Protection` |
| 403 | `PASSWORD_CHANGE_REQUIRED` | авторизованные, кроме me/change/logout/refresh | `must_change_password = true` |
| 400 | `INVALID_OR_EXPIRED_TOKEN` | `/auth/password/reset` | токен сброса невалиден/истёк/использован (без уточнения причины) |
| 404 | `NOT_FOUND` | любой | ресурс не существует **или** недоступен пользователю (чужой ресурс неотличим от несуществующего) |
| 409 | `EMAIL_ALREADY_EXISTS` | register, создание сотрудника | email занят |
| 409 | `PRICE_CHANGED` | `POST /orders` | `expected_total` ≠ расчёт; `details` --- актуальный quote |
| 409 | `IDEMPOTENCY_KEY_CONFLICT` | `POST /orders` | тот же ключ, другой payload |
| 409 | `IDEMPOTENCY_IN_PROGRESS` | `POST /orders` | исходный запрос с тем же ключом ещё выполняется |
| 409 | `INVALID_STATUS_TRANSITION` | смена статуса | переход не разрешён state machine |
| 409 | `CANCELLATION_NOT_ALLOWED` | запрос отмены, отмена | текущий статус не позволяет |
| 409 | `CANCELLATION_REQUEST_PENDING` | `POST …/cancellation-requests` | уже есть ожидающий запрос |
| 409 | `NO_COURIER_AVAILABLE` | auto-assign | нет доступного курьера (DEC-50) |
| 409 | `COURIER_NOT_AVAILABLE` | assign-courier | курьер без роли `courier` или профиля, неактивен, недоступен или на лимите (DEC-151 п. 3) |
| 409 | `ASSIGNMENT_NOT_ACCEPTED` | `picked-up` | курьер не принял назначение (DEC-83) |
| 409 | `ASSIGNMENT_ALREADY_ACCEPTED` | `decline` | отказ после принятия запрещён (DEC-92); после `out_for_delivery` без принятия `decline` и `accept` --- `INVALID_STATUS_TRANSITION` (DEC-151 п. 5) |
| 409 | `COURIER_HAS_ACTIVE_ASSIGNMENTS` | смена ролей, деактивация сотрудника | нельзя снять роль courier или деактивировать курьера с активными назначениями (DEC-29, DEC-150) |
| 409 | `ADMIN_ACCOUNT_PROTECTED` | `POST /admin/staff/{user_id}/deactivate`, `…/reactivate` | пользователь с ролью `admin`: API сотрудников не управляет административными аккаунтами (DEC-150) |
| 409 | `PAYMENT_NOT_ALLOWED` | `/payments/mock/confirm` | заказ не `mock_card`, не `pending` или срок оплаты истёк |
| 409 | `PAYMENT_REQUIRED` | подтверждение заказа | `mock_card` без успешной оплаты |
| 409 | `TELEGRAM_DISABLED` | `POST /telegram/link-token`, `/auth/telegram/webapp`, `…/register`, `…/link` | Telegram не настроен в конфигурации |
| 409 | `PASSWORD_NOT_SET` | `/auth/password/change` | у аккаунта нет пароля (аккаунт только с Telegram, DEC-142) |
| 422 | `CURRENT_PASSWORD_INVALID` | `/auth/password/change`, `DELETE /telegram/link` | текущий пароль указан неверно (DEC-143, DEC-152) |
| 409 | `CREDENTIALS_ALREADY_SET` | `/auth/credentials` | email и пароль уже установлены (DEC-142) |
| 409 | `TELEGRAM_NOT_LINKED` | `/auth/telegram/webapp` | проверенный Telegram-аккаунт не связан ни с одним пользователем; аккаунт не создаётся (DEC-152) |
| 409 | `TELEGRAM_ALREADY_LINKED` | `/auth/telegram/webapp/link`, `/start` бота (этап 10) | этот Telegram-аккаунт уже связан с другим пользователем; связь не переносится (DEC-152) |
| 409 | `ACCOUNT_ALREADY_LINKED` | `/auth/telegram/webapp/link`, `/start` бота (этап 10) | у аккаунта уже есть связь с другим Telegram-аккаунтом; связь не переносится (DEC-152) |
| 409 | `TELEGRAM_UNLINK_NOT_ALLOWED` | `DELETE /telegram/link` | у аккаунта нет email и пароля: отвязка оставила бы его без способа входа (DEC-142, DEC-152) |
| 409 | `TELEGRAM_BUSY` | `/auth/telegram/webapp/register`, `…/link` | блокировка не получена за `lock_timeout` 5 секунд; транзакция откатана, ничего не изменено; запрос можно повторить (DEC-155) |
| 422 | `CART_EMPTY` | quote, `POST /orders` | корзина пуста |
| 422 | `ITEM_UNAVAILABLE` | корзина, quote, заказ | товар/вариант/модификатор недоступен; `details` --- позиции |
| 422 | `MODIFIER_CONSTRAINT_VIOLATION` | корзина, quote, заказ | нарушены min/max/required/`max_quantity` |
| 422 | `OUT_OF_DELIVERY_ZONE` | quote, заказ | точка вне активных зон |
| 422 | `MIN_ORDER_NOT_REACHED` | quote, заказ | `details`: минимум и subtotal |
| 422 | `RESTAURANT_CLOSED` | quote, заказ | вне рабочих часов; `details`: `next_opening_at` |
| 422 | `DELIVERY_DISABLED` / `PICKUP_DISABLED` | quote, заказ | способ отключён |
| 422 | `ZONE_OVERLAP` | зоны | пересечение активных зон по площади |
| 422 | `INVALID_GEOMETRY` | зоны | невалидная геометрия или SRID ≠ 4326 |
| 422 | `INVALID_FILE` | изображения | тип/размер/содержимое |
| 422 | `INVALID_WORKING_HOURS` | `PUT /admin/working-hours` | нарушены правила рабочих часов (DEC-107) |
| 429 | `RATE_LIMITED` | любой | превышен лимит; заголовок `Retry-After` (исключение --- `/auth/password/forgot`, см. §2) |
| 405 | `METHOD_NOT_ALLOWED` | любой | HTTP-метод не поддерживается endpoint'ом; заголовок `Allow` (DEC-115) |
| 503 | `SERVICE_UNAVAILABLE` | `GET /health` | база данных недоступна (DEC-115) |
| 4xx | `HTTP_ERROR` | любой | резервный код для HTTP-ошибки, у которой нет отдельного кода в каталоге; не заменяет коды выше (DEC-115) |
| 500 | `INTERNAL_ERROR` | любой | непредвиденная ошибка; для всех необработанных исключений и HTTP 5xx без отдельного кода в каталоге (DEC-115) |

### 1.2 Rate limits

Значения хранятся в конфигурации приложения (DEC-80). Счётчики `slowapi`
хранятся в памяти; в v1 API работает одним процессом и одним Uvicorn
worker; при переходе к нескольким процессам/экземплярам --- Redis-backed
limiter (DEC-95).

| Область | Лимит | Ключ |
|---|---|---|
| `POST /auth/login`, `POST /auth/telegram/webapp/link` | 5 в минуту | IP; **общий** счётчик обоих endpoint'ов (DEC-152) |
| `POST /auth/telegram/webapp`, `POST /auth/telegram/webapp/register` | 5 в минуту (`RATE_LIMIT_TELEGRAM_WEBAPP`) | IP; общий счётчик этих двух endpoint'ов, отдельный от login (DEC-152, DEC-154) |
| `POST /auth/password/forgot` | 3 в час | аккаунт (email) и IP |
| Аутентифицированные запросы | 120 в минуту | пользователь |
| Публичные запросы без авторизации | 60 в минуту | IP |

### 1.3 Язык

Параметр `language` (`ru`, `ky`, `uz`) для локализуемых ответов.
Fallback: `language` → `users.preferred_language` (если авторизован) →
`ru` → первый доступный перевод.

### 1.4 Обновление данных

Push-механизмов (WebSocket/SSE) нет; используется RTK Query polling
(DEC-93):

-   клиентские экраны заказов --- каждые 20 секунд (DEC-74);
-   административная панель, кухня и курьерский интерфейс --- каждые 10
    секунд (DEC-85, DEC-93).

### 1.5 Телефон

Все поля телефона (`users.phone`, `customer_phone`, телефоны
сотрудников) принимают `+996 700 12 34 56`, `996700123456`,
`0700123456`, `700123456` и нормализуются backend-ом в `+996700123456`
(`+996` и 9 цифр); иные значения --- `422 VALIDATION_ERROR` (DEC-89).

### 1.6 Служебные endpoints

| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| GET | `/health` | Public | Состояние API и БД: `{"status": "ok" \| "degraded", "database": "ok", "postgis": "<версия>" \| null}`; `degraded` --- PostGIS ещё не установлен миграцией; недоступность БД --- `503 SERVICE_UNAVAILABLE` |
| GET | `/docs`, `/openapi.json` | Public, **только dev** | OpenAPI-документация и контракт для `openapi-typescript`; в `demo` отключены (`404`) |

Каждый ответ содержит заголовок `X-Request-ID`: присланное клиентом
значение (`[A-Za-z0-9._-]{1,128}`) или сгенерированное сервером.

### 1.7 Пароли

Единая политика для регистрации, смены, сброса пароля и CLI-команды:
8–128 символов, минимум одна буква и одна цифра; хранение --- Argon2id
(DEC-96).

## 2. Auth

| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| POST | `/auth/register` | Public | Регистрация по email и паролю; поля --- §2.2 (DEC-141); роль `customer` (DEC-24); `201` с `access_token`, `token_type`, `expires_in` и refresh-cookie новой семьи; занятый email --- `409 EMAIL_ALREADY_EXISTS` (DEC-140) |
| POST | `/auth/login` | Public | Login |
| POST | `/auth/telegram/webapp` | Public | Вход из Telegram Mini App по `init_data` для уже связанного Telegram; без связи --- `409 TELEGRAM_NOT_LINKED`; только access JWT, без refresh-cookie; §2.3 (DEC-142, DEC-152) |
| POST | `/auth/telegram/webapp/register` | Public | Явная регистрация нового клиента из Mini App по `init_data`; §2.3 (DEC-152) |
| POST | `/auth/telegram/webapp/link` | Public | Привязка существующего аккаунта сайта по `init_data`, email и паролю; §2.3 (DEC-152) |
| POST | `/auth/credentials` | Auth | Добавить email и пароль аккаунту только с Telegram; §2.3 (DEC-142) |
| POST | `/auth/refresh` | Refresh cookie | Refresh rotation |
| POST | `/auth/logout` | Refresh cookie + CSRF | access JWT не требуется; отзыв семьи refresh-токена, если запись токена существует; после подтверждённого COMMIT --- `204` во всех штатных случаях, включая отсутствие cookie и неизвестный токен, cookie очищается; без подтверждения успешного COMMIT --- `500 INTERNAL_ERROR`, cookie не очищается, результат отзыва неизвестен (DEC-140) |
| GET | `/auth/me` | Auth | Current user, roles, `must_change_password`, `has_password`; `email` --- `null` у аккаунта только с Telegram (DEC-142) |
| POST | `/auth/password/change` | Auth | Смена пароля (`current_password`, `new_password`); требует текущий пароль, неверный --- `422 CURRENT_PASSWORD_INVALID` (DEC-143); если пароль не установлен --- `409 PASSWORD_NOT_SET` (DEC-142); новый пароль --- по политике DEC-96; сбрасывает `must_change_password` (DEC-28); отзывает все семьи refresh-токенов пользователя, включая текущую; после подтверждённого COMMIT --- `204`, cookie очищается, требуется повторный вход; без подтверждения успешного COMMIT --- `500 INTERNAL_ERROR`, cookie не очищается, результат отзыва неизвестен; выданный access JWT действует до истечения срока, не более 15 минут (DEC-140) |
| POST | `/auth/password/forgot` | Public | Request reset |
| POST | `/auth/password/reset` | Reset token | Set new password |

Refresh token только в HttpOnly cookie; access JWT в ответе (frontend
хранит его только в памяти, DEC-110). Argon2id. Сроки (DEC-80): access
15 минут, refresh 30 дней, reset-токен 30 минут.

Login (DEC-103): неверный пароль, несуществующий email и неактивный
аккаунт дают одинаковый `401 INVALID_CREDENTIALS`. Перед созданием
семьи refresh-токенов login блокирует строку пользователя
(`FOR NO KEY UPDATE`) и повторно проверяет `is_active` по
заблокированной строке; неактивному --- тот же `401` (DEC-143).

Refresh (DEC-65, DEC-110, DEC-140). Запрос требует проверку CSRF (см.
ниже). Успешный refresh выдаёт новый токен той же семьи; старому
выставляются `revoked_at` и `replaced_by_id`. Проверки выполняются
строго в таком порядке, ответ при отказе ---
`401 INVALID_REFRESH_TOKEN`:

1.  нет cookie или токен неизвестен --- ничего не отзывается;
2.  владелец токена неактивен --- отзываются все refresh-сессии
    пользователя независимо от состояния предъявленного токена;
3.  токен уже ротирован или отозван (`revoked_at` задан) ---
    отзывается вся его семья;
4.  срок токена истёк, токен не ротирован и не отозван --- ничего не
    отзывается.

Ротация атомарна: в одной транзакции (уровень изоляции READ COMMITTED
задан явно) сначала блокируется строка пользователя и читается
актуальный `is_active`, затем блокируется и перечитывается строка
токена; состояние проверяется только после получения блокировок. Если
два запроса одновременно предъявляют один токен, второй получает
`401 INVALID_REFRESH_TOKEN`, и вся семья отзывается, включая токен,
выданный первому запросу; независимая вторая ветвь семьи не создаётся.

Отзыв токенов фиксируется (COMMIT) до отправки
`401 INVALID_REFRESH_TOKEN`. Если приложение не получило подтверждение
успешного COMMIT, оно не отправляет ответ, предполагающий успешное
выполнение операции, не отправляет новую refresh-cookie и возвращает
`500 INTERNAL_ERROR`; если ошибка возникла во время COMMIT, результат
фиксации неизвестен: отзыв мог как произойти, так и не произойти. Для
`/auth/logout` и `/auth/password/change` ответ `204` и очистка cookie
отправляются только после подтверждения успешного COMMIT; без
подтверждения --- `500 INTERNAL_ERROR`, cookie не очищается, результат
отзыва считается неизвестным.

Льготного окна для повторного предъявления нет. Конкурентный refresh из
нескольких вкладок предотвращает frontend (`navigator.locks`, см.
`UI_UX_GUIDELINES.md`).

Пока `must_change_password = TRUE`, из endpoints, требующих
авторизации, доступны только:

-   `/auth/me`;
-   `/auth/password/change`;
-   `/auth/logout`;
-   `/auth/refresh`.

Остальные возвращают `403 PASSWORD_CHANGE_REQUIRED`. `/auth/refresh`
выдаёт новую пару токенов, флаг при этом сохраняется; `/auth/me`
возвращает его значение. Публичные endpoints без авторизации этим
правилом не затрагиваются (DEC-28, DEC-140).

Роли и `is_active` проверяются по БД на каждом запросе (DEC-66).

CSRF (DEC-68, DEC-140): frontend и API работают на одном origin (Vite
proxy в dev, nginx в demo). Для cookie-based операций
(`/auth/refresh`, `/auth/logout`) заголовок `Origin` должен точно
совпадать с одним из значений настройки `CSRF_TRUSTED_ORIGINS`, а
заголовок `X-CSRF-Protection` --- равняться `1`; отсутствие или
несовпадение любого из них --- `403 CSRF_FAILED`.
`CSRF_TRUSTED_ORIGINS` --- отдельная настройка только для проверки
CSRF; она не связана с `CORS_ALLOWED_ORIGINS` и не заменяет её.
Cookie `refresh_token`: `HttpOnly`, `SameSite=Strict`,
`Path=/api/v1/auth`, `Max-Age` равен сроку refresh-токена. Флаг
`Secure` устанавливается при `APP_ENV=demo` и не устанавливается при
`APP_ENV=dev` или `APP_ENV=test` (DEC-68, DEC-140). CORS ограничен
отдельным allowlist `CORS_ALLOWED_ORIGINS`.

Ответ login/refresh:

``` json
{"access_token": "...", "token_type": "bearer", "expires_in": 900}
```

### 2.1 Сброс пароля (DEC-108)

`POST /auth/password/forgot` --- `{email}`:

-   всегда `202` с одинаковым телом («Если аккаунт существует, мы
    отправили письмо»); не раскрывает существование email, активность
    аккаунта и срабатывание лимита; искусственная задержка не
    добавляется;
-   для существующего активного пользователя: прежние неиспользованные
    reset-токены помечаются использованными, создаётся новый (32 байта,
    SHA-256 хеш, 30 минут), письмо на языке `preferred_language` со
    ссылкой `<FRONTEND_BASE_URL>/reset-password?token=<token>`
    отправляется после ответа (background task);
-   при превышении лимита 3/час --- тот же `202`, письмо не отправляется.

`POST /auth/password/reset` --- `{token, new_password}`:

-   валидный токен → в одной транзакции новый Argon2id-хеш, `used_at`,
    `must_change_password = false`, отзыв **всех** семей refresh-токенов
    пользователя; ответ `204`;
-   иначе --- `400 INVALID_OR_EXPIRED_TOKEN`.

Токены и ссылки не записываются в логи. SMTP --- из env; в dev/demo
письма перехватывает Mailpit.

Аккаунт без email (только с Telegram, DEC-142) по email не находится:
`forgot` отвечает тем же `202`, письмо не отправляется.

### 2.2 Регистрация (DEC-141)

`POST /auth/register`:

-   `email` --- обязательно; формат проверяет `email-validator` без
    DNS-проверки; пробелы по краям удаляются; для хранения и проверки
    уникальности адрес приводится к нижнему регистру; сравнение всегда
    без учёта регистра; после нормализации не более 255 символов. Так
    же email нормализуется в login, forgot, `/auth/credentials` и при
    создании сотрудника.
-   `password` --- обязательно; DEC-96 (буква --- любая буква Unicode,
    цифра --- десятичная цифра Unicode, длина в символах); пароль не
    изменяется.
-   `full_name` --- обязательно; пробелы по краям удаляются, затем
    1--150 Unicode-символов (code points); управляющие символы
    запрещены.
-   `phone` --- необязательно; §1.5 (DEC-89).
-   `preferred_language` --- необязательно; `ru` / `ky` / `uz`, по
    умолчанию `ru`.
-   Неизвестные поля --- `422 VALIDATION_ERROR`; роль всегда `customer`.

### 2.3 Telegram Mini App (DEC-142, DEC-152)

Три публичные операции. `init_data` --- строка `Telegram.WebApp.initData`
без изменений. Все три выдают только `200 {access_token, token_type,
expires_in}`: refresh-cookie не выдаётся, CSRF не требуется (cookie не
используется). После истечения access-токена Mini App повторяет
`POST /auth/telegram/webapp`. Бот не настроен --- `409
TELEGRAM_DISABLED`.

Проверка `init_data` выполняется первой во всех трёх операциях:

-   подпись (`HMAC-SHA256`, ключ --- `HMAC-SHA256("WebAppData", <токен
    бота>)`), обязательные поля `hash`, `auth_date`, `user`, отсутствие
    повторяющихся ключей, допустимая длина, возраст `auth_date` (не
    старше `TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS`, не в будущем сверх
    допустимого расхождения часов) и `user.is_bot = false`; только после
    этого данные используются;
-   `initDataUnsafe` для аутентификации не используется;
-   ошибка проверки --- `401 INVALID_TELEGRAM_AUTH` без указания причины.

Параметры и алгоритм проверки (DEC-154 пп. 1, 2): длина `init_data` не
более `TELEGRAM_WEBAPP_INIT_DATA_MAX_LENGTH` (4096); `auth_date` не
старше `TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS` (3600) и не позже времени
сервера более чем на `TELEGRAM_WEBAPP_CLOCK_SKEW_SECONDS` (60). Строка
проверки --- все полученные поля, кроме `hash` (поле `signature`, если
есть, входит в неё), в виде `key=value` после URL-декодирования,
отсортированные по ключу и соединённые `\n`; секретный ключ ---
`HMAC-SHA256(key="WebAppData", msg=<токен бота>)`; ожидаемый `hash` ---
hex от `HMAC-SHA256(<секретный ключ>, <строка проверки>)`; сравнение за
постоянное время. Проверка Ed25519 для сторонних сервисов не
используется. `language_code` сравнивается строго с `ru` / `ky` / `uz`,
иначе `ru`.

`telegram_links.is_active` (DEC-154 п. 3): отсутствие поля
`allows_write_to_pm` равносильно `false`; новая связь ---
`allows_write_to_pm = true` → `TRUE`, иначе `FALSE`; вход и повторная
привязка той же пары --- при `allows_write_to_pm = true` → `TRUE`, иначе
значение не меняется. `telegram_username` записывается только при
создании связи (DEC-154 п. 4): поля нет, строка пустая или длиннее 100
символов --- NULL; не строка --- `init_data` отклоняется (DEC-155 п. 2).
Длина `init_data` больше 4096 --- `401 INVALID_TELEGRAM_AUTH`, не `422`
(DEC-155 п. 3).

`POST /auth/telegram/webapp` --- `{init_data}`, только вход:

-   пользователь ищется по `telegram_links.telegram_chat_id = user.id`;
-   связь найдена: неактивный пользователь --- `401
    INVALID_TELEGRAM_AUTH`, нет роли `customer` --- `403 FORBIDDEN`,
    иначе токен (`is_active` связи --- по DEC-154 п. 3; другие поля связи
    и пользователя не меняются);
-   связи нет --- `409 TELEGRAM_NOT_LINKED`; в БД ничего не меняется,
    аккаунт автоматически не создаётся.

`POST /auth/telegram/webapp/register` --- `{init_data}`, новый клиент:

-   одна транзакция: advisory-блокировка по Telegram `user.id`, затем
    повторный поиск связи;
-   связи нет --- создаются пользователь с ролью `customer` без email и
    пароля (имя и `preferred_language` --- по DEC-142 и DEC-152 п. 10;
    `phone` --- NULL), его роль и `telegram_links`;
-   связь уже есть (повтор, параллельный запрос или привязанный аккаунт
    сайта) --- новый аккаунт не создаётся, ответ как у
    `/auth/telegram/webapp`.

`POST /auth/telegram/webapp/link` --- `{init_data, email, password}`,
привязка существующего аккаунта сайта:

-   email и пароль проверяются как в `/auth/login`: аккаунт без email не
    находится, для неизвестного email выполняется фиктивная проверка
    пароля; неверный пароль, неизвестный email и неактивный аккаунт ---
    одинаковый `401 INVALID_CREDENTIALS`;
-   пароль верный, но нет роли `customer` --- `403 FORBIDDEN` (первая
    проверка, до транзакции);
-   одна транзакция: advisory-блокировка по Telegram `user.id` →
    строка `users` (`FOR NO KEY UPDATE`) с повторным чтением
    `is_active` и `password_hash` (изменились --- `401
    INVALID_CREDENTIALS`) и повторной проверкой роли `customer` (её нет
    --- `403 FORBIDDEN` и полный откат, DEC-154 п. 5) → проверка связей
    после блокировки:
    -   этот Telegram связан с другим пользователем --- `409
        TELEGRAM_ALREADY_LINKED`;
    -   у пользователя есть связь с другим Telegram --- `409
        ACCOUNT_ALREADY_LINKED`;
    -   та же пара уже связана --- `200` без изменений связи,
        `telegram_username`, `linked_at` и данных пользователя;
        `is_active` --- по DEC-154 п. 3;
    -   иначе вставляется `telegram_links` (`telegram_username`,
        `is_active` по DATABASE_SCHEMA.md §11.2, `linked_at`);
-   ответ --- токен этого аккаунта; `full_name`, `phone`,
    `preferred_language`, email, пароль и заказы пользователя не
    изменяются; при любой ошибке транзакция откатывается целиком;
-   перенос связи и слияние аккаунтов не выполняются; нарушение
    уникальности `telegram_links` даёт тот же `409` с полным откатом.

Порядок блокировок любой операции создания или удаления связи:
advisory-блокировка (двухключевая форма: константа пространства имён и
32-битная свёртка Telegram `user.id`) → `users` → `telegram_links`;
удерживая `users`, брать эту advisory-блокировку нельзя (DEC-152 п. 3).
`register` и `link` выполняют `SET LOCAL lock_timeout = '5s'`; блокировка,
не полученная за это время (только SQLSTATE `55P03`), --- полный откат и
`409 TELEGRAM_BUSY` (DEC-155 п. 1). Вход (`/auth/telegram/webapp`) связь
не создаёт: он лишь повышает `is_active` одной строки `telegram_links`
без advisory-блокировки и без блокировки `users` (DEC-155 п. 4).
Проверка пароля (Argon2) в `link` выполняется до блокировок; повторный
хеш пароля (rehash) в `link` не выполняется. Если верны оба конфликта,
возвращается `TELEGRAM_ALREADY_LINKED`. Лимиты --- §1.2.

`POST /auth/credentials` --- `{email, password}` (Auth):

-   только если у пользователя `email IS NULL`, иначе
    `409 CREDENTIALS_ALREADY_SET`;
-   правила полей --- §2.2; занятый email --- `409 EMAIL_ALREADY_EXISTS`;
-   email и хеш записываются одним атомарным `UPDATE`; ответ `204`.

Для аккаунта без email и пароля: login --- `401 INVALID_CREDENTIALS`
(как для неизвестного email), forgot --- `202` без письма,
`/auth/password/change` --- `409 PASSWORD_NOT_SET`.

`init_data`, токены и пароли не записываются в логи и не возвращаются
в ответах `422` (DEC-152 п. 4).

## 3. Public catalog and restaurant

| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| GET | `/catalog/categories` | Public | Active categories |
| GET | `/catalog/products` | Public | Products; filters and pagination |
| GET | `/catalog/products/{id}` | Public | Product, variants, modifier groups |
| GET | `/restaurant` | Public | Название, телефон, адрес, координаты, рабочие часы, `delivery_enabled`, `pickup_enabled`, `is_open_now`, `next_opening_at` |

Query params: `category_id`, `search`, `featured`, `page`, `page_size`,
`language`.

Product response contains localized `name`, `description`, image URLs,
availability, `price_from` (минимальная цена доступного варианта),
variants with prices (у товара всегда минимум один вариант, DEC-06),
modifier groups and selection constraints (`selection_type`,
`is_required`, `min_selections`, `max_selections`) и для каждого
модификатора `price_delta`, `max_quantity`, `is_available`, а также
переопределённые цены по вариантам. Do not expose inactive or deleted
items as orderable; unavailable items may be shown with
`is_available = false`.

## 4. Profile and addresses

Требуется роль `customer` для адресов (DEC-23).

| Method | Endpoint | Access |
|---|---|---|
| GET/PATCH | `/users/me` | Auth |
| GET/POST | `/users/me/addresses` | Customer |
| PATCH/DELETE | `/users/me/addresses/{id}` | Owner |
| POST | `/users/me/addresses/{id}/default` | Owner |

Always check resource ownership. Address fields: label, address_text,
latitude, longitude, entrance, floor, apartment, comment, is_default.
Validate coordinate ranges. Для использования в доставке координаты
обязательны (DEC-01). `PATCH /users/me` изменяет `full_name`, `phone`
(нормализация §1.5), `preferred_language`; не изменяет email, роли и
флаги.

`GET /users/me` и `PATCH /users/me` (DEC-153) отвечают тем же телом, что
`GET /auth/me` (`id`, `email`, `full_name`, `phone`, `preferred_language`,
`roles`, `must_change_password`, `has_password`); `PATCH` --- `200` с
профилем после изменения. Тело `PATCH` --- частичное: поля `full_name`
(правила §2.2), `phone` (§1.5; явный `null` очищает телефон) и
`preferred_language` (`ru` / `ky` / `uz`); `null` в `full_name` или
`preferred_language` --- `422`. Пустое тело `{}` ничего не изменяет и
возвращает `200`. Любые другие поля (`email`, `password`, роли, флаги,
`id`, `user_id`) --- `422 VALIDATION_ERROR` без изменений. Изменяется
только профиль владельца access-токена; при `must_change_password` ---
`403 PASSWORD_CHANGE_REQUIRED`.

Реализация адресной книги (этап 6, DEC-148): `GET` возвращает `items` и
`pagination` (`page`, `page_size` 20, максимум 100); `POST` → `201`,
`PATCH` — частичное изменение (явный `null` очищает необязательное поле;
`latitude` и `longitude` меняются только вместе), `DELETE` → `204`,
`POST …/{id}/default` → адрес. Лимиты: `address_text` и `comment` до 500,
`label` 80, `entrance` 30, `floor` 20, `apartment` 30; координаты — не
более 7 знаков после запятой. Чужой адрес — `404`. `PATCH /users/me` в
этапе 6 не реализуется; `GET/PATCH /users/me` реализуется на этапе MA
(MA-1) строго в пределах описанного выше (DEC-152 п. 9).

## 5. Cart

Требуется роль `customer`. Гостевой корзины нет (DEC-13).

| Method | Endpoint | Access |
|---|---|---|
| GET | `/cart` | Customer |
| POST | `/cart/items` | Customer |
| PATCH/DELETE | `/cart/items/{id}` | Owner |
| DELETE | `/cart` | Customer |

Add item payload (DEC-07):

``` json
{
  "product_id": "uuid",
  "variant_id": "uuid",
  "quantity": 2,
  "modifiers": [{"id": "uuid", "quantity": 2}],
  "special_instructions": "Без острого соуса"
}
```

`variant_id` обязателен. `modifiers[].quantity` по умолчанию 1.

Update item payload (DEC-12) --- только:

``` json
{"quantity": 3, "special_instructions": "..."}
```

Never accept client-supplied price as authoritative. Backend validates
variant/product relation, modifier availability, group limits
(`min_selections`/`max_selections` по числу разных модификаторов,
`max_quantity` каждого модификатора, required, DEC-81), then calculates
totals. Одинаковые позиции объединяются (DEC-11).

Cart response: позиции с локализованными названиями, выбранными
модификаторами, `unit_price`, `line_total`, флагами `is_available` и
`issues` (например, недоступный модификатор), а также `subtotal` и
`items_count`. Все суммы рассчитаны сервером при каждом запросе.

Реализация этапа 5 (2026-11-12):

-   `GET /cart`, `POST /cart/items`, `PATCH /cart/items/{id}` отвечают
    `200` с полной корзиной; `DELETE /cart/items/{id}` и `DELETE /cart` ---
    `204`. Параметр `language` (ru/ky/uz) выбирает язык названий.
    `GET /cart` без корзины возвращает пустую корзину и ничего не создаёт.
-   Ограничения --- DEC-146 (1–99 на позицию, до 500 символов
    пожеланий, до 50 позиций). Поля цены в запросе запрещены
    (`extra` поля → `422 VALIDATION_ERROR`). Каждая добавка указывается
    в запросе один раз.
-   Недопустимый выбор при добавлении: `422 ITEM_UNAVAILABLE`, если
    недоступны товар, размер или добавка (в том числе добавка группы, не
    подключённой к товару); иначе `422 MODIFIER_CONSTRAINT_VIOLATION`.
    `details` --- список замечаний.
-   Замечания (`issues[].code` в позиции и `details` ошибки):
    `PRODUCT_UNAVAILABLE`, `VARIANT_UNAVAILABLE`, `MODIFIER_UNAVAILABLE`,
    `MODIFIER_QUANTITY_EXCEEDED`, `GROUP_REQUIRED`,
    `GROUP_MIN_SELECTIONS`, `GROUP_MAX_SELECTIONS`; дополнительно
    `group_id`, `modifier_id`, `group_name`, `modifier_name`, `limit`.
-   Ответ корзины: `items[]` (`product_name`, `variant_name`,
    `image_url`, `quantity`, `special_instructions`, `modifiers[]` с
    `group_name`, `name`, `quantity`, `unit_price`; `unit_price`,
    `line_total`, `is_available`, `issues`), `items_count` (DEC-146),
    `subtotal`, `currency` (`KGS`), `has_issues`, `max_line_quantity`,
    `max_lines`.
-   `subtotal` --- сумма только доступных позиций (без замечаний,
    DEC-147). Недоступные позиции остаются в корзине, показываются со
    своей ценой и предупреждением, но в `subtotal` не входят;
    `has_issues = true`, пока они есть.
-   Чужая позиция неотличима от несуществующей (`404 NOT_FOUND`).
-   Расчёт цены и проверка выбора --- единый модуль
    `app/modules/pricing` (DEC-08); quote и создание заказа (этап 6)
    используют его же.

## 6. Checkout and orders

| Method | Endpoint | Access |
|---|---|---|
| POST | `/checkout/quote` | Customer |
| POST | `/orders` | Customer |
| GET | `/orders` | Customer; own orders |
| GET | `/orders/{id}` | Owner only (DEC-25) |
| POST | `/orders/{id}/cancellation-requests` | Owner |

### 6.1 Quote

Payload: `delivery_type` и для доставки ровно одно из `address_id` или
`address` (как в создании заказа).

Checkout quote returns subtotal, delivery availability, zone, fee,
applicable minimum, `min_order_reached`, estimated total,
`is_open_now`, флаги `delivery_enabled`/`pickup_enabled`, и список
проблем позиций корзины. It is informational; order creation
recalculates everything.

Реализация (этап 6, DEC-148): ответ всегда `200` (кроме ошибок самого
запроса). Поля: `delivery_type`, `items_count`, `subtotal` (только
доступные позиции, DEC-147), `zone` (`id`, `name`) или `null`,
`delivery_fee`, `min_order_amount`, `min_order_reached`, `total`,
`currency`, `is_open_now`, `next_opening_at`, `delivery_enabled`,
`pickup_enabled`, `problems[]` (`code` из §1.1 и `details`: для
`MIN_ORDER_NOT_REACHED` — `min_order_amount` и `subtotal`, для
`RESTAURANT_CLOSED` — `next_opening_at`, для позиций — список
`item_id` + `issues`), `can_place_order`. Для `address` в quote нужны
только координаты. Параметр `language` выбирает язык названий.

### 6.2 Create order

Требуется заголовок `Idempotency-Key`: 1–128 символов `[A-Za-z0-9_-]`;
отсутствие или неверный формат --- `422 VALIDATION_ERROR` (DEC-109).

``` json
{
  "delivery_type": "delivery",
  "address_id": "uuid",
  "address": {
    "address_text": "ул. Ленина, 1",
    "latitude": "40.5283000",
    "longitude": "72.7985000",
    "entrance": "2", "floor": "3", "apartment": "12",
    "comment": "Домофон не работает",
    "label": "Дом"
  },
  "save_address": false,
  "customer_name": "Айбек",
  "customer_phone": "+996700123456",
  "comment": "Позвонить заранее",
  "payment_method_code": "cash",
  "expected_total": "1250.00",
  "language": "ru"
}
```

Правила (DEC-86, DEC-09, DEC-10, DEC-16):

-   `delivery`: ровно одно из `address_id` (адрес владельца с
    координатами) или `address` (координаты обязательны);
    `save_address` применим только к `address`;
-   `pickup`: `address_id`, `address`, `save_address` не передаются;
-   `customer_phone` нормализуется (§1.5);
-   `expected_total` обязателен и используется только для сравнения
    (DEC-09); при расхождении --- `409 PRICE_CHANGED` с актуальным quote,
    заказ не создаётся;
-   `language` необязателен; по умолчанию `preferred_language`; задаёт
    `orders.language_code` и язык snapshot'ов (DEC-15).

Create order in one DB transaction: register idempotency key, validate
cart, check working hours and delivery/pickup flags, reload prices,
validate modifiers, check zone/minimum, compare `expected_total`,
create order and snapshots, payment (`pending`), delivery if needed,
status history, clear cart, store idempotent response.

Idempotency (DEC-59, DEC-109): `request_hash` --- SHA-256 канонического
тела. Тот же ключ и то же тело → сохранённый ответ `201` с заголовком
`Idempotent-Replayed: true`; другое тело → `409
IDEMPOTENCY_KEY_CONFLICT`; параллельный запрос с тем же ключом ждёт
завершения первого (защита уникальным индексом PostgreSQL,
`lock_timeout` 5 с), по таймауту --- `409 IDEMPOTENCY_IN_PROGRESS`.
Ошибки не сохраняются как результат. Ключи хранятся 24 часа. Алгоритм
--- `DATABASE_SCHEMA.md` §14.2.

Реализация (этап 6, DEC-148; этап 7, DEC-149): принимается активный
способ оплаты `cash` или `mock_card` (иначе `422 VALIDATION_ERROR`); для
`mock_card` в ответе `payment_due_at` = `created_at` + 30 минут;
лимиты `customer_name` 150, `comment` 500, поля адреса — как в §4;
блокирующие условия quote — ошибки `422` с теми же кодами и `details`;
просроченный ключ этого же пользователя заменяется при записи нового
(фоновая очистка — этап 10).

Order response includes id, order_number, status, delivery_type,
payment_method_code, payment_status, `payment_due_at` (для `mock_card`),
subtotal, delivery_fee, total_amount, currency and created_at. Ответ
`201` означает, что заказ создан; для `mock_card` клиент затем проходит
имитацию оплаты.

### 6.3 Orders and cancellation

`GET /orders/{id}` возвращает snapshot позиций (с `group_name` и
модификаторами), адрес, суммы, платежи, историю статусов, запросы
отмены и флаг `can_request_cancellation`. Данных курьера (имя, контакты)
клиентские ответы в v1 не содержат (DEC-151 п. 7).

Реализация (этап 6): `GET /orders` — `items` (номер, статус, тип,
способ оплаты, сумма, `items_count`, дата) и `pagination` (20, максимум
100). В истории статусов `comment` показывается только для
`rejected`/`cancelled`. `reason` запроса отмены — 1–500 символов;
статус вне `pending`/`confirmed`/`preparing` → `409
CANCELLATION_NOT_ALLOWED`; ожидающий запрос уже есть → `409
CANCELLATION_REQUEST_PENDING`; ответ — `201` с запросом.

Customer cannot directly change order status or cancel order.
Запрос отмены (`{"reason": "..."}`) разрешён в статусах `pending`,
`confirmed`, `preparing` (DEC-38); одновременно не более одного
ожидающего запроса; после отклонения можно отправить новый (DEC-42).

## 7. Payments

| Method | Endpoint | Access |
|---|---|---|
| GET | `/payment-methods` | Public |
| POST | `/payments/mock/confirm` | Order owner |

`POST /payments/mock/confirm` payload (DEC-47, DEC-149):

``` json
{"order_id": "uuid", "attempt_id": "uuid", "outcome": "success"}
```

`attempt_id` --- `id` попытки из `payments[]` ответа `GET /orders/{id}`
(DEC-149).

`outcome`: `success` | `failure`. Разрешено только для заказа
`mock_card` в статусе `pending` с непросроченным `payment_due_at`, иначе
`409 PAYMENT_NOT_ALLOWED`. Успех: платёж `succeeded`, `payment_due_at =
NULL`, заказ попадает в очередь администратора. Неудача: платёж
`failed`, создаётся новая попытка `pending`, клиент может повторить
(DEC-46, DEC-99). Повторный `success` для уже оплаченного заказа
возвращает текущее состояние без изменений. Always `is_simulated=true`.
Never accept or store card number, CVV or expiry.

Если mock-оплата не завершена за 30 минут (конфигурация), worker
автоматически отменяет заказ с причиной `payment_timeout` (DEC-84,
DEC-97).

Реализация этапа 7 (DEC-149):

-   `GET /payment-methods` --- `{"items": [{"code", "sort_order"}]}`,
    только активные способы.
-   Отдельный `GET /orders/{id}/payments` не создаётся: попытки --- в
    `payments[]` ответа `GET /orders/{id}` (владелец): `id` (=
    `attempt_id`), `method_code`, `amount`, `currency`, `status`,
    `is_simulated`, `transaction_reference` (`MOCK-…` для `mock_card`,
    создаётся вместе с попыткой), `created_at`, `paid_at`, `refunded_at`.
    `payment_status` заказа: `succeeded`, если есть успешная попытка;
    иначе `pending`, если есть незавершённая; иначе статус последней.
-   Confirm: только владелец (чужой заказ или попытка --- `404`); заказ
    блокируется, параллельные запросы выполняются по очереди. Попытка
    `pending` при заказе `pending` и непросроченном `payment_due_at`:
    `success` → `succeeded`, `paid_at`, `payment_due_at = NULL` (заказ
    остаётся `pending`); `failure` → `failed` и новая `pending`-попытка
    с новым `transaction_reference`. Повтор с тем же `attempt_id` и тем же
    `outcome` → сохранённый результат, без новых записей; повторный
    `success` для оплаченного заказа → `200` с текущим состоянием;
    остальное (не `mock_card`, заказ не `pending`, срок истёк, попытка
    завершена с другим результатом, `failure` после оплаты) → `409
    PAYMENT_NOT_ALLOWED`. Лишние поля (в том числе данные карты) → `422`.
-   Ответ confirm `200`: `order_id`, `order_status`, `payment_status`,
    `payment_due_at`, `attempt` (`id`, `status`, `transaction_reference`,
    `amount`, `currency`, `created_at`, `paid_at`).
-   Отмена по таймауту выполняется ядром единой операции отмены (§14.3
    DATABASE_SCHEMA.md): `cancelled`, `payment_timeout`, история с
    комментарием `payment_timeout`, `pending`-попытка → `cancelled`,
    ожидающий запрос отмены → `approved`, доменное событие.
-   Наличные остаются `pending` до завершения заказа (этапы 8–9).

Cash: платёж `pending` до завершения заказа; становится `succeeded`
автоматически при завершении доставки (курьером или административным
вмешательством) или самовывоза администратором (DEC-43). Отдельного
endpoint'а нет.

## 8. Notifications and Telegram

Только для пользователей с ролью `customer` (DEC-57, DEC-85).

| Method | Endpoint | Access |
|---|---|---|
| GET | `/notifications` | Customer |
| POST | `/notifications/{id}/read` | Owner |
| POST | `/notifications/read-all` | Customer |
| GET | `/telegram/link` | Customer |
| POST | `/telegram/link-token` | Customer |
| DELETE | `/telegram/link` | Customer |

Notification item: `id`, `type`, `payload`, `order_id`, `is_read`,
`created_at`, `read_at`. Текст формирует frontend через i18next по
`type` (DEC-55). Список поддерживает фильтр `unread_only` и возвращает
`unread_count`. Значения `type` в v1 (DEC-126): `order_status_changed`,
`cancellation_request_approved`, `cancellation_request_rejected`; другие
значения API не возвращает (их запрещает CHECK в БД).

Telegram (DEC-87, DEC-105, DEC-152; endpoints `/telegram/*`, бот и outbox
--- этап 10):

-   `GET /telegram/link` → `{enabled, linked, telegram_username,
    linked_at}`; `enabled = false`, если Telegram не настроен.
-   `POST /telegram/link-token` → `{deep_link:
    "https://t.me/<BOT_USERNAME>?start=<token>", expires_at}`; токен 32
    байта, хранится SHA-256 хеш, живёт 10 минут, одноразовый; прежние
    неиспользованные токены пользователя аннулируются. Если Telegram не
    настроен --- `409 TELEGRAM_DISABLED`.
-   Привязка существующего аккаунта из Mini App --- `POST
    /auth/telegram/webapp/link` (§2.3); `POST /telegram/link/webapp` не
    реализуется (DEC-152).
-   `DELETE /telegram/link` --- JSON-тело `{current_password}`:
    аккаунт без email и пароля --- `409 TELEGRAM_UNLINK_NOT_ALLOWED`;
    неверный пароль --- `422 CURRENT_PASSWORD_INVALID`; иначе связь
    удаляется, `204`; без связи после проверки пароля --- `204`
    (идемпотентно). Порядок блокировок --- §2.3. Ранее выданный access
    JWT действует до истечения; следующий вход в Mini App ---
    `409 TELEGRAM_NOT_LINKED` (DEC-142, DEC-152 п. 5).
-   `telegram_chat_id` хранит Telegram `user.id`; для личного чата с
    ботом он совпадает с `chat_id` (DEC-142).
-   Бот работает через long polling (DEC-03); webhook в v1 не
    используется. `/start <token>` проверяет хеш, срок и
    неиспользованность; повторное использование токена отклоняется; чат,
    привязанный к другому аккаунту, и аккаунт, уже связанный с другим
    чатом, не привязываются; порядок блокировок --- §2.3 (DEC-152).
-   `telegram_links.is_active` --- разрешение боту писать пользователю
    (DATABASE_SCHEMA.md §11.2); outbox проверяет наличие связи и флаг в
    момент отправки; `requestWriteAccess` в Mini App --- этап 10
    (DEC-152).
-   Сообщения отправляются через outbox (DEC-75) на языке, сохранённом в
    событии при его создании; содержат номер заказа и статус/решение,
    без адреса, телефона, сумм и токенов. Telegram failure must not roll
    back an already committed order.

## 9. Admin API

Require `admin` unless noted. Административные экраны обновляются
polling каждые 10 секунд (DEC-93).

Dashboard (DEC-90):

-   `GET /admin/dashboard/summary`
-   `GET /admin/dashboard/orders-chart`
-   `GET /admin/dashboard/top-products`

Параметры периода: `date_from`, `date_to` --- календарные даты
(`YYYY-MM-DD`) в `Asia/Bishkek`, обе границы включительно. `date_to`
включает весь указанный календарный день в `Asia/Bishkek`. При
обработке период переводится в полуоткрытый интервал `[00:00 date_from,
00:00 дня после date_to)` в `Asia/Bishkek`, затем в UTC, чтобы не
терять записи последнего дня. `date_from > date_to` → `422
VALIDATION_ERROR`. Если параметры не переданы --- последние 7 дней
(текущий день и 6 предыдущих) для `summary`, `orders-chart` и
`top-products` (DEC-114).
Определения метрик:

-   количество заказов --- заказы с `created_at` в периоде; исключаются
    только mock-заказы, отменённые по `payment_timeout`; остальные
    отменённые и отклонённые учитываются;
-   выручка --- сумма `total_amount` заказов `completed` с `completed_at`
    в периоде;
-   средний чек --- выручка / количество заказов `completed` с
    `completed_at` в периоде, округление до 2 знаков; при отсутствии
    завершённых --- `"0.00"`;
-   группировка по дням --- часовой пояс `Asia/Bishkek`.

Остальные метрики (DEC-111):

-   `summary.active_orders` --- текущее количество заказов в статусах
    `confirmed`, `preparing`, `ready_for_pickup`, `out_for_delivery`; не
    зависит от `date_from`/`date_to`;
-   `orders-chart` --- массив по дням периода `{date, orders_created,
    revenue}`: `orders_created` по `created_at` (правило DEC-90),
    `revenue` по `completed_at`; дни без данных --- 0; период по
    умолчанию --- последние 7 дней (DEC-114);
-   `top-products` --- топ-10 товаров по суммарному `quantity` в
    заказах `completed` с `completed_at` в периоде; группировка по
    `product_id`, название --- из snapshot последнего такого заказа.

Все границы дней и периодов рассчитываются в `Asia/Bishkek`.

Catalog:

-   `GET /admin/categories` (включая неактивные, все переводы)
-   `POST/PATCH/DELETE /admin/categories[/{id}]` --- `DELETE` =
    деактивация (DEC-26)
-   `POST /admin/categories/{id}/image`
-   `GET /admin/products`, `GET /admin/products/{id}` (включая
    неактивные/удалённые по фильтру, все переводы, варианты, группы)
-   `POST/PATCH/DELETE /admin/products[/{id}]` --- создание требует
    минимум один вариант (DEC-06); `DELETE` = `deleted_at`
-   `POST /admin/products/{id}/images`
-   `DELETE /admin/products/{id}/images/{image_id}`
-   `POST /admin/products/{id}/variants`
-   `PATCH /admin/variants/{id}`
-   `PUT /admin/variants/{id}/modifier-prices` --- полный набор
    переопределений `[{modifier_id, price_delta}]`
-   `GET /admin/modifier-groups`, `POST/PATCH /admin/modifier-groups[/{id}]`
-   `GET /admin/modifiers`, `POST/PATCH /admin/modifiers[/{id}]`
    (включая `max_quantity`)
-   `PUT /admin/products/{id}/modifier-groups`

Переводы передаются массивом `translations: [{language_code, name,
description}]`. Prefer deactivate/soft delete instead of physically
deleting catalog records referenced by history.

Orders:

-   `GET /admin/orders` --- фильтры: статус, тип, период, номер.
    Заказы, ожидающие mock-оплаты, в рабочую очередь не попадают и
    показываются только с явным фильтром `awaiting_payment=true` (без
    действий) (DEC-84, DEC-97).
-   `GET /admin/orders/{id}`
-   `PATCH /admin/orders/{id}/status` --- `{"status": "...", "comment":
    "..."}`. Разрешены переходы администратора из таблицы
    `DATABASE_SCHEMA.md` §7.1. `comment` обязателен для `rejected`,
    `cancelled` и административного вмешательства в курьерские
    переходы.
    -   Отмена --- единая идемпотентная операция (DEC-82, DEC-101):
        повторная отмена возвращает текущее состояние без повторных
        побочных эффектов; `pending`-запрос клиента помечается
        `approved`.
    -   Административное вмешательство (DEC-91): `ready_for_pickup →
        out_for_delivery` (требуется активное назначение курьера,
        `accepted_at` не требуется и не записывается) и
        `out_for_delivery → completed` для доставки. В истории ---
        `is_admin_override = true`, администратор, время, комментарий.
-   `GET /admin/cancellation-requests`
-   `POST /admin/cancellation-requests/{id}/approve`
-   `POST /admin/cancellation-requests/{id}/reject` (`admin_comment`)

Этап 8 (DEC-150): `PATCH /admin/orders/{id}/status` применяет переходы
администратора, отклонение (платежи DEC-100, ожидающий запрос отмены
закрывается автоматически с комментарием «Заказ отклонён рестораном.
Запрос отмены закрыт автоматически»), завершение самовывоза (наличный
платёж → `succeeded`) и отмену единой операцией. Курьерские переходы,
вмешательство администратора (DEC-91) и endpoints назначения курьеров
ниже --- этап 9.

-   `POST /admin/orders/{id}/assign-courier` --- `{"courier_id": "uuid"}`;
    только заказ `delivery` в `confirmed`…`ready_for_pickup` (DEC-48),
    иначе `409 INVALID_STATUS_TRANSITION`; при наличии активного
    назначения другого курьера выполняется переназначение (DEC-51);
    повтор с тем же курьером, у которого уже есть активное назначение,
    --- `200` без изменений (DEC-151 п. 4); ручное назначение
    отказавшегося курьера допускается; курьер без роли, профиля,
    неактивный, недоступный или на лимите --- `409
    COURIER_NOT_AVAILABLE`
-   `POST /admin/orders/{id}/auto-assign-courier` (DEC-49, DEC-50);
    курьеры, отказавшиеся от этого заказа, исключаются (DEC-92);
    детерминированный порядок выбора --- DEC-151 п. 3 (число активных
    назначений, затем время последнего назначения `NULLS FIRST`, затем
    `user_id`). Заказ с уже существующим активным назначением (любого
    курьера) --- `200` с текущим назначением, без изменений в БД;
    проверка типа и статуса заказа (DEC-48) выполняется раньше.
    Заменить текущего курьера можно только через `assign-courier`
    (DEC-151 п. 4).
-   Порядок блокировок назначений, переназначений и курьерских действий
    --- DEC-151 п. 6.

Approve/reject идемпотентны: повторный вызов для уже рассмотренного
запроса с тем же решением возвращает текущее состояние.

Staff/settings:

-   `GET/POST /admin/staff` --- создание: `email`, `full_name`, `phone`,
    `roles`, `temporary_password` (политика DEC-96); выставляет
    `must_change_password` (DEC-28). Первый администратор создаётся
    только CLI-командой (DEC-88), не через API. По DEC-150: список ---
    пользователи с ролями `cook`/`courier`; API управляет только ролями
    `cook` и `courier` (`admin` не выдаёт и не снимает, `customer` не
    выдаёт); нельзя оставить систему без активного администратора.
-   `POST /admin/staff/{user_id}/deactivate` (DEC-150) --- `is_active =
    false` и отзыв всех refresh-сессий сотрудника; повтор идемпотентен.
    Пользователь с ролью `admin` --- `409 ADMIN_ACCOUNT_PROTECTED`;
    курьер с активными назначениями --- `409
    COURIER_HAS_ACTIVE_ASSIGNMENTS` без деактивации и отзыва сессий
    (проверка назначений --- этап 9).
-   `POST /admin/staff/{user_id}/reactivate` (DEC-150) --- `is_active =
    true`; пароль и роли сохраняются; при `must_change_password = true`
    действует обязательная смена пароля (DEC-28); повтор идемпотентен;
    пользователь с ролью `admin` --- `409 ADMIN_ACCOUNT_PROTECTED`.
-   `PATCH /admin/staff/{user_id}/roles` --- выдача `courier` создаёт
    `courier_profiles` (DEC-27); снятие `courier` при активных
    назначениях --- `409 COURIER_HAS_ACTIVE_ASSIGNMENTS` (DEC-29)
-   `GET /admin/couriers` --- доступность, `max_active_orders`, число
    активных назначений (этап 9, DEC-150)
-   `PATCH /admin/couriers/{user_id}/availability` (этап 9, DEC-150,
    DEC-151 п. 2) --- `{"is_available": bool, "max_active_orders":
    1..10}`, оба поля необязательны, хотя бы одно обязательно; вне
    диапазона --- `422 VALIDATION_ERROR`; пользователь без роли
    `courier` или профиля --- `404`. Уменьшение лимита ниже числа
    активных назначений не снимает их.
-   `GET/POST /admin/delivery-zones`
-   `PATCH/DELETE /admin/delivery-zones/{id}` --- GeoJSON MultiPolygon
    (SRID 4326); проверка валидности и пересечений выполняется на
    backend через PostGIS (DEC-53, DEC-94). По DEC-150: принимаются
    `Polygon` и `MultiPolygon`, хранится `MultiPolygon`; `DELETE` ---
    деактивация, без физического удаления.
-   `GET/PATCH /admin/settings` --- координаты ресторана меняются
    (карта и поля широты/долготы), `timezone` (`Asia/Bishkek`) через
    API не меняется (DEC-150)
-   `GET /admin/working-hours` --- 7 записей
-   `PUT /admin/working-hours` --- полный набор ровно из 7 дней; один
    интервал на день; правила DEC-107; атомарная замена; нарушения ---
    `422 INVALID_WORKING_HOURS`

Kitchen endpoints (`cook` и `admin`, DEC-25, DEC-106):

-   `GET /staff/kitchen/orders` --- заказы `confirmed`, `preparing`,
    `ready_for_pickup`, по времени подтверждения (ранние первыми); без
    заказов, ожидающих оплаты
-   `POST /staff/kitchen/orders/{id}/start` --- `confirmed → preparing`
-   `POST /staff/kitchen/orders/{id}/ready` --- `preparing →
    ready_for_pickup`

Ответы kitchen содержат номер заказа, тип, время подтверждения и начала
готовки, позиции с вариантами, модификаторами (группа, название,
количество) и `special_instructions` позиций (DEC-112). **Не** содержат
имя, телефон, адрес, `customer_comment`, суммы и способ оплаты. Cook must not
access finance, staff management, zones or restaurant settings.

## 10. Courier API

Require `courier` role and verify assignment ownership. Курьерский
интерфейс обновляется polling каждые 10 секунд (DEC-93).

-   `GET /courier/me`
-   `PATCH /courier/me/availability` --- `{"is_available": bool}`;
    `max_active_orders` курьер не меняет (DEC-151 п. 2)
-   `GET /courier/orders` --- активные назначения;
    `?history=true` --- `completed` и `declined`
-   `GET /courier/orders/{id}`
-   `POST /courier/orders/{id}/accept` --- заполняет `accepted_at`
    (DEC-52, DEC-83); повтор по своему принятому назначению --- `200`
    без изменений (DEC-151 п. 4); непринятое назначение после перехода
    заказа в `out_for_delivery` вмешательством администратора (DEC-91)
    принять нельзя --- `409 INVALID_STATUS_TRANSITION` (DEC-151 п. 5)
-   `POST /courier/orders/{id}/decline` --- `{"reason": "..."}`
    (необязательно); только до принятия и до `out_for_delivery`: после
    принятия --- `409 ASSIGNMENT_ALREADY_ACCEPTED`, после
    `out_for_delivery` без принятия (вмешательство DEC-91) --- `409
    INVALID_STATUS_TRANSITION` (DEC-151 п. 5); назначение → `declined`,
    статус заказа не меняется (DEC-92); повтор по своему уже
    отклонённому назначению --- `200` с текущим состоянием без повторных
    побочных эффектов (`declined_at`, `decline_reason` не
    перезаписываются); ответ --- только данные уровня истории, без
    адреса и контактов (DEC-106, DEC-151 п. 4)
-   `POST /courier/orders/{id}/picked-up` --- `ready_for_pickup →
    out_for_delivery`; без принятия --- `409 ASSIGNMENT_NOT_ACCEPTED`;
    повтор --- `409 INVALID_STATUS_TRANSITION` (DEC-151 п. 4)
-   `POST /courier/orders/{id}/delivered` --- `out_for_delivery →
    completed`; `deliveries.delivered_at`, назначение `completed`,
    наличный платёж `succeeded` (DEC-43); повтор по своему
    завершённому назначению --- `200` с текущим состоянием без повторных
    побочных эффектов (DEC-151 п. 4)

Неудачная доставка, отказ клиента и возврат заказа в v1 не имеют
отдельного статуса или endpoint'а: из `out_for_delivery` возможен только
`completed`; такие случаи администратор решает вне системы (DEC-151
п. 1). Курьерский интерфейс --- отдельный маршрут `/courier` (DEC-151
п. 9).

Do not allow a courier to query another courier's orders or submit
arbitrary courier IDs.

Видимость данных (DEC-106):

-   активное назначение: номер, статус, время создания, адрес из
    snapshot (текст, подъезд, этаж, квартира, координаты), комментарий
    для курьера, имя и телефон клиента, комментарий к заказу, состав,
    способ оплаты, `total_amount` («к получению» для `cash`, «оплачено»
    для `mock_card`);
-   не видит: email клиента, другие заказы клиента, историю статусов с
    именами сотрудников, платёжные записи;
-   история (`completed`, `declined`): номер, дата, сумма, способ
    оплаты; адрес, имя и телефон скрыты;
-   после переназначения на другого курьера или отмены заказа прежний
    курьер получает `404` на детали.

## 11. Access matrix

Роли сочетаются; права суммируются (DEC-23). Клиентские действия
требуют роли `customer`.

| Action | Customer | Cook | Courier | Admin |
|---|---|---|---|---|
| Public catalog | Yes | Yes | Yes | Yes |
| Own cart/address/order | Yes | Только с ролью customer | Только с ролью customer | Admin view |
| Change order status | No | Kitchen transitions only | Assigned delivery transitions | Yes; курьерские переходы --- как вмешательство (DEC-91) |
| Catalog CRUD | No | No | No | Yes |
| Kitchen queue | No | Yes | No | Yes |
| Assign courier | No | No | No | Yes |
| Accept/decline assignment | No | No | Own assignments | No |
| Own availability | No | No | Yes | Yes (для курьеров; этап 9, DEC-150) |
| Staff/settings/zones | No | No | No | Yes |
| Notifications/Telegram | Yes | No (v1) | No (v1) | No (v1) |
| Telegram Mini App (вход, регистрация, привязка) | Yes | Только с ролью customer | Только с ролью customer | Только с ролью customer |

## 12. API implementation rules

-   FastAPI routers by domain; Pydantic request/response schemas.
-   Thin endpoints; service layer owns business rules; worker использует
    те же сервисы (DEC-104).
-   Common exception handler (включая `RequestValidationError`) and
    request ID.
-   Pagination on large lists; cap page_size (e.g. 100).
-   Allowlist sort fields; never interpolate arbitrary user strings into
    SQL.
-   OpenAPI contract is used to generate frontend types via
    `openapi-typescript` (DEC-71).
-   Rate limits через `slowapi`, значения в конфигурации (DEC-80,
    DEC-95).
-   Библиотеки --- DEC-94; версии фиксируются в lock-файлах.
-   Test auth, RBAC, ownership, pricing, modifier constraints, delivery
    zones, idempotency, status transitions (включая административное
    вмешательство), courier accept/decline, cancellation idempotency,
    payment timeout and mock payments.

## 13. Decisions

Вопросы, ранее перечисленные здесь (checkout payload, status flows,
courier accept, mock payment lifecycle, refresh-cookie CSRF, Telegram
outbox), решены и зафиксированы в `docs/DECISIONS.md`. Новые решения
записываются туда же; do not silently invent behavior.
