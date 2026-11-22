# API

A short map of the REST API. The full contract — every endpoint, request and
response field, error code and access rule — is in
**[`docs/API_SPECIFICATION.md`](docs/API_SPECIFICATION.md)** (in Russian).
The machine-readable schema is the backend's **OpenAPI** document.

## Base URL and OpenAPI

- Prefix: **`/api/v1`**. In dev mode the backend is at
  `http://localhost:8000/api/v1`; through Vite (`http://localhost:5173`) or
  nginx in demo mode (`http://localhost:8080`) the same paths work on the
  site's own origin.
- OpenAPI (dev mode only, disabled with `APP_ENV=demo`):
  - Swagger UI: `http://localhost:8000/api/v1/docs`
  - JSON schema: `http://localhost:8000/api/v1/openapi.json`
- Health check: `GET /api/v1/health`.
- The frontend's TypeScript types are generated from the OpenAPI schema
  (`npm run gen:api`, see [DEVELOPMENT.md](DEVELOPMENT.md)).

## Conventions

| Topic | Rule | Spec |
|---|---|---|
| Errors | `{"error": {"code", "message", "details", "request_id"}}` with a stable machine-readable `code` | §1, §1.1 |
| Request id | Every response has `X-Request-ID` (the client's value if valid, otherwise generated) | §1.6 |
| Language | `language=ru\|ky\|uz` for localized responses; fallback to the user's language, then `ru` | §1.3 |
| Rate limits | Auth and API limits, `429` with a code | §1.2 |
| Phones | `+996` and 9 digits; several input formats are normalized on the server | §1.5 |
| Updates | No WebSocket/SSE; the frontend polls (20 s customers, 10 s staff) | §1.4 |
| Money | Decimal strings (`"550.00"`), currency KGS; totals are always computed by the server | §5–§6 |

## Authentication

- `Authorization: Bearer <access token>` for protected endpoints. The access
  token is short-lived (15 minutes) and kept in memory by the frontend.
- The refresh token is an `HttpOnly` cookie used only by
  `POST /auth/refresh` and `POST /auth/logout`; these two also require an
  allowed `Origin` and the `X-CSRF-Protection` header.
- The Telegram Mini App exchanges Telegram `initData` for an access token at
  `POST /auth/telegram/webapp` and does not use the refresh cookie.

See [ARCHITECTURE.md](ARCHITECTURE.md#authentication-sessions-and-roles) and
spec §2.

## Endpoint groups

| Area | Paths (under `/api/v1`) | Access | Spec |
|---|---|---|---|
| Service | `/health`, `/docs`, `/openapi.json` | Public (docs: dev only) | §1.6 |
| Auth | `/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/me`, password change and reset, `/auth/credentials` | Public / signed in | §2–§2.2 |
| Telegram Mini App | `/auth/telegram/webapp`, `…/register`, `…/link` | Telegram `initData` | §2.3 |
| Catalog and restaurant | `/catalog/categories`, `/catalog/products`, `/catalog/products/{id}`, `/restaurant` | Public | §3 |
| Profile and addresses | `/users/me`, `/users/me/addresses…` | Signed in / customer | §4 |
| Cart | `/cart`, `/cart/items…` | Customer | §5 |
| Checkout and orders | `/checkout/quote`, `/orders`, `/orders/{id}`, cancellation requests | Customer | §6 |
| Payments | `/payment-methods`, `/payments/mock/confirm` | Public / customer | §7 |
| Admin | `/admin/…`: dashboard, orders, cancellation requests, catalog, staff, couriers, delivery zones, settings, working hours | Admin | §9 |
| Kitchen | `/staff/kitchen/orders…` | Admin, cook | §9 |
| Courier | `/courier/…` | Courier | §10 |

The access matrix of all roles is in spec §11.

**Not implemented yet:** the notification and Telegram-bot endpoints of
spec §8 (in-app notifications, Telegram link tokens) belong to stage 10.

## Payments

Only two methods exist: **`cash`** and **`mock_card`**. `mock_card` is a
simulation: `POST /payments/mock/confirm` marks an attempt as succeeded or
failed without contacting any payment provider, and the API never accepts or
stores card numbers, CVV or expiry dates. Unpaid `mock_card` orders are
cancelled by the worker after 30 minutes. Details: spec §7.

## Example

```bash
curl -s "http://localhost:8000/api/v1/catalog/products?language=ru&page=1"
```
