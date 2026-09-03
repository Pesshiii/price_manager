---
name: run-price-manager
description: Build, run, and drive the price_manager Django app (web UI + Celery worker) in Docker. Use when asked to start price_manager, bring up the stack, run its tests, take a screenshot of the UI, or interact with the running app (login, search, HTMX filters).
---

price_manager is a Django + HTMX app served by Gunicorn behind Docker Compose (`db`, `redis`, `web`, `celery_worker`). For agent/automated use, drive the running app with the Playwright REPL at `.claude/skills/run-price-manager/driver.mjs` — pipe it commands via a heredoc or tmux `send-keys`.

All paths below are relative to the repo root.

## Prerequisites

- Docker Desktop (or another Docker Engine) running. On Windows, if `docker compose` fails with `failed to connect to the docker API at npipe:...`, Docker Desktop's engine isn't up yet:
  ```bash
  # Windows only, adjust for your platform
  powershell -c "Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe'"
  timeout 180 bash -c 'until docker info >/dev/null 2>&1; do sleep 3; done'
  ```
- Node.js + npm (for the Playwright driver). Verified with Node v25.9.0 / npm 11.12.1.

## Setup

Install the driver's dependency (Playwright) once:

```bash
cd .claude/skills/run-price-manager
npm install
npx playwright install chromium   # downloads the browser binary, ~1-2 min first time
```

### `docker-compose.yml` is now tracked

It used to be excluded by `.gitignore` (`*.yml`), so every clone carried its own broken copy. That rule is gone and the file is in git with four previously-local fixes baked in — `redis.ports` interpolation, `PIM_TOKEN`/`PIM_HOST` placeholders, a correct `ALLOWED_HOSTS`, and `POSTGRES_DB`/`USER`/`PASSWORD` interpolated from `.env`. You should not need to patch it by hand any more; if the stack misbehaves, check the Troubleshooting section rather than editing the compose file.

**`SECRET_KEY` comes from `.env`.** Both `web` and `celery_worker` read `${SECRET_KEY:-django-insecure-dev-only-...}`, deliberately the same value — they share sessions and signed data, and previously ran on *different* keys. `.env` is gitignored; without it you get the insecure dev default, which is fine locally and must never be used in production.

## Build

```bash
docker compose up --build -d
```

First build takes ~15 min (pip install of a large `requirements.txt`). If you hit a stale-container name conflict (`Conflict. The container name "..." is already in use`) from a previous interrupted run:

```bash
docker compose down   # removes containers only — does NOT touch the postgres_data/redis_data volumes
docker compose up -d
```

Wait for the app to actually serve before driving it — gunicorn logs `Listening at: http://0.0.0.0:8000` but Django still runs `migrate`/`collectstatic` first, so poll instead of guessing:

```bash
timeout 60 bash -c 'until curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/admin/ 2>/dev/null | grep -qE "^[23]"; do sleep 2; done'
```

## Run (agent path)

Drive it with the Playwright REPL. It reads `BASE_URL` (default `http://localhost:8000`) and writes screenshots to `SCREENSHOT_DIR` (default `./driver_shots` relative to wherever you launch it from).

```bash
cd .claude/skills/run-price-manager
node driver.mjs <<'EOF'
launch
nav /mainproduct/
login
wait-for text=Главный прайс
fill input[name="search"] Молоток
sleep 1500
screenshot search-result
console --errors
quit
EOF
```

For iterative/interactive use, wrap it in tmux and `send-keys` one command at a time instead of piping a whole heredoc.

### Commands

| command | what it does |
|---|---|
| `launch` | start headless Chromium |
| `nav <path-or-url>` | navigate (relative paths resolve against `BASE_URL`) |
| `wait-for <css-sel>` / `wait-for text=<text>` | wait up to 10s for an element or visible text |
| `screenshot [name]` | full-page PNG → `driver_shots/<name>.png` |
| `click <css-sel>` | click an element |
| `fill <css-sel> <text...>` | fill an input (text is everything after the first space) |
| `press <key>` | keyboard press, e.g. `Enter` |
| `sleep <ms>` | fixed wait — needed for HTMX's debounced/deferred requests (see Gotchas) |
| `text [css-sel]` | print `innerText` of an element (or the whole body) |
| `eval <js-expr>` | evaluate JS in the page, print JSON |
| `url` | print the current page URL |
| `console [--errors]` | print captured browser console messages |
| `login [user] [pass]` | log in via `/accounts/login/`; defaults to `agent_test` / `agent-test-pass-123` (see below) |
| `quit` | close the browser, exit |

### Test account

The app requires login for everything. A real superuser (`radch`) already exists in the dev database but its password is unknown to this skill — **don't try to reset it**. Instead a dedicated throwaway superuser was created for driving:

```bash
docker compose exec -T web python manage.py shell -c "
from django.contrib.auth import get_user_model
U = get_user_model()
u, _ = U.objects.get_or_create(username='agent_test', defaults={'is_staff': True, 'is_superuser': True})
u.set_password('agent-test-pass-123'); u.is_staff = True; u.is_superuser = True; u.save()
"
```

(Already run once against the current `postgres_data` volume — if you're on a fresh volume, re-run it.) The driver's `login` command uses these credentials by default.

## Run (human path)

```bash
docker compose up --build
```

Then open `http://localhost:8000` in a browser. `Ctrl-C` to stop, or `docker compose down` from another terminal (add `-v` only if you intentionally want to wipe the DB/redis volumes — don't do this by default, there is real product/supplier data in `postgres_data`).

## Test

```bash
docker compose exec -T celery_worker python manage.py test <app_label> --keepdb
# e.g.
docker compose exec -T celery_worker python manage.py test product_price_manager --keepdb
```

Verified this command runs correctly end-to-end. Not every app has tests — `core`, for instance, reports "Found 0 test(s)" despite having a `tests.py`.

**Suite health is stale information — re-check before trusting it.** An earlier run of `product_price_manager` recorded 3 errors from a `supplier_manager_currency_name_key` duplicate-key IntegrityError in fixtures plus 1 assertion failure in `test_build_generated_name_includes_all_requested_parts`. That observation predates both a migration-ordering fix and `product` migrations 0002–0005, so it may no longer hold. Run the suite before reporting on its state; don't quote these numbers as current.

## Gotchas

- **HTMX search is debounced, not driven by pressing Enter.** The product search box (`input[name="search"]`, `hx-trigger="input changed delay:0.5s, search"`) fires 0.5s after the value changes via `hx-target="#mainproducts-table"` / `hx-swap="outerHTML"`. After `fill`, you must `sleep` (≥1000ms is safe) before asserting on results — otherwise you'll read stale content and think the filter didn't apply (or worse, match text that was already on the unfiltered page and wrongly conclude it worked).
- **Piped/heredoc stdin to the driver requires sequential command processing.** `readline`'s `'line'` event fires for every buffered line as soon as they're available (which for a heredoc is immediately), so an event-listener-based dispatcher runs `nav`/`click`/etc. before an awaited `launch` finishes. The driver uses `for await (const line of rl)` instead, which only pulls the next line once the current command's promise resolves. If you fork this driver, keep that shape.
- **Django admin autodiscovery imports a live external API client at startup.** `main_product_manager/pim_client.py` does `site = SiteAPI(token=settings.PIM_TOKEN, host=settings.PIM_HOST, ...)` at module import time, and `supplier_product_manager/admin.py` imports it transitively. If `PIM_TOKEN`/`PIM_HOST` are unset, the whole app fails to boot (not just PIM-dependent features) — compose supplies placeholder defaults for exactly this reason.
- **Existing named volumes may not match what `POSTGRES_DB` resolves to.** If someone ran this stack before with a different `POSTGRES_DB`, `docker compose up` against the old volume fails migrate with "database does not exist" — check `docker compose exec -T db psql -U priceuser -d postgres -c "\l"` before assuming your `.env` is right, and don't reach for `docker compose down -v` to "fix" it (that deletes real data).

## Troubleshooting

- **`failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`**: Docker Desktop's engine isn't running (Windows). Launch `Docker Desktop.exe` and poll `docker info` until it succeeds (can take 1-3 min).
- **`invalid hostPort: $6379`**: `docker-compose.yml`'s redis port mapping lost its interpolation — it must read `"${REDIS_PORT:-6379}:6379"`.
- **Django crashes on startup with `pydantic_core._pydantic_core.ValidationError` for `SiteAPI` (`token`/`host` "Input should be a valid string")**: `PIM_TOKEN`/`PIM_HOST` resolved empty. Compose supplies `${PIM_TOKEN:-dummy-token}` / `${PIM_HOST:-http://pim.invalid}`; check whether your `.env` sets either to a blank value, which overrides the default with an empty string.
- **Every page returns HTTP 400 with no visible error body**: `ALLOWED_HOSTS` doesn't include the host you're requesting (`localhost`/`127.0.0.1`). Check `docker compose logs web` for Django's `DisallowedHost` detail.
- **`django.db.utils.OperationalError: ... database "price_manager" does not exist`**: the `postgres_data` volume was initialized with a different `POSTGRES_DB` than what resolves now. Check actual DB names with `docker compose exec -T db psql -U priceuser -d postgres -c "\l"` and align `.env`, rather than assuming — and don't reach for `docker compose down -v`, that deletes real data.
- **You get logged out of the app after pulling these changes**: expected once. `web` previously used a `SECRET_KEY` hardcoded in compose; it now reads `.env`, so pre-existing sessions no longer validate. Log in again.
- **`Conflict. The container name "..." is already in use by container "..."`**: stale containers from a prior interrupted `docker compose up`. Run `docker compose down` (safe — doesn't touch volumes) then `docker compose up -d` again.
- **`node driver.mjs` throws `Error [ERR_USE_AFTER_CLOSE]: readline was closed`**: only relevant if you're editing the driver — happens if you call `rl.prompt()` after stdin EOF has already closed `rl`. The shipped driver guards every prompt call with a `closed` flag; keep that guard if you touch this code.
