---
title: The PIM link — chain, reads, writes, reindex
summary: PriceManagerProduct link chain, get_pim_data, push_pim_links, _search_pim_product_id, reindex_pim_ids.
code: price_manager/main_product_manager/utils.py, price_manager/main_product_manager/tasks.py
---
# The PIM link — chain, reads, writes, reindex

## The PIM link chain

MainProduct → `product.Product` (**local** match, `Product.number =
MainProduct.sku`) → `Product.pim_id` = id of a PIM **`PriceManagerProduct`**
(PMP) — a through record, `platformID` = `str(local Product pk)`, `productId`
= the PIM `Product` → the PIM `Product` itself. **Two PIM hops per read.**
Refs: `_pim_id_of` (`utils.py:29-44`), `get_pim_data` (`utils.py:210-241`),
`PIM_LINK_ENTITY = 'PriceManagerProduct'` (`utils.py:142`). The Product
model side (nullable `pim_id`, migration `0007` which zeroes every
pre-existing `pim_id`) belongs to [[product]].

This "PMP, not PIM Product, is what pim_id names" design is deliberate, not
legacy confusion. Grepped clean out of `utils.py`/`tasks.py` (survives only
as a historical mention in `migrations/0011_mainproduct_product_fk.py`):
`_push_pim_products`, `_link_main_products`, `_link_supplier_products`,
`_pim_product_row`, `push_missing_pim_products`,
`push_supplier_products_to_pim`, `create_pim_links`, `_search_pim_id_result`,
`_resolve_pim_id`, `_search_pim_id`, `PimSearchError`, the
`pim_no_match:{pk}` cache, `PimProductWidget`.

## Read path — two hops, two caches (`get_pim_data`, `utils.py:210-241`)

1. `_get_pim_link(pim_id)` (`utils.py:191-207`) fetches the PMP, cached
   `pim_link:{pim_id}` — one call per distinct **local Product**.
2. If the PMP has a `productId`, fetch the PIM `Product`, cached
   `pim_product:{productId}` (`utils.py:229`) — dedupes across local
   Products whose PMPs point at one PIM Product.
3. No `productId` yet → `None` (PIM staff haven't linked it, or reindex's
   search hasn't found one).

Both caches sit at `PIM_CACHE_TTL` = 24h, bypassed by `refresh=True`, which
both detail views pass (`views.py:85,102`). A fetch no longer queues
anything — `sync_pim_relations` (copied PIM brand/categories onto
`MainProduct.manufacturer`/`.categories`) went with those columns in Phase
2b; [[product]]'s `sync_product_from_pim` fills `Product` instead.

**`_note_pim_404`** (`utils.py:169-184`) no longer unlinks MainProducts
fleet-wide. Counts consecutive 404s on the **PMP fetch only**; at threshold 3
it clears `product.Product.pim_id`, nothing else — `MainProduct.product`
(local, sku-based) is untouched, next reindex pushes a fresh PMP. A 404 on
the PIM `Product` behind a PMP never reaches this — `get_pim_data`'s second
hop just returns `None` (`utils.py:238-240`).

## Writing links: `push_pim_links` / `_push_pim_links`

Only `reindex_pim_ids` writes to PIM. **The render path never searches,
pushes or links**: `get_pim_data_for_product` only reads through an existing
link. Every write path links the ГП row to its (sku, brand) Product itself
([[product/identity]]); a row left unlinked is invisible on `/products/`
until the nightly reindex, no error anywhere. Canary:
`unlinked_main_product_count()` in `product/views.py`.

`push_pim_links(pks)` (`utils.py:789-850`), run per-batch as
`reindex_pim_ids_batch_task` (`tasks.py:166-175`, `atomic=False` — see
[[core/task-runner]]; wrapping this in a transaction would turn
"skip this chunk on error" into "lose everything since the last commit"):

- Per local Product `pim_id__isnull=True` with a `number`: search PIM by
  `number` and the Product's brand via `_search_pim_product_id` (a brandless
  Product matches only a brandless card). FOUND → push with `productId`;
  ABSENT/AMBIGUOUS → push without it; ERROR → skip (an unanswered search
  must not drop a `productId` it might have found).
- Payload name/description come from the **lowest-pk MainProduct** on that
  Product (`utils.py:812-842`) — description off that MainProduct's first
  `SupplierProduct.description` (MainProduct's own field is gone).
- `_push_pim_links` `upsertAsync`s the batch. PIM matches an upsert on the
  PMP's unique field — since 2026-10-13 only `platformID` (`number` lost
  `unique` when PIM went to (number, brand)): a record with it → `NotModified`/
  `Updated` with its id. A `Failed`/id-less item (job still ends `Success`) is
  logged, recorded and counted as rejected. **`_take_over_pim_link` was
  deleted**: it repointed the PMP holding our *number* to our platformID,
  which with shared numbers would trade one PMP between Products every night.
- Before `bulk_update`, any other local Product still holding a
  newly-linked PMP id gets `pim_id=None` first (`utils.py:775-783`) —
  `Product.pim_id` is `unique=True`.
- Result shape/length validated before zipping against the input chunk
  (`utils.py:742-755`) — results tie back by *position only*.
- Never sends `productId: null`, omits the key on no match
  (`utils.py:840-841`) — a push can never clear a link PIM staff set by hand.
- Raises `PimScanError` (`utils.py:845-849`) *after* all writes on any
  unanswered search or rejected push, so `TaskRunHistory` records an error
  even though committed progress survives. **Returns a plain `int`** — must
  stay scalar: `core/task_runner.py`'s `_normalize_updated_count` (`:14-21`)
  sums every numeric element of a *tuple* return, so `(linked, rejected)`
  would silently inflate `TaskRunHistory.updated_count`.
- Celery's `SoftTimeLimitExceeded` is neither an ERROR search nor a skipped
  chunk. `_search_pim_product_id` and `_push_pim_links` re-raise it ahead of
  their `except Exception` and do not pass it to `_record_pim_error`, so the
  batch ends as an error row with its lock released
  ([[core/task-runner]], *Time limits*). Every search runs before the first
  write, so a batch the limit cuts short in the search loop has written
  nothing. The next run takes the same pks, so a batch too slow for its
  limit errors every night without progress.

PIM is unique by (number, brand) since its 2026-10-06 cleanup, so one
number may name several cards — one per brand.

## `_search_pim_product_id(number, brand_pim_id)`: one `equals`, four outcomes, no cache

No cache — a scan re-searches a known-bad row every time it's due. It selects
`id` and `brandId` (list mode returns `brandId` only when selected) and keeps
the cards whose `brandId` equals the Product's brand — `None` for a brandless
Product, which therefore never binds to a branded card. Outcomes over those:
`_SEARCH_FOUND` (exactly one), `_SEARCH_ABSENT` (zero), `_SEARCH_AMBIGUOUS`
(>1, links nothing), `_SEARCH_ERROR`.

**Must stay `equals`, measured not reasoned**: AtroPIM feeds a `like` value
straight into SQL LIKE — live, `like '2001_-04_z01'` returns the
differently-numbered `20015-04_z01`, `like '%'` returns all 36k rows. PIM
numbers routinely contain `_`, sku is supplier-supplied, so `like` risks
matching the *wrong* product and landing as `_SEARCH_FOUND`.

**Rendering the table in a test makes live PIM calls unless patched — and
"live" can mean production** (repo-root `.env`, gitignored, carries real PIM
creds). `site` is bound into `utils`'s own namespace — patch
`main_product_manager.utils.site`, not `pim_client.site`.
`_PimSearchTestCase` (`tests.py:467-491`) is the shared fixture;
`SearchPimProductIdTests`/`PushPimLinksTests`/`GetPimDataTests`
(`tests.py:495`/`696`/`855`) are the current pattern, under
`@override_settings(CACHES=LOCMEM_CACHE)`.

## `reindex_pim_ids` — order matters (`tasks.py:129-163`)

The local half is `link_unlinked_main_products()` alone, inside the parent
task's transaction. It used to be preceded by `backfill_product_numbers()`,
which numbered the `number=NULL` placeholders of `product.0005`/
`main_product_manager.0011` from their rows' sku. It skipped a placeholder
whose sku another Product already held, which left ~900 skus split across a
numbered Product and a numberless twin. `product.0016` merged those twins,
and `product.0017` made `number` NOT NULL and non-empty, so the backfill and
its ordering constraint are gone.

`link_unlinked_main_products` counts linked rows as `before - after`, not
`update()`'s count — its last step is one correlated `UPDATE ... SET
product_id = (subquery)` that also "updates" already-NULL rows with NULL. A
sku longer than `PRODUCT_NUMBER_MAX_LENGTH` (`utils.py:25`) stays unlinked,
only logged.

PIM-facing half fans out via `iter_unpushed_product_pk_batches`
(`utils.py:652-668`), dispatched through `dispatch_after_commit`
(`tasks.py:146-150`). **The two halves are not equally safe on a snapshot.**
`link_unlinked_main_products()` is purely local — safe directly on prod
data. The fan-out **writes to PIM**, so
**never run the task itself against a snapshot with real credentials**; use
[[product]]'s `load_pim_mirror` for read-only Product content. Measured on
the 2026-09-03 snapshot: linking picked up 122 stragglers.
