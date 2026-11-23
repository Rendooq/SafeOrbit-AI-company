## 2026-11-23 · Release verification

- Demo language selection verified in Edge at 390 px in Ukrainian, English, Russian, Polish, and Simplified Chinese. The selected language persisted after navigation and refresh. Reports, client search, sign-in, registration, theme labels, and translated FAQ search were checked.
- Opened 11 owner routes and two superadmin routes with synthetic data. Replaced unsupported sales and security claims in the old FAQ with eight guides tied to existing workflows.
- Fixed chat preview rendering and restricted replies to existing conversations in the same business. Product image names are generated server-side and file content and size are checked before storage. Fixed the public widget API's booking overlap check against existing service durations.
- 60 tests passed. Coverage includes SQL query isolation, authentication, CSRF, private document access, SSRF controls, demo isolation, and the new chat, upload, and booking regressions. 44 Python files passed syntax validation.
- Reviewed raw SQL use. Startup DDL is fixed SQL, the startup data update is parameterized, and application request filters use ORM expressions. Verified the configured PostgreSQL connection and a bound text parameter in a read-only transaction. Application regression writes used isolated SQLite data.
- Bandit recorded 12 low-severity findings and zero medium or high findings. pip-audit reported no known advisories across 49 resolved packages. pip check passed.
- Release validation remains incomplete for public HTTPS operation, concurrent PostgreSQL mutations and bookings, restore from backup, and live payment, messaging, and third-party CRM integrations. Browser checks cover the flows above and do not establish complete translation coverage of every integration response or legacy page state.

# SafeOrbit — verification, 2026-11-21

## Latest: contrast repair and black theme

- Reproduced the reported superadmin white-on-white nav pills.
- Added a final semantic token layer covering light/dark surfaces, active/inactive
  tabs, primary/outline buttons, labels, placeholders, form values, tables,
  status colors, modals, alerts, calendar and legacy inline white-text colors.
- Added header theme button on public/auth/workspace pages, localStorage
  persistence, early initialization and cross-tab synchronization.
- Excluded the dynamic theme control from the translation system so its title
  and accessible state do not revert after switching.
- Feature CSS now loads before the final theme sheet. Chart tick/grid colors
  follow theme tokens.
- **41 tests passed**, 38 Python files parsed, JS syntax/dependencies passed.
- Added WCAG AA ratio tests (at least 4.5:1) for semantic body text, muted text
  and accent-on-soft backgrounds in both themes. This tests shared tokens,
  not a complete accessibility certification of every legacy element.
- Browser checked superadmin tabs/business-profile controls in light and black
  themes, saved state after navigation, dark workspace/edit dialog, real login.
- Evidence: `qa/superadmin-contrast-light.png`,
  `qa/superadmin-contrast-dark.png`, `qa/theme-login-dark.png`.
- Restarted **only the chat-owned application on 8001**; current home/login/
  registration return the theme scripts and final stylesheet.
- Source backup: `.backups/contrast-themes-20261121-222251`.
- Existing `.env`, database contents and unrelated projects untouched.

## Latest: radical visual replacement

See `REDESIGN.md`. New real application verified at
**http://127.0.0.1:8001/**, marker `data-design="radical-v2"`.
**39 tests passed**, 38 Python files parsed, JS/dependency checks passed.
New homepage/auth/workspace, orange-charcoal-white palette, original SVG brand
and product illustration, locally served Manrope font with OFL license.
Desktop/mobile visuals and synthetic record edit/save verified.

Port 8000 is still the old process: Windows denied permission to stop it.
New instance starts with lifespan disabled while that process remains, avoiding
duplicate background work. No existing DB data, `.env`, passwords or other
projects were modified for this pass. No production/perfectness claim.

## Latest: SaaS redesign and performance pass

Scope: only `G:\SafeOrbit`. Source backup:
`.backups/saas-redesign-20261121-183000` (check the directory list for the exact
timestamp if moved). Existing `.env`, real database, existing account passwords,
and prior stored uploads were not edited. No deployment and no database-provider
switch. The running real server was not restarted during isolated QA.

### Implemented

- Original, responsive B2B login/registration/activation pages; semantic form
  labels, visible focus, show-password buttons, native form fallback, reduced
  motion, and two-step registration.
- Light workspace shell, persistent role navigation, mobile menu, quick page
  search, dashboard cards/charts/recent records/team, and functional legacy
  calendar/modals/forms.
- Server-side escaping for untrusted business/customer/master/service names;
  safe JSON chart labels and calendar DOM strings.
- Local pinned frontend packages with MIT/OFL/CC BY license notices.
- CSS/JS extraction, duplicate page script removal, conditional chart/calendar
  dependencies, Gzip, Windows-safe cache path normalization, ETags and privacy
  headers; strict same-origin asset/form policy on auth pages.
- Threadpool password hashing/checking, bounded login/registration throttling,
  normalized phone login, atomic account creation, unique document filenames,
  file signatures/limits, document cleanup on failure, background notifications.
- Registration preserves payment-country settings, plan availability,
  promotion/discount storage and the signed-document contract.
- Activation status requires the pending business ID in the signed session.
- Corrected monthly metrics that counted future months, bounded calendar month
  queries, tenant/status/date indexes, workspace appointment assignment checks
  and limited-master edit guards.
- Browser-discovered fixes: registration `us_swift` model mismatch, missing
  creation-modal target, collapsed-details modal ancestry, light modal contrast,
  early toast execution before `body`, floating preference-switch placement.

### Verification

- **37 tests passed**; **38 Python files** parsed; JS syntax checks passed.
- `pip check`: no broken requirements.
- Desktop browser checks: login, registration step navigation, workspace,
  quick navigation dialog, reveal new-record form, edit/save synthetic record.
- Responsive visual checks: 390px login and workspace.
- Browser preview uses only synthetic, in-memory SQLite data and dummy auth.
- Visual evidence saved in `qa/login-desktop.png`, `qa/workspace-desktop.png`,
  and `qa/workspace-mobile.png`.
- Existing server on port 8000 still returned the old login at final check;
  restart that process to load new Python code. Local-only synthetic preview
  was opened at `http://127.0.0.1:8011/login`.

### Measured, reproducible

`tests/benchmark_frontend.py`, 100 sequential warm ASGI requests, in-memory DB:

| Measurement | Result |
|---|---:|
| Shared workspace shell HTML | 63,005 → 5,496 bytes (**−91.3%**) |
| Duplicated page scripts | 2 → 1 |
| Login HTML | 6,190 bytes; 2,274 bytes gzip |
| Registration HTML | 12,675 bytes; 4,101 bytes gzip |
| Auth JS | 4,380 bytes |
| Login p50 / p95 | 0.379 / 0.534 ms |
| Registration p50 / p95 | 1.83 / 2.271 ms |

These are local processing measurements, not internet page loads or a claim
that the application is “perfect.” Network/production DB latency still matters.

### Remaining production requirements

- Real PostgreSQL/external integration/load testing and broader CRM/superadmin
  UI coverage are still needed. No Rust service or Neon migration was performed.
- Existing legacy pages contain additional inline scripts/styles; the modern
  shell is not a complete rewrite of every CRM feature.
- Throttling is process-local; multiple instances need Redis/shared limits.
- Document file signatures are not virus scanning. Existing uploads remain under
  static URLs; sensitive documents need authorized delivery/private storage.
- Existing timezone conventions and SQLite/PostgreSQL differences need a
  dedicated migration rather than silent conversion.
- Large production index creation should be managed with PostgreSQL concurrent
  migrations to avoid startup lock duration.
- 36 pre-existing deprecation warnings remain.

---

## Earlier stability pass

## Scope

Work performed only in `G:\SafeOrbit` after the project-location correction.
No edits to the existing `.env`, production database, existing user credentials,
or stored uploads. Original edited files were backed up within this project:
`.backups/20261121-174649`.

## Fixed

1. Clean dependency installation was missing `greenlet`, causing SQLAlchemy
   asyncio initialization to fail. Requirements now use `sqlalchemy[asyncio]`.
2. `/login` was missing although redirects pointed there.
3. Static files, dotenv loading, and SQLite fallback depended on the caller's
   working directory. Paths now resolve from the application directory.
4. Startup created a superadmin with a public hardcoded password. Provisioning
   now requires an explicit bootstrap password; existing accounts are untouched.
5. Demo access/account creation is now opt-in.
6. Known-default session secrets are rejected in production; local fallback
   uses a persistent random secret. Production cookies are HTTPS-only.
7. Login clears pre-existing session state.
8. Disabled businesses no longer authenticate via saved sessions;
   disabled businesses no longer authenticate with API keys.
9. Appointment idempotency no longer tries to serialize raw datetime objects.
10. Idempotency keys no longer collide across businesses.
11. Idempotent retries return the complete original response rather than just
    `id`/`status`.
12. Failed validation no longer commits a reservation before resource creation;
    the resource and completed reservation now commit atomically.
13. Expired reservations can be reused, using UTC expiry comparisons.
14. Appointment creation/update validates master and customer tenant membership.
15. Null updates to required appointment fields return a client error rather
    than failing database constraints.
16. Long/Unicode passwords work with current bcrypt while legacy bcrypt hashes
    still verify.
17. The syntax-check script no longer exits on import and checks all source
    modules instead of only `main.py`.
18. Periodic tasks are retained, canceled, and awaited on shutdown; the engine
    is disposed.
19. Webhook dispatcher awaits its child delivery tasks rather than detaching
    unowned tasks.
20. API health and incoming webhook routes now require tenant authentication;
    database health reports `degraded` on a failed query.
21. Removed invalid wildcard-origin/credentialed-CORS combination. Same-origin
    session requests remain supported.

## Verified

- **21 regression tests passed**, including full startup/shutdown with mocked
  periodic loops; `/`, `/login`, a real static image, and OpenAPI responses.
- Syntax check: **32 Python files**.
- `pip check`: **No broken requirements found**.
- Import/static-path verification from a different directory.
- In-memory API create/update/replay, tenant-isolation, expiry, invalid-input,
  disabled-key/session, password, and production-secret tests.

## Limitations / remaining risks

- Corrected the later reported login regression: `User` has no mapped
  `is_active` field. Session authentication checks business activity only.
  The original test incorrectly attached a transient Python attribute to a
  cached ORM object; the replacement verifies users loaded in a fresh session.

- This is not a claim that every bug in the application has been found.
- PostgreSQL-specific SQL/migrations, real concurrent PostgreSQL idempotency
  races, AI providers, mail, Telegram, payments, and external webhooks have not
  been exercised against live services.
- SQLite does not reproduce every PostgreSQL datetime/locking behavior.
- Full browser/UI flows and all CRM/superadmin routes still need broader
  integration coverage.
- 36 deprecation warnings remain, primarily existing Pydantic class-based
  configuration, FastAPI `on_event`, and `datetime.utcnow` usage.
- Existing installations may still contain old default-password/admin/demo
  accounts. These were deliberately not altered; audit them before deployment.
- Existing unscoped idempotency rows are not migrated and will not replay under
  the new scoped keys.
- API consumers relying on unauthenticated health/webhook access must provide
  credentials. Production requires an explicit private session secret.
