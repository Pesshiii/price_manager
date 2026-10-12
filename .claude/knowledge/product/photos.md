---
title: Product photos — ProductPhoto and the nightly photo pass
summary: ProductPhoto mirrors a Product's PIM image files plus their anonymous public links; the nightly keyset scan, the weekly full link pass, the browser fallback, the card carousel, and the test traps.
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
- Cost at `maxSize=1000` (also in the module docstring, `photos.py:9-17`):
  `ProductFile` 466k rows, ~1.5 s/page, ~12 min total; `Sharing` 293k rows,
  ~8.4 s/page (PIM computes thumbnail paths per row), ~41 min total.
- `id greaterThan` and `createdAt greaterThanOrEquals` both work as `where`.
  PIM ids are UUIDv7 (grow with time).

## The nightly pass — `refresh_product_photos` (`photos.py:312-346`)

- **Keyset paging, not offset** (`_iter_pages`, `photos.py:96-121`): `where id
  greaterThan <last>` + `sortBy=id`, `maxSize=PAGE_SIZE` (1000), `timeout=120`.
  A 12-minute scan runs while PIM files are unlinked; a deletion shifts offset
  pages and silently skips the next row, so a product would lose a photo for a
  night. It calls `pim_client.site.get` directly, **not `fetch_list`**: there is
  no `truncated` flag to check, a short page is the end, any PIM error raises,
  and a row without `id` raises. No per-page retry (same as `fetch_list`).
- **Mapping** (`_local_products`, `:135-143`): every Product with a non-empty
  `raw_data['id']`, via `KT`, **whatever its `pim_id`** (unlike
  `stale_product_pks`, which skips `pim_id` NULL — so sets with PIM content are
  covered). Several local Products on one PIM Product all get the rows
  (`test_every_local_product_on_one_pim_product_gets_the_photos`). A
  `ProductFile` of a PIM product no local Product points at is skipped.
- **Images only** (`:48-52`, `:124-125`): the listing has no type, so a file
  name must end in an image extension — a PDF slide would be a broken picture,
  and the proxy refuses non-`image/*` anyway.
- **Order** (`:154`): main (`isMainImage`) first, then `sorting`, then
  `fileName`, then `fileId`; duplicates by `fileId` collapse. `position` is the
  index; `is_main` is PIM's flag.
- **Every PIM read comes first, then one transaction writes everything**
  (`:326-342`). Reads, in order: `ProductFile` (full), `Sharing` (the full scan,
  or `createdAt >= since − 1 day`), and — incremental only — the
  `Sharing where fileId in` lookup for the files of rows *about to be created*.
  Only then `with transaction.atomic()` runs `_write_rows` and `_apply_links`.
  So a PIM failure at **any** step writes nothing, and the next run retries the
  same files (`test_a_pim_failure_mid_scan_writes_nothing`,
  `test_a_failed_link_lookup_for_new_files_writes_nothing_either`). The
  ordering is load-bearing: when the rows were written before the lookup, a
  failed lookup left them without links until the Sunday full pass — the next
  night they are no longer "new", and their `Sharing`s are older than the
  watermark. The task is `atomic=False`; the transaction belongs to the service.
- **Plan, then write** (`:235-286`). `_plan_rows(desired)` only reads the DB and
  returns `(creates, updates, deletes)` as **plain tuples**, not model
  instances: the first run creates ~466k rows. It walks products in chunks of
  `WRITE_CHUNK` (2000). `_write_rows` applies the plan in `WRITE_CHUNK` slices
  (delete, create, update) inside the one transaction and returns the number
  actually created. A Product absent from the scan loses all its rows — no PIM
  image files, no `raw_data['id']` (the products planned are `desired ∪
  products that already have photos`). Re-ordered/re-flagged rows are updated;
  their `public_url` is kept.
- **A Product deleted during the scan is skipped**: `_write_rows` checks each
  chunk of creates against `Product` and drops the dead ones — otherwise the FK
  would fail and roll back the whole night. `stats['created']` counts only rows
  really created (`test_a_product_deleted_during_the_scan_is_skipped`).
- **Links, incremental on Monday–Saturday** (`:333-338`): `Sharing createdAt >=
  last successful run − 1 day` (`SHARING_OVERLAP`, covers time-zone skew and a
  link made while the last run was going), plus `Sharing where fileId in` for
  the files in `creates`, in chunks of 100 (200 gives 414, `:39-41`). It
  **never clears** a link (`_apply_links(clear_missing=False)`, `:289-309`).
- **Links, full on Sunday** (`full=True`): all `Sharing` rows, then every row
  not in the result gets `public_url=''` — this is how revoked links leave. With
  no successful run yet, the pass is full too (`:328`).
- "Last successful run" is `TaskRunHistory.started_at` of the newest `success`
  row of `product.refresh_product_photos` (`last_successful_run`, `:220-225`).
  The current run's row is written after the runner returns, so a pass never
  counts itself; a skipped (lock) or errored run does not move the cursor.
- **A link is usable** (`_usable_link`, `:173-187`) unless `active is False`,
  `available is False`, or `validTill` is past. A **missing** key means "don't
  know", not "off" — list mode drops fields silently and a strict check would
  null every link. The link must also pass `pim_public_url` (https, host equal
  to `settings.PIM_HOST` verbatim, `_on_pim_host`, `utils.py:435-437`): a
  `PIM_HOST` that carries a scheme (the compose placeholder
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

Task `product.refresh_product_photos` (`tasks.py:112-131`, `execute_locked_task`,
`atomic=False`, `lock_ttl` 2 h, `updated_count` = created + updated + deleted +
links). Two beat entries on one task (`settings/celery.py:107-117`): 05:30
Monday–Saturday (`day_of_week='1-6'`), and 05:30 Sunday with `kwargs={'full':
True}`; both `expires=_DAY`. Routed to the `pim` queue (`celery.py:43`; the pim
worker runs `-c 2` by default, `docker-compose.yml:140`), and listed in
`core/tests.py:204` — a new PIM task must be added to both
`CELERY_TASK_ROUTES` and that test. 05:30 comes after the 05:00 content
refresh, but that fan-out can run for hours on the same worker, so a product
that got its `raw_data['id']` that night is photographed the next one. The full
pass is ~53 min of PIM reads.

## Rendering

- `product_photos(product)` (`photos.py:78-91`): the prefetched `photos` rows
  (`list(product.photos.all())`), else — no rows yet — one photo from
  `raw_data['mainImageId'] or ['imageId']` through the proxy. It **guards an
  unsaved Product** (`if product.pk`): a reverse FK manager on an unsaved
  instance raises `ValueError` in Django 5.2, and `render_photo`'s test passes an
  unsaved `Product(...)`. Mirrored rows win: `mainImageId` is ignored once any
  exist.
- `photo_sources` (`:60-75`): **with a public link `src` and `zoom` are both the
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

- `FakePim` (`test_photos.py:27-57`) answers an `EntityList` by `name` and
  honours `where` (`greaterThan`, `greaterThanOrEquals`, `in`) and `maxSize`; it
  is installed with `patch.object(SiteAPI, 'get', side_effect=pim.get)` — not by
  patching `fetch_list`, which `photos.py` does not use. Patch
  `photos.PAGE_SIZE` to a small number to exercise paging, and set
  `@override_settings(PIM_HOST=...)` to a bare host or no link is accepted.
- **`fail_on_call=N` counts PIM calls in order**, so it pins *which* read fails:
  for an incremental run with one new file, call 1 is `ProductFile`, 2 is
  `Sharing` by `createdAt`, 3 is `Sharing` by `fileId`
  (`test_a_failed_link_lookup_for_new_files_writes_nothing_either`). Assert
  `pim.calls[-1].where[0].attribute` so the test fails if the sequence changes
  and it stops testing the lookup.
- To simulate a Product deleted mid-scan, take `photos._local_products()` first,
  delete the Product, then run with `patch.object(photos, '_local_products',
  return_value=products)` (`test_a_product_deleted_during_the_scan_is_skipped`).
- The card's CSS and script always contain `pd-gallery`, `pd-gallery-nav` and
  `data-pd-current`, so "no gallery" assertions must target **markup**:
  `id="pd-carousel"`, `data-bs-slide-to=`, `<span data-pd-current>`,
  `class="pd-gallery-nav`.
- `src="X"` also matches inside `data-zoom-src="X"`; count `<img src="X"`
  (`test_views.py:372,379`).
- Task tests need `@override_settings(CACHES=LOCMEM_CACHE)` + `cache.clear()`
  (the lock is `cache.add`); patch `tasks.refresh_product_photos` and assert
  `since=` against a `TaskRunHistory` row you created.
