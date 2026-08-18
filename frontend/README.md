# BanK frontend

A minimal Flask starter — page structure and a couple of worked examples,
not a finished UI. Whoever builds the real frontend can keep extending
this, replace it with a JS framework, or start over; nothing in the
backend assumes Flask specifically. What the backend *does* assume is
documented below, and that part matters regardless of what this folder
ends up looking like.

## How auth works here (read this first)

The backend (`../backend`) uses **cookie-based sessions**: after logging
in, the browser holds an `HttpOnly` cookie and sends it automatically on
every request. That has one big consequence for how this frontend is
built:

**The browser must call the FastAPI backend directly** (`fetch(...,
{credentials: "include"})`), not through a server-side proxy in Flask.
Flask here only renders page shells and static assets — it never sees or
forwards the session cookie itself. See `templates/base.html`'s
`apiFetch()` helper, which every page's inline script uses.

This means the backend's `CORS_ORIGINS` setting must include this app's
origin (already set up — `backend/.env.example` lists
`http://localhost:5000` alongside `:3000`, with `allow_credentials`
turned on). If you change this app's port or replace it with something
else, that setting needs to grow too, or every request will fail with an
opaque CORS error before it even reaches the API.

If you'd rather do a server-side proxy (Flask forwards the cookie itself,
managing its own session) instead of calling the API from the browser,
that's a reasonable alternative architecture — just know it's a
deliberate change from what's scaffolded here, not a small tweak.

## Running it

```bash
# 1. Start the backend first (separate terminal)
cd ../backend && ./start.sh

# 2. This app
cd frontend
python -m venv .venv
.venv/Scripts/activate        # .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Visit `http://localhost:5000`. Register an account, then `/accounts` is the
fullest worked example of a data page — it calls the real backend and
renders the list (or a "please log in" state if your session expired).

## What's scaffolded vs. what's TODO

| Page | Status |
|---|---|
| `/` | Static placeholder |
| `/register` | **Working**: creates an account and logs you in |
| `/login` | **Working** |
| `/accounts` | **Working example**: calls `GET /accounts`, renders the list, handles 401 |
| `/transfers` | Stub with comments only — follow the accounts.html pattern |

Auth is fully live now (`/auth/register`, `/auth/login`, `/auth/logout` —
see the reference below). Registration requires a valid Romanian national
ID (CNP) — the backend checks the real checksum, not just that it's 13
digits.

## API reference

Base URL: `http://localhost:8000/api/v1` (interactive, always-current docs
at `http://localhost:8000/docs`). All money amounts are integer **minor
units** (cents) — `1250` means `$12.50`, never a float.

Every error response has the same shape:
```json
{ "error": { "code": "insufficient_funds", "message": "..." } }
```

### Accounts

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/accounts` | `{name, currency}` | `201` account |
| GET | `/accounts` | — | `200` list of accounts |
| GET | `/accounts/{id}` | — | `200` account |
| POST | `/accounts/{id}/close` | — | `200` account (fails `409` if balance isn't zero) |
| GET | `/accounts/{id}/transactions` | query: `date_from`, `date_to`, `limit`, `offset` | `200` list of ledger entries |

Account shape:
```json
{
  "id": "uuid", "name": "Checking", "currency": "USD",
  "status": "active", "balance_minor": 12500,
  "created_at": "2026-01-01T00:00:00Z"
}
```

### Transfers

Between two accounts **owned by the same logged-in user** (moving your own
money between your own accounts — sending to someone else is a different,
not-yet-built feature).

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/transfers` | see below, **requires `Idempotency-Key` header** | `201` transfer |
| GET | `/transfers` | — | `200` list |
| GET | `/transfers/{id}` | — | `200` transfer |

```json
// POST /transfers request body
{
  "from_account_id": "uuid", "to_account_id": "uuid",
  "amount_minor": 2500, "currency": "USD", "description": "optional"
}
```

The `Idempotency-Key` header must be a unique string per logical transfer
attempt (a `crypto.randomUUID()` generated once per form submission, and
**reused on retry** of that same submission — never a new one per retry,
or the whole point of it is lost). Submitting the same key twice returns
the original result instead of moving money again — that's what makes it
safe to retry a failed request without double-charging.

### Users

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/users/me` | — | `200` current user |
| PATCH | `/users/me` | `{first_name?, last_name?, phone?, address?}` | `200` updated user |

User shape:
```json
{
  "id": "uuid", "email": "jane@example.com",
  "first_name": "Jane", "last_name": "Doe", "email_verified": false,
  "national_id": "1234567890123", "gender": "F", "date_of_birth": "1990-01-01",
  "phone": null, "address": null, "created_at": "2026-01-01T00:00:00Z"
}
```

### Auth

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/auth/register` | see below | `201` user, sets session cookie (auto-login) |
| POST | `/auth/login` | `{email, password}` | `200` user, sets session cookie |
| POST | `/auth/logout` | — | `204`, clears session cookie |

```json
// POST /auth/register request body
{
  "email": "jane@example.com", "password": "at least 8 chars",
  "first_name": "Jane", "last_name": "Doe",
  "national_id": "1234567890123",
  "phone": "optional", "address": "optional"
}
```

`national_id` must be a structurally valid Romanian CNP (13 digits,
correct checksum) — `gender` and `date_of_birth` are derived from it
automatically, don't send them separately. Login failures always return
the same generic `401` message regardless of whether the email exists or
the password is wrong (avoids leaking which accounts exist); after 5
failed attempts for the same email within 15 minutes, login returns `429`
(`login_rate_limited`) even for the correct password until the window
passes.
