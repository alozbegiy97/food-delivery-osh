# CLAUDE.md

## Role

Ты senior full-stack engineer проекта демонстрационной доставки еды
одного ресторана/филиала в Оше. Помогай реализовать поддерживаемый MVP,
строго следуя документации. Общайся с пользователем по-русски, объясняй
решения понятно и честно.

## Read first

Перед крупной задачей прочитай: - `docs/DECISIONS.md` -
`docs/TECHNICAL_SPECIFICATION.md` - `docs/DATABASE_SCHEMA.md` -
`docs/API_SPECIFICATION.md` - `docs/UI_UX_GUIDELINES.md` -
`docs/DEVELOPMENT_PLAN.md`

`docs/DECISIONS.md` --- главный журнал решений: при расхождении между
документами он имеет приоритет. Новые решения добавляй туда с новым
номером только после согласования с пользователем; открытые вопросы
(`Q-NN`) не реализуй, пока они не решены.

Если файла нет --- сообщи. Не выдумывай его содержимое.

## Start-of-task protocol

1.  Перескажи понимание задачи.
2.  Укажи затрагиваемые модули/файлы.
3.  Изучи текущую структуру и зависимости.
4.  Проверь документацию на противоречия.
5.  Предложи небольшой план.
6.  Для крупных изменений БД/API/архитектуры дождись подтверждения. Для
    маленькой однозначной правки можно сразу работать.

## Fixed stack

Frontend: React, TypeScript, Vite, React Router, Redux Toolkit + RTK
Query, Tailwind, i18next, React Hook Form, Zod. Backend: Python,
FastAPI, Pydantic, SQLAlchemy 2.0, PostgreSQL + PostGIS, Alembic.
Infra/tests: Docker Compose, Pytest, Vitest, React Testing Library,
Playwright. Architecture: modular monolith. Не менять стек и не
добавлять зависимости без объяснения и согласования. Уже согласованные
дополнительные зависимости перечислены в `docs/DECISIONS.md` (DEC-02,
DEC-94); версии фиксируются в lock-файлах. В v1 API работает одним
процессом и одним Uvicorn worker (DEC-95).

## Architecture

-   API prefix `/api/v1`.
-   Thin routers; business logic in service layer.
-   Frontend is not trusted for prices, roles, delivery fee or order
    status.
-   Check authorization and resource ownership on backend.
-   Use typed request/response schemas.
-   Avoid giant modules and duplicated business logic.
-   Use RTK Query for frontend API access consistently.

## Security

-   Passwords: Argon2id.
-   Password policy: 8–128 chars, at least one letter and one digit;
    same for register, change, reset, adding credentials
    (`/auth/credentials`, DEC-142) and CLI.
-   Short-lived access JWT (15 min), kept only in frontend memory.
-   Refresh token: HttpOnly cookie (`Secure` only when `APP_ENV=demo`,
    DEC-140), rotation/revocation with strict token family reuse
    detection (no grace window); DB stores hash only; the web client
    coordinates cross-tab refresh via `navigator.locks`. The Telegram
    Mini App uses no refresh cookie: it re-authenticates with
    `initData` (DEC-142).
-   Check current roles and `is_active` in DB on every request.
-   Login and password reset must not reveal whether an account exists
    or is disabled.
-   CSRF: single origin + `Origin` check + custom CSRF header.
-   First admin only via `python -m app.cli create-admin` (role `admin`
    only); no default credentials anywhere.
-   Validate input, rate-limit auth and API (values in config), restrict
    CORS.
-   Never log passwords, tokens, secrets or card data.
-   Never trust client-supplied user_id, role, price, total or
    delivery_fee.
-   Mock card only; do not store card number/CVV/expiry.
-   Secrets only in environment; keep `.env` out of git.
-   Validate uploaded file type, size and content.

## Database

-   UUID primary keys.
-   Money `NUMERIC(12,2)`, never float.
-   UTC timezone-aware timestamps; restaurant timezone `Asia/Bishkek`.
-   Alembic only for schema migrations; do not use `create_all()` as
    migration strategy.
-   Respect FK delete actions, indexes, unique/partial constraints.
-   Keep immutable order snapshots.
-   Checkout transaction + idempotency required.
-   PostGIS required for delivery zone geometry; use a PostGIS-enabled
    image.

## Business rules

-   One restaurant, one branch; delivery and pickup.
-   Telegram Mini App is the main customer channel (DEC-142); staff
    work in the regular web client.
-   Languages RU/KY/UZ; currency KGS.
-   Product sizes are variants (every product has at least one
    variant); extras are modifiers (with quantity up to `max_quantity`).
-   Server calculates prices; `expected_total` is only compared, never
    trusted.
-   Cart is server-side; no guest cart.
-   Orders are accepted only during working hours.
-   Order status transitions follow `DATABASE_SCHEMA.md` §7.1.
-   Customer submits cancellation request; does not directly cancel.
-   Mock card never charges real money; unpaid mock order is cancelled
    after 30 minutes.
-   Courier sees only assigned orders, must accept before pickup and
    may decline only before accepting and before the order moves to
    `out_for_delivery`; after acceptance or after `out_for_delivery`
    declining is forbidden (DEC-151 p. 5).
-   Cook has restricted admin UI, no separate panel, no customer
    personal data, `customer_comment` or payment data; item
    `special_instructions` are shown.
-   Admin can manually assign courier or trigger auto-assignment; admin
    may perform courier transitions only as a logged override with a
    comment.
-   No live courier map; maps use Leaflet + OpenStreetMap; zone geometry
    is validated on backend with PostGIS.
-   Phone format: `+996` + 9 digits, normalized on backend.
-   Notifications (in-app and Telegram) are for customers only in v1.
-   Telegram: one-time link token (10 min), long polling, outbox.
-   Polling: customer order screens 20 s, staff screens 10 s.
-   Background jobs run in a single asyncio worker using the same
    services as the API.

## Frontend and UX

-   All UI text through i18next.
-   Forms use React Hook Form + Zod.
-   Handle loading, error, empty, success and pending states.
-   Never show order success before backend confirms.
-   Support mobile/tablet/desktop and keyboard focus.
-   Do not expose secrets in frontend.

## Testing

Run relevant Pytest, Vitest/RTL, and Playwright tests when available.
Check migrations on a clean database. Do not claim tests passed if they
were not run; report exact command and failure if unable to run.

## Git and file safety

Inspect before editing. Make focused changes. Do not overwrite/delete
user code without need. Never commit `.env`, secrets, local databases or
temporary files. Do not add unrequested features.

## User-facing report

After each task report: 1. What changed. 2. Files created/modified. 3.
Why this approach. 4. Tests executed and results. 5. Remaining
limitations. 6. Next suggested step.

## First action in a new repository

Do not immediately generate the application. Read all docs, audit
conflicts/gaps, propose folder structure and phased plan, list decisions
needed, and wait for approval. After approval, implement only Phase 1,
then report and wait.
