# main_product_manager

`MainProduct` — the canonical product record: a per-supplier stock+price row
hanging off `product.Product`. Owns the PIM integration. Full audit pass
against current `main` on 2026-09-22: the PMP through-link design (originally
PR #184) is merged, so it's simply how the code reads now. Every line ref
below was re-checked in this pass — most had drifted tens of lines from
docstring/refactor churn. This file rots fast; re-verify before trusting.

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

## Writing links: `push_pim_links` / `_push_pim_links` / `_take_over_pim_link`

Only `reindex_pim_ids` writes to PIM. **The render path never searches or
pushes**: `_link_to_local_product` (`utils.py:47-63`, used by
`get_pim_data_for_product` and «Добавить товар», `views.py:118-124`) and its
batched twin `link_to_local_products` (`utils.py:66-88`, used by
copy-to-main) only link to an *existing* local Product with `number=sku` —
never create, never call PIM. Since Phase 2b these are explicit calls (used
to be a side effect of the now-removed `_build_searchvector`); forgetting to
link a newly-created MainProduct makes it invisible on `/products/` until
the nightly reindex, no error anywhere. Canary:
`unlinked_main_product_count()` in `product/views.py`.

`push_pim_links(pks)` (`utils.py:755-816`), run per-batch as
`reindex_pim_ids_batch_task` (`tasks.py:166-175`, `atomic=False` — see
CLAUDE.md's shared-infra note; wrapping this in a transaction would turn
"skip this chunk on error" into "lose everything since the last commit"):

- Per local Product `pim_id__isnull=True` with a `number`: search PIM by
  `number` via `_search_pim_product_id`. FOUND → push with `productId`;
  ABSENT/AMBIGUOUS → push without it; ERROR → skip (an unanswered search
  must not drop a `productId` it might have found).
- Payload name/description come from the **lowest-pk MainProduct** on that
  Product (`utils.py:781-807`) — description off that MainProduct's first
  `SupplierProduct.description` (MainProduct's own field is gone).
- `_push_pim_links` (`utils.py:678-752`) `upsertAsync`s the batch, matching
  PIM's live behaviour on the PMP's two unique fields (`number`,
  `platformID`): both match one record → `NotModified`/`Updated` with its
  id; only one matches → per-item `Failed` (unique violation; job still ends
  `Success`). A `Failed`/id-less item goes to `_take_over_pim_link`
  (`utils.py:637-675`): GET the PMP holding `number`, upsert
  `{...payload, id: that_id}` to repoint its `platformID`. What even that
  can't place is logged, not raised.
- Before `bulk_update`, any other local Product still holding a
  newly-linked PMP id gets `pim_id=None` first (`utils.py:741-749`) —
  `Product.pim_id` is `unique=True`.
- Result shape/length validated before zipping against the input chunk
  (`utils.py:708-721`) — results tie back by *position only*.
- Never sends `productId: null`, omits the key on no match
  (`utils.py:806-807`) — a push can never clear a link PIM staff set by hand.
- Raises `PimScanError` (`utils.py:811-815`) *after* all writes on any
  unanswered search or rejected push, so `TaskRunHistory` records an error
  even though committed progress survives. **Returns a plain `int`** — must
  stay scalar: `core/task_runner.py`'s `_normalize_updated_count` (`:14-21`)
  sums every numeric element of a *tuple* return, so `(linked, rejected)`
  would silently inflate `TaskRunHistory.updated_count`.

PIM's own metadata doesn't declare `Product.name`/`number` unique, so
`_SEARCH_AMBIGUOUS` is reachable in principle (no duplicates in a 2400-row
sample so far).

## `_search_pim_product_id`: one `equals`, four outcomes, no cache (`utils.py:255-297`)

No cache — a scan re-searches a known-bad row every time it's due. Outcomes:
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
`_PimSearchTestCase` (`tests.py:473-499`) is the shared fixture;
`SearchPimProductIdTests`/`PushPimLinksTests`/`GetPimDataTests`
(`tests.py:503`/`666`/`825`) are the current pattern, under
`@override_settings(CACHES=LOCMEM_CACHE)`.

## `reindex_pim_ids` — order matters (`tasks.py:129-163`)

`backfill_product_numbers()` (`utils.py:512-556`) runs **before**
`link_unlinked_main_products()` (`utils.py:559-615`) inside the parent
task's transaction — deliberately. Placeholder Products seeded by
`product.0005`/`main_product_manager.0011` have `number=NULL`; linking first
would let an unlinked MainProduct with a matching sku claim its own new
Product, permanently blocking the placeholder's backfill. Backfill only
assigns a number when every linked MainProduct on that Product agrees on
`sku`, it fits `max_length`, and no other Product holds it already;
otherwise logs and moves on, never touching an *existing* link.

`link_unlinked_main_products` counts linked rows as `before - after`, not
`update()`'s count — its last step is one correlated `UPDATE ... SET
product_id = (subquery)` that also "updates" already-NULL rows with NULL. A
sku longer than `PRODUCT_NUMBER_MAX_LENGTH` (`utils.py:25`) stays unlinked,
only logged.

PIM-facing half fans out via `iter_unpushed_product_pk_batches`
(`utils.py:618-634`), dispatched through `dispatch_after_commit`
(`tasks.py:146-150`). **The two halves are not equally safe on a snapshot.**
`backfill_product_numbers()`/`link_unlinked_main_products()` are purely
local — safe directly on prod data. The fan-out **writes to PIM**, so
**never run the task itself against a snapshot with real credentials**; use
[[product]]'s `load_pim_mirror` for read-only Product content. Measured on
the 2026-09-03 snapshot: backfill numbered 154,050 Products, left 919
unnumbered (sku disagreement); linking picked up 122 stragglers.

## `compute_supplier_sku` — the only thing left tying import to PIM

`compute_supplier_sku(article, supplier)` (`utils.py:500-509`) applies
`supplier.sku_type`/`sku_value` as prefix/suffix, feeds
`copy_supplier_products_to_main_task`'s `MainProduct.sku`
(`supplier_product_manager/tasks.py:244`). The pre-copy PIM push this used to
agree with is gone. **The Excel upload no longer talks to PIM at all** — it
only has to produce the right `sku`, which becomes `product.Product.number`
via `link_unlinked_main_products` (the copy task's own link step,
`supplier_product_manager/tasks.py:263`), and `number` is reindex's only
search key into PIM. `SupplierProduct.pim_id`
(`supplier_product_manager/models.py:17`) is dead weight — only the field
def and its migrations reference it, no read/write site (confirm with
[[supplier_product_manager]] if its code changes).

**It doesn't strip `article` — fine, because PIM does.** On the snapshot,
21% of Product numbers carry leading/trailing whitespace vs. 3 of PIM's
178,605; PIM strips whitespace on its side (confirmed by the user), so these
link normally in production. Don't "fix" it at import — the gap only shows
where matching happens *locally* against PIM's numbers
([[product]]'s `load_pim_mirror` loses ~400 matches to it).

## Open question — no path left to link different skus onto one Product

Dropping the Excel `ID` mapping removed the only way to put MainProducts
with **different** skus onto one Product — a new multi-supplier group now
only forms when two MainProducts share an identical `sku`. (The old main
page's `grouping.py`/`group_key()` that partitioned on this is gone entirely
with Phase 2b; whatever grouping `/products/` does now is [[product]]'s to
document.) Existing cross-sku links survive — migration `0007` touches only
`product.Product.pim_id`/`number`/`name`, never `MainProduct.product` — but
nothing creates new ones. **Not decided**; don't build a replacement
unilaterally.

## Detail page — three PIM states (`templates/mainproduct/partials/detail.html:65-84`)

No `product` → «Не привязан». `product` set, no `pim_id` → «Не отправлен в
PIM». `pim_id` set, `pim_data` empty → «Нет данных» (PMP exists with no
`productId` yet, or PIM unreachable). Only the third state is a live call.

## `maybe_notify_pim_error` deliberately not gated on `settings.DEBUG` (`utils.py:109-139`)

DEBUG defaults false, so gating on it meant production — the environment a
PIM outage actually costs something — got no signal. Throttled per user
instead (`_PIM_NOTIF_THROTTLE_TTL`, 30 min).
`test_notifies_even_though_debug_is_false` (`tests.py:1006`) guards it.

## `sync_main_products_task` has no `@shared_task` (`tasks.py:120-127`)

Plain function `chain()`ing **four** tasks into one `apply_async()` — «Обновить»
on `/products/`: `update_prices_task`, `update_stocks_task`,
`delete_outdated_logs_task`, `notify_sync_main_products_task` (each passes
its `stats` payload along via `_append_step`). `recalculate_vectors_missing`
and `rebuild_categories` are gone from the whole repo now, not just this
chain. `reindex_pim_ids` is a **separate** scheduled task, not part of this
chain. `reindex_pim_ids_batch_task` uniquifies `task_name` per chunk
(`tasks.py:169`) so batches don't contend on one Redis lock.

## PIM photos — `get_file_url` vs `pim_image_url` (`utils.py:341-405`)

`get_file_url()` (`:341-372`) loops `(f'{size}ThumbnailUrl', 'url',
'downloadUrl')` through `_absolute_pim_url` (`:314-338`). Live PIM: thumbnail
keys/`url` don't exist on File records; `downloadUrl` is the only populated
key, always scheme-less, so `size` has no observable effect. It returns the
**PIM-side** URL — server use only, and every PIM image URL answers
anonymous with 401, so this must never reach a template.

Templates get `pim_image_url(file_id, size)` (`:400-405`) instead — our
proxy path (`product.views.PimImageView`, behind `LoginRequiredMiddleware`),
no network touched. `fetch_pim_image()` (`:408-453`) does the actual fetch:
token only to `settings.PIM_HOST`, redirects followed **by hand** with the
same host check each hop (httpx's own redirect-follow would carry the token
to any host off a relative 302), bytes cached a day, failures not cached.
Callers of `get_file_url` render full-size, not thumbnail: `render_photo` in
[[product]]'s `ProductTable` (`product/tables.py:176-188`, imports
`pim_image_url` from here) and `mainproduct/partials/detail.html`.
`GetFileUrlTests` (`tests.py:311`) still describes the older
`downloadUrl`-only shape, which also remains handled.

## Where brand data lives after Phase 2b

`MainProduct.manufacturer`/`SupplierProduct.manufacturer` are gone (confirmed
absent from both models). Brand is `product.Product.brand` (PIM only). If
reading an old analysis: `MainProduct.manufacturer` used to hold *whichever
ran last* of copy-to-main (supplier value) or `sync_pim_relations` (PIM
brand) — never raw supplier data.

## `MainProductFilter` is the cart's filter, not a page's (`filters.py`)

Since Phase 2a it serves the cart's «Добавить товары» modal
(`core/views.py` `CartItemProductSelectView`), shopping-tab import
auto-match (`core/utils.py` `find_main_products`). «Привязать из ГП»
(`ResolveMainproduct`, `/resolve`) was removed from the card on 2026-09-24.
Rows are MainProduct, but search/brand/categories go
**through `MainProduct.product`** via [[product]]'s shared
`matching_product_pks`. Must not touch `MainProduct.search_vector`/
`.categories`/`.manufacturer` (removed from the model, confirmed absent from
`filters.py`); `core/views.py` imports it at module scope
(`core/views.py:33`) — a stale field reference stops the whole app booting.
Rows without a Product are still found by own `sku`/`name`/`article` (in the
cart, invisible would mean unbuyable).

**Category tree expansion is computed by the filter, not the shared
template.** `product/templates/product/partials/category_tree_node.html:17,23`
just reads `node.pk in field.field.expanded_pks` — see [[product]] for the
full mechanism. `MainProductFilter.config_filters`
(`filters.py:208-209`) sets it via `product.filters.expanded_category_pks`
(one query: selected category pks + their ancestors). It must be set on
`self.filters['categories'].field` inside `__init__`, before the bound form
is built (`config_filters` runs at `filters.py:88`) — a Filter's `.field` is
built once and shared with the form, so setting the attribute later would
miss the render. Silent failure mode: without `expanded_pks`,
`node.pk in None` is falsy under Django's `{% if %}`, so the tree just
renders every branch collapsed, including one holding a ticked category —
no error anywhere. Any new filter that reuses this tree partial must set
`expanded_pks` the same way.

The old main page — `MainPageFilter`, `MainProductTable`, `grouping.py`,
`columns.py`, the column-preference cache — was deleted in Phase 2b
(confirmed gone repo-wide); `/mainproduct/` permanently redirects to
`/products/` (`urls.py:13`, no query params carried over). This app's own
`urls.py` still owns the per-row routes: create/update/info/detail/
logs and the pricetag-list proxy (`urls.py:15-23`). This app's `tables.py` is
tiny now too — `MainProductLogTable` only. The card's «Наценки» column
(`product_price_manager` `PriceTagList`) splits PriceTags into «Фиксированные»
(`p_manager IS NULL`, editable in place) and «Из менеджеров наценок» (opens the
rule's modal — a rule's apply overwrites its tags, so they are not edited here).

## Three columns that look like fields but aren't

`MainProductLog` has three writers: `utils.update_logs()` (`utils.py:819-853`
— has leftover `print()` debug calls in its body) and
[[product_price_manager]]'s `PriceManager.apply(logs=True)` /
`PriceTag.get_mp()` (the latter reached unconditionally every run via
`update_prices()`).
`supplier_product_price`/`supplier_product_rrp`/`supplier_product_discount_price`
are not `MainProduct` fields but correlated Subqueries over the latest
`SupplierProduct` row, now built in [[product]]'s
`views._latest_supplier_prices()`.

## `update_stocks` — NULL vs `0`, and its batching trap (`utils.py:456-498`)

Tests `stock__isnull` separately rather than coalescing both sides —
coalescing would compare NULL=0 as equal and never update never-synced
products. Batches over a `pks = list(...values_list('pk', ...))` snapshot
rather than `range(0, count(), batch_size)`: `MainProduct.pk` is a
never-reset `BigAutoField`, so one deleted row makes an offset-derived range
stop short and silently skip the tail. `timezone.now()` read once above the
loop so one run stamps one `stock_updated_at`. Same gap-safe idiom as
`iter_unpushed_product_pk_batches`.
