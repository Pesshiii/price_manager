---
title: Product photos — ProductPhoto and the nightly photo pass
summary: ProductPhoto mirrors a Product's PIM image files plus their anonymous public links; the nightly pass in batches of PIM products, the weekly full link pass, the browser fallback, the card carousel, and the test traps.
code: price_manager/product/models.py, price_manager/product/migrations/0019_productphoto.py, price_manager/product/services/photos.py, price_manager/product/tasks.py, price_manager/price_manager/settings/celery.py, price_manager/product/tables.py, price_manager/product/templates/product/detail.html, price_manager/static/js/pim-photo-fallback.js
---
# Product photos — `ProductPhoto` and the nightly pass

`raw_data` carries only `mainImageId`, and every PIM image URL answers 401
without the token (the proxy exists for that, see
[[main_product_manager/detail-page-and-photos]]). `ProductPhoto` mirrors all of
a product's image files plus, where PIM has one, their **public link**, so the
browser can fetch photos from PIM directly and our 3 gunicorn workers stay out
of it (`docker-compose.yml:79`; the proxy costs ~2 PIM requests per cold image).

## Model — `models.py:174-207`, migration `0019_productphoto`

`product` (FK, `related_name='photos'`, CASCADE), `pim_file_id`, `position`,
`is_main`, `public_url` (`URLField(max_length=500)`, empty = no link).
`Meta.ordering = ['position', 'pk']`; unique `(product, pim_file_id)`
(`product_photo_file_uniq`). There is no `name` or `sorting` column: `position`
is computed during the scan. Written only by `services/photos.py`.
`public_url` is capped at 500 because `pim_public_url` rejects longer links
(`main_product_manager/utils.py:452-463`).

## PIM facts (measured on the live PIM 2026-10-12, read-only; reported to the keeper, not re-run)

- A product's files are `ProductFile {productId, fileId, fileName,
  isMainImage, sorting}`; the list carries no file type.
- Public links are the `Sharing` entity; `link` is scheme-less
  `pim.tirado.kz/sharings/<id>.<ext>`. They open **anonymously** (200), unlike
  every other PIM image URL (401). They come back as `application/octet-stream`
  with `Content-Disposition: attachment`, but `<img>` still renders them
  cross-origin.
- `File.sharedDownloadUrl` / `sharedViewUrl` are null in a GET, so the only way
  to a link is `Sharing where fileId`. Coverage: ~58% of sampled files.
- Several files of one product share **one `sorting`** (PIM hands it out in
  batches), so ties are broken by `fileName`.
- Cost of a full list scan at `maxSize=1000`: `ProductFile` 466k rows,
  ~1.5 s/page, ~12 min total; `Sharing` 293k rows, ~8.4 s/page (PIM computes
  thumbnail paths per row), ~41 min total. Cost of a filtered request
  (2026-10-16): `ProductFile productId in [100 ids]` ~1.1 s (≈277 rows),
  `Sharing fileId in [100 ids]` ~2.1 s. Per row the filtered requests are
  dearer, so the batched pass spends more PIM time than one scan did: roughly
  half an hour of `ProductFile` a night and 2–3 h of `Sharing` on Sunday at
  ~150k linked products, spread over the `pim` worker's slots.
- `id greaterThan`, `createdAt greaterThanOrEquals`, `productId in` and
  `fileId in` all work as `where`; more than 100 ids in an `in` answers 414.
  PIM ids are UUIDv7 (grow with time). PIM has ~285k Products.

## The nightly pass — a dispatcher and batches of PIM products

One task of about an hour could not finish inside the worker's 30-minute
limit (see [[core/task-runner]], *Time limits*), and a killed run wrote
nothing. Since 2026-10-16 the pass is split, the repo's usual fan-out shape.

- **Dispatcher** `plan_photo_batches(full, since)` (`photos.py:337-366`), run by
  `refresh_product_photos_task` (`tasks.py:132`). It reads PIM first and only
  for incremental runs: `Sharing createdAt >= since − SHARING_OVERLAP`. Then one
  short transaction deletes the photos of every Product without
  `raw_data['id']` (no batch covers them) and puts those new links on rows that
  already exist. It returns `batches`: the pks of our Products on
  `BATCH_SIZE` (1000) PIM products each, **all Products of one PIM product in
  the same batch** (twins, see below). The task then
  `dispatch_after_commit`s one `refresh_product_photos_batch_task` per batch
  with `full=plan['full']`, not its own argument: with no successful run yet
  the pass is full even when called with `full=False`. `updated_count` is
  deleted + links.
- **Batch** `refresh_photo_batch(pks, full)` (`photos.py:369-394`), task
  `refresh_product_photos_batch_task` (`tasks.py:162`). It is self-contained:
  `_local_products(pks)` → `ProductFile productId in` those PIM products (chunks
  of `ID_CHUNK` = 100, each paged by keyset) → plan → `Sharing fileId in`
  (all the batch's files when full, only the files of rows about to be created
  otherwise) → **one transaction** writes rows and links. A PIM failure at any
  step writes nothing for that batch and leaves other batches alone; the next
  night retries it.
- **Writers are scoped to the batch.** `_plan_rows(desired, pks)` plans only
  the batch's pks, and `_apply_links(links, rows, clear_missing)` takes the
  rows to touch. Before batching both were global (every product with photos,
  `ProductPhoto.objects.all()`): reused unscoped in a batch they would delete
  every other batch's photos and, when full, clear every other batch's links
  (`test_a_batch_leaves_other_batches_rows_and_links_alone`, verified red on
  an unscoped clear).
- **Watermark.** "Last successful run" is the newest `success` row named
  exactly `product.refresh_product_photos` (`last_successful_run`,
  `photos.py:247`), i.e. the dispatcher's. Batches lock and record under
  `product.refresh_product_photos_batch:<first>-<last>`, so they never move
  it (`test_a_batch_runs_under_its_own_name_and_does_not_move_the_watermark`).
  A failed batch created no rows, so the next night its files are "new" again
  and get the per-file lookup. A link made for an existing row while batches
  wait in the queue is caught by the next dispatcher, thanks to the one-day
  overlap.
- **Keyset paging, not offset** (`_iter_pages`, `photos.py:109-134`): `where id
  greaterThan <last>` + `sortBy=id`, `maxSize=PAGE_SIZE` (1000), `timeout=120`,
  appended to the batch's `productId in` / `fileId in` filter. PIM files are
  unlinked while the pass runs; a deletion shifts offset pages and silently
  skips the next row. It calls `pim_client.site.get` directly, **not
  `fetch_list`**: a short page is the end, any PIM error raises, and a row
  without `id` raises. No per-page retry.
- **Mapping** (`_linked_products`/`_local_products`, `photos.py:148-165`): every
  Product with a non-empty `raw_data['id']`, via `KT`, **whatever its
  `pim_id`** (unlike `stale_product_pks`, which skips `pim_id` NULL — so sets
  with PIM content are covered). Several local Products on one PIM Product all
  get the rows (`test_every_local_product_on_one_pim_product_gets_the_photos`).
- **Images only** (`IMAGE_EXTENSIONS`, `_is_image`): the listing has no type,
  so a file name must end in an image extension — a PDF slide would be a
  broken picture, and the proxy refuses non-`image/*` anyway.
- **Order** (`_desired_photos`): main (`isMainImage`) first, then `sorting`,
  then `fileName`, then `fileId`; duplicates by `fileId` collapse. `position`
  is the index; `is_main` is PIM's flag.
- **Plan, then write.** `_plan_rows` only reads the DB and returns
  `(creates, updates, deletes)` as **plain tuples**, not model instances.
  `_write_rows` applies the plan in `WRITE_CHUNK` (2000) slices (delete,
  create, update) and returns the number actually created. A Product of the
  batch with no PIM image files loses all its rows. Re-ordered/re-flagged rows
  are updated; their `public_url` is kept.
- **A Product deleted during the pass is skipped**: `_write_rows` checks each
  chunk of creates against `Product` and drops the dead ones — otherwise the FK
  would fail and roll back the whole batch
  (`test_a_product_deleted_during_the_scan_is_skipped`).
- **Links, incremental on Monday–Saturday**: the dispatcher's `createdAt` scan
  for existing rows, plus the batch's `fileId in` lookup for the files in its
  `creates`. Neither ever clears a link. The ordering inside a batch is
  load-bearing: when rows were written before their lookup, a failed lookup
  left them without links until Sunday — the next night they are no longer
  "new", and their `Sharing`s are older than the watermark
  (`test_a_failed_link_lookup_for_new_files_writes_nothing_either`).
- **Links, full on Sunday** (`full=True`, and the first run): the dispatcher
  reads nothing from PIM; each batch reads `Sharing` for all its files and
  clears `public_url` on its own rows that got none — this is how revoked
  links leave.
- **A link is usable** (`_usable_link`, `photos.py:200-214`) unless `active is
  False`, `available is False`, or `validTill` is past. A **missing** key means
  "don't know", not "off" — list mode drops fields silently and a strict check
  would null every link. The link must also pass `pim_public_url` (https, host
  equal to `settings.PIM_HOST` verbatim, `_on_pim_host`, `utils.py:435-437`):
  a `PIM_HOST` that carries a scheme (the compose placeholder
  `http://pim.invalid`) matches nothing, so dev shows proxy photos only. First
  usable link per file wins.
- **Between weekly passes a revoked link is caught in the browser**:
  `static/js/pim-photo-fallback.js`, included in `<head>` (`base.html:8`) —
  a capture-phase `error` listener on `document` (an `<img>` error does not
  bubble; the head script also catches an image that fails before the body
  scripts ran). `data-fallback-src` is swapped in **once**, and
  `data-zoom-fallback-src` replaces `data-zoom-src`. The list's hover zoom does
  the same by hand (`list.html:1144-1152`).

## Schedule, queue, lock

Two beat entries on the dispatcher (`settings/celery.py:111-126`): 05:30
Monday–Saturday (`day_of_week='1-6'`), and 05:30 Sunday with `kwargs={'full':
True}`; both `expires=_DAY`. Dispatcher: `PIM_SCAN_TIME_LIMIT` (1 h) as limit
and `lock_ttl`; batch: `PIM_BATCH_TIME_LIMIT` (30 min), a batch takes about a
minute. Both are routed to the `pim` queue (`CELERY_TASK_ROUTES`; the pim
worker runs `-c 2` by default) and listed in `core.tests.CeleryTaskRoutesTests`
and `PimTaskTimeLimitTests` — a new PIM task goes into all three. 05:30 comes
after the 05:00 content refresh, whose batches can occupy the same worker for
hours, so photo batches may run well after 05:30, and a product that got its
`raw_data['id']` that night is photographed the next one.

**By hand** on prod: `refresh_product_photos_task(full=True)` in
`manage.py shell` runs only the dispatch in process; the batches go to the
`pim` queue as usual. Run it in a container that reaches PIM (a running
worker, via `exec`).

## Rendering

- `product_photos(product)` (`photos.py:91-104`): the prefetched `photos` rows
  (`list(product.photos.all())`), else — no rows yet — one photo from
  `raw_data['mainImageId'] or ['imageId']` through the proxy. It **guards an
  unsaved Product** (`if product.pk`): a reverse FK manager on an unsaved
  instance raises `ValueError` in Django 5.2, and `render_photo`'s test passes an
  unsaved `Product(...)`. Mirrored rows win: `mainImageId` is ignored once any
  exist.
- `photo_sources` (`photos.py:73-88`): **with a public link `src` and `zoom` are both the
  link** (the original — a Sharing link has no thumbnail) and the proxy
  medium/large are the fallbacks; without a link the proxy is the primary and
  there is no fallback; a file id the proxy rejects (`pim_image_url` regex)
  drops out.
- `/products/`: `_base_queryset` prefetches `'photos'` (`views.py:56`) — one
  extra query per page; `render_photo` (`tables.py:360-388`) shows only the first
  photo with `class="product-photo"`, `data-fallback-src`, `data-zoom-src`,
  `data-zoom-fallback-src` — keep the class, the hover-zoom script selects it
  (`list.html:1161-1167`). Guarded by
  `test_views.ProductPhotoTests.test_page_shows_photos_by_default_with_one_query_for_all_rows`
  (query count for 1 row == for 3 rows).
- `'photo'` is a **default column** now (`columns.py:87-91`). Saved column
  choices (cache `product_page:columns:user:<id>`, 30 days) are **not** migrated:
  only users without one see it. The export still drops it (`export.py:67`).
- The card: `ProductDetailView.get_queryset` prefetches `'photos'`
  (`views.py:346-349`), context `photos` = `product_photos(product)`
  (`:379`). The old single `photo_url` thumbnail is gone.

## The card carousel — traps (`detail.html`)

- The gallery is in the header (`:92-134`, `#pd-carousel`); the enlarge modal is
  **`#pd-photos-modal`** (`:386-422`, carousel `#pd-photos-carousel`), never
  `#modal-container`, whose `.modal-content` the HTMX forms (edit, delete,
  attach) swap. With no photos neither block renders; with one photo there are
  no arrows, counter or thumbnails, but it still enlarges.
- **`{% block script %}` renders before the Bootstrap bundle** (`base.html:68`
  vs `:72`). The card script (`detail.html:443-480`) only attaches listeners;
  calling `bootstrap.*` at parse time would throw.
- Header and modal slide in step by toggling `.active` on the `.carousel-item`s
  (on `show.bs.modal` and `hidden.bs.modal`), **not** `Carousel.to()`:
  Bootstrap reads the current slide from the markup, and a hidden carousel does
  not animate the transition. `slide.bs.carousel` updates the counter and the
  thumbnail strip.
- The arrows are custom (`.pd-gallery-nav`), not `carousel-control-*`:
  Bootstrap's white icons vanish on white product photos.

## Tests — traps (`tests/test_photos.py`, `test_detail.py`, `test_views.py`)

- `RefreshProductPhotosTests.run_refresh` plays a whole night: the
  dispatcher, then each batch in turn. A test of one batch calls
  `refresh_photo_batch(pks, full=...)` itself.
- `FakePim` (`test_photos.py:27-57`) answers an `EntityList` by `name` and
  honours `where` (`greaterThan`, `greaterThanOrEquals`, `in`) and `maxSize`; it
  is installed with `patch.object(SiteAPI, 'get', side_effect=pim.get)` — not by
  patching `fetch_list`, which `photos.py` does not use. Patch
  `photos.PAGE_SIZE` to a small number to exercise paging, and set
  `@override_settings(PIM_HOST=...)` to a bare host or no link is accepted.
- **`fail_on_call=N` counts PIM calls in order**, so it pins *which* read fails:
  for an incremental night with one new file, call 1 is the dispatcher's
  `Sharing` by `createdAt`, 2 the batch's `ProductFile`, 3 its `Sharing` by
  `fileId` (`test_a_failed_link_lookup_for_new_files_writes_nothing_either`).
  A full night's dispatcher makes no call. Assert
  `pim.calls[-1].where[0].attribute` so the test fails if the sequence changes
  and it stops testing the lookup. A batch's `ProductFile` request carries two
  `where`s: `productId in` first, then the page's `id greaterThan`.
- To simulate a Product deleted mid-pass, take `photos._local_products()` first,
  delete the Product, then run the batch with `patch.object(photos,
  '_local_products', return_value=products)`
  (`test_a_product_deleted_during_the_scan_is_skipped`).
- The card's CSS and script always contain `pd-gallery`, `pd-gallery-nav` and
  `data-pd-current`, so "no gallery" assertions must target **markup**:
  `id="pd-carousel"`, `data-bs-slide-to=`, `<span data-pd-current>`,
  `class="pd-gallery-nav`.
- `src="X"` also matches inside `data-zoom-src="X"`; count `<img src="X"`
  (`test_views.py:372,379`).
- Task tests need `@override_settings(CACHES=LOCMEM_CACHE)` + `cache.clear()`
  (the lock is `cache.add`). For the dispatcher patch `tasks.plan_photo_batches`
  and `tasks.dispatch_after_commit`, and assert `since=` against a
  `TaskRunHistory` row you created; for a batch patch
  `tasks.refresh_photo_batch`.
