# Deployment

This project is a **demo**. It is **not deployed on a permanent public
server**, it has no production hosting with a domain and certificate yet
(planned for stage 11), and it takes **no real payments** (`cash` and
`mock_card` only). This page describes the modes that exist and how the
Telegram Mini App was checked on a temporary, access-restricted sandbox.

No real addresses, tunnel URLs, IP addresses or secrets are used in this
document; replace the placeholders in angle brackets with your own values.

## Modes

| Mode | Compose files | Purpose | Database |
|---|---|---|---|
| dev | `compose.yaml` + `compose.dev.yaml` | Development, hot reload | `food_delivery` (`db`), tests on `db-test` |
| demo | `compose.yaml` + `compose.demo.yaml` | Production build behind nginx, on localhost | `food_delivery` (`db`) |
| sandbox | dev files + `compose.sandbox.yaml` | Manual checks in a browser and in Telegram on an isolated database | `food_delivery_sandbox` (`db-sandbox`) |

## Demo mode (local)

Production images: the backend runs as a non-root user with one Uvicorn
worker; the frontend is built and served by nginx (`frontend/nginx/default.conf`),
which proxies `/api/` and `/media/` to the backend and adds basic security
headers. Only `127.0.0.1:8080` (nginx) and `127.0.0.1:8025` (Mailpit UI) are
published; OpenAPI docs are off (`APP_ENV=demo`), and the refresh cookie is
marked `Secure`.

Start, migrate, seed and create the administrator as described in
[INSTALLATION.md → Demo mode](INSTALLATION.md#4-demo-mode-production-build-behind-nginx).

Because the refresh cookie is `Secure` in demo mode, browsers keep it only
over HTTPS or on `localhost`. Exposing demo mode on another host requires
HTTPS in front of nginx and the variables from
[Public origin settings](#public-origin-settings).

## Sandbox mode

An isolated stack for manual checks, which never touches the main database.

1. Create `.env.sandbox` next to `.env` (it is git-ignored by the `.env.*`
   rule):

   ```dotenv
   SANDBOX_POSTGRES_PASSWORD=<url-safe password>
   # SANDBOX_POSTGRES_USER=sandbox   # default
   ```

2. Start the sandbox database, backend and worker (command from the header
   of `compose.sandbox.yaml`):

   ```bash
   docker compose --env-file .env --env-file .env.sandbox \
     -f compose.yaml -f compose.dev.yaml -f compose.sandbox.yaml up -d db-sandbox backend worker
   ```

   Then apply migrations and seeds inside this backend
   (`alembic upgrade head`, `python -m app.seeds base`,
   `python -m app.seeds demo`) using the same `docker compose … exec backend`
   prefix.

3. Data and uploaded images live in the sandbox-only volumes
   `food-delivery_db-sandbox-data` and `food-delivery_media-sandbox-data`;
   they survive restarts and are never shared with the main stack. The
   sandbox database port is not published.

Notes:

- The sandbox reuses the dev backend image (`APP_ENV=dev`), so the refresh
  cookie is not `Secure` and OpenAPI is enabled on the backend itself. Any
  public reverse proxy in front of it must expose only the API routes the
  frontend needs.
- The merged configuration keeps the dependencies of the base and dev files:
  `backend` depends on `db`, `db-sandbox` and `db-test`, `worker` on `db`
  and `db-sandbox`. Compose starts them too unless services are started with
  `--no-deps`. Decide this deliberately if the main database must stay
  stopped.
- **Never run `docker compose down -v`** in this setup: it deletes the
  sandbox and main volumes.

## Telegram Mini App

The Mini App is the same SPA under `/tg`. It needs:

1. A bot created with [@BotFather](https://t.me/BotFather) and its token in
   `TELEGRAM_BOT_TOKEN` (in `.env`, never committed). With an empty token the
   Mini App endpoints answer `409 TELEGRAM_DISABLED` and the site works as
   usual.
2. A **public HTTPS origin** that serves the production build and proxies
   `/api/` and `/media/` to the backend on the same origin.
3. The Mini App URL `https://<public-host>/tg` set for the bot in BotFather
   (done manually by the bot owner; there is no bot process in this
   project yet).
4. The variables from [Public origin settings](#public-origin-settings).

The Mini App cannot be opened in a normal browser: every request needs
Telegram's signed `initData`. Automated tests use a fake `window.Telegram`
instead (see [DEVELOPMENT.md](DEVELOPMENT.md)).

### Public origin settings

Set these for the backend when the site is reached through any origin other
than the local defaults:

| Variable | Value |
|---|---|
| `CSRF_TRUSTED_ORIGINS` | Exact browser origin(s), e.g. `https://<public-host>` — no path, no trailing slash |
| `FRONTEND_BASE_URL` | `https://<public-host>` — used in password-reset links |
| `TELEGRAM_BOT_TOKEN` | The bot token (secret) |

`CORS_ALLOWED_ORIGINS` stays empty: the frontend and the API share one origin.

## How the sandbox was published for manual checks

For manual checks in real Telegram clients the author temporarily published
the **sandbox** (never the main database) as follows (decision DEC-159 in
[`docs/DECISIONS.md`](docs/DECISIONS.md)):

```text
Telegram client → Cloudflare → temporary Cloudflare Quick Tunnel → separate nginx → backend (sandbox)
                                                                     └─ serves frontend/dist (read-only)
```

- The address of a Quick Tunnel is **temporary** and changes on every start;
  `CSRF_TRUSTED_ORIGINS`, `FRONTEND_BASE_URL` and the bot's Mini App URL
  must be updated to match.
- The separate nginx is the only entry point: no application or database
  port is published on the host; it forwards only an agreed set of API
  routes, serves the build read-only and allows only an owner-defined list
  of client IP addresses.
- The client address is taken from `CF-Connecting-IP` only for connections
  coming from the tunnel connector; client-supplied `X-Forwarded-For` and
  similar headers are ignored.
- A new frontend build is published only with a backup of the previous
  build, checksums and a way to roll back.

The configuration of that nginx, the tunnel and the IP allowlist are
operational materials of the author's machine and **are not part of this
repository**. Use them only as requirements if you build a similar setup.

## Before any public deployment

This checklist is what stage 11 still needs; it is not done yet:

- A real host with a domain and a TLS certificate instead of a temporary
  tunnel; demo mode (`APP_ENV=demo`) with a `Secure` refresh cookie.
- Strong secrets in the environment only: `JWT_SECRET_KEY`, database
  passwords, `TELEGRAM_BOT_TOKEN`.
- A real SMTP server instead of Mailpit, if password reset by e-mail is
  needed.
- Database backups for the volumes.
- End-to-end tests and a security review.
- A real payment provider would require a separate design: the project
  never stores card numbers, CVV or expiry dates.
