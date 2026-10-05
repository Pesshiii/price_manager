---
title: Applying prices
summary: get_fitting_mps (starts from the supplier's MainProducts, price-list filters as Exists), empty source means no price, update_prices.
code: price_manager/product_price_manager/models.py
---
# Applying prices

See [[product_price_manager/models-and-lifecycle]] for `PriceManager` and
`PriceTag` themselves — `save`, `apply`, `delete` and `deprecate` all call
into `get_fitting_mps()` below.

## `get_fitting_mps()` (`models.py:194`) — starts from the supplier's ГП rows

Returns the matching `MainProduct` queryset **annotated with `changed_price`**,
the post-markup value, computed via a `Subquery` over `calc_qs`
(`:277`/`:292`/`:307` per source branch, annotated at `:320`). A rule without a
supplier branches off at `:222` into `_fitting_unsupplied_mps` (`:326`).

**The candidate set starts from `MainProduct.objects.filter(supplier_id=rule.supplier_id)`
(`:230`), not from the supplier's `SupplierProduct` rows.** It used to start from
the price list; a hand-made ГП row (no `SupplierProduct`) was therefore never
reachable. Every price-list condition is now an `Exists` subquery on
`SupplierProduct(main_product=OuterRef('pk'))`, never a join:

- `has_rrp=True` → `Exists(rrp > 0)`; `has_rrp=False` → `Exists(rrp = 0 or NULL)`
  **OR no `SupplierProduct` at all** (a row without a price list is a row without
  an РРЦ) (`:233`–`:238`).
- discount groups → `Exists(discount in …)` (`:239`–`:240`); a row with no
  price-list row has no discount and never matches a rule scoped by discounts.
- a source in `SP_PRICES` **always requires** `Exists(SupplierProduct with the
  price range Q)` (`:242`–`:249`). So a row without a price-list row never matches
  a rule computing from a supplier price. This is deliberate: otherwise
  `clear_unsourced_prices` would find the dest "sourced" by an empty price and
  wipe the hand-typed value nightly.
- `MP_PRICES` source or fixed price: no price-list condition; the range Q (for
  `MP_PRICES`) is applied to `MainProduct` itself.

Why `Exists` and not a join: `mps` is re-wrapped as `pk__in` (`:256`) and stays
**join-free** because `apply()` updates it and `calc_qs` correlates against it
(`mps.filter(pk=OuterRef("pk"))`); a join would be dragged into both.

Consequence: **hand-made ГП rows of any supplier («Свой склад» included) are now
covered by that supplier's ГП-price and fixed-price rules**, and saving such a
rule builds `PriceTag`s on them. A test that creates "the same" rule tag by hand
now hits `pricetag_constraint` — fetch the auto-built tag instead.

Verified on the 2026-10-05 production snapshot when it changed (aggregates only):
0 of 130 rules changed their candidate set; 0 of 146,476 rows differed after
`update_prices` + `update_stocks`; total `PriceTag` count equal.

### One price-list row per product

Until #142 the docstring promised that supplier-price sourcing "takes the
minimum" across a product's supplier rows. It never did, and could not since
`SupplierProduct.main_product` became a `unique=True` FK (migration
`0009_alter_supplierproduct_main_product_unique`,
`supplier_product_manager/models.py:24`–`:30`). The uniqueness is on
`main_product` alone, not `(main_product, supplier)` — a `MainProduct` has at most
one `SupplierProduct`. There is nothing left to minimise over. The docstring
(`models.py:195`–`:202`) records the real behaviour; any other doc or comment
promising a minimum predates #142.

The source-price subquery (`:260`) is
`SupplierProduct.objects.filter(main_product=OuterRef('pk')).order_by('-updated_at').values(source)[:1]`
wrapped in `NullIf(..., 0)` — a tie-break that can no longer tie.
`PriceTag.get_sprice()` (`:581`) does the identical latest-row lookup on the
instance side (`self.mp.supplierproducts.order_by('-updated_at').first()`, `:585`)
before multiplying by `self.mp.supplier.currency.value`.

## An empty source is "no price" — cleared, never priced

A NULL **or 0** source price (supplier price, or a `MainProduct` price for
chained rules) means the product has no price. Before `clear_unsourced_prices`
existed, the SP branch coalesced NULL to 0, so a rule without
`price_from`/`price_to` priced such a product at its bare `increase` (or 0),
while a rule **with** a range simply lost the product — its old price stayed
forever, since no rule selected it any more.

Now:

- `get_fitting_mps` yields `changed_price = NULL` for an empty source
  (`NullIf(…, 0)` in both the SP and the MP branch) and `apply()` skips NULL
  rows (`changed_price__isnull=False`). **A rule only ever writes a real
  price.** Don't try to clear through `apply()`: `~Q(dest=F('changed_price'))`
  against a NULL is not a reliable selector.
- `PriceTag.get_sprice()` returns `None` for an empty source, so `get_mp()`
  skips manual tags too.
- **`clear_unsourced_prices()`** (`models.py:658`) runs last in
  `update_prices()` and does the clearing, keyed on active `PriceTag`s — the
  record of "this dest is computed from that source". A dest is set to NULL
  (with a `MainProductLog` row) only when **every** active tag on it has an
  empty source; a fixed-price tag or any tag with a real source keeps it. It
  repeats until nothing changes (bounded by `len(MP_PRICES)` passes), which
  clears the cascade (empty `prime_cost` → `basic_price` → `m_price`).
- `_clearing_candidates()` (`models.py:638`) prefilters with plain joins
  before the exact, subquery-heavy check. Without it the check scanned the
  whole catalogue on every `update_prices` (tens of seconds on production
  volume, where the whole task normally takes well under a minute); with it
  an ordinary run costs about a second. Keep the prefilter if you touch the
  exact check.

Measured on the production snapshot before rollout: almost everything the first
run clears is a `0` becoming NULL (including zeros cascaded through chained
rules); real non-zero prices cleared are on the order of a hundred.

`PriceTag.get_aggfunc()` was deleted in #142 (no `get_aggfunc` anywhere in the
app).

**Don't write code or tests that assume several `SupplierProduct` rows feed
one `MainProduct`'s price** — that shape is no longer reachable at the DB
level. See [[supplier_product_manager]] for the constraint itself and why it's
`unique=True` rather than `OneToOneField` (a `related_name` compatibility
reason, documented in a comment at `supplier_product_manager/models.py:20`).

Everything downstream — `save`, `apply`, `delete`, `deprecate` — calls this.
The live `get_price_querry` is the inner function at `models.py:203`; it has a
commented-out earlier version as its first lines (`:204`–`:211`) — don't mistake
the dead block for the implementation.

## `update_prices()` (`models.py:714`)

The bulk entry point, wrapped by `product_price_manager.update_prices`
(`tasks.py:9`–`:15`). Its inner `get_updated_mps(pricetags)` (`:715`) **merges
by product pk**: when several pricetags touch the same `MainProduct` with
different `dest` fields, it accumulates each `dest` onto one instance so a
single write carries all of them. Keep that merge if you refactor — dropping
it means later tags clobber earlier ones.

`clear_unsourced_prices()` runs once at the very end (`models.py:777`), after
every rule and every manual tag had its chance to write a real price.

The app's other two tasks are thin re-exports of
`main_product_manager.utils`: `update_stocks` and `update_logs`
(`tasks.py:18`, `:27`). All three route through `execute_locked_task`
([[core]]'s `core/task_runner.py`).
