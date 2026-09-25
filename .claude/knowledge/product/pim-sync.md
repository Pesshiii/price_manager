---
title: Syncing content from PIM
summary: sync_product_from_pim, the production backfill, the phantom-field trap, load_pim_mirror.
code: price_manager/product/services/pim_sync.py, price_manager/product/tasks.py
---
# Syncing content from PIM

## Sync path — `sync_product_from_pim(pim_id, data=None)` (`services/pim_sync.py:101-144`)

`pim_id` here is a **PMP id** (see [[product/pim-link]]), not a PIM `Product` id.

- **Local row lookup** (`:120-133`): the `Product` already holding `pim_id` →
  else the `Product` whose `number` equals the PMP's `number` (matched
  `iexact`) and whose `pim_id` is still `NULL` adopts it → else a new
  `Product(number=...)`.
- **`data`** is the PIM `Product` reached through the PMP's `productId`
  (`_fetch_pim_product`, `:34-36`), fetched unless passed in.
- **Writes:** `name`, `raw_data`, `brand` (via `_ensure_pim_brand`,
  `:81-98` — matched on `brandId`, never `brandName`, for the same
  fork-on-rename reason as the `Brand` model itself; updates the local
  `Brand.name` in place when PIM's `brandName` changed), categories (via
  `categoriesIds` → `_ensure_pim_category`), then `rebuild_search_vector()`
  (**after** `save()` — the rebuild does an `update()` by `pk`, which a
  brand-new row doesn't have yet). **Never `number`** — PIM staff can link a
  PMP to a PIM `Product` numbered differently from our local sku, and
  `number` is the local match key, not PIM's. This full "name/raw_data/
  brand/categories" write step is factored out as `apply_pim_product(product,
  data)` (`services/pim_sync.py:147-166`) so `sync_product_from_pim` and
  `services/sets.py` (see [[product/sets]]) both call it — one place, one rule.
- **PMP with no `productId` yet:** only the link (`pim_id`/`number`) is
  saved; `name`/`raw_data`/`brand`/`categories` are left alone
  (`test_link_without_product_id_saves_the_link_only`).
- **One fetch of the link, not two:** `link` is fetched once and reused
  (`:120-138`) whether it's needed for matching, for `productId`, or both. A
  resync of a row that **already holds `pim_id`**, with `data` supplied,
  makes zero PMP calls (`test_resync_updates_existing_row_and_never_touches_number`
  asserts `fetch_link.assert_not_called()`) — but a not-yet-linked row still
  needs one `_fetch_pim_link` call even with `data` supplied, purely to learn
  the `number` it matches on.
- **Fetches happen before any write**, so a failed PIM fetch leaves no
  half-made `Product` row (`test_failed_link_fetch_leaves_no_row`).
  `_ensure_pim_category`/`_ensure_pim_brand` can still create rows before
  `product.save()` runs.
- `IntegrityError` still propagates uncaught: a new `Product` whose `number`
  another `Product` already holds under a different `pim_id` (now
  case-insensitively, per the `Lower('number')` constraint — see [[product/overview]]).
- **`or None`, two fields, two different reasons:** `number = link.get('number')
  or None` (`:126`) is constraint-driven (Postgres treats `NULL`s as
  distinct in a unique index but `''` as equal — coercing to `''` would let
  the first numberless `Product` save and `IntegrityError` every one after
  it). `apply_pim_product`'s `product.name = data.get('name') or None`
  (`:155`) is **not** — `name` stopped being unique (see [[product/pim-link]])
  — it's now just convention (`__str__` reads `f'{number} — {name}'`); tests
  assert the `None`, not `''`.
- **Callers.** `product/tasks.py:17-23`
  (`sync_product_from_pim_task`, via `execute_locked_task`, per-`pim_id`
  lock) wraps the function as a task but nothing dispatches that task
  (`.delay()`/`.apply_async()`) — the production caller goes through the
  plain function instead, from inside `sync_products()` (below). The other
  caller is the retiring-stack `supplier_feed` create-product endpoint
  ([[retiring_stack]] owns it) — expects a PMP id in its request body.
- **Tests:** `product/tests/test_pim_sync.py` mocks `_fetch_pim_link` and
  `_fetch_pim_product` at two separate seams (`LINK_PATCH`/`PRODUCT_PATCH`),
  plus a `PimClientWiringTests` class that patches only `SiteAPI.get` to
  confirm those two functions build the right `Entity`. Brand behaviour:
  `test_brand_is_created_from_brand_id_and_linked`,
  `test_brand_is_matched_on_id_so_a_rename_does_not_fork_it`,
  `test_product_without_brand_id_keeps_brand_null`.
  `test_sync_rebuilds_the_search_vector` guards the post-save rebuild.

### Backfilling content in production — `product.backfill_products_from_pim`

`product/tasks.py` also has a full pipeline for the third stage (content,
after `reindex_pim_ids` has assigned `pim_id`s, see [[main_product_manager]]):
`backfill_products_from_pim_task` (`tasks.py:26-59`) finds unsynced pks via
`unsynced_products()`/`iter_unsynced_product_pk_batches`
(`services/pim_sync.py:169-190`, "unsynced" = `pim_id` set, `raw_data={}`)
and, per batch, uses `dispatch_after_commit()` — not `.delay()` — to hand off
to `sync_products_batch_task` (`tasks.py:62-73`), for the same reason
`reindex_pim_ids` does (its own transaction can still roll back). That batch
task runs with `atomic=False` (it's on the network per-product and sleeps
between calls) and calls `sync_products(pks)` (`services/pim_sync.py:193-217`),
which calls the **plain** `sync_product_from_pim` function per pk (not the
Celery task) and tolerates individual failures — a failed row just stays
eligible for the next pass (`test_failed_rows_stay_eligible_for_the_next_run`,
`product/tests/test_backfill.py`). **Not in `CELERY_BEAT_SCHEDULE`**
(`price_manager/settings/celery.py`) — unlike `reindex_pim_ids`, which runs
nightly, this has to be triggered manually, same `manage.py run_task
product.backfill_products_from_pim` pattern as the deploy note in
[[product/migrations]].

### The phantom-field trap (fixed; the shape can recur)

`sync_product_from_pim` used to write `product.category_path = ...` before
`save()`, but `category_path` was never a real field — Django's `save()`
silently ignores assignment to a non-field attribute, so the write was a
no-op every sync. Both the helper and the assignment are gone. There is
**no** denormalised category-path column, deliberately: PIM's payload carries
no path string (only `categoriesIds`), so a path must be derived from the
local MPTT tree via `Category.get_ancestors()` — the `categories` M2M is the
source of truth. If something needs a path string, derive it at read time.
See [[product/testing]] for how this bug's regression test is structured.

## Filling the mirror from PIM (dev-only) — `load_pim_mirror`

`services/pim_sync.py`: `sync_category_tree_from_pim()` (`:220-285`) and
`load_products_by_number()` (`:288-384`), wrapped by `manage.py
load_pim_mirror`. This is distinct from the production `backfill_products_from_pim`
pipeline above — this one is bulk/oneshot and matches by `number` across the
whole PIM catalogue rather than walking already-assigned `pim_id`s one at a time.

- **Read-only against PIM.** It exists because `reindex_pim_ids` (the
  production path in [[main_product_manager]]) *creates* `PriceManagerProduct`
  records in PIM, which must never happen from a dev or snapshot database.
- **`sync_category_tree_from_pim` is the fix for stale categories.**
  `_ensure_pim_category` (`:43-78`) returns early when a category exists and
  never updates `name` or `parent`, and only runs when a product happens to
  reference that category, so it can never see a rename on an untouched
  branch. The tree sync walks PIM's whole list; it re-parents with MPTT
  `move_to`, because a plain `save()` leaves `lft`/`rght`/`level` broken.
- **PIM list mode omits fields silently.** Without an explicit `select`,
  `Product` rows come back with no `categoriesIds` and no `description` at
  all — not empty, absent. Use `PRODUCT_SELECT` (`:14-17`).
- **PIM facts measured on the live API:** 178,605 products, 668 categories in
  15 roots, 6 levels deep. `linkedWith` on >100 category ids returns
  `414 URI Too Long`. PIM does **not** expand a category to its descendants
  (a root alone returns 0 products), so the MPTT expansion in
  `categories_method` (see [[product/products-page]]) is required, not an
  optimisation.
- **Coverage is ~36%, and that is real.** 55,281 of 155,087 Products match a
  PIM number. Whitespace/case/prefix-suffix stripping do not meaningfully
  close it. The old `mainproduct.pim_id` values in the dump are dead ids from
  an earlier generation of PIM records — every one returns 404.
- **Network flakes are normal over a 50-minute pass** (TLS EOF, DNS
  `Name or service not known`); page fetches retry 6 times (~1 min, `_PAGE_RETRIES`
  at `:24`). Use `--start-offset` to resume and `--vectors-only` to finish
  just the vectors.
