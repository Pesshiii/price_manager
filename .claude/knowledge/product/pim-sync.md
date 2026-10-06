---
title: Syncing content from PIM
summary: sync_product_from_pim, the production backfill and why the mirror froze, the nightly refresh, the phantom-field trap, load_pim_mirror.
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
- **A PMP without a number raises `ValueError`** instead of creating a
  `Product`: `number` is NOT NULL and non-empty since `0017`. (It used to
  be `or None`, which made numberless placeholders.) `apply_pim_product`'s `product.name = data.get('name') or None`
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
`product/tests/test_backfill.py`). The backfill itself is **not** in
`CELERY_BEAT_SCHEDULE`; `run_task` doesn't know it either (that command only
lists `main_product_manager` tasks) — start it from `manage.py shell` with
`backfill_products_from_pim_task.delay()`.

**`sync_products` counts content, not calls.** A PMP with no `productId`
makes `sync_product_from_pim` save the link only, leaving `raw_data={}`.
It used to count as synced, so `TaskRunHistory` showed whole backfill passes
as successful while most rows got nothing. Now only rows that end up with
`raw_data` count, and the link-only ones are logged separately.

### Why the mirror froze, and the nightly refresh — `product.refresh_products_from_pim`

The backfill selects only `raw_data={}`, and nobody re-ran it. So two things
never reached the mirror: a PMP that PIM staff linked to a Product **after**
the backfill (most PMPs had no `productId` when it ran — reindex sets one only
when the number search finds exactly one Product), and any edit made in PIM
afterwards (descriptions filled in later). The «Без данных PIM» counter on
`/products/` (`Product.raw_data={}`) is exactly that frozen tail. It is not a
count of unlinked PMPs, and it is not wrong.

`refresh_products_from_pim_task` (beat `refresh-products-from-pim`, 05:00,
after `reindex_pim_ids` at 03:00 and sets at 04:00) runs
`stale_product_pks()` (`services/pim_sync.py`). That function makes two
**list** passes, `PriceManagerProduct` `id→productId` and `Product`
`id→modifiedAt`, a few hundred requests in total. A row is stale when its
PMP's `productId` differs from `raw_data['id']` (this includes never-synced
rows) or when PIM's `modifiedAt` differs from `raw_data['modifiedAt']`.
Stale rows go to the same `sync_products_batch_task` fan-out, so `raw_data`
keeps the full single-GET shape. A list `select` would cut it to
the selected keys and silently blank photos (`mainImageId`), `ean`, `status`
and `categoriesNames` in the vector.

- PMPs without `productId` are skipped, not fetched nightly.
- Rows without `pim_id` (sets) are never touched; `services/sets.py` owns them.
- `modifiedAt` is compared as a datetime, so one notation in the list and
  another in the single GET doesn't make the whole catalogue look stale every
  night. A listing row **without** `modifiedAt` means "can't tell", not
  "changed" (`_changed_since`), for the same reason — list mode drops fields
  silently. If every row lacks it, a warning is logged and only new PMP links
  get refreshed.
- If something in PIM rewrites every Product nightly (`price`, `rrp`,
  `quantity` live on it), `modifiedAt` moves for all of them and every night
  becomes a full refetch. `updated_count` of
  `product.refresh_products_from_pim` in `TaskRunHistory` is the number to
  watch.
- A truncated listing raises instead of reading as "not linked".
- The first run after a long gap fetches the whole tail. A batch of 500 is
  1,000 GETs plus 250 s of sleep on one worker process, so a tail as large as
  the catalogue keeps workers busy for hours — the `pim` queue's worker only
  (`CELERY_TASK_ROUTES`, `celery_worker_pim`), not the one imports, exports
  and `update_prices` run on.

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

Characteristics are **not** synced into raw_data; the card fetches them lazily —
see [[product/pim-content]].

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
