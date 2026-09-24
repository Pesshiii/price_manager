---
title: Applying prices
summary: get_fitting_mps, empty source means no price, update_prices.
code: price_manager/product_price_manager/models.py
---
# Applying prices

## `get_fitting_mps()` (`:140`) — one supplier row per product, by construction

Returns the matching `MainProduct` queryset **annotated with `changed_price`**,
the post-markup value, computed via a `Subquery` (`_changed_price`, built at
`:216`/`:231`/`:246` depending on the source branch) over `calc_qs`.

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
The docstring (`:142`–`:147`) now records the real behaviour; any other doc or
comment promising a minimum predates #142.

The SP_PRICES branch (`:199`–`:211`) takes the **latest row by `updated_at`**:
`products.filter(main_product=OuterRef('pk')).order_by('-updated_at')
.values(source)[:1]` — a tie-break that can no longer tie now that the FK is
unique — wrapped in `NullIf(..., 0)`. `PriceTag.get_sprice()` does the
identical latest-row lookup on the instance side
(`self.mp.supplierproducts.order_by('-updated_at').first()`) before multiplying
by `self.mp.supplier.currency.value`.

## An empty source is "no price" — cleared, never priced

A NULL **or 0** source price (supplier price, or a `MainProduct` price for
chained rules) means the product has no price. Before `clear_unsourced_prices`
existed, the SP branch
coalesced NULL to 0, so a rule without `price_from`/`price_to` priced such a
product at its bare `increase` (or 0), while a rule **with** a range simply lost
the product — its old price stayed forever, since no rule selected it any more.

Now:

- `get_fitting_mps` yields `changed_price = NULL` for an empty source
  (`NullIf(…, 0)` in both the SP and the MP branch) and `apply()` skips NULL
  rows (`changed_price__isnull=False`). **A rule only ever writes a real
  price.** Don't try to clear through `apply()`: `~Q(dest=F('changed_price'))`
  against a NULL is not a reliable selector.
- `PriceTag.get_sprice()` returns `None` for an empty source, so `get_mp()`
  skips manual tags too.
- **`clear_unsourced_prices()`** runs last in `update_prices()` and does the
  clearing, keyed on active `PriceTag`s — the record of "this dest is computed
  from that source". A dest is set to NULL (with a `MainProductLog` row) only
  when **every** active tag on it has an empty source; a fixed-price tag or any
  tag with a real source keeps it. It repeats until nothing changes, which
  clears the cascade (empty `prime_cost` → `basic_price` → `m_price`).
- `_clearing_candidates()` prefilters with plain joins before the exact,
  subquery-heavy check. Without it the check scanned the whole catalogue on
  every `update_prices` (tens of seconds on production volume, where the whole
  task normally takes well under a minute); with it an ordinary run costs about
  a second. Keep the prefilter if you touch the exact check.

Measured on the production snapshot before rollout: almost everything the first
run clears is a `0` becoming NULL (including zeros cascaded through chained
rules); real non-zero prices cleared are on the order of a hundred.

`PriceTag.get_aggfunc()` — a same-era leftover returning a bare `max` that
nothing but its own test ever called — was deleted in #142, together with
`test_pricetag_get_aggfunc_callable`. Confirmed gone (no `get_aggfunc` anywhere
in the app).

**Don't write code or tests that assume several `SupplierProduct` rows feed
one `MainProduct`'s price** — that shape is no longer reachable at the DB
level. See [[supplier_product_manager]] for the constraint itself and why it's
`unique=True` rather than `OneToOneField` (a `related_name` compatibility
reason, documented in a comment right above the field).

Everything downstream — `save`, `apply`, `delete`, `deprecate` — calls this.
`get_price_querry` (`:149`) has a commented-out earlier version directly above
the live one (`:150`–`:157`); don't mistake the dead block for the
implementation.

## `update_prices()` (`models.py:464`)

The bulk entry point, wrapped by `product_price_manager.update_prices`
(`tasks.py:9`). Its inner `get_updated_mps(pricetags)` (`:465`) **merges by
product pk**: when several pricetags touch the same `MainProduct` with different
`dest` fields, it accumulates each `dest` onto one instance so a single write
carries all of them. Keep that merge if you refactor — dropping it means later
tags clobber earlier ones.

The app's other two tasks are thin re-exports of
`main_product_manager.utils`: `update_stocks` and `update_logs` (`tasks.py:18`,
`:28`). All three route through `execute_locked_task`.
