# main_product_manager

`MainProduct` — the canonical product record. Owns the PIM integration.

## `.save()` deliberately doesn't rebuild the search vector

`MainProduct.save()` (`models.py:178`) is a bare `super().save()` — don't
"fix" that by adding a rebuild call. `_build_searchvector()` makes a PIM
network call per row (CLAUDE.md's cross-app-dependencies note); adding it to
`save()` would turn every save in the codebase into an HTTP request. Trace
whether a loop over `MainProduct` reaches `rebuild_search_vector()`
(`models.py:172`) regardless of how cheap the queryset looked — that's one
round-trip per row.

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

## The PIM cache's render-path cost — and why it bites tests too

`get_pim_data` (`utils.py:133`) on a cache miss does **both**: queues async
population (`_queue_pim_population`, `utils.py:141`) and falls through, next
line, to a synchronous `_fetch_pim_product(...)` (`utils.py:142`) — not an
early return, so a cold cache blocks the request on a PIM HTTP round-trip.
`get_file_url` (`utils.py:370`) has the same shape on a miss (`:380-387`),
minus the queueing.

`prefetch_pim_data` (`utils.py:322`) loops products one at a time, and
`MainProductTableView.get_context_data` (`views.py:214`) then calls
`get_file_url` again per entry (`views.py:226`): up to **2N** PIM calls per
cold page (the main page paginates 5 categories at a time, `views.py:89`,
each firing its own `hx-trigger="load"` fetch, `tables_bycat.html:53,82`).
**But calls dedupe by `pim_id`/file id, not by row** — `get_pim_data` caches
on `pim_product:{pim_id}` (`:136`), `get_file_url` on `pim_file:{file_id}`
(`:378`) — so real cost is bounded by distinct `pim_id`s on the page.
`MainProductTable._pim` still reads `pim_map` by `record.pk`
(`tables.py:230-231`).

**Rendering this table in a test makes live PIM HTTP calls unless
patched — and "live" can mean production.** `docker-compose.yml`'s
placeholder `PIM_TOKEN`/`PIM_HOST` only applies when no `.env` is picked up;
the repo-root `.env` (gitignored, absent from a fresh worktree per CLAUDE.md's
"Running more than one agent") holds **real** PIM credentials, so a compose
invocation that loads it — `--env-file <repo>/.env` included — runs the
suite against the live production PIM, and an unpatched test then makes real
calls to it. Working recipe (`test_grouping.py:29-30`): patch
`main_product_manager.views.prefetch_pim_data` and `.maybe_notify_pim_error`.
Creating `MainProduct`s is safe — `save()` doesn't reach PIM — but a test
needing a populated `search_vector` should set it directly with
`SearchVector` over local fields (`test_grouping.py:64-68`) instead of
calling `rebuild_search_vector()`. `get_file_url` has its own direct-mock
recipe instead (`GetFileUrlTests`, `tests.py:261`, patches
`main_product_manager.utils.site`).

## `get_file_url`'s PIM File payload — the precedence bug is fixed (#160/PR #169)

`get_file_url` (`utils.py:370`) now loops over `(f'{size}ThumbnailUrl',
*_PIM_FILE_URL_KEYS)`, `_PIM_FILE_URL_KEYS = ('url', 'downloadUrl')`
(`utils.py:340`), normalizing each candidate through `_absolute_pim_url`
(`utils.py:343-367`). Old bug: the return was
`"https://" + data.get(f'{size}ThumbnailUrl') or data.get('url') or
data.get('downloadUrl')` — `+` binds tighter than `or`, so a missing
`{size}ThumbnailUrl` raised an uncaught `TypeError` before either fallback
ran, and the fallbacks were dead code besides.
`views.py:226` and `render_pim_photo` (`tables.py:233-244`) now get a clean
`None`/URL instead of a 500 on a missing thumbnail.

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
`downloadUrl`, full-size
rather than a thumbnail, is what every caller actually renders. Matters for
the «PIM • Фото» column (`tables.py:47`, `render_pim_photo`): sized as a
thumbnail, renders full-size. **`downloadUrl` also needs a PIM session** —
an unauthenticated GET of the built URL returns `401`, so a browser without
a PIM login still renders a broken image, just not a 500 anymore. Not filed
as an issue yet.

## `MainProductFilter` — `.order_by()` bleeding into `GROUP BY`

`search_method`'s `.order_by("-rank")` (`filters.py:200`) folds into
`GROUP BY` once something downstream does `.values(...).annotate(...)` on
the same queryset — `get_table_data` (`views.py:194-201`) and
`search_rank`'s own docstring (`filters.py:183-189`) both explain the
workaround in place; the trap is real, not hypothetical, so don't drop
either without re-deriving why `search_rank` lives as a separate
`@staticmethod`.

## `_search_pim_id` docstring does not match its code

The docstring (`utils.py:159-170`) promises a search of `ContributorProduct`
"by priceManagerId, then by sku/number", reading `masterRecordId` to reach the
merged `Product`. The code (`utils.py:175-182`) does neither: a single-element
`searches` list — `Where(attribute='number', type='like', value=product.sku)`
— queried straight against `EntityList(name='Product', ...)`. No
`ContributorProduct` step, no `masterRecordId`, no `priceManagerId` fallback
— verified by reading both, not inferred.

Consequence: `sku` is nullable (`models.py:50-53`), so a `MainProduct` with no
`sku` can **never** resolve a `pim_id` through this path — a firmer
explanation for stuck-NULL `pim_id`s than the backlog and the 4h no-match
cache (`_PIM_NO_MATCH_TTL`, `utils.py:154`) alone.

## The 11 Celery tasks, and one that isn't

`sync_main_products_task` (`tasks.py:143`) has no `@shared_task` — it's a
plain function that `chain(...)`s the other 11 into one `apply_async()`
workflow; each link still goes through `execute_locked_task` on its own.
`reindex_pim_ids_task`'s fan-out uniquifies `task_name` per chunk
(`tasks.py:190`, `f"...:{pks[0]}-{pks[-1]}"`) — without it every batch would
contend on the same Redis lock.

## Three columns that look like fields but aren't

`supplier_product_price`, `supplier_product_rrp` and
`supplier_product_discount_price` are `tables.Column`s (`tables.py:39-41`)
offered in `AVAILABLE_COLUMN_GROUPS` (`columns.py:36-38`), but they're not
`MainProduct` fields — `MainProductTableView.get_table_data`
(`views.py:146-154`) builds each as a correlated `Subquery` on
`SupplierProduct`, ordered `-updated_at`. That's ordering a singleton, since
`SupplierProduct.main_product` is `unique=True`
(`supplier_product_manager/models.py:24-30`). `kaspi_price`, by contrast, is
a genuine field but an orphan in the column picker: offered at
`columns.py:33`, absent from `MainProductTable.Meta.fields`
(`tables.py:100-127`) — selecting it does nothing.

## `pim_id` is indexed, but the index doesn't make grouping cheap

`models.py:46-49` gives `pim_id` a plain `db_index=True` (added with #155),
distinct from the `GinIndex` on `search_vector`. It isn't `unique` — several
`MainProduct`s from different suppliers legitimately share one `pim_id`
(`sync_pim_relations`'s docstring, `utils.py:296-301`), which is exactly
what `grouping.py` collapses into one head row.

**The index removes a lookup cost, not the grouping cost.**
`MainProductTableView.get_table_data` (`views.py:145-185`) computes
`Window(partition_by=[F('grp_key')])` (`grouping.py:105-155`) per
category/uncategorised bucket, and `grp_key` is
`Coalesce(NullIf(pim_id, ''), Cast('id', TextField()))` (`grouping.py:50-64`)
— an expression, not the indexed column, so Postgres sorts every row in the
bucket regardless. On a restored production snapshot: 156,016 of 156,481
`MainProduct`s have no category, so the uncategorised bucket is effectively
the whole catalog while the largest real category holds 67 rows — the
window pass costs ~+6ms there versus ~70ms→~3s on the uncategorised one
(merge sort spilling ~107MB to disk; aggregates/counts only, per
prod-snapshot rule 3). **Benchmark grouping changes against the
uncategorised bucket** — a category table always looks fast.

## `render_<column>` is silently skipped when the cell value is empty

Every branching renderer on `MainProductTable` declares `empty_values=()`:
`actions` (`tables.py:33`), `stock_msg` (`:38`), `delivery_days` (`:45`), all
eight `pim_*` columns (`:47-54`). Without it, django-tables2 skips the
renderer and returns the column's `default` whenever the value is `None`/`""`
— a `render_foo` added without `empty_values=()` works for populated rows and
silently renders the table-wide `—` for empty ones, reading like a data
problem, not a wiring one. `GroupHeadRecord` (`grouping.py:207-244`) relies
on the inverse on purpose: `__getattr__` (`:238-241`) returns `None` for any
unset attribute, so an unhandled column falls through to `—` for free — only
the three branching renderers needed an `is_group_head` branch when #155
added the header row.

## `update_stocks` and `render_stock_msg` — NULL vs `0`, three copies of the check

`update_stocks`'s docstring (`utils.py:428-438`) covers why the candidate
filter tests `stock__isnull` separately rather than coalescing both sides —
that bug silently skipped never-synced products forever.
`UpdateStocksNullSafeTests` (`tests.py:51`) guards it.

The render-path version of the same NULL is fixed in two of three places.
`render_stock_msg` (`tables.py:166-186`) branches on `record.stock is None`
before zero/nonzero and returns `NO_STOCK_DATA`; `StockSelectionTests`
(`test_grouping.py:271-349`) guards it. `Supplier.get_delivery_days_for_stock`
(`supplier_manager/models.py:109-122`) also branches on `stock is None`
explicitly, though it still returns the zero-case value — a deliberate
default, not a silent conflation. Unfixed:
`core/templates/shopping_tab/includes/stock_badge.html:2,4` still tests
truthy `product.stock` — see [[core]], named here, not owned here.
