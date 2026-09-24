---
title: product — overview and status
summary: What product is now and is not, and where it stands between the live and retiring stacks.
code: price_manager/product/models.py
---
# product — overview and status

**Read this before assuming anything about `product`.** PR #184 changed what
`Product.pim_id` *means*; the product-shift Phase 1 (2026-09-19) made
`Product` the root of search and filtering at `/products/`; PR #197
(2026-09-2x) redesigned that page (sticky filters, compact table, search
fixes); PRs #230/#236/#233 (2026-09-24) added **product sets** (`ProductSetItem`,
sync from PIM, set cost/buildable, page + export surfacing) — see that section
below. Re-verify anything below that predates those if this file looks old.
Design and decisions: `.claude/shift-to-product-brief.md`.

## What it is *now*

A **PIM-linked mirror**, being deliberately recreated and reconnected to the
live legacy stack — treat anything here as in-motion; check
`git log -- product/` if something surprises you.

`product/models.py` — read the whole thing:
- `Category(MPTTModel)` — `parent`(PROTECT) / `name` / `slug` / `pim_id`,
  unique constraint on `(parent, name)`, `order_insertion_by = ['name']`.
  `save()` auto-generates a unique `slug` via `slugify(allow_unicode=True)`
  with a `-2`, `-3` … suffix loop. **`__str__` recurses through `self.parent`**
  — see the N+1 trap below.
- `Brand` — `pim_id` (unique, PIM `brandId`), `name`. **Keyed on the id, never
  the name**: a PIM rename would otherwise fork one brand into two (real: R5,
  2026-09-21, 14 groups like STAYER/Stayer across 321 brands, merged in PIM
  not here). No alias layer by design — `supplier_manager.ManufacturerDict`
  solved that for supplier names, had 0 rows in prod, retired in Phase 2b-3.
  Added later than the rest of the model, in migration `0008`, alongside
  `search_vector`.
- `Product` — `pim_id` (nullable, unique — see next section for what it now
  identifies), `number` (nullable, the local match key = `MainProduct.sku`,
  never overwritten from PIM). **Not `unique=True` on the field** —
  uniqueness is a `Meta.constraints` `UniqueConstraint(Lower('number'),
  name='product_product_number_lower_uniq')` (`models.py:113-115`, added by
  migration `0009_product_number_case_insensitive`), i.e. **case-insensitive**:
  `sync_product_from_pim` matches with `number__iexact`, and so does
  `services/sets.py`'s `_candidates` — any new code matching a PIM number to a
  local `Product` must use `iexact` too, or it will create a duplicate that
  differs only in case. `name` (**not** unique), M2M `categories`, FK `brand`
  (nullable — PIM returns `brandId` as a **scalar**, hence FK not M2M),
  `raw_data` JSON, `search_vector` + GIN (`product_search_vector_gin`,
  `config='russian'`), timestamps. `ordering = ['-updated_at']`.
- `Product.display_name` (`models.py:120-133`) — `name`, else the first linked
  MainProduct's name, else (none linked) `number`, else `pim_id`. Needed because
  `name` comes from PIM and most Products (still true as of the last measured
  pass — see coverage below) have no PIM content at all.
- `Product._build_searchvector()` (`models.py:135-158`) builds **only from
  `raw_data`** — no network call. Joins with `' '`, not `''`: the old
  `MainProduct` version glued category names into one token, so neither word
  was searchable.
- `ProductSetItem` (`models.py:165-209`) — see «Product sets» below.
- `ProductExport` (`models.py:212-234`) — `user` FK (`related_name=
  'product_exports'`), `file` (`upload_to='product_exports/'`), `rows_count`,
  `created_at`. One row per completed export run; see the export section below.

## What it is *not* — earlier docs described these; they do not exist

No embeddings. No characteristics JSONB. No `ImportJob`. No
`CharacteristicMutationJob`. No pgvector usage anywhere in the Python code. If
you find a reference to any of these, it is stale documentation, not code you
haven't found yet.

## Status boundary — the subtle part

`CLAUDE.md` still lists `product` among the retiring five, with an exception
for the PIM-mirror reconnection. **The product shift has since gone further
than that exception described:** `Product` is now the root of search and
filtering, with its own page, and now also carries a second concept (sets)
entirely native to this app — not mirrored from `MainProduct`. Work that
serves that shift — decided by the user and specified in
`.claude/shift-to-product-brief.md` — is in scope. Growing `product` into
something *independent of PIM and the legacy stack* is still not. It remains
the only one of the five with no `api/` package — not mounted in
`api_urls.py`. Its siblings are covered by [[retiring_stack]].
