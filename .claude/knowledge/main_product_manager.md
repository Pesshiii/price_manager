# main_product_manager

`MainProduct` — the canonical product record. Owns the PIM integration.
Re-verified against `feat/pim-pmp-through-link` (PR #184, unmerged) on
2026-09-14 — this branch replaced the whole link/push design described in
earlier revisions of this file. Re-verify again once PR #184 merges or moves
further, before trusting these refs.

## The PIM link chain (new this branch)

MainProduct → `product.Product` (a **local** match, `Product.number =
MainProduct.sku`) → `Product.pim_id` = id of a PIM **`PriceManagerProduct`**
(PMP) — a through record, `platformID` = `str(local Product pk)`, `productId`
= the PIM `Product` → the PIM `Product` itself. **Two PIM hops per read now,
not one.** Refs: `_pim_id_of` (`utils.py:29-44`), `get_pim_data`
(`utils.py:207-246`), `PIM_LINK_ENTITY = 'PriceManagerProduct'`
(`utils.py:116`). The Product model side (nullable `pim_id`, non-unique
`name`, migration `0007_product_pim_id_is_price_manager_product` which zeroes
every pre-existing `pim_id` because its meaning changed from "PIM Product id"
to "PriceManagerProduct id") belongs to [[product]] — don't restate it here.

**The user decided the old "wrong entity" behaviour is now the intended
design.** Earlier revisions flagged `_push_pim_products` for storing a
PriceManagerProduct id where every read path expected a PIM `Product` id,
marked "open decision with the user." Decided: correct, and the surrounding
mechanism was rebuilt to make the two hops explicit. Removed (grepped clean;
historical mention only survives in `migrations/0011`): `_push_pim_products`,
`_link_main_products`, `_link_supplier_products`, `_pim_product_row`,
`push_missing_pim_products`, `push_supplier_products_to_pim`,
`create_pim_links` (+ its 30-min beat entry, `run_task --skip-non-empty`),
`_search_pim_id_result`, `_resolve_pim_id`, `_search_pim_id`,
`PimSearchError`, the `pim_no_match:{pk}` cache, `PimProductWidget`.

## Read path — two hops, two caches (`get_pim_data`, `utils.py:207-246`)

1. `_get_pim_link(pim_id)` (`:188-204`) fetches the PMP, cached
   `pim_link:{pim_id}` — one call per distinct **local Product** (`pim_id`
   here names a Product, since it lives on `product.Product.pim_id`).
2. If the PMP has a `productId`, fetch the PIM `Product`, cached
   `pim_product:{productId}` (`:226`) — *this* hop dedupes across local
   Products whose PMPs happen to point at one PIM Product.
3. A PMP with no `productId` yet → `get_pim_data` returns `None` (PIM staff
   haven't linked it, or reindex's search hasn't found one).

Both caches sit at `PIM_CACHE_TTL` = 24h, so a `productId` PIM staff set
later only surfaces after expiry — or on `refresh=True`, which both detail
views pass (`views.py:251,267`). **A cold page now costs one PMP call per
distinct local Product plus one per distinct PIM Product** — more
round-trips than the old one-hop design, not fewer; don't describe the cost
as "bounded by distinct pim_ids" anymore. `sync_pim_relations` and
`_queue_pim_population` are unchanged in shape but key off the PMP id now:
`sync_pim_relations` filters `MainProduct.objects.filter(product__pim_id=pim_id)`
(`utils.py:391`).

## `_note_pim_404` no longer unlinks MainProducts, fleet-wide or otherwise (`utils.py:166-181`)

It counts consecutive 404s on the **PMP fetch only**
(`pim_404_count:{pim_id}`). At `_PIM_404_THRESHOLD=3` it runs
`PimProduct.objects.filter(pim_id=pim_id).update(pim_id=None)` — clears the
local Product's PMP link, nothing else. `MainProduct.product` (the local,
sku-based link) is untouched, and the next `reindex_pim_ids` pushes a fresh
PMP. A 404 on the PIM `Product` behind a PMP never reaches this function —
`get_pim_data`'s second hop just returns `None` on that 404 (`:243-245`),
changing nothing locally. (The pre-#184 design unlinked every MainProduct
sharing a dead pim_id fleet-wide, possibly inside one page render — gone with
the one-hop link it depended on.)

## Writing links: `push_pim_links` / `_push_pim_links` / `_take_over_pim_link`

Only `reindex_pim_ids` writes to PIM now. **The render path never searches or
pushes**: `_link_to_local_product` (`utils.py:47-63`), used by
`_build_searchvector` (`models.py:151-173`) and `get_pim_data_for_product`
(`utils.py:307-315`), only links to an *existing* local Product with
`number=sku` — never creates one, never calls PIM. The Excel import
(`MainProductPimImportResource`, below) is local-only too.

`push_pim_links(pks)` (`utils.py:819-877`), run per-batch as
`reindex_pim_ids_batch_task` (`tasks.py:192-201`, `atomic=False`):

- For each local Product still `pim_id__isnull=True` with a `number`, search
  PIM `Product` by `number` via `_search_pim_product_id` (below). FOUND →
  push with `productId`; ABSENT/AMBIGUOUS → push without it; ERROR → skip
  that Product (pushing on an unanswered search would drop a `productId` the
  search might have found).
- Payload: `{'platformID': str(pk), 'number', 'name', 'description'}`,
  name/description from the **lowest-pk MainProduct** on that Product
  (`:842-848`).
- `_push_pim_links` (`:742-816`) sends the batch through `upsertAsync`,
  matching PIM's live behaviour on the PMP's two unique fields (`number`,
  `platformID`): both match one record → `NotModified`/`Updated` with its id
  (how a PMP whose id never got saved locally recovers it just by being
  re-pushed); only one matches → per-item `Failed` (Postgres unique
  violation; the job itself still ends `Success`).
- A `Failed`/id-less item goes to `_take_over_pim_link` (`:701-739`): GET the
  PMP currently holding `number`, then upsert `{...payload, id: that_id}` to
  repoint its `platformID` at our pk. What even that can't place (our
  `platformID` already sits on a PMP with a *different* `number` too) is
  logged and counted, not raised per-item.
- Before `bulk_update`, any *other* local Product still holding one of the
  newly-linked PMP ids gets `pim_id=None` first (`:805-813`) — a taken-over
  PMP is being reassigned, and `Product.pim_id` is `unique=True`, so the old
  owner must give it up before the new one can take it.
- Result shape/length is validated before zipping against the input chunk
  (`:772-785`) — `Job.message` ties results back to inputs by *position
  only*, so a short/malformed list would silently write ids onto the wrong
  Products. Same reasoning the old `_push_pim_products` validation used to
  need; it now lives here.
- Never sends `productId: null`, omits the key entirely on no match
  (`:867-868`) — a push can never clear a link PIM staff set by hand.
- Raises `PimScanError` (`:258-259`) *after* all its writes if any search was
  unanswered or any push stayed rejected, so `TaskRunHistory` records the
  batch as an error even though committed progress survives. **Returns a
  plain `int` (linked count)** — must stay scalar: `core/task_runner.py`'s
  `_normalize_updated_count` (`:14-21`) sums every numeric element of a
  *tuple* return, so returning `(linked, rejected)` instead would silently
  inflate `TaskRunHistory.updated_count`.

**PIM behaviour, measured against live PIM** (a metadata read, plus write
tests against a fake record): PMP fields are `name`/`description`/`number`
(required, unique)/`platformID` (required, unique, spelled exactly that)/the
product link (JSON key `productId`). PIM `Product.name`/`Product.number` are
*not* declared unique in PIM's own metadata (`GET /api/metadata`, lowercase —
`/api/Metadata` and `/api/v1/Metadata` 404), so `_SEARCH_AMBIGUOUS` is
reachable in principle even though a 2400-row sample showed no duplicate
`number`s.

## `_search_pim_product_id`: one `equals`, four outcomes, no cache (`utils.py:262-304`)

Replaces `_search_pim_id_result`/`_resolve_pim_id`/`_search_pim_id` and the
`pim_no_match:{pk}` cache — there is **no cache here at all**; a scan
re-searches a known-bad row every time it's due. Query:
`EntityList(name='Product', select=['id'], where=[Where(attribute='number',
type='equals', value=number)])`. Outcomes: `_SEARCH_FOUND` (exactly one),
`_SEARCH_ABSENT` (zero), `_SEARCH_AMBIGUOUS` (>1, logs and links nothing),
`_SEARCH_ERROR` (request raised). No `_SEARCH_NO_SKU` — callers only invoke
this with a real `number` in hand (`push_pim_links` filters
`number__isnull=False` first).

**Must stay `equals`, measured not reasoned** (this finding predates #184 and
still holds): AtroPIM feeds a `like` value straight into SQL LIKE — live,
`like '2001_-04_z01'` returns the differently-numbered `20015-04_z01`, and
`like '%'` returns all 36k rows. PIM numbers routinely contain `_`, sku is
supplier-supplied, so under `like` a sku can match the *wrong* product and
land as `_SEARCH_FOUND` — `_SEARCH_AMBIGUOUS` only fires on >1 match and
would not catch it.

**Rendering the table in a test makes live PIM calls unless patched — and
"live" can mean production**, since the repo-root `.env` (gitignored) carries
real PIM creds; `test_grouping.py`'s module docstring has the full story
(three unpatched 404s trip `_note_pim_404` mid-suite-run). `site` is bound
into `utils`'s own namespace, so tests patch `main_product_manager.utils.site`,
not `pim_client.site`. `_PimSearchTestCase` (`tests.py:540-566`) is the
shared PIM-link fixture; `SearchPimProductIdTests`, `PushPimLinksTests`,
`GetPimDataTests` etc. (`tests.py:570+`) are the current pattern, all under
`@override_settings(CACHES=LOCMEM_CACHE)` so cache assertions see the same
cache the code under test wrote to.

## `reindex_pim_ids` — order matters (`tasks.py:157-189`)

Inside the parent task's transaction, `backfill_product_numbers()`
(`utils.py:576-620`) runs **before** `link_unlinked_main_products()`
(`utils.py:623-679`) — deliberately (`tasks.py:166-168`). Placeholder
Products seeded by `product.0005`/`main_product_manager.0011` have
`number=NULL`. If linking ran first, an unlinked MainProduct with a matching
sku would get its own new Product, permanently blocking the placeholder's
backfill ("number taken"). Backfill only assigns a number when every linked
MainProduct sharing that Product agrees on `sku`, the sku fits `number`'s
`max_length`, and no other Product already holds it — otherwise it logs and
moves on; it never touches an *existing* link.

`link_unlinked_main_products` counts linked rows as `before - after`, not
`update()`'s row count, because its last step is one correlated `UPDATE ...
SET product_id = (subquery)` that also "updates" already-NULL rows with NULL.
A sku longer than `PRODUCT_NUMBER_MAX_LENGTH` (`utils.py:25`, from PIM
`Product.number`'s `max_length`) stays unlinked and is only logged.

The PIM-facing half fans out via `iter_unpushed_product_pk_batches`
(`utils.py:682-698`, replaces `iter_pim_id_pk_batches`) — Products with
`pim_id__isnull=True`, a `number`, and `main_products__isnull=False` —
dispatched through `dispatch_after_commit` (`tasks.py:174-178`; see
CLAUDE.md's Shared infrastructure section for the general rule).

**The two halves are not equally safe to run.** `backfill_product_numbers()`
and `link_unlinked_main_products()` are purely local — call them directly on a
prod snapshot to give Products their numbers. The fan-out **writes to PIM**
(creates and repoints `PriceManagerProduct` records), so **never run the task
itself against a snapshot with real credentials**. To fill Product content
read-only, use [[product]]'s `load_pim_mirror` instead. Measured on the
2026-09-03 snapshot: backfill numbered 154,050 Products and left 919 unnumbered
(their MainProducts disagree on `sku`); linking picked up 122 stragglers.

## `compute_supplier_sku` — the only thing left tying import to PIM

`compute_supplier_sku(article, supplier)` (`utils.py:564-573`) still applies
`supplier.sku_type`/`sku_value` as prefix/suffix and still feeds
`copy_supplier_products_to_main_task`'s `MainProduct.sku`
(`supplier_product_manager/tasks.py:255`). What changed: the pre-copy push
(`push_supplier_products_to_pim`, the second caller that used to need this to
agree with) is gone — `supplier_product_manager/functions.py` is grepped
clean of any PIM reference now. **The Excel upload no longer talks to PIM at
all.** It only has to produce the right `sku`, because that `sku` becomes
`product.Product.number` via `link_unlinked_main_products`, and `number` is
reindex's only search key into PIM. `SupplierProduct.pim_id` (plain
CharField, `supplier_product_manager/models.py:17`) is dead weight from the
old design — grepping `pim_id` across `supplier_product_manager/` turns up
only the field definition and its two migrations, no read or write site —
but that's this app's read, not [[supplier_product_manager]]'s; confirm there
before relying on it if that app's own code changes.

The copy task still reaches PIM indirectly: `copy_supplier_products_to_main_task`
→ `recalculate_search_vectors` → `_build_searchvector` → `get_pim_data`, once
per touched row (read-only now, not a push).

**It does not strip `article` — and that is fine, because PIM does.** On the
snapshot, **32,123 of 154,168 Product numbers (21%)** carry leading or trailing
whitespace (supplier articles land in `sku` verbatim), against **3** in all of
PIM's 178,605 numbers. **PIM strips whitespace from numbers on its side**
(confirmed by the user), and `reindex_pim_ids` matches by asking PIM, so these
rows link normally in production. Don't "fix" it at import on the strength of
the 21% figure. It only shows up where matching happens *locally* against PIM's
numbers — [[product]]'s `load_pim_mirror`, a dev tool, loses ~400 matches to it.

## `MainProductPimImportResource` — `ID` column dropped (`resources.py:256-287`)

Reads only `PriceManagerId` (→ `MainProduct.id`) and `Categories`. The PIM
export's `ID` column (a PIM Product id) is deliberately not read — comment at
`:264-266`: the link now lives in the PMP, pushed by `reindex_pim_ids`, and
`product.Product.pim_id` holds *that* record's id, not a PIM Product id one
could import directly. `PimProductWidget` (the old
get-or-create-a-placeholder-Product-from-an-import-row widget) is gone with
it.

## Open question with the user — no path left to link different skus onto one Product

Dropping the Excel `ID` mapping removed the only way to put MainProducts with
**different** skus onto one Product. `group_key()` (`grouping.py:50-79`)
partitions the main page by `product_id`, so a new multi-supplier group can
now only form when two MainProducts happen to share an identical `sku`.
Existing cross-sku links survive — migration `0007` touches
`product.Product.pim_id`/`number`/`name` only, never `MainProduct.product` —
but nothing currently creates new ones. **Not decided**; don't build a
replacement unilaterally.

## Detail page — three PIM states, not two (`templates/mainproduct/partials/detail.html:65-84`)

No `product` → «Не привязан». `product` set but no `pim_id` yet → «Не
отправлен в PIM» (waiting on nightly reindex). `pim_id` set but `pim_data`
still empty → «Нет данных» (PMP exists with no `productId` yet, or PIM is
unreachable). Only the third state involves a live call — the first two are
answerable from local FKs alone. Views pass `refresh=True`
(`views.py:251,267`), so the detail page always bypasses both caches.

## `.save()` deliberately doesn't rebuild the search vector

`MainProduct.save()` (`models.py:180-181`) is a bare `super().save()`.
`_build_searchvector()` (`models.py:151-173`) makes PIM network calls per row
via `_link_to_local_product`/`get_pim_data` — adding it to `save()` would
turn every save in the codebase into an HTTP request. A loop over
`MainProduct` that calls `rebuild_search_vector()` (`:174-178`) directly
costs one PIM round-trip per row unless routed through
`recalculate_search_vectors` (below).

## PIM scans and `atomic=False`

`reindex_pim_ids_batch_task` (`tasks.py:192-201`) passes `atomic=False` — see
CLAUDE.md's Shared infrastructure section for why (the transaction opens
before the runner is called; write placement doesn't change that). Don't
wrap `push_pim_links` in a transaction "to compensate": a chunk whose
transport/job call fails is recorded and skipped without aborting the rest
(`utils.py:769-771`), and a transaction would turn "skip this chunk" into
"lose everything since the last commit."

## `maybe_notify_pim_error` is deliberately not gated on `settings.DEBUG` (`utils.py:83-113`)

DEBUG defaults false, so gating on it meant production — the one environment
a PIM outage actually costs something — got no signal. It's throttled per
user instead (`_PIM_NOTIF_THROTTLE_TTL`, 30 min). `test_notifies_even_though_debug_is_false`
guards it — don't re-add a DEBUG gate as an easy "fix."

## `MainProduct.product` FK — grouping traps

`group_key()` (`grouping.py:50-79`) must stay
`Case/When(product__isnull=True, then=Concat('mp-', id))`,
`default=Concat('pim-', product_id)` — not `Coalesce(Concat(...))`. Postgres
`CONCAT()` treats NULL as `''`, so `Concat('pim-', NULL)` returns `'pim-'`,
not NULL: under `Coalesce` every unlinked product would collapse into one
fake group. Both branches need their own prefix too, independently:
`product_id` and `MainProduct.id` are separate sequences, so an unlinked row
can otherwise collide with an unrelated `Product.id`. Guarded by
`test_unlinked_products_never_group` and
`test_unlinked_product_does_not_join_group_with_matching_product_id`
(`test_grouping.py:190-204`, `:206-225`).

`recalculate_search_vectors` (`utils.py:507-517`) is the one place that has
to `select_related('product')` before calling `_build_searchvector` →
`_pim_id_of` — a module function, deliberately not a `MainProduct` property
(a property named `pim_id` would keep working in templates and silently
break in `.filter()`/annotations, where the lookup is `product__pim_id`).
Its three callers (`main_product_manager/tasks.py`,
`supplier_product_manager/tasks.py:277`,
`supplier_product_manager/functions.py`, plus `views.py:421-422`) stay
correct without adding the `select_related` themselves.

## `sync_main_products_task` has no `@shared_task` (`tasks.py:146-155`)

It's a plain function that `chain()`s six of the app's ten tasks into one
`apply_async()` workflow; the task count dropped from 11 to 10 this branch
(`create_pim_links` is gone). `reindex_pim_ids_batch_task` uniquifies
`task_name` per chunk (`tasks.py:195`, `f"...:{pks[0]}-{pks[-1]}"`) so
batches don't contend on one Redis lock.

## `get_file_url`'s PIM File payload — precedence bug stays fixed

`get_file_url` (`utils.py:460-487`) loops
`(f'{size}ThumbnailUrl', 'url', 'downloadUrl')`, normalizing each through
`_absolute_pim_url` (`:433-457`). Sampled against live PIM: the thumbnail
keys and `url` don't exist on File records at all; `downloadUrl` is the only
populated key, always scheme-less (`host/path`), which is why the scheme is
decided per-value rather than prepended unconditionally. So `size` has no
observable effect today, and every caller (`render_pim_photo`,
`tables.py:234-245`) renders a full-size image, not a thumbnail.
`downloadUrl` also needs a PIM session — an unauthenticated GET 401s, so a
logged-out browser shows a broken image rather than a 500.

## `MainProduct.manufacturer` is not raw supplier data

`sync_pim_relations` (`utils.py:437-449`) **overwrites
`MainProduct.manufacturer` with the PIM brand** for linked products, while
`copy_supplier_products_to_main_task` writes the supplier's value. So the column
holds whichever of the two ran last. To measure what suppliers actually report,
use `SupplierProduct.manufacturer`, which only the Excel import writes.
Comparing a PIM brand against `MainProduct.manufacturer` is partly comparing
PIM with itself. On raw supplier data the two agree **99.2%** where both exist
(21,381 of 21,559); see §0.5 of `.claude/shift-to-product-brief.md`.

## Two filtersets since Phase 2a — which one you are looking at

Since Phase 2a (2026-09-21) `filters.py` holds two classes, and the name that
used to mean "the main page's filter" now means something else:

- **`MainProductFilter`** — the cart's «Добавить товары» modal
  (`core/views.py` `CartItemProductSelectView`), the shopping-tab import
  auto-match (`core/utils.py` `find_main_products`) and «Привязать из ГП»
  (`ResolveMainproduct`). Rows are still MainProduct, but search, brand and
  categories go **through `MainProduct.product`**, using [[product]]'s shared
  `matching_product_pks`. It must not touch `MainProduct.search_vector`,
  `.categories` or `.manufacturer`: Phase 2b drops them, and `core/views.py`
  imports this class at module scope, so a stale reference stops the whole app
  booting. Rows without a Product are still found by own `sku`/`name`/`article`
  — in the cart, invisible would mean unbuyable.
- **`MainPageFilter`** — the old main page only, byte-for-byte the previous
  `MainProductFilter`. It lives until Phase 2b deletes it with the page. Do not
  wire anything new to it. Everything below about `search_rank`, `.getlist()`
  and `GROUP BY` describes this class.

## `MainPageFilter.search_rank` — `F()`, not a string

Fixed 2026-09-19. It used to pass the string `"search_vector"` to
`SearchRank`, which Django treats as a text field to vectorize:
`ts_rank(to_tsvector(search_vector::text), …)`. That re-tokenizes the stored
vector on every row, with the default config instead of `russian`, and bypasses
the GIN index. It is now `F("search_vector")`. Because the method is shared by
`search_method` and `MainProductTableView`'s group ordering, the one fix covers
both. The same bug had been copied into [[product]]'s `ProductFilter`.

Separately, `MainPageFilter` still calls `self.data.getlist()` directly in
`config_filters`. That works only because views always pass `request.GET`;
building the filterset from a plain `dict` raises `AttributeError` inside
`__init__`. Use a `QueryDict` in shell and tests.

## `MainPageFilter` — `.order_by()` bleeding into `GROUP BY`

`search_method`'s `.order_by("-rank")` (`filters.py:200`) folds into
`GROUP BY` once `get_table_data` (`views.py:194-201`) does
`.values(...).annotate(...)` on the same queryset — `search_rank`
(`filters.py:182-189`) is a separate `@staticmethod` specifically to work
around this; don't inline it.

## Three columns that look like fields but aren't

`MainProductLog` has three writers: `utils.update_logs()`
(`utils.py:880-914`), and [[product_price_manager]]'s
`PriceManager.apply(logs=True)` / `PriceTag.get_mp()`, the latter reached
unconditionally every run via `update_prices()`.
`supplier_product_price`/`supplier_product_rrp`/`supplier_product_discount_price`
(`tables.py:39-41`) are correlated Subqueries built in
`MainProductTableView.get_table_data` (`views.py:146-160`), not
`MainProduct` fields. `kaspi_price` is a genuine field (`columns.py:33`) but
absent from `MainProductTable.Meta.fields` — selecting it in the column
picker does nothing.

## The `product` FK is indexed, but that doesn't make grouping cheap

Django gives `MainProduct.product` a btree index automatically, same as the
old `pim_id` CharField's explicit one — that removes a lookup cost, not the
grouping cost. `annotate_groups` (`grouping.py:120-170`) computes
`Window(...)` per partition over the *expression* `grp_key`, not the indexed
column, so Postgres still sorts every row in a bucket. On a restored
production snapshot the uncategorised bucket (156,016 of 156,481
MainProducts) costs ~70ms→~3s depending on the pass — benchmark grouping
changes there, never against a real category, which always looks fast.
`GroupHeadRecord.__init__` (`grouping.py:237-244`) exposes `product_id`
rather than resolving `pim_id`, precisely to avoid adding a join to that hot
path.

## `render_<column>` is silently skipped when the cell value is empty

Every branching renderer on `MainProductTable` declares `empty_values=()`
(`actions`, `stock_msg`, `delivery_days`, all eight `pim_*` columns,
`tables.py:33-54`). Without it, django-tables2 skips the renderer for
`None`/`""` and returns the column's `default` — reads like a data problem,
not a wiring one. `GroupHeadRecord.__getattr__` (`grouping.py:257-260`)
relies on the inverse on purpose: an unhandled column falls through to `—`
for free.

## `update_stocks` — NULL vs `0`, and its batching trap

`update_stocks` (`utils.py:520-562`) tests `stock__isnull` separately rather
than coalescing both sides — coalescing would compare NULL=0 as equal and
never update never-synced products. Batches over a
`pks = list(...values_list('pk', ...))` snapshot rather than
`range(0, count(), batch_size)`: `MainProduct.pk` is a never-reset
`BigAutoField`, so a single deleted row makes an offset-derived range stop
short and silently skip the tail. `timezone.now()` is read once above the
loop so one run stamps one `stock_updated_at`. Same gap-safe idiom as
`iter_unpushed_product_pk_batches` (`utils.py:682-698`, feeding
`push_pim_links`'s `pk__in=pks`, `utils.py:838`).
