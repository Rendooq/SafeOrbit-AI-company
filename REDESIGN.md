# SafeOrbit — radical redesign, 2026-11-21

## Open the new version

**http://127.0.0.1:8001/**

This is `main:app`, using the project's existing environment/database configuration,
not the synthetic preview. Verified `/`, `/login`, `/register` return 200 and
`data-design="radical-v2"`. Existing `.env`, credentials and business data were not
edited by this redesign.

Port **8000 still serves an old Python process**. Its listener was verified as
SafeOrbit before attempting to restart it; Windows returned “Access denied” on
`Stop-Process`. No privilege bypass was attempted. Use 8001 to see this release.

The second instance was started with `--lifespan off` to avoid duplicate
background schedulers and startup migrations while the original server is still
running. It is a local transition arrangement, not a production deployment.
When the original process is stopped, start one normal instance without
`--lifespan off`:

```powershell
cd G:\SafeOrbit
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Process metadata and output are in `qa/radical-live-process.json`,
`qa/radical-live-stdout.log`, and `qa/radical-live-stderr.log`.

## Replaced

- New public homepage: large editorial hero, original SVG product illustration,
  feature sections, call-to-action, new navigation/footer.
- New orange brand mark; only the SafeOrbit product name is retained from the
  earlier visual direction.
- Charcoal/orange/white palette and locally hosted Manrope typography.
- Login/register/activation layouts replaced, including the dark manifesto
  panel, forms, controls, document upload and payment sections.
- Workspace dark navigation, new dashboard hero, metric composition, chart,
  status distribution, team and recent-record layout.
- Shared component theme changes cards, fields, tables, modals, calendars and
  buttons across the existing business routes.

Native form contracts, access checks and real data are retained. Some specialized
legacy pages still generate their own inline feature markup; this is not a claim
that every business screen was rewritten from scratch.

## Verification

- **39 tests passed**, Python syntax check: **38 files**.
- JavaScript checks and `pip check` passed.
- Desktop home/auth/workspace visual checks.
- Mobile home checked at a 390px embedded viewport.
- Synthetic appointment edit/save confirmed after theme replacement.
- Real-server home → login navigation confirmed; no real credentials submitted.
- Font license included at `static/v2/FONT-LICENSE`; origin in
  `static/v2/NOTICE.md`.

Source backup: `.backups/radical-redesign-20261121-213755`.
No external deployment, Rust service, database-provider change, or edits to
other projects.
