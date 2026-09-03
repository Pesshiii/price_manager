# AGENTS.md

Instructions for AI coding agents working in this repository.

**Read [CLAUDE.md](CLAUDE.md) first — it is the full guide** (commands, architecture, where the UI lives, conventions, cross-app dependencies). This file exists so agents that don't read `CLAUDE.md` still get the facts that are dangerous to get wrong. Keep the two in sync; `CLAUDE.md` is the source of truth.

## The four things you must not get wrong

**1. `DJANGO_SETTINGS_MODULE` is `price_manager.settings.prod`, not `price_manager.settings`.**
Settings is a package under `price_manager/price_manager/settings/`. Its `__init__.py` is empty — pointing Django at `price_manager.settings` loads no settings at all. `prod.py` star-imports the topic files (`base`, `api`, `project`, `celery`, `databases`, `messages`, `storages`, `third_party`). Edit the topic file that owns the setting; there is no `settings.py`.

**2. The legacy stack is the live system. Build there.**
`core`, `supplier_manager`, `supplier_product_manager`, `main_product_manager`, `product_price_manager` (plus `file_manager`, `blogapp`, `api_auth`, `pim_api`).

**3. The API-driven stack is being retired. Do not build new features there.**
`product`, `pricing`, `supplier`, `supplier_feed`, `dataframe`. The API-first rewrite did not work out. `product` is being recreated as a PIM-linked mirror and reconnected to the legacy stack.

**4. Do not delete the retiring apps or their routes.**
They are still served at `/api/dataframe/`, `/api/supplier-feed/`, `/api/suppliers/`, `/api/pricing/` behind token auth. Whether anything outside this repo consumes them is an **open question** — ask a human before removing any of it.

## Working conventions

- **Docker only.** The local venv is broken. Run tests with `docker compose exec -T celery_worker python manage.py test <app_label> --keepdb`, and management commands with `docker compose exec web python manage.py <command>`.
- **UI strings are Russian** — `verbose_name`, `Meta.verbose_name`, form labels, template copy. Code identifiers and comments stay English.
- **Routes are registered centrally** in `price_manager/price_manager/urls.py`. Only `main_product_manager` and `blogapp` are `include()`d.
- **Always commit migrations.** They are tracked normally.
- **Most of the front end is in `core`** — 102 of 146 templates, and the whole shopping-tab/cart feature in `core/views.py`.
