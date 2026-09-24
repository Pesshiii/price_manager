---
title: Migrations — 0007 and the migration-graph trap
summary: The pim_id meaning-change migration, the seed migrations, and cross-app ordering traps.
code: price_manager/product/migrations/
---
# Migrations — 0007 and the migration-graph trap

## Migration `0007_product_pim_id_is_price_manager_product` — the meaning-change migration

The worked example for tightening/loosening a constraint on `Product` against
a populated database (`0006` used to be it — same step-ordering shape, plus a
cross-app dependency wrinkle here):

1. `AlterField pim_id → nullable` (`:55`) first — the next step can't write
   NULLs into a NOT-NULL column.
2. `RunPython(reset_pim_ids)` (`:27`) nulls **every** `pim_id` unconditionally
   — the old values are PIM `Product` ids, meaningless under the new schema.
   `reindex_pim_ids` re-derives them by `number` search.
3. Same RunPython deletes "residue": `Product`s with `number IS NULL` that
   nothing references — checked against `MainProduct.product`,
   `supplier_feed.SupplierFeedEntry.product` **and**
   `supplier_feed.SupplierLink.product` (`:36-41`). `SupplierLink.product` is
   `on_delete=CASCADE`; skipping that exclusion would silently take a
   supplier link down with its "orphan" `Product`.
4. Then `AlterField` on `number` (verbose name only) and `name` (drops
   `unique=True`).

Depends on `main_product_manager.0011` and `supplier_feed.0001` (`:48-51`)
because the `RunPython` reads those apps' models — a real cross-app migration
dependency, not just ordering. Not reversible on data (reverse is noop).
**CI migrates an empty database**, so this data step never meets a row there —
`product/tests/test_migration_0007.py` (imports the module via `importlib`
since its name starts with a digit, calls `reset_pim_ids` directly against
real rows) is the only coverage. **Deploy note:** run
`manage.py run_task reindex_pim_ids` right after migrating — no PIM data shows
on any `Product` until it re-pushes.

`0005_seed_products_from_main_product_pim_ids` bulk-creates a bare
`Product(pim_id=pim_id, number=None)` per then-existing `MainProduct.pim_id`
and never touches `name` — every seeded row lands with `name=''` (Django's
default for a nullable `CharField`) — invisible to CI since `0005` seeds zero
rows there. `0006_alter_product_name` added a unique constraint on `name`
despite that (nullable → `RunPython` turning `''` into `NULL`, raising with
the offending duplicate values rather than a bare `IntegrityError` →
`AlterField unique=True`); `0007` removes the constraint again for the reason
above, repeating the same three-step shape. `0002`/`0003` briefly carried
embedding/characteristics-era fields (`sku`, `characteristics`,
`embedding_text_hash`, an FK to `supplier_manager.Manufacturer`, a
`product_chars_gin_idx`); `0003` removes every one of them — see "What it is
not" below. `0008_brand_and_product_search_vector` is purely additive
(`Brand`, `Product.brand`, `Product.search_vector` + its GIN index) — no data
migration, nothing to trap here. `0009_product_number_case_insensitive`
replaces `number`'s plain `unique=True` with the `Lower('number')`
`UniqueConstraint` above. `0010_product_export` adds `ProductExport` (see the
export section below) — purely additive. `0011_productsetitem` adds
`ProductSetItem` — purely additive, see below.

### Migration-graph trap — a cross-app FK can silently reorder old migrations

`0002_product_sku.py` (now `:7-16`) originally added a `brand` FK to
`supplier_manager.Manufacturer` **without declaring a dependency on
`supplier_manager`**, and `supplier_manager.0011` (which deletes
`Manufacturer`) didn't depend on `product.0003` (which drops that FK) either.
Fresh-DB migration order held on luck until `core.0012` (an FK to
`product.Product`, depending on `product.0011`) reshuffled the graph and CI
started failing with «Related model 'supplier_manager.manufacturer' cannot be
resolved». Fixed in #233 by adding `('supplier_manager', '0001_initial')` to
`product.0002` and `('product', '0003_...')` to `supplier_manager.0011`
(`0002_product_sku.py:7-16`). **Lesson: any new cross-app dependency on
`product.*` can reorder migrations that looked settled for years — verify
with `migrate` on a fresh throwaway DB, not just CI as it stands today.**
