# product_price_manager

The markup engine: takes a source price, applies a rule, writes a destination
price onto `MainProduct` (cross-app imports per CLAUDE.md's *Key cross-app
dependencies*). Changes here have the widest blast radius per line in the
repo — `save()`/`apply()`/`delete()`/`deprecate()` on `PriceManager` all
rewrite product data catalog-wide, not just the rule row.

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
- `source` (`:77`) may be a **supplier** price (`rrp`, `supplier_price` — "в
  валюте поставщика", so currency conversion applies), a **main** price
  (`basic_price`, `prime_cost`, `m_price`, `wholesale_price`,
  `wholesale_price_extra`, `discount_price`), or the literal `fixed_price`.
- `dest` (`:90`) is main-product only — you can read from a supplier price but
  never write back to one.
- Modifiers: `markup` (multiplier), `increase` (additive), `fixed_price`.

**`PriceTag:339`** — the per-product-per-rule **snapshot**. It copies `source`,
`dest`, `markup`, `increase`, `fixed_price` off the rule at write time. So a
`PriceTag` records what the rule said *then*, not what it says now. Unique on
`(mp, p_manager, dest)` — that triple is the identity used by every upsert.

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

## Lifecycle methods have side effects — all four of them

- **`save():286`** calls `super().save()` then immediately **bulk-upserts
  PriceTags** for every fitting product (`update_conflicts=True`,
  `unique_fields=['mp','p_manager','dest']`). Saving a rule is a catalog-wide
  write. It short-circuits when `deprecated`.
- **`apply():311`** is the one that moves money: filters to products whose dest
  differs from `changed_price`, bulk-creates `MainProductLog` rows, refreshes
  pricetags via `update_pricetags()`, then `.update(dest=F('changed_price'),
  price_updated_at=now)`. Contains leftover `print()` debugging (`:319`–`:322`,
  four statements) that fires on every non-empty apply — noise in worker logs,
  not an error.
- **`delete():325`** **nulls the dest price on every fitting product** before
  deleting the rule. Deleting a rule is destructive to product data.
- **`deprecate():330`** — deletes the rule's pricetags, sets `deprecated=True`,
  nulls dest prices. The soft-delete counterpart to `delete()`. Note it computes
  `get_fitting_mps()` *before* deleting the pricetags, which is safe since that
  query doesn't depend on pricetag rows.

`update_pricetags():262` is the incremental version of the `save()` upsert — it
only creates tags for products that don't already have one from this rule
(`~Q(pk__in=self.pricetags.values_list('mp', flat=True))`).

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

## When touching this app

`PriceTag` is denormalised on purpose. Before "fixing" the duplication between
`PriceManager` and `PriceTag` fields, understand that the copy is the audit
trail. See [[main_product_manager]] for the dest price fields and
[[supplier_product_manager]] for `SP_PRICES`.

Test suite trap: any test that creates two `SupplierProduct` rows against one
`MainProduct` to exercise "minimum across rows" behaviour will fail with
`IntegrityError` on the unique constraint, not with a wrong price — the
constraint fires before any pricing code runs.

Line numbers throughout this file drift with every edit to `models.py` (the
whole file shifted ~9-13 lines since the last audit, 2026-09-22) — treat them
as approximate and re-grep before quoting one in an answer.
