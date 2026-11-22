# Architecture

A modular monolith: one FastAPI application, one background worker that uses
the same service layer, one PostgreSQL/PostGIS database and one React
single-page application that serves both the website and the Telegram
Mini App. Detailed specifications live in [`docs/`](docs/); this page is an
overview with pointers.

## Components

```text
 Browser (site)            Telegram client (Mini App, /tg)
        \                     /
         \   same origin     /
     Vite dev server (dev)  or  nginx (demo / sandbox)
        |  static SPA          |  /api/*, /media/*  → backend
        |                      v
        |              FastAPI backend (1 process, 1 Uvicorn worker)
        |                      |
        |              PostgreSQL 16 + PostGIS  <——  worker (asyncio jobs)
        |                      |
        |              media volume (uploaded images)
        v
     Mailpit (password-reset e-mails, dev/demo only)
```

- **One origin.** The SPA and the API are served from the same origin (Vite
  proxy in dev, nginx in demo), so CORS stays disabled by default
  (`CORS_ALLOWED_ORIGINS` empty).
- **One API process with one Uvicorn worker** (DEC-95): rate-limit counters
  live in process memory.
- **Restaurant time zone** `Asia/Bishkek`; timestamps are stored in UTC.

## Backend (`backend/app`)

| Folder | Role |
|---|---|
| `api/v1/` | Thin routers under `/api/v1`: request/response schemas, dependencies, no business logic |
| `modules/<name>/` | Business logic per domain: models, schemas, services, enums |
| `db/` | Engine, async sessions, base model, model registry |
| `core/` | Settings (`pydantic-settings`, environment only), security, errors, logging |
| `worker/` | Background job runner |
| `seeds/` | `python -m app.seeds base\|demo` |
| `cli/` | `python -m app.cli create-admin` |

Modules: `auth`, `users`, `addresses`, `catalog`, `admin_catalog`, `cart`,
`pricing`, `delivery`, `restaurant`, `orders`, `payments`, `admin_orders`,
`dashboard`, `staff`, `kitchen`, `courier`, `telegram_auth`, `notifications`
(data model only; sending is not implemented yet).

Principles (see [`CLAUDE.md`](CLAUDE.md) and `docs/TECHNICAL_SPECIFICATION.md`):

- **The server is the source of truth** for prices, totals, delivery fee,
  roles and order status. `expected_total` from the client is only compared,
  never trusted.
- **Checkout** runs in one transaction with an idempotency key; the order
  keeps immutable snapshots of products, options and prices.
- **Order statuses:** `pending`, `confirmed`, `preparing`,
  `ready_for_pickup`, `out_for_delivery`, `completed`, `rejected`,
  `cancelled`; allowed transitions are defined in
  `docs/DATABASE_SCHEMA.md` §7.1 and enforced by one status service.
  Customers send a cancellation *request*; cancellation itself goes through
  one idempotent operation.
- **Delivery zones** are PostGIS polygons; geometry and overlaps are
  validated on the backend.
- **Uploaded images** are checked for type, size and content and stored in
  the media volume, served at `/media`.
- Errors use one JSON format with a machine-readable `code`; every response
  carries a request id.

## Database

PostgreSQL 16 with PostGIS, schema managed **only by Alembic**
(`backend/alembic/versions/0001…0009`; `create_all()` is not used). UUID
primary keys, money as `NUMERIC(12,2)`, timezone-aware UTC timestamps,
explicit foreign-key delete rules, partial unique indexes. The full schema is
in [`docs/DATABASE_SCHEMA.md`](docs/DATABASE_SCHEMA.md).

Databases by purpose:

| Database | Where | Used for |
|---|---|---|
| `food_delivery` | service `db`, volume `db-data` | Dev and demo modes |
| `food_delivery_test` | service `db-test`, tmpfs | Pytest in dev mode (discarded when the container stops) |
| `food_delivery_sandbox` | service `db-sandbox`, own volumes | Sandbox mode for manual checks (see [DEPLOYMENT.md](DEPLOYMENT.md)) |

## Worker

`python -m app.worker`: a single asyncio process running jobs on their own
intervals with the same services as the API. Today it runs one job:
`payment_timeout` cancels unpaid `mock_card` orders after
`PAYMENT_TIMEOUT_MINUTES` (default 30), checking every 60 s in batches of 50
with `SKIP LOCKED`, one transaction per order. A heartbeat file feeds the
container health check. Notification sending and idempotency-key cleanup
are planned for stage 10.

## Authentication, sessions and roles

**Website.**

- Passwords: Argon2id; policy 8–128 characters with at least one letter
  and one digit (same rule for registration, change, reset and the CLI).
- Access token: a short-lived JWT (15 min) kept **only in frontend memory**;
  it carries the user id only.
- Refresh token: an `HttpOnly`, `SameSite=Strict` cookie (`Secure` when
  `APP_ENV=demo`), rotated on every use, with token-family reuse detection;
  the database stores only its hash. Browser tabs coordinate refreshes with
  `navigator.locks`.
- CSRF: one origin, an exact `Origin` check for `/auth/refresh` and
  `/auth/logout` (`CSRF_TRUSTED_ORIGINS`) and a custom
  `X-CSRF-Protection` header.
- Sign-in and password reset never reveal whether an account exists.
- Rate limits for auth and the API (values in settings).

**Telegram Mini App.** The frontend sends the raw `initData` string to
`POST /auth/telegram/webapp`; the backend verifies its HMAC-SHA256 signature
with the bot token, its age and size, and returns an access token. The Mini
App uses **no refresh cookie**: when the token expires it exchanges
`initData` again. A Telegram account can register a new customer account or
link an existing site account (`…/register`, `…/link`).

**Roles:** `customer`, `admin`, `cook`, `courier`. Roles and `is_active` are
read from the database on **every request**; ownership of orders, addresses
and courier assignments is checked on the backend. The first administrator is
created only with `create-admin`; there are no default credentials.

| Role | Access |
|---|---|
| customer | Cart, checkout, own orders, own addresses and profile |
| admin | Everything in `/admin`; courier actions only as a logged override with a comment |
| cook | Kitchen queue only, without customer personal data, comments or payment data |
| courier | Only assigned orders; must accept before pickup; may decline only before accepting |

## Frontend (`frontend/src`)

| Folder | Role |
|---|---|
| `app/` | Providers, store, routers (`routes.tsx` for the site, `miniAppRoutes.tsx` for `/tg`), layouts |
| `pages/` | Route pages (home, menu, product, cart, checkout, orders, account, auth, admin, courier, telegram) |
| `features/` | Domain features: API slices (RTK Query), components and hooks (catalog, cart, orders, auth, admin, courier, telegram, restaurant) |
| `shared/` | API base, UI components, i18n (`ru`, `ky`, `uz`), types (generated from OpenAPI), utilities |
| `styles/` | Tailwind v4 design tokens and global CSS |
| `test/` | Vitest setup, fixtures, fetch and Telegram mocks |

- All API access goes through **RTK Query**; API types are generated from
  the backend OpenAPI schema (`npm run gen:api`).
- Forms: React Hook Form + Zod. All UI text goes through i18next.
- Polling: customer order screens every 20 s, staff screens every 10 s.
- Maps: Leaflet + OpenStreetMap; delivery zones are edited with Geoman.

### Telegram Mini App mode

The mode is decided once, by the path, before the router is created:
`/tg` and everything under it get a **separate router with basename `/tg`**,
so no in-app link can lead to a site page. The Mini App reuses the site's
pages and API slices, adds its own layout (no site header/footer, bottom tab
bar, Telegram BackButton, safe areas) and maps Telegram's theme colours onto
the design tokens only when they keep WCAG AA contrast. The Telegram SDK is
the official script; the bot token never reaches the frontend.

## Further reading

- [`docs/TECHNICAL_SPECIFICATION.md`](docs/TECHNICAL_SPECIFICATION.md) — functional scope
- [`docs/DATABASE_SCHEMA.md`](docs/DATABASE_SCHEMA.md) — tables, constraints, status transitions
- [`docs/API_SPECIFICATION.md`](docs/API_SPECIFICATION.md) — endpoints and error codes
- [`docs/UI_UX_GUIDELINES.md`](docs/UI_UX_GUIDELINES.md) — design system and screens
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — decision log (has priority)
