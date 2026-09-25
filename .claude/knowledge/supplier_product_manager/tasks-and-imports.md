---
title: Tasks and imports — the convention exceptions
summary: The known task convention exception and the one live exception to "import up, not down".
code: price_manager/supplier_product_manager/tasks.py, price_manager/supplier_product_manager/models.py
---
# Tasks and imports — the convention exceptions

## Tasks — the known convention exception

`process_supplier_file_import` (`tasks.py:138`) runs through
`execute_locked_task` with a lock **per setting**
(`supplier_import:setting:<pk>`, `IMPORT_LOCK_TTL_SECONDS`, `tasks.py:39`) and
`atomic=False` — `load_setting` commits the data in its own transaction, and
the run, file status and notification must be written whatever happens. A
second import of a busy setting (double click, a new file uploaded mid-import)
is not started: the user gets «уже импортируется» (`_refuse_busy`,
`tasks.py:174`), a confirmed run goes back to pending, and a queued file
nobody will read is marked `ERROR`. The import is started only by POST
(`setting_upload`, `views.py:217`; `load_partial.html` uses `hx-post`).

The other three `@shared_task`s still work **inline**: `process_setting_upload`
(`tasks.py:379`, a compatibility alias of the import), `cleanup_supplier_files_task`
(`tasks.py:384`), `copy_supplier_products_to_main_task` (`tasks.py:458`). This
is pre-existing and documented as a known exception in the convention
reviewer — do not report it as a new finding, but **new** tasks here should
route through it.

**An applied import refreshes the catalog** (`schedule_catalog_refresh`
`tasks.py:348` → `refresh_catalog_after_import` `tasks.py:362`): on commit, if
no refresh is pending (`CATALOG_REFRESH_PENDING_KEY` via `cache.add`), one is
queued with a 60 s countdown, so a series of imports shares one refresh. It
runs `update_stocks` then `update_prices` through `execute_locked_task` under
the **beat tasks' lock names** (`main_product_manager.update_stocks/_prices`),
so it never overlaps a beat run; a step that finds the lock held retries the
task (up to `CATALOG_REFRESH_RETRIES` = 3×, 60 s) — the running beat pass may
have started before the import committed. The pending key is cleared *before*
the refresh runs, so an import committed during it queues the next one.
`on_commit` also keeps tests from enqueueing into the real broker (the suite
has no eager mode).

**Freshness per setting** (settings table): `SettingList.get_queryset`
(`views.py:496`) annotates `last_applied_at`, `maps_stock`, `maps_prices`.
After a failed or pending last run the cell adds «данные от dd.mm»;
`tables.setting_overdue` (`tables.py:130`) flags a setting whose last applied
import is older than the supplier's `stock_update_days`/`price_update_days`
for what it maps (the smaller). The supplier-level `update_status` cannot
show this: any of its settings moves the supplier's dates, so a frozen second
setting hides behind a working first.

The mapping screen (`SettingUpdate.form_valid`, `views.py:388`) is
`@transaction.atomic`: it saves the mapping by deleting every `Link` and
recreating it, and a failure halfway used to leave the setting with no mapping.

`copy_supplier_products_to_main_task` (`tasks.py:458`) is the bridge into
[[main_product_manager]]; it records a `CopySupplierProductsToMainRun` row
(`models.py:419`) with `processed_count` / `created_count` /
`updated_links_count`, restores a saved filter via `_restore_querydict`
(`tasks.py:434`) and batches with `_chunked` (`tasks.py:446`). Since Phase 2b-2 it
copies nothing but the row itself: `MainProduct` lost `manufacturer`,
`description` and `categories`, and `SupplierProduct` lost `category` and
`manufacturer`. What it still does besides creating rows is **link them to
`product.Product` — explicitly**, via [[main_product_manager]]'s
`link_to_local_products(ids)`: one lookup and one bulk update per chunk,
existing Products only (`number=sku`), never creates one. Before 2b-2 the link
was a side effect of rebuilding `MainProduct.search_vector`; dropping the
vector without this step would have left every imported row with `product IS
NULL`, invisible on `/products/` until the nightly `reindex_pim_ids`, with no
error. For a brand-new row the matching `Product` usually doesn't exist yet
(its `sku` was just computed), so the step mostly helps rows whose `Product`
appeared since; creating Products stays reindex's job
(`link_unlinked_main_products`, which is unscoped and table-wide).

## Imports — the "up, not down" rule has one live exception

`models.py` imports `MainProduct` (`main_product_manager.models`) and
`Supplier`/`Discount` (`supplier_manager.models`) — that direction is clean,
and `main_product_manager/models.py` does not import anything from this app.

**But `main_product_manager/utils.py` does:
`from supplier_product_manager.models import SupplierProduct`** — used by
`update_stocks()` (`main_product_manager/utils.py:457-480`) to read the most
recently updated `SupplierProduct` per product. This is a real import back
down, not a stale claim to prune: it works because `utils.py` imports
`.models` (`MainProduct`, already loaded) before reaching into
`supplier_product_manager.models`, and `supplier_product_manager/tasks.py:11`
completes the loop the other way
(`from main_product_manager.utils import compute_supplier_sku,
link_to_local_products, update_stocks`). So the two apps are mutually
dependent through `utils.py` specifically — do not assume "main_product_manager
never imports this app" when touching either side.

`main_product_manager/pim_client.py` instantiates `SiteAPI(token=…,
host=…)` at module import — per CLAUDE.md, unset `PIM_TOKEN`/`PIM_HOST` breaks
whatever imports it. Within this app that is **not** `admin.py` (checked: it
only imports `.models` and `.functions`, neither of which reach
`main_product_manager.utils`/`pim_client`) — it is `views.py:49`
(`from .tasks import ...`) → `tasks.py:11`
(`from main_product_manager.utils import ...`) → `main_product_manager/utils.py`
(`from .pim_client import site`). So loading `views.py` (which Django's URL
conf does at startup) is what fails, not the admin site specifically.
