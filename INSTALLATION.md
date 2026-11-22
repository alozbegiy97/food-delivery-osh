# Installation

How to run the project locally from a fresh clone. Everything runs in
Docker; local Python and Node.js are not required.

## 1. Requirements

- Docker Desktop (with WSL 2 on Windows) or Docker Engine, with
  Docker Compose v2 (`docker compose`).
- Enough memory for Docker to run PostgreSQL, Python and Node containers
  together (on Docker Desktop, the frontend tests are run with one worker to
  keep memory low).
- Free local ports `5173`, `8000`, `5432`, `5433`, `8025` (dev mode) or
  `8080`, `8025` (demo mode). All of them can be changed in `.env`.

## 2. Configure `.env`

```bash
cp .env.example .env        # PowerShell: Copy-Item .env.example .env
```

`.env` is git-ignored — never commit it. Fill in the required values:

| Variable | What to put |
|---|---|
| `POSTGRES_PASSWORD` | Password of the main database. URL-safe characters only (letters, digits, `-`, `_`, `.`): it becomes part of a database URL. |
| `TEST_POSTGRES_PASSWORD` | Password of the isolated test database (dev mode). Same rule. |
| `JWT_SECRET_KEY` | Random secret, at least 32 characters. |

Generate a secret, for example:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
# or, without Python:
openssl rand -base64 48
```

`docker compose` refuses to start while a required value is missing. There
are no default credentials anywhere. Every other variable has a working
default; they are described in `.env.example`.

`TELEGRAM_BOT_TOKEN` may stay empty: the site works fully, and the Mini App
endpoints answer `409 TELEGRAM_DISABLED` (see [DEPLOYMENT.md](DEPLOYMENT.md)).

## 3. Development mode

Hot reload for backend and frontend; source code is bind-mounted.

```bash
docker compose -f compose.yaml -f compose.dev.yaml up --build -d
```

Services: `db` (main database), `db-test` (test database, data in tmpfs),
`backend`, `worker`, `frontend` (Vite), `mailpit`.

To shorten the commands below, you can define an alias. Bash:

```bash
DC="docker compose -f compose.yaml -f compose.dev.yaml"
```

PowerShell:

```powershell
function dc { docker compose -f compose.yaml -f compose.dev.yaml @args }
```

### Database schema and data

Run once after the first start (and after pulling new migrations):

```bash
$DC exec backend alembic upgrade head      # migrations 0001…0009, installs PostGIS
$DC exec backend python -m app.seeds base  # roles, payment methods, restaurant settings, hours
$DC exec backend python -m app.seeds demo  # demo delivery zone and demo catalog (needs base)
```

- The seeds run only on the latest migration revision.
- Both are idempotent: they add missing records and never change or delete
  existing ones. They create no users.
- Exit codes: `0` success, `1` seed or database error (rolled back),
  `2` invalid arguments, `130` interrupted.

### First administrator

```bash
$DC exec backend python -m app.cli create-admin
```

The command asks (in Russian) for the administrator's name, the e-mail used
as the login, and the password twice (never shown). It works only while no
administrator exists. Password rules: 8–128 characters,
at least one letter and one digit. Further staff (cooks, couriers, other
roles) are created by the administrator in the admin interface.

Customers register themselves on the site (`/register`).

### Open

| URL | What |
|---|---|
| http://localhost:5173 | Website (Vite; `/api` and `/media` are proxied to the backend) |
| http://localhost:5173/admin | Staff area (sign in as the administrator) |
| http://localhost:8000/api/v1/health | Backend health check |
| http://localhost:8000/api/v1/docs | OpenAPI (Swagger UI), dev mode only |
| http://localhost:8025 | Mailpit: password reset e-mails |

All ports are bound to `127.0.0.1`. Host ports can be changed in `.env`:
`FRONTEND_HOST_PORT`, `BACKEND_HOST_PORT`, `DB_HOST_PORT`,
`TEST_DB_HOST_PORT`, `MAILPIT_UI_PORT`.

The Telegram Mini App (`/tg`) does not open in a normal browser: it needs
Telegram's signed `initData`. See [DEPLOYMENT.md](DEPLOYMENT.md).

### Stop

```bash
$DC down          # stops containers, keeps data
```

> **Warning:** `down -v` deletes the volumes, including the main database
> (`db-data`) and uploaded images (`media-data`). Use it only to erase local
> data on purpose.

## 4. Demo mode (production build behind nginx)

```bash
docker compose -f compose.yaml -f compose.demo.yaml up --build -d
docker compose -f compose.yaml -f compose.demo.yaml exec backend alembic upgrade head
docker compose -f compose.yaml -f compose.demo.yaml exec backend python -m app.seeds base
docker compose -f compose.yaml -f compose.demo.yaml exec backend python -m app.seeds demo
docker compose -f compose.yaml -f compose.demo.yaml exec backend python -m app.cli create-admin
```

Open http://localhost:8080. nginx serves the built SPA and proxies `/api/`
and `/media/` to the backend (one origin). Only nginx (`127.0.0.1:8080`)
and the Mailpit UI (`127.0.0.1:8025`) are published; OpenAPI docs are
disabled. Dev and demo modes share the same database volume.

Stop: `docker compose -f compose.yaml -f compose.demo.yaml down`.

## 5. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `set POSTGRES_PASSWORD in .env` (or another `set … in .env`) | A required variable is empty. Fill it in `.env`. |
| Backend exits with a `JWT_SECRET_KEY` validation error | The secret is shorter than 32 characters. |
| API answers 500 with `UndefinedTable` in the logs | Migrations were not applied: run `alembic upgrade head`. |
| Empty menu, checkout says the restaurant is closed or no payment methods | Seeds were not run (`base`, then `demo`), or it is outside the demo working hours (Asia/Bishkek time). |
| `create-admin` refuses | An administrator already exists, or migrations/`seeds base` were not applied. |
| Sign-in works but session refresh fails with a CSRF error | The browser origin is not in `CSRF_TRUSTED_ORIGINS`. The defaults match `localhost` and `127.0.0.1` on the configured port. |
| Frontend does not reload on file changes (Windows) | Polling is enabled by default in dev mode (`VITE_USE_POLLING`); give it a few seconds. |
| Port already in use | Change the matching `*_HOST_PORT` variable in `.env`. |

Logs: `$DC logs -f backend` (or `worker`, `frontend`). Passwords, tokens and
`initData` are never written to logs.
