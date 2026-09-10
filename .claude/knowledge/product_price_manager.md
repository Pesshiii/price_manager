# product_price_manager

The markup engine: takes a source price, applies a rule, writes a destination
price onto `MainProduct` (cross-app imports per CLAUDE.md's *Key cross-app
dependencies*). Changes here have the widest blast radius per line in the
repo — `save()`/`apply()`/`delete()`/`deprecate()` on `PriceManager` all
rewrite product data catalog-wide, not just the rule row.

## Two models

**`PriceManager:20`** — the rule. Scoped by `supplier`, M2M `discounts` and
`categories`, a `date_from`/`date_to` window, a `price_from`/`price_to` band,
and `has_rrp`.

The arithmetic is `source → dest`, where:
- `source` (`:72`) may be a **supplier** price (`rrp`, `supplier_price` — "в
  валюте поставщика", so currency conversion applies), a **main** price
  (`basic_price`, `prime_cost`, `m_price`, `wholesale_price`,
  `wholesale_price_extra`, `discount_price`), or the literal `fixed_price`.
- `dest` (`:84`) is main-product only — you can read from a supplier price but
  never write back to one.
- Modifiers: `markup` (multiplier), `increase` (additive), `fixed_price`.

**`PriceTag:326`** — the per-product-per-rule **snapshot**. It copies `source`,
`dest`, `markup`, `increase`, `fixed_price` off the rule at write time. So a
`PriceTag` records what the rule said *then*, not what it says now. Unique on
`(mp, p_manager, dest)` — that triple is the identity used by every upsert.

## `get_fitting_mps()` (`:135`) — one supplier row per product, by construction

Returns the matching `MainProduct` queryset **annotated with `changed_price`**,
the post-markup value, computed via a `Subquery` over `_changed_price`
(`:248`).

Until #142 the docstring promised that supplier-price sourcing "takes the
minimum" across a product's supplier rows — verbatim: `(при подсечете от цен
поставщика берет минимальное значение)`, typo "подсечете" included. It never
did, and could not since `supplier_product_manager` made
`SupplierProduct.main_product` a `unique=True` FK (migration
`0009_alter_supplierproduct_main_product_unique`,
`supplier_product_manager/models.py:24`–`:30`). The uniqueness is on
`main_product` alone, not `(main_product, supplier)` — so a `MainProduct` can
be sourced from at most one `SupplierProduct`, from at most one supplier,
globally. There is nothing left to minimise over, and only one `PriceManager`
(via its `supplier` scope) can ever reach a given product through SP_PRICES.
The docstring (`:137`–`:142`) now records the real behaviour; any other doc or
comment promising a minimum predates #142.

The SP_PRICES branch (`:191`–`:202`) takes the **latest row by `updated_at`**:
`products.filter(main_product=OuterRef('pk')).order_by('-updated_at')
.values(source)[:1]`, wrapped in `Coalesce(..., Decimal('0'))` — a tie-break
that can no longer tie now that the FK is unique. `PriceTag.get_sprice()`
(`:407`–`:418`) does the identical latest-row lookup on the instance side
(`self.mp.supplierproducts.order_by('-updated_at').first()`) before multiplying
by `self.mp.supplier.currency.value`.

`PriceTag.get_aggfunc()` — a same-era leftover returning a bare `max` that
nothing but its own test ever called — was deleted in #142, together with
`test_pricetag_get_aggfunc_callable`.

**Don't write code or tests that assume several `SupplierProduct` rows feed
one `MainProduct`'s price** — that shape is no longer reachable at the DB
level. See [[supplier_product_manager]] for the constraint itself and why it's
`unique=True` rather than `OneToOneField` (a `related_name` compatibility
reason, documented in a comment right above the field).

Everything downstream — `save`, `apply`, `delete`, `deprecate` — calls this.
`get_price_querry` (`:144`) has a commented-out earlier version directly above
the live one; don't mistake the dead block for the implementation.

## Lifecycle methods have side effects — all four of them

- **`save():273`** calls `super().save()` then immediately **bulk-upserts
  PriceTags** for every fitting product (`update_conflicts=True`,
  `unique_fields=['mp','p_manager','dest']`). Saving a rule is a catalog-wide
  write. It short-circuits when `deprecated`.
- **`apply():298`** is the one that moves money: filters to products whose dest
  differs from `changed_price`, bulk-creates `MainProductLog` rows, refreshes
  pricetags, then `.update(dest=F('changed_price'), price_updated_at=now)`.
  Contains leftover `print()` debugging (`:306`–`:309`) that fires on every
  non-empty apply — noise in worker logs, not an error.
- **`delete():312`** **nulls the dest price on every fitting product** before
  deleting the rule. Deleting a rule is destructive to product data.
- **`deprecate():317`** — deletes the rule's pricetags, sets `deprecated=True`,
  nulls dest prices. The soft-delete counterpart to `delete()`.

`update_pricetags():253` is the incremental version of the `save()` upsert — it
only creates tags for products that don't have one yet.

## `update_prices()` (`models.py:455`)

The bulk entry point, wrapped by `product_price_manager.update_prices`
(`tasks.py:9`). Its inner `get_updated_mps(pricetags)` (`:456`) **merges by
product pk**: when several pricetags touch the same `MainProduct` with different
`dest` fields, it accumulates each `dest` onto one instance so a single write
carries all of them. Keep that merge if you refactor — dropping it means later
tags clobber earlier ones.

The app's other two tasks are thin re-exports of
`main_product_manager.utils`: `update_stocks` and `update_logs` (`tasks.py:18`,
`:28`). All three route through `execute_locked_task`.

## When touching this app

`PriceTag` is denormalised on purpose. Before "fixing" the duplication between
`PriceManager` and `PriceTag` fields, understand that the copy is the audit
trail. See [[main_product_manager]] for the dest price fields and
[[supplier_product_manager]] for `SP_PRICES`.

Test suite trap: any test that creates two `SupplierProduct` rows against one
`MainProduct` to exercise "minimum across rows" behaviour will fail with
`IntegrityError` on the unique constraint, not with a wrong price — the
constraint fires before any pricing code runs.
