# Food Delivery — Osh (demo)

A full-stack demo of food ordering for **one restaurant with one branch** in
Osh, Kyrgyzstan: a customer website, a **Telegram Mini App**, and staff
interfaces for the administrator, the cook and the courier.

Modular monolith: **FastAPI + PostgreSQL/PostGIS** backend, **React +
TypeScript** frontend, one background worker, everything in Docker Compose.

> **Demo project.** It is not deployed on a permanent public server, takes no
> real payments, and all restaurant, menu and price data is fictitious.
> See [Demo limitations](#demo-limitations).

## What it does

### Customer website

- Home page, menu with categories, search and pagination, product page.
- Product configuration: sizes (variants) and extras (modifiers with a
  quantity limit); prices always come from the server.
- Server-side cart (signed-in customers only, no guest cart).
- Checkout with delivery (address inside a delivery zone) or pickup;
  orders are accepted only during working hours; idempotent order creation.
- Payment by **cash** or by **`mock_card`** (a simulated card that never
  charges money); unpaid mock-card orders are cancelled after 30 minutes.
- Order list and order page with live status (polling every 20 s);
  cancellation is a *request* that an administrator approves or rejects.
- Registration, sign-in, password change and password reset by e-mail.
- Languages: Russian, Kyrgyz, Uzbek. Currency: KGS. Mobile-first layout.

### Telegram Mini App (`/tg`)

- Sign-in by Telegram `initData` (verified on the backend with the bot
  token); first launch offers to register or to link an existing site
  account.
- Menu, product, cart, checkout, mock-card payment, orders and profile —
  the same pages and API as the site, inside the Mini App router.
- Follows the Telegram light/dark theme; bottom tab bar; Telegram
  BackButton; the interface language is stored in the profile.

### Staff

- **Administrator** (`/admin`): dashboard, order queue and status changes,
  cancellation requests, catalog (categories, products, variants,
  modifiers, images), staff and roles, couriers (manual or automatic
  assignment), delivery zones drawn on a map (Leaflet + Geoman, validated
  with PostGIS), restaurant settings and working hours.
- **Cook** (`/admin/kitchen`): kitchen queue only — no customer personal
  data, comments or payment data.
- **Courier** (`/courier`): assigned orders only; accept (or decline before
  accepting), "picked up", "delivered", history.
- Staff screens refresh every 10 s.

## Demo limitations

- **No real payments.** Only `cash` and `mock_card` exist; `mock_card`
  simulates a card payment and never stores card numbers, CVV or expiry.
- **E-mail** (password reset) goes to [Mailpit](https://mailpit.axllent.org/),
  a local mail catcher; nothing is sent to real mailboxes.
- **Telegram bot, notifications and the outbox are not implemented yet**
  (planned stage 10). The Mini App works; there is no bot process and no
  Telegram or in-app notifications.
- **No permanent hosting.** The project runs locally; manual Mini App
  checks used a temporary tunnel to a local sandbox
  (see [DEPLOYMENT.md](DEPLOYMENT.md)).
- **Demo data is fictitious:** restaurant, address, phone, prices, delivery
  zone. Kyrgyz and Uzbek texts are drafts awaiting native-speaker review.
- No end-to-end (Playwright) tests yet; see [DEVELOPMENT.md](DEVELOPMENT.md).

## Stack

| Part | Technologies |
|---|---|
| Backend | Python 3.14, FastAPI, Pydantic, SQLAlchemy 2.0 (async), psycopg 3, Alembic, GeoAlchemy2, Argon2id, PyJWT, slowapi — locked in `backend/uv.lock` |
| Database | PostgreSQL 16 + PostGIS 3.6 |
| Frontend | Node.js 24, React 19, TypeScript, Vite, React Router, Redux Toolkit + RTK Query, React Hook Form + Zod, Tailwind CSS v4, i18next, Leaflet — locked in `frontend/package-lock.json` |
| Tests | Pytest, Vitest + React Testing Library |
| Infra | Docker Compose (dev and demo modes), nginx (demo), Mailpit |

## Quick start

Requirements: Docker Desktop (WSL 2 on Windows) with Docker Compose v2.

```bash
cp .env.example .env        # then fill in the required values (see INSTALLATION.md)
docker compose -f compose.yaml -f compose.dev.yaml up --build -d
docker compose -f compose.yaml -f compose.dev.yaml exec backend alembic upgrade head
docker compose -f compose.yaml -f compose.dev.yaml exec backend python -m app.seeds base
docker compose -f compose.yaml -f compose.dev.yaml exec backend python -m app.seeds demo
docker compose -f compose.yaml -f compose.dev.yaml exec backend python -m app.cli create-admin
```

Then open http://localhost:5173. Step-by-step instructions, the demo mode
and troubleshooting are in **[INSTALLATION.md](INSTALLATION.md)**.

## Documentation

| Document | Contents |
|---|---|
| [INSTALLATION.md](INSTALLATION.md) | Running the project locally from scratch |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Backend, frontend, database, worker, Mini App, auth and roles |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Project layout, dev mode, checks and tests |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Demo and sandbox modes, temporary publication |
| [API.md](API.md) | API overview and links to the full specification |
| [`docs/`](docs/) | Specifications: technical spec, database schema, API, UI/UX, plan, decision log |

[`docs/DECISIONS.md`](docs/DECISIONS.md) is the decision log; where documents
disagree, it has priority. [`CLAUDE.md`](CLAUDE.md) holds the working rules
used with the Claude Code assistant during development.

## Project layout

```text
backend/    FastAPI app: app/api/v1 (routers), app/modules (services), app/db,
            app/worker, app/seeds, app/cli; alembic/ migrations; tests/
frontend/   React app: src/app, src/pages, src/features, src/shared, src/styles;
            nginx/ config for the demo image
infra/      Database init override (PostGIS is installed by Alembic only)
docs/       Specifications and the decision log
compose.yaml, compose.dev.yaml, compose.demo.yaml, compose.sandbox.yaml
```

## Status

Implemented: infrastructure, database, auth and roles, catalog and admin
catalog, cart, checkout and orders, payments (cash, mock card), admin and
staff operations, courier, the Telegram Mini App and its visual design.
Not implemented: the Telegram bot and notifications (stage 10), end-to-end
tests and permanent hosting (stage 11). The stage plan is in
[`docs/DEVELOPMENT_PLAN.md`](docs/DEVELOPMENT_PLAN.md).
