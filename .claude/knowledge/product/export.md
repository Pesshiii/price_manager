---
title: Export — xlsx from the page and full CSV
summary: The «Экспорт» button, main values by supplier levels, supplier sheets, FullCsvExporter.
code: price_manager/product/export.py, price_manager/product/tasks.py
---
# Export — xlsx from the page and full CSV

## The «Экспорт» button — `/products/` to xlsx (`product/export.py`, `product/tasks.py`)

Background export of the exact page a user is looking at: click «Экспорт» →
`export_products_task` (Celery, `EXPORT_TIME_LIMIT = 60*60`,
`product/tasks.py:77-115`) builds the file and drops a toast notification
(`core.tasks._notify`) with a download link to `ProductExport`
(`product-export-download`). The task is locked per user
(`task_name=f'product.export_products:{user_id}'`, `lock_ttl=EXPORT_TIME_LIMIT`)
and runs `atomic=False` — reading + one file upload + one insert, no reason to
hold a transaction for up to an hour. `ProductExport` rows
(`product/models.py:212-234`, `upload_to='product_exports/'`) are **never
cleaned up** — a known gap, not a bug.

**The workbook is no longer one wide sheet.** It used to be a single sheet
with a `<колонка> • <поставщик>` column per selected supplier column times
supplier; a user asked for supplier data split out, and the shape changed
(this branch):

- **Sheet «Товары»** (`MAIN_SHEET`, `export.py:55`) — one row per `Product`:
  `PRODUCT_TITLES` (`export.py:56`, артикул/название/бренд/категории) + the
  selected product columns, then, per selected supplier-row column, **one
  main value**, not one column per supplier: price columns get a `… (основная)`
  header, `stock` gets `Остаток (основной)` (`main_titles`, `export.py:224-232`),
  then, **only if the export contains a set** (`detect_sets`, see above),
  `SET_TITLES` («Себестоимость из комплектующих», «Комплектующих без цены»).
  Any other selected supplier-row column (article, stock_msg, delivery_days,
  supplier__*…) does **not** appear on this sheet at all.
- **One sheet per supplier** that actually has a `MainProduct` row among the
  exported products, in `Supplier.price_priority` order (`ranked_suppliers`,
  `export.py:142-153`; ascending, unranked last by name/pk, `supplier=NULL`
  rows always last as «Без поставщика»). Header is `IDENTITY_TITLES`
  (`export.py:58`, «Артикул», «Название» — so the sheet reads standalone) +
  every selected supplier-row column under its plain `COLUMN_LABELS` label,
  built by `supplier_titles` (`export.py:234-236`). A supplier's sheet
  contains only the products it has a row for, in the same order as «Товары».
  No supplier-row column selected → only «Товары» is written
  (`supplier_sheets` stays `{}`, `build`, `export.py:293-326`).
- **`sheet_names()`** (`export.py:65-83`) turns supplier names into legal,
  distinct Excel sheet names: `SHEET_NAME_FORBIDDEN` maps `[]:*?/\` to spaces,
  truncates to `SHEET_NAME_LIMIT = 31`, and — because Excel compares sheet
  names **case-insensitively** — a name colliding with `MAIN_SHEET` or with
  another (possibly truncated) supplier name gets a `" (n)"` suffix that
  itself respects the 31-char limit. An empty/all-forbidden name becomes
  `NO_SUPPLIER` = «Без поставщика». `SheetNamesTests`
  (`test_export.py:66`) is the guard, including a supplier literally named
  «товары» colliding with «Товары».
- **Main values are by supplier *levels*** (`Supplier.price_priority` /
  `stock_priority` may repeat; see [[supplier_manager]]) — the rule now lives
  in `main_values.py` (see the sets section above), `export.py` re-imports
  it. `supplier_levels()` groups the exported suppliers top-down; all
  unranked suppliers are **one shared bottom level** (they used to be ordered
  by name, a hidden alphabetical priority), `supplier=NULL` rows a level of
  their own at the very end. `main_value(levels, pick)` returns
  `pick(non-zero values)` of the first level that has any, else `0` if any
  explicit `0`, else empty (a `NULL` stock stays distinct from a confirmed
  `0`).
  - **Prices — winner supplier, not per-column min.** `main_value_cells()`
    orders each price level by `winner_order()`: lowest non-zero
    `prime_cost` first (`supplier_costs()` computes it from the rows even
    when the prime_cost column is not exported), no cost last, ties by name.
    Every MP price then takes the first non-zero value in that flat order —
    so all prices of a row come from the winner, and only a price the winner
    lacks falls to the next by cost on the same level, then lower levels.
    Per-column min was rejected by the owner: it mixed suppliers inside one
    row (a basic price below the prime cost it came with).
  - **Stock — max** on the first stock level that has a non-zero value.
  - **Only MP prices (KZT) and stock get a main value** (`MAIN_PRICE_COLUMNS`).
    `supplier_product_price/rrp/discount_price` are in the supplier's
    currency and cannot be compared across suppliers; they appear only on
    supplier sheets / supplier blocks of the csv.
  - `supplier_values()` folds **one supplier's own `MainProduct` rows** (no
    unique `(product, supplier)`) by the same rule: rows by `prime_cost`,
    prices first non-zero, stock max; `_joined()` («; »-separated distinct
    values) for every other supplier-row key.
- **Supplier columns for the header set, per-sheet values via one collected
  `supplier_ids` set.** `build()` (`export.py:293-326`) makes one chunked
  pre-pass over `pks` collecting `MainProduct.supplier_id` distinct
  (`export.py:296-301`) *only if* any supplier-row column is selected, then
  builds `ranked_suppliers` (sheet order) and the price/stock levels from it before opening any sheet — sheet
  creation needs the full ranked list up front to know how many sheets and in
  what order. A product-page supplier filter still produces sheets for every
  supplier that appears in the filtered rows — not narrowed further.
- **`export_columns()`** (`export.py:112-118`) still splits `selected` into
  product columns vs. `SUPPLIER_ROW_COLUMNS`, dropping `NOT_EXPORTED =
  {'actions', 'photo'}` from either.
- **Chunked `pk__in` loses order; the pk list restores it.** The main loop in
  `build()` (`export.py:328-347`) walks `_chunks(pks)`, looks up `products`
  and `main_products` per chunk by `pk__in`, then re-emits rows in the
  original chunk order — `IN` itself does not preserve order. Don't switch to
  iterating the ordered queryset with `.iterator()`: without an explicit
  `chunk_size` it silently drops `prefetch_related` (the categories N+1 would
  come back).
- **openpyxl rejects model instances and tz-aware datetimes.** `self.cell`
  (`export.py:212-222`) can yield a `Supplier` object (the `supplier__*`
  columns) or a tz-aware `*_updated_at`. `_excel_value` (`export.py:161-171`)
  localizes and strips tzinfo from datetimes, and stringifies anything else
  non-scalar. Caught only once every selectable column was actually
  exercised — `test_every_selectable_column_is_writable`
  (`test_export.py:148`) exports the full `COLUMN_LABELS` set for this
  reason; earlier tests exporting only price columns passed while a real run
  raised `Cannot convert <Supplier: …> to Excel`.
- **`write_only=True` workbook** (`export.py:306`) — cells are streamed via
  `WriteOnlyCell`/`sheet.append`, not built in memory as a normal `Workbook`
  would. Confirmed to handle ~60 interleaved sheet appends per chunk fine
  (one to «Товары» plus up to one per supplier per row, `export.py:341-347`).
  **Re-measured after the sheet split**, same synthetic ~158k-product /
  ~174k-`MainProduct` / 60-supplier dataset in an isolated DB, `DEFAULT_COLUMNS`:
  73.5 s, 63 sheets, 11.5 MB — faster than the old single-sheet shape's ~130 s,
  because a supplier a product has no row for now writes nothing instead of an
  empty cell pair. Re-measure again if `DEFAULT_COLUMNS` or the supplier count
  changes materially — the 60-minute task time limit is headroom, not a
  guarantee, as catalogue growth continues.
- **`ordered_product_pks(params)`** (`export.py:88-109`) — the page-ordering
  contract this export must stay in lockstep with — is unchanged by the
  sheet split: reproduces `ProductPage`'s `sort` param (captured as
  `SORT_PARAM`, `export.py:39`) → `by_category=True` when no sort →
  `ProductFilter` → invalid filterset returns `[]` → `best_match_groups_first`
  when `by_category` and a search term → `ProductTable(qs, order_by=…)`.
  `ExportOrderTests` (`test_export.py:175`) still pins it against the page's
  own `product_rows`.
- **Test trap: openpyxl `read_only` `iter_rows` drops trailing empty cells.**
  A row ending in `None`/`None` (e.g. a supplier sheet where the last
  selected column is blank for that row) comes back shorter than the header
  when read back. `test_export.py`'s `read_sheets()` helper (`:23-35`) pads
  every row to header width before comparing — write tests against that
  helper, not raw `iter_rows` output, or a real trailing-`None` bug reads as
  a passing test.

### Full CSV export from the admin (`FullCsvExporter`)

The Product changelist in the admin has a «Полный экспорт (csv)» button
(`product/templates/admin/product/product/change_list.html`, POST to
`admin:product_product_export_full_csv`, `ProductAdmin.export_full_csv_view`,
view permission required) → `export_products_full_csv_task`. It always exports
the **whole catalogue**, whatever the changelist is filtered to (empty
`QueryDict` → page default order), with a fixed column set
`FULL_EXPORT_COLUMNS` (every price in `PRICE_COLUMNS` + `stock`).

- **Same rules as the xlsx, not a copy of them.** `build()` was split into
  `suppliers(pks)` and the `rows()` generator; `FullCsvExporter.write()` consumes
  the same rows. Change main-value rules in one place and both formats follow.
  Set columns follow the same `detect_sets` gate as the xlsx path.
- **CSV has one sheet, so suppliers are column blocks**: `<поставщик> • <колонка>`,
  price-priority order, only suppliers that have rows. A product a supplier
  lacks gets empty cells there.
- **Format**: `;` delimiter + UTF-8 BOM + **comma decimals** (`_csv_value`) —
  for RU-locale Excel. `;` with dot decimals is the one wrong pair: that Excel
  reads `3.10` as 3 October. A zero collapsed by `main_value` is written as
  `0`, not `0,00`.
- Written to a `TemporaryFile`, not `BytesIO` — hundreds of columns × ~158k rows.
- Its own lock (`product.export_products_full_csv:{user}`), so a running xlsx
  export doesn't make it «пропущен». Both tasks share `_run_export`.
- `ProductExportDownloadView` takes the extension from the stored file name —
  it used to hardcode `.xlsx`.
- The admin doesn't render `PersistentNotification`s; the message tells the
  user the link arrives «в оповещениях на сайте».

See [[core]] for the export notification/toast mechanics (the 204 response
trap on the triggering HTMX request) — not repeated here.
