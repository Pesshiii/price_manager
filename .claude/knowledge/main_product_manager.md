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

"Idempotent, resumes cleanly" is true now, and was not before: the
no-match cache used to conflate a PIM *error* with a genuine no-match, so a
re-scan restarted inside the 4h window after an outage silently skipped the
rows the outage hit. The cache now records *which* it was and an error is held
for minutes, not hours (see the section below) — and a run that hit one is
recorded as an error instead of a success, so "it resumed" is checkable rather
than assumed.

## The PIM cache's render-path cost — and why it bites tests too

`get_pim_data` (`utils.py:138`) is synchronous on a cache miss or when
`refresh=True` — `_fetch_pim_product(...)` (`utils.py:146`) runs in-line, no
early return, so a cold cache blocks the request on a PIM HTTP round-trip.
`get_file_url` (`utils.py:436`) has the same shape on a miss (`:446-453`),
minus the queueing.

`prefetch_pim_data` (`utils.py:388`) loops products one at a time, and
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
recipe instead (`GetFileUrlTests`, `tests.py:356`, patches
`main_product_manager.utils.site`).

## `get_file_url`'s PIM File payload — the precedence bug is fixed (#160/PR #169)

`get_file_url` (`utils.py:436`) now loops over `(f'{size}ThumbnailUrl',
*_PIM_FILE_URL_KEYS)`, `_PIM_FILE_URL_KEYS = ('url', 'downloadUrl')`
(`utils.py:406`), normalizing each candidate through `_absolute_pim_url`
(`utils.py:409-433`). Old bug: the return was
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

## `_search_pim_id_result`: one `like` on `number`, and why an empty answer has to say *why*

`_search_pim_id_result(product) -> tuple[str | None, str]` (`utils.py:184`) is
the resolver; `_search_pim_id` (`utils.py:251`) is a thin id-only wrapper kept
for `_resolve_pim_id`, which has nothing to decide on a miss. One round-trip:
`Where(attribute='number', type='like', value=product.sku)` against
`EntityList(name='Product', select=['id'])` — a direct `Product` search, no
`ContributorProduct` step, no `masterRecordId`, no `priceManagerId` fallback.

The outcome is one of five (`utils.py:173-177`): `_SEARCH_FOUND`,
`_SEARCH_ABSENT`, `_SEARCH_AMBIGUOUS`, `_SEARCH_ERROR`, `_SEARCH_NO_SKU`.
**Only `_SEARCH_ABSENT` means PIM was asked and answered "no such product."**
That distinction is load-bearing rather than tidy, because
`push_missing_pim_products` (`utils.py:638`) *writes to PIM* — it creates a
`PriceManagerProduct` — so anything else reaching it creates a duplicate
record for a product that may already be there. `create_pim_links`
(`utils.py:656`) and `reindex_pim_ids_batch` (`utils.py:728`) branch on the
outcome, not on `pim_id is None`. A new caller that writes on a miss must do
the same.

**The three edges this closed.** Until then the search returned the first
non-empty id with no count check; a no-sku product was not skipped but sent an
*unconstrained* `like` (`Where.get()` omits the `value` key entirely when it is
None, `pim_api/__init__.py:24-25`); and an API error fell through to the same
`cache.set(no_match_key, True, ...)` as a genuine miss. The last one was the
severe one, and not for the reason it looks: a PIM outage mid-scan did not just
suppress retries for 4h, it fed every unlinked row it touched to
`push_missing_pim_products`. Do not restore the older, tidier claim that a
no-sku product "can never resolve" — that was an assumption the query-string
construction contradicted.

**How each is handled now**: several matches log a warning and link nothing
(`_SEARCH_AMBIGUOUS`); no sku returns before any request (`_SEARCH_NO_SKU`,
restoring the guard `86f3289` dropped — not the `priceManagerId` search it
dropped alongside); a failed request returns `_SEARCH_ERROR`.

**One cache key, deliberately.** `pim_no_match:{pk}` holds the outcome string
rather than a bare flag, so `get_pim_data_for_product`'s single `cache.delete`
on the 404-recovery path stays correct and there is no second key to leave
stale. TTLs differ by reason: `_PIM_SEARCH_ERROR_TTL` = 5 min for an error,
`_PIM_NO_MATCH_TTL` = 4h for a confirmed absence or an ambiguous match, those
being conditions of the data rather than of the network (`utils.py:166-167`).
A legacy bare `True` matches no outcome, so it is dropped and re-searched
instead of guessed at (`utils.py:212-217`).

**Both scans raise `PimSearchError` (`utils.py:180`)** when a search went
unanswered — *after* their writes, so committed progress survives. It is the
only durable signal there is: `maybe_notify_pim_error` is DEBUG-gated
(`utils.py:45`) and prod runs under `settings.prod`, so `_PIM_LAST_ERROR_KEY`
is written and read by nobody there; `TaskRunHistory` (from
`execute_locked_task`'s `except`, `core/task_runner.py:112-132`) is what
records it. The return must stay a 2-tuple — `_normalize_updated_count`
(`core/task_runner.py:14-21`) sums every numeric element, so a third "failed"
element would silently inflate `updated_count`. Ambiguity does not raise.
Consequence: `manage.py run_task` in sync mode calls the task function directly
(`management/commands/run_task.py:81`), so its no-argument form now stops at
the failing task instead of continuing down the loop.

**The cost of that correctness, in `create_pim_links` only.** Its window is
`filter(pim_id__isnull=True)[:1000]` under `Meta.ordering = ['id']` — the same
lowest-1000 unlinked rows every run — and it used to drain because every
product left the unlinked set: linked, or pushed to PIM and given the id
`_push_pim_products` wrote back. An unsearchable product now does neither, so
it would hold a slot and a `time.sleep(delay)` at the head of the window
forever. No-sku rows are excluded from the queryset itself
(`utils.py:657-670`); drop that exclusion if a search that works without an sku
is ever added back. `_SEARCH_AMBIGUOUS` rows have no such containment by
design — an ambiguous match is a data problem someone has to settle in PIM.

**How it got this way.** `86f3289` collapsed a two-element `searches` list
(priceManagerId, then sku) to one and dropped its `if product.sku` guard;
`48c31f8` swapped the entity from `ContributorProduct`/`masterRecordId` to
`Product`/`id`. Neither touched the prose, so three docstrings outlived their
code by two commits and were reported as having been read as the real lookup
path during #164's triage (not visible in that issue's body or comments —
grepped). The docs-only fix (#172) corrected the prose and documented the three
edges; this work closed them.

**Testing.** `site` is bound into `utils`'s own namespace (`utils.py:16`), so
tests patch `main_product_manager.utils.site`, **not** `pim_client.site`.
`SearchPimIdOutcomeTests` and `PimScanPushGuardTests` (`tests.py:532`, `:658`)
are the pattern, both under `@override_settings(CACHES=LOCMEM_CACHE)` — the
outcome cache has to be visible to in-process assertions rather than the
worker container's shared Redis.

**Stale UI copy this produces, still not fixed:**
`templates/mainproduct/partials/detail.html:78` tells the user, in Russian,
"Проверьте соответствие priceManagerId/названия" — but the lookup matches
`number`/sku only; neither `priceManagerId` nor the product name participates.
Correct copy needs to name `sku`/`number` and cover the no-sku case, which is
now an explicit early return rather than a stray unconstrained query. This line
is the last surviving `priceManagerId` reference in the repo outside `pim_api`
itself (grepped, not assumed).

## The 11 Celery tasks, and one that isn't

`sync_main_products_task` (`tasks.py:143`) has no `@shared_task` — it's a
plain function that `chain(...)`s the other 11 into one `apply_async()`
workflow; each link still goes through `execute_locked_task` on its own.
`reindex_pim_ids_task`'s fan-out uniquifies `task_name` per chunk
(`tasks.py:190`, `f"...:{pks[0]}-{pks[-1]}"`) — without it every batch would
contend on the same Redis lock.

## Three columns that look like fields but aren't

**Three writers feed `MainProductLog`, and the dominant one is not the
name-obvious one.** `utils.update_logs()` (`utils.py:776`) reads like the
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
(`sync_pim_relations`'s docstring, `utils.py:362-367`), which is exactly
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

`update_stocks`'s docstring (`utils.py:494-513`) covers why the candidate
filter tests `stock__isnull` separately rather than coalescing both sides —
that bug silently skipped never-synced products forever.
`UpdateStocksNullSafeTests` (`tests.py:51`) guards it; each of its tests
creates a single `MainProduct`, so none of them exercise batching — see the
next section.

The render-path version of the same NULL is fixed in two of three places.
`render_stock_msg` (`tables.py:166-186`) branches on `record.stock is None`
before zero/nonzero and returns `NO_STOCK_DATA`; `StockSelectionTests`
(`test_grouping.py:271-349`) guards it. `Supplier.get_delivery_days_for_stock`
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
production. `update_stocks` (`utils.py:522-528`) instead snapshots
`pks = list(MainProduct.objects.order_by('pk').values_list('pk', flat=True))`
once, then `chunk = pks[i:i+batch_size]` bounds the query with
`pk__gte=chunk[0], pk__lte=chunk[-1]` — equivalent to `pk__in=chunk` (chunk is
a contiguous slice of every existing pk in order, so nothing sits strictly
between its ends) without shipping a `batch_size`-long IN list. Same
gap-safe idiom as `iter_pim_id_pk_batches` (`utils.py:711-725`), which feeds
`reindex_pim_ids_batch`'s `pk__in=pks` (`utils.py:741`).

`timezone.now()` (`utils.py:515`) is read once, above the loop — read
per-iteration it produces one distinct `stock_updated_at` per chunk instead
of one per run; guarded by
`UpdateStocksBatchingTests.test_one_run_stamps_one_timestamp`
(`tests.py:202`).

`UpdateStocksBatchingTests` (`tests.py:136-227`) is what actually exercises
multi-batch behaviour: `batch_size=2` over 5 products with distinct stocks
(so a chunk-scoping slip shows in the logs, not just the counts), a
deleted-row pk gap not dropping the tail, the timestamp guard above, and
`logs=False` (`tests.py:213`) — the one branch the loop adds statements to
without bounding a log list, and which no caller reaches.

`batch_size` had no caller until this fix — `update_stocks_task`
(`main_product_manager/tasks.py:66-72`, `product_price_manager/tasks.py:18-23`)
both call `runner=update_stocks` bare, and `run_task.py`'s `--batch-size`
flag only reaches `create_pim_links`/`reindex_pim_ids` (`run_task.py:67`).
