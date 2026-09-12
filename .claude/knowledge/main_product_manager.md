# main_product_manager

`MainProduct` — the canonical product record. Owns the PIM integration. Its
link to PIM is `MainProduct.product`, a nullable FK to `product.Product`
(see [[product]]) — replacing `MainProduct`'s own CharField `pim_id` as of
the `MainProduct.product` FK conversion. `SupplierProduct.pim_id` is a
**separate, still-live CharField** (`utils.py:685,688`), untouched by this —
don't go looking for a FK there. The sections below are line-numbered
against the tree as of that conversion (worktree `mainproduct-product-fk`),
so re-check line numbers after it merges and drifts further.

## `.save()` deliberately doesn't rebuild the search vector

`MainProduct.save()` (`models.py:180`) is a bare `super().save()` — don't
"fix" that by adding a rebuild call. `_build_searchvector()` (`models.py:151`)
makes a PIM network call per row (CLAUDE.md's cross-app-dependencies note);
adding it to `save()` would turn every save in the codebase into an HTTP
request. Trace whether a loop over `MainProduct` reaches
`rebuild_search_vector()` (`models.py:174`) regardless of how cheap the
queryset looked — that's one round-trip per row.

## PIM scans run with `atomic=False` — moving the write is not enough

CLAUDE.md's "Shared infrastructure" section covers why these two runners pass
`atomic=False` (`tasks.py` `create_pim_links_task`/`reindex_pim_ids_batch_task`).
What it doesn't say: hoisting `bulk_update` out of the API loop does **not**
help on its own — `execute_locked_task`'s transaction opens *before* the
runner is called, so it stays open for the whole loop regardless of where the
write lands. Do **not** wrap `push_missing_pim_products` (HTTP, `bulk_update`
and `sleep` interleaved per chunk, underneath `_push_pim_products`) in a
transaction "to compensate" — that breaks its promise that one failing chunk
doesn't lose the others.

"Idempotent, resumes cleanly" is true now, and was not before: the
no-match cache used to conflate a PIM *error* with a genuine no-match, so a
re-scan restarted inside the 4h window after an outage silently skipped the
rows the outage hit. The cache now records *which* it was and an error is held
for minutes, not hours (see the section below) — and a run that hit one is
recorded as an error instead of a success, so "it resumed" is checkable rather
than assumed.

## `MainProduct.product` — the FK that replaced `pim_id`, and its traps

**`group_key()` (`grouping.py:50-79`) must not be `Coalesce` over `Concat`.**
It partitions the main page so several `MainProduct`s sharing one PIM
`product.Product` collapse into one head row. The first draft wrote it as
`Coalesce(Concat(Value('pim-'), Cast('product_id', TextField())),
Concat(Value('mp-'), Cast('id', TextField())))` and it silently broke:
Postgres `CONCAT()` treats NULL as the empty string (unlike `||`), so
`Concat('pim-', NULL)` returns `'pim-'`, not NULL — `Coalesce` never reaches
its second branch, and **every unlinked product collapses into one fake
group keyed `'pim-'`**, exactly what the key exists to prevent. The fix is
`Case/When(product__isnull=True, then=Concat('mp-', id))`, `default=Concat('pim-',
product_id)` — an explicit branch, not a NULL-swallowing fallback.

**Both branches must carry their prefix**, for a second, independent reason:
`product_id` and `MainProduct.id` are separate integer sequences. Without
`'pim-'`/`'mp-'`, an unlinked row with `id = N` silently joins the group of
whatever is linked to a `Product` with `id = N`. The old string `pim_id` was
immune purely because it never looked like a small integer — this hazard is
new with the FK and has no precedent in the file. Guarded by two tests in
`test_grouping.py`: `test_unlinked_products_never_group` (`:190-204`) pins
the NULL-swallowing case, `test_unlinked_product_does_not_join_group_with_matching_product_id`
(`:206-225`) pins an explicit `Product.id` collision against an unlinked
`MainProduct.pk`.

**`recalculate_search_vectors` absorbs the FK hop — don't push
`select_related('product')` out to its callers.** `_build_searchvector()`
used to read `self.pim_id` off the row for free; it now calls `_pim_id_of()`
(`utils.py:28-40`), a module function (deliberately not a `MainProduct`
property — a property named `pim_id` would keep working in templates and
silently break in `.filter()`/annotations, where the lookup is
`product__pim_id`), which crosses the FK. The fix already lives in the one
place that needed it: `recalculate_search_vectors` (`utils.py:549-559`) adds
`.select_related('supplier', 'manufacturer', 'product')` itself (`:554`), so
its three callers — `main_product_manager/tasks.py`,
`supplier_product_manager/tasks.py:277`, `supplier_product_manager/functions.py`,
plus `main_product_manager/views.py:421-422` (which only passes
`select_related('supplier', 'manufacturer')`) — stay correct without change.
Don't add `select_related('product')` at those call sites (redundant) and
don't remove it from `recalculate_search_vectors` (N+1 per already-linked
row). `create_pim_links` (`utils.py:765-819`) is the deliberate exemption,
commented in place at `:774-777`: it only ever *writes* the link, never reads
it via `_pim_id_of`, so it skips `select_related('product')` on purpose.

**`_push_pim_products` stores the wrong PIM entity's id — known, preserved on
purpose, open decision with the user.** `_push_pim_products`
(`utils.py:625-681`) creates PIM `PriceManagerProduct` records via
`upsertAsync` and persists the id PIM returns through a caller-supplied
`link_fn` — split out because the two callers store the link differently:
`_link_supplier_products` (`utils.py:684-692`) still writes
`SupplierProduct.pim_id`, a plain CharField; `_link_main_products`
(`utils.py:695-717`) writes the FK. Every *read* path (`get_pim_data`,
`_search_pim_id_result`) addresses the PIM **`Product`** entity, but
`PriceManagerProduct.id` is not a `Product` id — `PriceManagerProduct.productId`
is. Under the old CharField this mismatch sat inert as a string that never
resolved. **Under the FK it now materialises a placeholder `product.Product`
row per push** — `_link_main_products` calls `_pim_product_row(pim_id)`
(`utils.py:43-62`, `get_or_create` on `product.Product.pim_id`) with the
unresolvable id, so [[product]] gains a real row keyed by a
`PriceManagerProduct` id instead of a `Product` id. Preserved deliberately,
per the comment at `utils.py:698-706` — the existing "already pushed, don't
re-push" suppression depends on the FK being set to *something* — and
flagged there as an open decision with the user, **not as correct
behaviour**: don't "clean this up" unilaterally. `PimProductWidget`
(`resources.py:258-280`) does the same `get_or_create` for the Excel-import
path (`MainProductPimImportResource`, `resources.py:286-296`), for the
legitimate reason: PIM exports can carry ids the local mirror doesn't have
yet.

## The PIM cache's render-path cost — and why it bites tests too

`get_pim_data` (`utils.py:185-210`) is synchronous on a cache miss or when
`refresh=True` — `_fetch_pim_product` (def `utils.py:115`, called at `:193`)
runs in-line, no early return, so a cold cache blocks the request on a PIM
HTTP round-trip. `get_file_url` (`utils.py:502-529`) has the same shape on a
miss (`:511-519`), minus the queueing.

`prefetch_pim_data` (`utils.py:453-469`) loops products one at a time, and
`MainProductTableView.get_context_data` (`views.py:214`) then calls
`get_file_url` again per entry (`views.py:226`): up to **2N** PIM calls per
cold page (the main page paginates 5 categories at a time, `views.py:89-90`,
each firing its own `hx-trigger="load"` fetch, `tables_bycat.html:53,82`).
**But calls dedupe by `pim_id`/file id, not by row** — `get_pim_data` caches
on `pim_product:{pim_id}` (`:188`), `get_file_url` on `pim_file:{file_id}`
(`:510`) — so real cost is bounded by distinct `pim_id`s on the page.
`MainProductTable._pim` still reads `pim_map` by `record.pk`
(`tables.py:231-232`).

**Rendering this table in a test makes live PIM HTTP calls unless
patched — and "live" can mean production.** `docker-compose.yml`'s
placeholder `PIM_TOKEN`/`PIM_HOST` only applies when no `.env` is picked up;
the repo-root `.env` (gitignored, absent from a fresh worktree per CLAUDE.md's
"Running more than one agent") holds **real** PIM credentials, so a compose
invocation that loads it — `--env-file <repo>/.env` included — runs the
suite against the live production PIM, and an unpatched test then makes real
calls to it. Working recipe: `GroupingTestCase.PIM_PATCHES`
(`test_grouping.py:73-77`, applied in `setUp` at `:79-86`) patches
`main_product_manager.views.prefetch_pim_data`, `.maybe_notify_pim_error`,
and `main_product_manager.utils.site` with `_PimUnreachable()`
(`test_grouping.py:45-58`) — a class that raises on any attribute access
rather than a `MagicMock`, because a "working" mock would cache a fabricated
PIM response and queue a real background task against it. Creating
`MainProduct`s is safe — `save()` doesn't reach PIM — but a test needing a
populated `search_vector` should set it directly with `SearchVector` over
local fields (`test_grouping.py:122`, inside the `make_product` factory,
`:103-123`) instead of calling `rebuild_search_vector()`. `get_file_url` has
its own direct-mock recipe instead (`GetFileUrlTests`, `tests.py:357`,
patches `main_product_manager.utils.site`).

## `get_file_url`'s PIM File payload — the precedence bug is fixed (#160/PR #169)

`get_file_url` (`utils.py:502-529`) loops over `(f'{size}ThumbnailUrl',
*_PIM_FILE_URL_KEYS)`, `_PIM_FILE_URL_KEYS = ('url', 'downloadUrl')`
(`utils.py:472`), normalizing each candidate through `_absolute_pim_url`
(`utils.py:475-499`). `views.py:226` and `render_pim_photo`
(`tables.py:234-245`) get a clean `None`/URL rather than raising on a missing
thumbnail.

**The lasting fact is the payload shape**, sampled read-only against the
live PIM — both the `File` list endpoint and the single-record endpoint
`get_file_url` actually calls, across every record returned:

- `smallThumbnailUrl` / `mediumThumbnailUrl` / `largeThumbnailUrl` and `url`
  — **do not exist** on the record at all.
- `downloadUrl` — present on every record, always **scheme-less**
  `host/path` (why `_absolute_pim_url` picks the scheme per-value instead of
  prepending one unconditionally — a future PIM sending an absolute
  `url`/thumbnail won't come out double-schemed).
- The record does carry `path` and `thumbnailsPath` (plus `folderPath`,
  `storageId`, `mimeType`, `extension`, `width`/`height`, `hash`) — none read
  by `get_file_url`.

So `size` currently selects a key that never exists —
`'small'|'medium'|'large'` has **no observable effect today** — and
`downloadUrl`, full-size rather than a thumbnail, is what every caller
actually renders. Matters for the «PIM • Фото» column (`tables.py:47`,
`render_pim_photo`): sized as a thumbnail, renders full-size. **`downloadUrl`
also needs a PIM session** — an unauthenticated GET of the built URL returns
`401`, so a browser without a PIM login still renders a broken image, just
not a 500 anymore. Not filed as an issue yet.

## `MainProductFilter` — `.order_by()` bleeding into `GROUP BY`

`search_method`'s `.order_by("-rank")` (`filters.py:200`) folds into
`GROUP BY` once something downstream does `.values(...).annotate(...)` on
the same queryset — `get_table_data` (`views.py:194-201`) and
`search_rank`'s own docstring (`filters.py:183-189`) both explain the
workaround in place; the trap is real, not hypothetical, so don't drop
either without re-deriving why `search_rank` lives as a separate
`@staticmethod`.

## `_search_pim_id_result`: one `equals` on `number`, and why an empty answer has to say *why*

`_search_pim_id_result(product) -> tuple[str | None, str]` (`utils.py:231`)
is the resolver; `_search_pim_id` (`utils.py:307`) is a thin id-only wrapper
kept for `_resolve_pim_id` (`utils.py:316`), which has nothing to decide on a
miss. One round-trip: `Where(attribute='number', type='equals',
value=product.sku)` (`utils.py:280-286`) against `EntityList(name='Product',
select=['id'])` — a direct `Product` search, no `ContributorProduct` step, no
`masterRecordId`, no `priceManagerId` fallback.

**It must stay `equals`, and this was measured, not reasoned.** AtroPIM passes
a `like` value straight into a SQL LIKE: against the live API
`like '2001_-04_z01'` returns the product numbered `20015-04_z01` (so `_` is a
single-character wildcard) and `like '%'` returns all 36k rows. PIM numbers
routinely carry `_` — `20015-04_z01`, `20110-8_z02` — and sku is
supplier-supplied, so under `like` a sku can match a *different* product.
The `_SEARCH_AMBIGUOUS` guard does not save you there: it only fires on >1
match, and the dangerous case is exactly one wrong match, which returns
`_SEARCH_FOUND` and gets written to the DB with nothing ever re-checking it.
Switching costs nothing — bare `like` never did substring matching either (a
genuine prefix returns no rows), so `equals` only removes the wildcard
surface.

Sampled alongside: 2400 consecutive `Product.number` values, **no duplicates**.
So `_SEARCH_AMBIGUOUS` may be unreachable under `equals` in practice. It is
kept anyway — the sample is not the whole 36k catalog, nothing checked
guarantees uniqueness, and the guard costs one `len()`. Don't read a passing
`test_ambiguous_match_links_nothing` as evidence PIM returns duplicates.

The outcome is one of five (`utils.py:220-224`): `_SEARCH_FOUND`,
`_SEARCH_ABSENT`, `_SEARCH_AMBIGUOUS`, `_SEARCH_ERROR`, `_SEARCH_NO_SKU`.
**Only `_SEARCH_ABSENT` means PIM was asked and answered "no such product."**
That distinction is load-bearing rather than tidy, because
`push_missing_pim_products` (`utils.py:746-762`) *writes to PIM* — it creates a
`PriceManagerProduct` — so anything else reaching it creates a duplicate
record for a product that may already be there. `create_pim_links`
(`utils.py:765-819`) and `reindex_pim_ids_batch` (`utils.py:845-892`) branch on
the outcome, not on `product_id is None`. A new caller that writes on a miss
must do the same. (Earlier revisions returned the first non-empty id with no
count check, sent no-sku products as an unconstrained match, and conflated a
PIM error with a genuine miss under one cache flag — all three closed here;
`Where.get()` still omits the `value` key entirely when it is `None`,
`pim_api/__init__.py:24-25`, which is why `_SEARCH_NO_SKU` returns before any
request rather than relying on that.)

**How each is handled now**: several matches log a warning and link nothing
(`_SEARCH_AMBIGUOUS`); no sku returns before any request (`_SEARCH_NO_SKU`);
a failed request returns `_SEARCH_ERROR`.

**One cache key, deliberately.** `pim_no_match:{pk}` holds the outcome string
rather than a bare flag, so `get_pim_data_for_product`'s single `cache.delete`
(`utils.py:355`) on the 404-recovery path stays correct and there is no
second key to leave stale. TTLs differ by reason: `_PIM_SEARCH_ERROR_TTL` = 5
min for an error, `_PIM_NO_MATCH_TTL` = 4h for a confirmed absence or an
ambiguous match, those being conditions of the data rather than of the
network (`utils.py:213-214`). A legacy bare `True` matches no outcome, so it
is dropped and re-searched instead of guessed at (`utils.py:270-273`).

**Both scans raise `PimSearchError` (`utils.py:227-228`)** when a search went
unanswered — *after* their writes, so committed progress survives. `TaskRunHistory`
(from `execute_locked_task`'s `except`, `core/task_runner.py:112-132`) is what
records it. **`maybe_notify_pim_error` (`utils.py:82-112`) now fires in prod
too** — earlier it was gated on `settings.DEBUG`, which inverted the intent
(DEBUG defaults false, so production, the one environment where a PIM outage
costs something, got no signal at all); it's per-user and throttled
(`_PIM_NOTIF_THROTTLE_TTL`, 30 min) instead, so `TaskRunHistory` is no longer
the *only* durable signal, just the unconditional one. The return must stay a
2-tuple — `_normalize_updated_count` (`core/task_runner.py:14-21`) sums every
numeric element, so a third "failed" element would silently inflate
`updated_count`. Ambiguity does not raise. Consequence:
`manage.py run_task` in sync mode calls the task function directly
(`management/commands/run_task.py:81`), so its no-argument form now stops at
the failing task instead of continuing down the loop.

**The cost of that correctness, in `create_pim_links` only.** Its window is
`filter(product__isnull=True).exclude(sku__isnull=True).exclude(sku='')[:1000]`
(`utils.py:778-782`) under `Meta.ordering = ['id']` — the same lowest-1000
unlinked rows every run — and it used to drain because every product left the
unlinked set: linked, or pushed to PIM and given the id `_push_pim_products`
wrote back. An unsearchable product now does neither, so it would hold a slot
and a `time.sleep(delay)` at the head of the window forever. No-sku rows are
excluded from the queryset itself; drop that exclusion if a search that works
without an sku is ever added back. `_SEARCH_AMBIGUOUS` rows have no such
containment by design — an ambiguous match is a data problem someone has to
settle in PIM.

**Testing.** `site` is bound into `utils`'s own namespace (`utils.py:16`), so
tests patch `main_product_manager.utils.site`, **not** `pim_client.site`.
`SearchPimIdOutcomeTests` and `PimScanPushGuardTests` (`tests.py:537`, `:690`)
are the pattern, both under `@override_settings(CACHES=LOCMEM_CACHE)` — the
outcome cache has to be visible to in-process assertions rather than the
worker container's shared Redis.

**Stale UI copy — fixed.** `templates/mainproduct/partials/detail.html:78`
used to tell the user "Проверьте соответствие priceManagerId/названия" while
the lookup actually matched `number`/sku and neither `priceManagerId` nor the
name participated. It now reads "Поиск идёт по артикулу товара — проверьте,
совпадает ли он с полем «number» в PIM, или привяжите вручную" — matches the
real lookup, and `priceManagerId` no longer appears anywhere in the repo
(grepped).

## The 11 Celery tasks, and one that isn't

`sync_main_products_task` (`tasks.py:138`) has no `@shared_task` — it's a
plain function that `chain(...)`s the other 11 into one `apply_async()`
workflow; each link still goes through `execute_locked_task` on its own.
`reindex_pim_ids_task`'s fan-out uniquifies `task_name` per chunk
(`tasks.py:185`, `f"...:{pks[0]}-{pks[-1]}"`) — without it every batch would
contend on the same Redis lock.

## Three columns that look like fields but aren't

**Three writers feed `MainProductLog`, and the dominant one is not the
name-obvious one.** `utils.update_logs()` (`utils.py:895`) reads like the
writer, but [[product_price_manager]]'s `PriceManager.apply(logs=True)`
(`product_price_manager/models.py:302-308`) and `PriceTag.get_mp()`
(`:426-434`) also insert rows, reached via module-level `update_prices()`
(`:455`) — which has its own beat entry and is a step in the
`sync_main_products_task` chain above. `get_mp()` is reached unconditionally
every run: `update_prices()`'s `get_updated_mps()` helper calls it for every
`PriceTag` with `p_manager__isnull=True` (three separate calls, `:488,493,498`
— manual/orphan tags, as opposed to the `PriceManager.apply()` path for
rule-driven ones). Any change to `MainProductLog` has to account for all
three call sites, not just the one named after the model.

`supplier_product_price`, `supplier_product_rrp` and
`supplier_product_discount_price` are `tables.Column`s (`tables.py:39-41`)
offered in `AVAILABLE_COLUMN_GROUPS` (`columns.py:36-38`), but they're not
`MainProduct` fields — `MainProductTableView.get_table_data`
(`views.py:146-160`) builds each as a correlated `Subquery` on
`SupplierProduct`, ordered `-updated_at`. That's ordering a singleton, since
`SupplierProduct.main_product` is `unique=True`
(`supplier_product_manager/models.py:24-30`). `kaspi_price`, by contrast, is
a genuine field but an orphan in the column picker: offered at
`columns.py:33`, absent from `MainProductTable.Meta.fields`
(`tables.py:100-128`) — selecting it does nothing.

## The `product` FK is indexed automatically, but the index doesn't make grouping cheap

`models.py:46-51` gives `MainProduct.product` a plain nullable
`ForeignKey('product.Product', ...)`, not `unique` — several `MainProduct`s
from different suppliers legitimately share one linked `Product`
(`sync_pim_relations`'s docstring, `utils.py:426-432`), which is exactly what
`grouping.py` collapses into one head row. Django gives an FK column its own
btree index automatically, same as the old `pim_id` CharField's explicit
`db_index=True` did — that part didn't change with the conversion.

**The index removes a lookup cost, not the grouping cost.**
`MainProductTableView.get_table_data` (`views.py:146-213`) computes
`Window(...)` per-partition inside `annotate_groups`
(`grouping.py:120-171`), and `grp_key` is still an *expression* —
`Case/When` over `Concat(..., Cast('product_id'/'id', TextField()))`
(`grouping.py:72-79`) — not the indexed column itself, so Postgres sorts
every row in the bucket regardless of the FK's index. On a restored
production snapshot: 156,016 of 156,481 `MainProduct`s have no category, so
the uncategorised bucket is effectively the whole catalog while the largest
real category holds 67 rows — the window pass costs ~+6ms there versus
~70ms→~3s on the uncategorised one (merge sort spilling ~107MB to disk;
aggregates/counts only, per prod-snapshot rule 3). **Benchmark grouping
changes against the uncategorised bucket** — a category table always looks
fast. Consistent with this: `GroupHeadRecord.__init__` (`grouping.py:237-244`)
deliberately exposes `product_id` (the local FK's target pk) rather than
resolving and exposing `pim_id`, precisely to avoid adding a `product.Product`
join to that hot path.

## `render_<column>` is silently skipped when the cell value is empty

Every branching renderer on `MainProductTable` declares `empty_values=()`:
`actions` (`tables.py:33`), `stock_msg` (`:38`), `delivery_days` (`:45`), all
eight `pim_*` columns (`:47-54`). Without it, django-tables2 skips the
renderer and returns the column's `default` whenever the value is `None`/`""`
— a `render_foo` added without `empty_values=()` works for populated rows and
silently renders the table-wide `—` for empty ones, reading like a data
problem, not a wiring one. `GroupHeadRecord` (`grouping.py:222-263`) relies
on the inverse on purpose: `__getattr__` (`:257-260`) returns `None` for any
unset attribute, so an unhandled column falls through to `—` for free — only
the three branching renderers needed an `is_group_head` branch when #155
added the header row.

## `update_stocks` and `render_stock_msg` — NULL vs `0`, three copies of the check

`update_stocks`'s docstring (`utils.py:562-582`) covers why the candidate
filter tests `stock__isnull` separately rather than coalescing both sides —
that bug silently skipped never-synced products forever.
`UpdateStocksNullSafeTests` (`tests.py:52`) guards it; each of its tests
creates a single `MainProduct`, so none of them exercise batching — see the
next section.

The render-path version of the same NULL is fixed in two of three places.
`render_stock_msg` (`tables.py:167-187`) branches on `record.stock is None`
before zero/nonzero and returns `NO_STOCK_DATA`; `StockSelectionTests`
(`test_grouping.py:351`) guards it. `Supplier.get_delivery_days_for_stock`
(`supplier_manager/models.py:109-122`) also branches on `stock is None`
explicitly, though it still returns the zero-case value — a deliberate
default, not a silent conflation. Unfixed:
`core/templates/shopping_tab/includes/stock_badge.html:2,4` still tests
truthy `product.stock` — see [[core]], named here, not owned here.

## `update_stocks` batching — the pk-range trap (c284b65)

Chunk bounds must come from a real pk snapshot, never from
`range(0, count(), batch_size)`. `pk__gte=i, pk__lt=i+batch_size` looks like
the natural way to slice that range and is badly wrong: as a negative
control it updated 0 of 5 products in `UpdateStocksBatchingTests`, not merely
the tail. `MainProduct.pk` is a `BigAutoField` whose sequence is never reset,
so live pks sit far above `count()` in any real or test DB, and a single
deleted row (`count() < max(pk)`) is enough to trigger the same gap in
production. `update_stocks` (`utils.py:591-599`) instead snapshots
`pks = list(MainProduct.objects.order_by('pk').values_list('pk', flat=True))`
once, then `chunk = pks[i:i+batch_size]` bounds the query with
`pk__gte=chunk[0], pk__lte=chunk[-1]` — equivalent to `pk__in=chunk` (chunk is
a contiguous slice of every existing pk in order, so nothing sits strictly
between its ends) without shipping a `batch_size`-long IN list. Same
gap-safe idiom as `iter_pim_id_pk_batches` (`utils.py:828-842`), which feeds
`reindex_pim_ids_batch`'s `pk__in=pks` (`utils.py:858`).

`timezone.now()` (`utils.py:584`) is read once, above the loop — read
per-iteration it produces one distinct `stock_updated_at` per chunk instead
of one per run; guarded by
`UpdateStocksBatchingTests.test_one_run_stamps_one_timestamp`
(`tests.py:203`).

`UpdateStocksBatchingTests` (`tests.py:137-252`) is what actually exercises
multi-batch behaviour: `batch_size=2` over 5 products with distinct stocks
(so a chunk-scoping slip shows in the logs, not just the counts), a
deleted-row pk gap not dropping the tail, the timestamp guard above, and
`logs=False` (`tests.py:214`) — the one branch the loop adds statements to
without bounding a log list, and which no caller reaches.

`batch_size` had no caller until this fix — `update_stocks_task`
(`main_product_manager/tasks.py:65-72`, `product_price_manager/tasks.py:18-23`)
both call `runner=update_stocks` bare, and `run_task.py`'s `--batch-size`
flag only reaches `create_pim_links`/`reindex_pim_ids` (`run_task.py:67`).
