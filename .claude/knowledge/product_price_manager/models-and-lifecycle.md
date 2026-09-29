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

**Category and brand scope (migration 0008)** — M2M `categories`
(`product.Category`) and `brands` (`product.Brand`), applied in
`_in_scope()` to both `get_fitting_mps()` and `_fitting_unsupplied_mps()`.
A chosen category covers its descendants (`get_queryset_descendants`); the
two narrow together (AND). The filter is a `product__in=<Product subquery>`,
not a join: a product in two chosen categories would otherwise yield its row
twice, and the PriceTag upsert (`bulk_create(update_conflicts=True)`) fails
when one statement updates the same row twice. The M2M go through
`PriceManagerCategory`/`PriceManagerBrand` with `on_delete=PROTECT` on the
category/brand: with auto-created through tables, deleting a rule's only brand
would empty its scope and silently widen it to every row. Custom through
tables also keep the two fields out of the admin form (`formfield_for_manytomany`
skips them) — the rule form is where they are edited.

**Known gap:** when PIM moves a product to another category or brand, its row
leaves a rule's scope, but `apply()` only *adds* tags (`update_pricetags`) —
the stale tag and the price stay until the rule is edited and re-synced.

**Legacy stale tags:** before `sync_pricetags` existed, create ran `save()`
before `discounts.set()`, so rules with discount groups hold tags on rows
outside their groups. The first edit of such a rule prunes them and NULLs
the unclaimed prices. The earlier `categories`
field (flat nodes, no descendants, unused) was dropped by 0006, which
**raises** while any rule still has categories.

**PriceTags are built after the M2M, not in a bare `save()`.** Scope lives in
M2M, and M2M is written only after `save()`, so a rule that built its tags in
`save()` tagged every row of its supplier on create. The views
(`views._save_rule`) and the admin (`save_model`/`save_related`) therefore save
with `sync_pricetags=False`, write the M2M, then call `sync_pricetags()`.
A bare `save()` still syncs (tests, `deprecate()` short-circuits on
`deprecated`). `sync_pricetags()` also **removes** the rule's tags of rows that
left the scope or sit on an old `dest`, and NULLs that price when no other
active tag (`_active_pricetags`) claims the row's dest — otherwise the price
would freeze. Rows claimed by another rule keep it until the next
`update_prices`.

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

- **`save()`** calls `super().save()` then, unless `sync_pricetags=False`,
  `sync_pricetags()`: prunes stale tags and **bulk-upserts PriceTags** for
  every fitting product (`update_conflicts=True`,
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
