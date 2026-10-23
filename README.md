# RIM — Lab Equipment Inventory

A web application for tracking lab equipment: what exists, where it is, what condition it is in and who has it. I built it during my internship at a university.

**Stack:** Python 3 · FastAPI · SQLAlchemy 2 · SQLite · Jinja2 · PyJWT (RS256) · vanilla JS / CSS

## Features

- **Item types and instances.** Each instance is a physical item with an auto-generated inventory number (configurable prefix, `INV` by default), price, tags, condition (working / in repair / broken / absent) and lifecycle status (active / written off).
- **Locations.** Warehouse locations and laboratory locations, shown as a location tree.
- **Issuing equipment.** Items can be issued to people and returned, with a full issue history per item and per person.
- **Bulk actions.** Select several instances with checkboxes to issue, return, move, change condition, write off or delete them all at once.
- **People and roles.** Admin and user roles. The first admin is assigned from `FIRST_ADMIN_NICK`, but only while there are no admins yet.
- **Audit log.** Every change is recorded with the user and the time.
- **REST API** under `/api/v1`, with Pydantic schemas for every response.

## Authentication

The app does not store passwords. It works with an external auth service (SSO):

- the user signs in on the auth service and comes back with JWT cookies (access, refresh, info);
- tokens are verified locally with the service's **RS256 public key**, which is cached and re-downloaded when the cache expires;
- an expired access token is refreshed through the auth service;
- the API also accepts `Authorization: Bearer <token>`;
- redirects after login only go to pages on the same site, which blocks open redirects;
- if the auth service is down, the app returns `503` instead of crashing.

## REST API overview

| Resource | Endpoints |
|---|---|
| Current user | `GET /me` |
| Users | `GET /users`, `GET /users/{id}`, `/users/{id}/instances`, `/users/{id}/issues` |
| Item types | `GET`, `POST /item-types` · `GET`, `PATCH`, `DELETE /item-types/{id}` |
| Instances | `GET`, `POST /instances` · `GET`, `PATCH`, `DELETE /instances/{id}` · `/instances/{id}/issues` |
| Bulk operations | `POST /instances/issue`, `/return`, `/move`, `/condition`, `/write-off`, `/delete` |
| Locations | `/lab-locations`, `/warehouse-locations` (CRUD) |
| Audit | `GET /audit` |

## Project structure

```
app/
├── auth/           # Auth provider interface, external JWT implementation, middleware
├── models/         # SQLAlchemy models
├── repositories/   # Database queries
├── services/       # Business logic (inventory, locations, users, audit)
├── routers/        # HTML pages + REST API (/api/v1)
├── schemas/        # Pydantic schemas for the API
├── templates/      # Jinja2 templates
├── static/         # CSS and JS for bulk actions
├── utils/          # Formatting, inventory numbers, tags
└── config.py       # Settings from environment variables / .env
```

## Running

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py            # http://127.0.0.1:8010
```

Configuration is done through environment variables or a `.env` file:

| Variable | Default | Purpose |
|---|---|---|
| `AUTH_BASE_URL` | `http://127.0.0.1:8000` | Address of the auth service |
| `DATABASE_URL` | `sqlite:///data/app.sqlite3` | Database connection |
| `FIRST_ADMIN_NICK` | `admin` | Nickname that becomes the first admin |
| `HOST` / `PORT` | `127.0.0.1` / `8010` | Where the server listens |
| `COOKIE_SECURE` | `false` | Set to `true` behind HTTPS |

You need a running auth service that issues RS256 JWTs and serves its public key at `/keys/public` to sign in.
