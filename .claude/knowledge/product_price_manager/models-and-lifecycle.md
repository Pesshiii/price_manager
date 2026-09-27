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

**`PriceManager`** — the rule. Scoped by `supplier`, M2M `discounts`, a
`date_from`/`date_to` window, a `price_from`/`price_to` band, and `has_rrp`.

**There is no category scope any more** — migration 0006 dropped
`PriceManager.categories` (flat nodes, no descendants, unused; category pricing
belongs to `product_pricing.ProductPriceRule`, which expands descendants).
Dropping the field drops its filter, so 0006 **raises** while any rule still
has categories, like 0004 did — a scoped rule would otherwise widen to the
whole supplier on its next `save()`/`apply()`.

**The rule form is live** (`forms.PriceManagerForm`). The supplier is a field
of the form — there is no separate «choose supplier» step — and the
discount/source choices are narrowed in `__init__` *before* validation, from
the posted supplier. Changing supplier/source/dest posts the whole form to the
same URL with `?refresh=1` (`views.RuleFormRefreshMixin`), which re-renders
`#pm-rule-fields` from `initial` and never reaches `form_valid` — a real save
rebuilds PriceTags. On edit the supplier is `disabled`: `save()` never removes
PriceTags of rows that fall out of a rule, so moving a rule to another supplier
would leave the old rows priced. `create-for/<pk>` and `?supplier=` only
preselect; the form always posts to `price-manager/create/`.

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
