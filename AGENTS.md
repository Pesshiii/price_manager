# AGENTS.md

Instructions for AI coding agents working in this repository.

**Read [CLAUDE.md](CLAUDE.md) first — it is the full guide** (commands, architecture, where the UI lives, conventions, cross-app dependencies). This file exists so agents that don't read `CLAUDE.md` still get the facts that are dangerous to get wrong. Keep the two in sync; `CLAUDE.md` is the source of truth.

## The four things you must not get wrong

**1. `DJANGO_SETTINGS_MODULE` is `price_manager.settings.prod`, not `price_manager.settings`.**
Settings is a package under `price_manager/price_manager/settings/`. Its `__init__.py` is empty — pointing Django at `price_manager.settings` loads no settings at all. `prod.py` star-imports the topic files (`base`, `project`, `celery`, `databases`, `messages`, `storages`, `third_party`). Edit the topic file that owns the setting; there is no `settings.py`.

**2. The legacy stack is the live system. Build there.**
`core`, `supplier_manager`, `supplier_product_manager`, `main_product_manager`, `product_price_manager` (plus `file_manager`, `blogapp`, `developers`, `releases`, `pim_api`).

**3. `product` is the PIM-linked mirror on top of it.** Recreated from the failed API-first rewrite, it is now the root of search and filtering, served at `/products/` — see `.claude/shift-to-product-brief.md`. Build there when the work serves that shift.

**4. The API-first stack is gone — do not bring it back unasked.**
`pricing`, `supplier`, `supplier_feed`, `dataframe`, `api_auth`, the `/api/` mount and DRF were removed; `product.0018` drops their tables. Suppliers are only `supplier_manager.Supplier`. To remove an app, cut every migration dependency on it and drop its tables in a migration (as `product.0015`/`0018` do), never just delete the directory — see CLAUDE.md.

## Working conventions

- **Docker only.** The local venv is broken. Run tests with `docker compose exec -T celery_worker python manage.py test <app_label> --keepdb`, and management commands with `docker compose exec web python manage.py <command>`.
- **UI strings are Russian** — `verbose_name`, `Meta.verbose_name`, form labels, template copy. Code identifiers and comments stay English.
- **Routes are registered centrally** in `price_manager/price_manager/urls.py`. Only `main_product_manager` and `blogapp` are `include()`d.
- **Always commit migrations.** They are tracked normally.
- **Each app has a knowledge keeper.** Consult `<app>`'s keeper agent before working in it (e.g. `core-keeper`, `main-product-keeper`), and record what you learn back with `/record-insight <app>`. Notes live in `.claude/knowledge/<app>/`, one file per topic; start from `.claude/knowledge/README.md` (generated — never edit it) and `glossary.md` for Russian UI terms. See CLAUDE.md for the full table.
- **Most of the front end is in `core`** — 81 of 123 templates, and the whole shopping-tab/cart feature in `core/views.py`.
- **`backups/` holds production dumps.** Use the `prod-snapshot` skill; never restore over `price_manager_db`; never let a dump-derived value reach a commit, issue or Telegram message. They are for investigation, not for tests — `backups/` is gitignored, so CI cannot see them and a test that needs one fails there.
