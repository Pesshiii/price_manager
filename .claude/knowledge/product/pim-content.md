---
title: PIM content on the product card
summary: Descriptions (from the mirror) and characteristics (lazy flat fetch, cached) on /products/<pk>/ — cache key, flattened record shape, label/URL/HTML traps.
code: price_manager/product/pim_content.py, price_manager/product/templates/product/partials/pim_panel.html, price_manager/pim_api/__init__.py, price_manager/product/views.py
---
# PIM content on the product card («Описание», «Характеристики»)

Display only. Filtering by characteristics is not possible from this path;
that needs mirroring (see "List mode" below). Facts verified with read-only
GETs against the live PIM on 2026-09-29.

## Two sources, two paths

- **Descriptions come from the mirror** (`Product.raw_data`, filled by
  [[product/pim-sync]]); the card never calls PIM for them
  (`views.py:362-367`, `description_html` + `clean_description`).
- **Characteristics are not in the mirror.** `ProductPimView`
  (`views.py:380`, route `product-pim`, `products/<pk>/pim/`) is a lazy HTMX
  panel (`#product-pim`, `hx-trigger="load"`) that calls
  `pim_content.fetch_flat_product` — one `GET Product/{id}` with header
  `Flatten-Attributes: true`. The card itself never waits on PIM.
- **Keyed by `raw_data['id']`** (the PIM `Product` id), **not** `Product.pim_id`
  (a PMP id, NULL for sets — see [[product/pim-link]]). No `raw_data['id']`
  means «Товара нет в PIM».
- **`pim_api.FlatEntity`** exists because `SiteAPI.get` cannot take extra
  headers; the `Method` object merges `Flatten-Attributes` itself.

## Cache and failure

- Key `pim_product_flat:{id}`, TTL 1 h (`pim_content.py:35,119`). Deliberately
  **not** `pim_product:{id}`: `main_product_manager.utils` keeps the
  non-flattened shape under that key, and the two would mix.
- `?refresh=1` skips the cache read. On any PIM failure the **stale cached copy
  is served, even on refresh**; only with no cache does it raise
  `PimUnavailable` -> «PIM не ответил». A 404 deletes the cache entry and
  yields «Товар не найден в PIM».
- Timeout is 10 s (`FETCH_TIMEOUT`), not `SiteAPI`'s 5.

## Flattened record shape

- The value sits under the attribute `code`. `attributesDefs[code]` has
  `label`, `type`, `attributeGroup {id,name,sortOrder}`, `sortOrder`,
  `sortOrderInAttributeGroup`, `channelName`.
- A numeric attribute with a unit has a sibling def `<code>Unit`
  (`unitIdField: true`, skipped) and `<code>UnitData.symbol`.
- **Trap: for attributes with a unit the label carries the value type** —
  «Длина (Float)», «Количество в упаковке (Integer)». `_label` strips the
  `(…)` suffix only when a `<code>Unit` def exists (`pim_content.py:164`);
  a label that legitimately ends in parentheses on a unit-less attribute is
  left alone.
- Types on our instance: varchar, float, bool, int, text, url, linkMultiple
  (`setProducts` — skipped on purpose; set composition is drawn from
  `ProductSetItem`). No enums. Unknown types are dropped (`_KINDS`).
- `url` values become links only for http(s); anything else renders as text
  (an autoescaped `javascript:` in `href` still executes).

## List mode (for future mirroring, not used yet)

`Flatten-Attributes` alone on a list returns **no attributes**. With
`allAttributes=true` it does, but `attributesDefs` shrink to
`{attributeId, type}` — no labels or groups, so names must come from the
`Attribute` catalogue. A 200-product page took ~2.7 s; PIM holds ~283k
products. The owner plans to bind characteristics to categories and filter by
them later — that is the path.

## Descriptions

- `description` is PIM type `text`, `longDescription` is `wysiwyg`, but
  **both contain HTML in practice** (~20k / ~67k products), and `description`
  is often a full article with headings, not a short summary. So the card shows
  both under «Описание», below prices, never in the header. `…RuRu` variants
  are empty everywhere. `description_html` drops a `description` that just
  repeats the product name.
- `clean_description`: `nh3` with the `releases.rendering` allowlist **minus
  `<img>`** (PIM images answer 401 without a token). It strips empty wrappers
  and headings left with nothing under them (PIM templates leave
  «<h4>Преимущества</h4><ul></ul>»). Text with no tags goes through
  `linebreaks(escape())`; `a < b` is still text.
- The legacy `MainProduct` card
  (`main_product_manager/templates/mainproduct/partials/detail.html`) used to
  print them autoescaped (literal tags); its views now pass them through the
  same `clean_description` (`main_product_manager/views.py:99-100,120-121`).
  Import direction: `main_product_manager` imports from `product.pim_content`.

## PIM link

`pim_product_url` -> `https://{PIM_HOST}/#Product/view/{id}`; it tolerates a
scheme in `PIM_HOST` (the compose placeholder has one). `price`/`rrp` from PIM
are left out of «Прочее из PIM» on purpose — beside ГП prices they confuse.
