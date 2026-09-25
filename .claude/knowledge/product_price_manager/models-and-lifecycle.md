---
title: PriceManager, PriceTag and their lifecycle
summary: The two models and the catalog-wide side effects of save/apply/delete/deprecate.
code: price_manager/product_price_manager/models.py
---
# PriceManager, PriceTag and their lifecycle

See [[product_price_manager/overview]] for how this app fits the rest of the
repo, and [[product_price_manager/pricing]] for `get_fitting_mps()` and
`update_prices()`, which every method below calls into.

## Two models

**`PriceManager:21`** — the rule. Scoped by `supplier`, M2M `discounts` and
`categories`, a `date_from`/`date_to` window, a `price_from`/`price_to` band,
and `has_rrp`.

**`categories` are `product.Category` since Phase 2b (migration 0004), read
through `MainProduct.product`.** Three things follow, all deliberate:
- **An empty `categories` means "every product of the supplier".**
  `get_fitting_mps` only filters when `categories.exists()`. So anything that
  empties the field silently widens a rule to the whole catalogue on its next
  `save()`/`apply()`. Migration 0004 had to recreate the M2M (Django can't
  retarget one), so it **raises** if any rule has categories instead of
  wiping them — it was proven on the restored snapshot.
- **Flat membership, no descendants** — as before the move. Choosing
  «Инструмент» does not match products filed under «Инструмент > Дрели».
  (The product page and the cart *do* expand descendants; rules never did.)
- **A `MainProduct` with no `product` can't match a scoped rule.** The join
  goes through the nullable FK. Unscoped rules still see it.

The rule form's category picker offers the categories the supplier's products
have, via `views._supplier_categories()` (`views.py:52`).

The arithmetic is `source → dest`, where:
- `source` (`models.py:77`) may be a **supplier** price (`rrp`,
  `supplier_price` — "в валюте поставщика", so currency conversion applies),
  a **main** price (`basic_price`, `prime_cost`, `m_price`,
  `wholesale_price`, `wholesale_price_extra`, `discount_price`), or the
  literal `fixed_price`.
- `dest` (`models.py:90`) is main-product only — you can read from a supplier
  price but never write back to one.
- Modifiers: `markup` (multiplier), `increase` (additive), `fixed_price`.

**`PriceTag:348`** — the per-product-per-rule **snapshot**. It copies `source`,
`dest`, `markup`, `increase`, `fixed_price` off the rule at write time. So a
`PriceTag` records what the rule said *then*, not what it says now. Unique on
`(mp, p_manager, dest)` (`UniqueConstraint` at `models.py:352`) — that triple
is the identity used by every upsert.

## Lifecycle methods have side effects — all four of them

- **`save():290`** calls `super().save()` then immediately **bulk-upserts
  PriceTags** for every fitting product (`update_conflicts=True`,
  `unique_fields=['mp','p_manager','dest']`). Saving a rule is a catalog-wide
  write. It short-circuits when `deprecated`.
- **`apply():315`** is the one that moves money: filters to products whose
  dest differs from `changed_price`, bulk-creates `MainProductLog` rows,
  refreshes pricetags via `update_pricetags()`, then
  `.update(dest=F('changed_price'), price_updated_at=now)`. Contains leftover
  `print()` debugging (`:328`–`:331`, four statements) that fires on every
  non-empty apply — noise in worker logs, not an error.
- **`delete():334`** **nulls the dest price on every fitting product** before
  deleting the rule. Deleting a rule is destructive to product data.
- **`deprecate():339`** — deletes the rule's pricetags, sets
  `deprecated=True`, nulls dest prices. The soft-delete counterpart to
  `delete()`. Note it computes `get_fitting_mps()` *before* deleting the
  pricetags, which is safe since that query doesn't depend on pricetag rows.

`update_pricetags():266` is the incremental version of the `save()` upsert —
it only creates tags for products that don't already have one from this rule
(`~Q(pk__in=self.pricetags.values_list('mp', flat=True))`).
