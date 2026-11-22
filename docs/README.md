# Project specifications

This folder holds the detailed specifications of the Food Delivery — Osh demo
(one restaurant, one branch; a website and a Telegram Mini App). The
specifications are written in Russian. For an English overview start with the
documents in the repository root:

- [README](../README.md) — what the project does, demo limitations, quick start
- [INSTALLATION](../INSTALLATION.md) · [ARCHITECTURE](../ARCHITECTURE.md) ·
  [DEVELOPMENT](../DEVELOPMENT.md) · [DEPLOYMENT](../DEPLOYMENT.md) ·
  [API](../API.md)

## Documents

| Document | Contents |
|---|---|
| [DECISIONS.md](DECISIONS.md) | Decision log (`DEC-NN`) with revision history. **Has priority** when documents disagree. |
| [TECHNICAL_SPECIFICATION.md](TECHNICAL_SPECIFICATION.md) | Purpose, scope, user roles, functional requirements for the site and the Mini App |
| [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) | PostgreSQL/PostGIS tables, constraints, indexes, order status transitions (§7.1) |
| [API_SPECIFICATION.md](API_SPECIFICATION.md) | REST API `/api/v1`: common contract, error codes, endpoints, access matrix |
| [UI_UX_GUIDELINES.md](UI_UX_GUIDELINES.md) | Design direction and system, screens, Telegram Mini App interface, accessibility |
| [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) | Stages, their scope, tests and current status |

## How these documents are used

- Decisions are recorded in `DECISIONS.md` first; the other documents refer to
  them as `DEC-NN`.
- Open questions (`Q-NN`) are not implemented until they are decided.
- The working rules for the AI assistant used during development (Claude Code)
  are in [`CLAUDE.md`](../CLAUDE.md) at the repository root.
- Dates and stage notes in these documents reflect the development history of
  a demo project; they do not describe a production deployment.
