# product_price_manager

The markup engine: takes a source price, applies a rule, writes a destination
price onto `MainProduct`. This is the app that **bridges** the catalogs — it
imports from `supplier_manager`, `supplier_product_manager` *and*
`main_product_manager` (`models.py:3`–`:5`). Changes here have the widest blast
radius per line in the repo.

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

**`PriceTag:325`** — the per-product-per-rule **snapshot**. It copies `source`,
`dest`, `markup`, `increase`, `fixed_price` off the rule at write time. So a
`PriceTag` records what the rule said *then*, not what it says now. Unique on
`(mp, p_manager, dest)` — that triple is the identity used by every upsert.

## `get_fitting_mps()` (`:133`) — read the docstring before touching it

Returns the matching `MainProduct` queryset **annotated with `changed_price`**,
the post-markup value, computed via a `Subquery` over `_changed_price`
(`:244`). When the source is a supplier price it takes the **minimum** across
that product's supplier rows.

Everything downstream — `save`, `apply`, `delete`, `deprecate` — calls this.
`get_price_querry` (`:140`) has a commented-out earlier version directly above
the live one; don't mistake the dead block for the implementation.

## Lifecycle methods have side effects — all four of them

- **`save():273`** calls `super().save()` then immediately **bulk-upserts
  PriceTags** for every fitting product (`update_conflicts=True`,
  `unique_fields=['mp','p_manager','dest']`). Saving a rule is a catalog-wide
  write. It short-circuits when `deprecated`.
- **`apply():298`** is the one that moves money: filters to products whose dest
  differs from `changed_price`, bulk-creates `MainProductLog` rows, refreshes
  pricetags, then `.update(dest=F('changed_price'), price_updated_at=now)`.
  Contains leftover `print()` debugging (`:305`–`:308`) that fires on every
  non-empty apply — noise in worker logs, not an error.
- **`delete():311`** **nulls the dest price on every fitting product** before
  deleting the rule. Deleting a rule is destructive to product data.
- **`deprecate():316`** — deletes the rule's pricetags, sets `deprecated=True`,
  nulls dest prices. The soft-delete counterpart to `delete()`.

`update_pricetags():249` is the incremental version of the `save()` upsert — it
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
