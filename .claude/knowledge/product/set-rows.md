---
title: Set rows — the ГП row of a set
summary: MainProduct.is_set: one supplier-less ГП row per set whose prime cost, stock and delivery days only product/services/set_rows writes; when it runs and how a row is retired.
code: price_manager/product/services/set_rows.py, price_manager/main_product_manager/models.py, price_manager/product_price_manager/models.py, price_manager/main_product_manager/utils.py
---
# Set rows — the ГП row of a set

A set row is a `MainProduct` with `is_set=True` and `supplier` NULL, one per set
(partial `UniqueConstraint` on `product` where `is_set`,
`main_product_manager/models.py:46`). Returns, bonuses and leftovers belong to
«Свой склад» instead ([[supplier_manager/own-stock]]). For what a set is, see
[[product/sets]].

A set row behaves like any ГП row — prices, markups, cart, export, the
product's main prices — except three numbers that **only
`product/services/set_rows.py` writes**, from the composition
(`set_costs.set_totals_for`):

- `prime_cost` = Σ amount × the component's **main** prime cost;
- `stock` = how many sets the components' main stocks make;
- `set_delivery_days` = the longest of the components' delivery days, each taken
  from the supplier of that component's main-stock row.

**Incomplete is never written.** If any component lacks the value (no price,
not in Price Manager, no stock, no delivery days), the field stays **NULL**,
not a partial sum: a markup from a partial prime cost would pass off a price
for an incomplete set as real. The empty source then clears that markup's price
too, via `clear_unsourced_prices` ([[product_price_manager/pricing]]).

`MainProduct.get_delivery_days()` (`models.py:130`) is **the one way to read a
row's delivery days**: `set_delivery_days` for a set row, the supplier's
stock-dependent days otherwise.

## When it runs

- **End of `update_prices`**, after every rule and fixed markup — sets go
  last because the rules just changed the components' prime costs. Then one
  more pass of the **supplier-less rules** (non-`SP_PRICES` sources) and the set
  rows' own fixed markups, on the new prime cost
  (`product_price_manager/models.py:763-775`).
- **After `sync_product_sets`** (`product/tasks.py:118`) — a new set gets its
  row, a changed composition its numbers.
- **End of `update_stocks`**: `sync_set_stocks` recounts stock and delivery
  days only (`main_product_manager/utils.py:551`), so stock does not wait for
  the price run. `update_stocks` itself skips set rows ([[main_product_manager/tasks]]).

All local DB work, no PIM.

## Creation and retirement

`sync_set_rows` creates a missing row (`_create_missing_rows`) and **retires**
the row of a product that stopped being a set (`_retire_stale_rows`,
`set_rows.py:87`) instead of deleting it — it may carry markups and cart
references. Retiring sets `is_set=False`, supplier → «Свой склад», and **clears
`prime_cost`** (with a log row) and `set_delivery_days`: a frozen component sum
would look typed in. Stock keeps its last computed value and is hand-edited from
then on — the row has no `SupplierProduct`, so `update_stocks` leaves it alone.
The same pass moves **stray** supplier-less non-set rows (e.g. an admin import
with an empty supplier) to «Свой склад», prices as they are.

## Who may write these fields

- A rule without a supplier never writes a set row's `prime_cost`
  (`_fitting_unsupplied_mps` excludes `is_set` rows for `dest='prime_cost'`).
- The «Строка ГП» modal disables supplier, sku, article, `prime_cost` and
  `stock` on a set row ([[main_product_manager/gp-rows-by-hand]]).
