---
title: Satu export — ids, photos, the groups sheet
summary: The «Выгрузка для Satu» xlsx (SatuExporter) — what Satu does with an import, why «Идентификатор_товара» is Product.pk and why the first upload is unproven (duplicate-item risk), the photo column, the groups sheet built from PIM category codes, and the test traps.
code: price_manager/product/satu_export.py, price_manager/product/tests/test_satu_export.py, price_manager/product/tasks.py, price_manager/product/admin.py
---
# Satu export — `SatuExporter`

The admin's Product changelist has «Выгрузка для Satu (xlsx)» (POST, view
permission: `admin.py:74-76`, `:94-108`, button `change_list.html:16-21`) →
`export_products_satu_task` (`tasks.py:323-331`) → `build_satu_export`
(`satu_export.py:433-440`). It always exports the whole catalogue in the layout
of Satu's own store export (`export-products-*.xlsx`): sheets «Export Products
Sheet» and «Export Groups Sheet» (`:75-76`). `SatuExporter` subclasses
`ProductExporter` ([[product/export]]) and reuses its main-value rules.

The task has its own limit, `SATU_EXPORT_TIME_LIMIT` = 3 h (`tasks.py:318-320`,
~1,600 PIM requests of ~2 s), its own lock `product.export_products_satu:{user}`,
and the shared `_run_export` (`tasks.py:239-282`). It stays on the default
`celery` queue because a user waits for it (CLAUDE.md, *Two workers*).
`_pim_get` retries and swallows `SoftTimeLimitExceeded`: [[core/task-runner]].

## Read this before anyone uploads the file

**The first upload of a pk-keyed file is unproven.** Satu's 36,100 existing items
carry other ids: 32,382 have «Идентификатор_товара» = «Код_товара», 1,008 have old
numeric ids, 2,710 have it empty (owner's analysis of Satu's own export,
2026-10-17). Our file puts `Product.pk` there, so its rows will not match them.
Whether Satu then creates duplicates, or matches by «Уникальный_идентификатор»
first (which we leave empty), is not known. It needs a **manual pilot in the Satu
cabinet** — a few rows — before the full file goes up.

Keeper's inference, not the owner's analysis, from fact 2 below: the products
sheet carries no group (`test_groups_sheet_is_pim_categories_parents_first`,
`test_satu_export.py:247-249`), and Satu creates new items only for rows that have
one, so unmatched rows might be skipped rather than duplicated. If so, the other
half matters just as much: the upload would then also update none of the 36,100
existing items, and their prices and stock would stay stale with no error. The
pilot decides which of the three happens.

## What Satu does with an import — external, not verified in code

From Satu's format spec (support.satu.kz/hc/ru/articles/360005181198), read by
the owner's analysis session on 2026-10-17. The page answers 403 to automated
fetches, so an agent cannot re-read it; treat these as the owner's word.

1. Rows are matched to existing items by **«Идентификатор_товара»**, a required
   field together with «Название_позиции» and «Описание». It does *not* match on
   «Код_товара» — this closes the open item in `.claude/shift-to-product-brief.md`
   step 3 (and the note in [[product/identity]]).
2. On re-import Satu creates new items **only when they have a group**.
3. Empty `HTML_*` cells and an empty «Идентификатор_подраздела» do not overwrite
   existing values, so leaving them empty is safe.
4. PIM `Category.code` equals the Satu group number for all 668 groups (read-only
   comparison of Satu's store export of 2026-09-22 with PIM, 2026-10-17: codes,
   names and parent links matched exactly). 183,432 of 183,433 categorized PIM
   products have exactly one most-specific category.

«Идентификатор_подраздела» is Satu's *marketplace* category (`SatuCategory.code`,
`.claude/skills/pim-fill-from-export/SKILL.md`), not the store group «Номер_группы».
The export leaves it empty.

## «Идентификатор_товара» = `Product.pk`

`'Идентификатор_товара': str(product.pk)` (`satu_export.py:355`), the owner's call
of 2026-10-17 («Используй id в pm»; docstring `:13-18`). Not `Product.number`:
it repeats across brands since identity step 3 and step 4 renumbers it
([[product/identity]]). Not `pim_id`: that is a PriceManagerProduct id and NULL
for sets ([[product/pim-link]]); `test_product_identifier_is_pm_pk_for_every_row`
(`test_satu_export.py:140-151`) builds a set with no `pim_id` for this.
«Уникальный_идентификатор» stays empty (same test, `:151`). «Код_товара» is still
`Product.number` (`:354`).

A pk lives as long as its Product row. Identity step 4 merges and splits
Products (brief §0.6), so some pks will leave the file; decide then what happens
to their Satu items.

## «Ссылка_изображения» — public PIM links only

`image_links(pks)` (`satu_export.py:239-251`) is called once per chunk of 1000 in
`iter_rows` (`:383`; `_chunks` = `export.CHUNK_SIZE`). One query:
`ProductPhoto` rows with a non-empty `public_url`, `order_by('position', 'pk')`,
joined with `", "` (Satu's separator, `IMAGE_SEPARATOR` `:121`). It is pinned by
`assertNumQueries(1)` (`test_satu_export.py:227-235`).

- **Order is the main photo.** Position 0 is PIM's main image (`_desired_photos`
  sorts `not is_main` first, [[product/photos]]), and Satu treats the first URL as
  main. The format filter runs *after* ordering, so a main image in a dropped
  format makes the next photo Satu's main one.
- **A denylist, not an allowlist.** Satu takes only JPG/GIF/PNG, up to 10 MB each,
  and dedupes re-imported images by checksum (owner's reading of the spec).
  `NOT_SATU_IMAGE_EXTENSIONS` = webp/bmp/svg/avif (`:115-120`) — the non-Satu
  members of `services/photos.IMAGE_EXTENSIONS` — is matched on the URL *path*,
  case-insensitively (`:249`). That a Sharing link's suffix equals the file's
  extension rests on one live measurement (2026-10-12, `pim.tirado.kz/sharings/
  <id>.<ext>`) and an example in the AtroCore 2.3.15 REST docs
  (`docs/10.developer-guide/10.rest-api/index.md:654`). An allowlist would silently
  empty the column if the link shape changed, so a link **without** an extension is
  kept (`test_satu_export.py:213,223-224`).
- **No link, no photo.** A photo without `public_url` opens only with the PIM
  token, so it is skipped; coverage is ~58% of files ([[product/photos]]). The dev
  compose `PIM_HOST` placeholder stores no public links at all, so a dev export has
  an empty column. No URLs at all → the cell is `None` (`:359`).
- **Open risks, not verified.** Sharing links answer `application/octet-stream` +
  `Content-Disposition: attachment`: fine for `<img>`, unknown for Satu's fetcher.
  The 10 MB limit is not checked; `ProductPhoto` stores no size.

## The groups sheet — PIM categories

`write()` calls `fetch_categories()` once, at the top (`:402`), before the product
requests, so a bad answer fails the run in seconds instead of after 1,600 calls.
It is a plain `fetch_list`, with no `_pim_get` retries (only `fetch_flat_products`
retries, `:258`; attributes and countries are plain too, `:160,172`).

`fetch_categories()` (`:177-206`) selects `id/code/name/parentId`, ordered by `id`
(offset paging over a field with equal values duplicates and loses rows, as it
did for brands), `timeout=PIM_TIMEOUT` (`:125`). It **raises `RuntimeError`**:

- on a truncated list (`:193`): a child whose parent is missing from the list
  would be written as a top-level group (`group_rows`, `:219`), and Satu would move
  it to its root;
- when more than one category came back and none has a parent (`:202`). Per our
  instance's metadata (pim-docs, AtroCore 2.3.15) `entityDefs.Category.fields` has
  no `parentId`/`parentsIds`: it has `parents` (linkMultiple, relation
  `CategoryHierarchy`) and `parent` (link, `notStorable`, `openApiDisabled`);
  `scopes.Category` is a `Hierarchy` with `multiParents: false`, so one parent at
  most. List mode does return `parentId` (`probe_pim_category_size` built the
  15-root tree from it on 2026-09-16), but nothing documents it, and a silent drop
  would flatten Satu's tree. A one-category list passes the guard.

`group_rows(categories)` (`:209-236`): parents before children, siblings by
`(name, code)`. «Номер_группы» = `code`, «Название_группы» = `name`,
«Номер_родителя» = the parent's `code`, empty for top-level. Every other group
column stays empty (`test_groups_sheet_is_pim_categories_parents_first`,
`test_satu_export.py:237-249`).

- **A category without a code gets no row** (`:228`). Its children get an empty
  «Номер_родителя» (`:223,231`) and are written where the traversal reaches them,
  under the codeless node, not re-sorted among the real roots
  (`test_satu_export.py:251-262`).
- **The per-product «Номер_группы»/«Название_группы» are not filled.** The owner
  has not decided: by fact 2, filling them would let Satu create up to ~120k new
  items (the catalogue is ~158k, Satu has 36k).
- **Local `product.Category` has no `code`** (`models.py:15-28`) and was
  deliberately not given one: a migration stops autodeploy (CLAUDE.md, *Production
  deploy*). The code lives only in PIM and is fetched at export time.

## Other traps in the module

- **`*Name` in `select` silently drops the record's id and attribute values**
  (`PIM_SELECT`, `:129-132`; modelled by `fake_pim`, `test_satu_export.py:67-70`).
  Country is an id looked up in the `Country` list.
- **Rows spill to a temp jsonl first** (`:404-408`): the sheet's width is the
  widest product's characteristics, and a `write_only` workbook writes the header
  first. Dates go through the jsonl as ISO strings and are turned back into dates
  (`:414-420`).
- **`rows_count` is `len(pks)`** (`:430`), including pks whose Product vanished
  mid-run (skipped in `iter_rows`, `:385-387`).

## Tests — traps (`test_satu_export.py`)

- `fake_pim` (`:59-72`) answers `Attribute`/`Country`/`Category` lists by name and
  **asserts that everything else is a `FlatEntityList`** (`:66`). A new list fetch
  needs its own branch there, or the assert fires.
- `export_with()` (`:292-301`) and `test_wider_than_satu…` (`:326-339`) patch the
  fetchers one by one — `fetch_flat_products`, `fetch_attributes`,
  `fetch_countries`, `fetch_categories`. **A new fetcher must be patched in both**,
  or those tests make a real HTTP call. They patch `fetch_categories` to `{}`,
  which **bypasses both guards**; the guard tests go through `fake_pim`
  (`:264-290`).
- Photo tests create `ProductPhoto` rows directly (`:210-218`, `:227-232`); no
  nightly pass is involved.
