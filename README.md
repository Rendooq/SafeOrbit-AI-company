# SafeOrbit

## Current redesign

### Readable light and black themes

The header's moon/sun button toggles **Чорна тема / Світла тема** on the home,
login, registration and workspace. It saves `safeorbit-theme` in localStorage,
restores before the first paint and synchronizes other tabs on the same origin.
`static/v2/theme.css` is the final semantic override for old light-text rules:
tabs, buttons, tables, labels, fields, statuses, dialogs and charts.

The local app on **8001 was restarted** to load this update. A different running
process on 8000 may still have earlier Python code; use 8001 or restart your
normal server before expecting a newly added header switch.

Open **http://127.0.0.1:8001/** for the radical charcoal/orange redesign.
The old listener on 8000 could not be stopped because Windows denied access.
The new local `main:app` instance uses the existing DB; startup schedulers are
disabled there to avoid duplicating the original server's background jobs.
See `REDESIGN.md` for the verified runtime state and normal single-server startup.

FastAPI CRM application with multi-tenant API, appointments, integrations, and
background notifications.

## Local development (PowerShell)

Run from `G:\SafeOrbit`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

After updating the Python files, restart the running server. For local editing
only, add `--reload`; do not use reload in production.

## B2B SaaS frontend

The earlier green theme below was superseded by `static/v2/`: a new marketing
homepage, orange/charcoal auth and workspace designs, local Manrope fonts, and
recomposed dashboard. Business/data contracts remain unchanged.

- `/login`, `/register`, and activation-status pages use cached, autoescaped
  Jinja templates. Native forms work without JavaScript.
- Auth pages load only local CSS and 4.4 KB of progressive-enhancement JS.
  They do not load Bootstrap, Chart.js, Google Fonts, or a CDN.
- The workspace uses a light, responsive green/neutral theme, tenant navigation,
  mobile sidebar, keyboard navigation search (`Ctrl/Cmd K`), and live dashboard
  metrics (no fabricated production statistics).
- Existing calendar, creation forms, edit modals, and role navigation remain.
  Dashboard history is bounded; calendar requests support a bounded date range.
- Bootstrap, Chart.js, FullCalendar, SweetAlert2, and Font Awesome are pinned and
  served locally. Licenses/upstream repositories are in `static/vendor/NOTICE.md`.
- Gzip is enabled; static assets have ETag/cache headers. Tenant/auth HTML is
  `private, no-store`. Version strings on assets must change when releasing edits.
- Expensive password hashing runs in a threadpool instead of blocking the event
  loop. Registration uploads have bounded size and validated PDF/PNG/JPEG
  signatures; client filenames are not used as filesystem paths.
- Registration still requires the existing receipt, signed NDA, and signed
  contract; plan availability/discounts and payment details come from settings.
- Six additive SQL indexes are applied on startup (`checkfirst=True`). Large
  production PostgreSQL installations should create equivalent indexes
  concurrently during a maintenance window instead of startup.
- Rust was not introduced: measurements identified HTML duplication, blocking
  work, repeated third-party resources, and DB access patterns, not a template
  rendering CPU bottleneck.

### Isolated visual preview

```powershell
$env:PYTHONPATH = "G:\SafeOrbit;G:\SafeOrbit\tests"
.\.venv\Scripts\python.exe -m uvicorn preview_server:app --host 127.0.0.1 --port 8011
```

This is a **synthetic, in-memory preview**, not the real workspace. Routes:
`/login`, `/register`, `/__preview/workspace`,
`/__preview/mobile?view=login`, and `/__preview/mobile?view=workspace`.
Never deploy `tests/preview_server.py` or expose it beyond loopback.

Reproduce frontend measurements:

```powershell
$env:PYTHONPATH = "G:\SafeOrbit;G:\SafeOrbit\tests"
.\.venv\Scripts\python.exe tests\benchmark_frontend.py
```

The benchmark writes `qa/performance.json`. These are warm in-process timings,
not network latency, production capacity, or a substitute for load testing.

The existing `.env` is read from the project directory, not the terminal's
current directory. When `DATABASE_URL` is absent, `local.db` is created in the
project directory. `/` and `/login` both serve the login page.

Do not commit `.env`, database files, uploads, or session secrets.

## Authentication configuration

- Set `SECRET_KEY` to a private, high-entropy value.
- With `ENVIRONMENT=production` (or `prod`), an absent or known-default session
  secret causes startup to fail, and session cookies require HTTPS.
- For local development without `SECRET_KEY`, the application creates a
  persistent, ignored `.session-secret` file. Keep it private.
- No admin account with a built-in password is created automatically.
  To provision a new admin deliberately, set `BOOTSTRAP_ADMIN_PASSWORD` and,
  optionally, `BOOTSTRAP_ADMIN_USERNAME` (default `admin`). This only creates a
  missing account; it does not reset existing credentials. Remove the bootstrap
  password from the deployment environment after provisioning.
- `/login-demo` opens an isolated CRM workspace with sample data. Demo edits expire after one hour of inactivity and are stored only in the serving process. Deploy with a single worker or sticky sessions for consistent demo access.
  Leave this disabled for real customer data.
- Existing accounts and password hashes are preserved. New password hashes
  prehash with SHA-256 before bcrypt, avoiding bcrypt's 72-byte input limit.
- Existing default-password/admin or demo accounts are **not** deleted or reset
  by these fixes. Audit them before exposing an existing installation.

## API changes

- `/api/v1/health` and `/api/v1/webhooks/events` require valid tenant API
  credentials. Health checks also accept an authenticated tenant session.
- Deactivated businesses cannot use saved sessions or API keys.
- Appointment customer/master IDs must belong to the authenticated business.
- `Idempotency-Key` is scoped to the business and appointment-create operation.
  A retry returns the full original response. A changed payload returns `409`.
  Reservations expire after the existing one-hour lifetime. The appointment
  and response reservation commit in the same transaction.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe test_syntax.py
.\.venv\Scripts\python.exe -m pip check
```

Tests use a separate in-memory SQLite database, replace background loops and
outgoing webhooks with local mocks, and use dummy credentials. They do not
connect to the database in `.env`, send messages, or call AI services.

See `QA_REPORT.md` for the scope and limitations of the latest verification.
