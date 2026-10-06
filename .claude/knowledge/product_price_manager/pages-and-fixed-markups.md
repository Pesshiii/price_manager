---
title: «Менеджеры цен», «Наценки», «Наборы» rules and fixed markups
summary: The two list pages and their filters, supplier-less («Наборы») rules, and the per-row fixed markup (PriceTag without a rule) with its single modal.
code: price_manager/product_price_manager/views.py, price_manager/product_price_manager/models.py, price_manager/product_price_manager/templates/price_manager/
---
# «Менеджеры цен», «Наценки», «Наборы» rules and fixed markups

UI vocabulary: a `PriceManager` is «менеджер цен», a `PriceTag` is «наценка».
The models themselves are in [[product_price_manager/models-and-lifecycle]].

## «Менеджеры цен» — `/price-manager/` (`PriceManagerPage`)

Every rule, of suppliers and without. `?supplier=none|<pk>` filters
(`none` = the «Наборы» pill), `?deprecated=1` shows deprecated ones. The rule
form is a modal; its live refresh (`?refresh=1`) and the supplier lock on edit
are in [[product_price_manager/models-and-lifecycle]].

## «Наборы» — a rule with `supplier` NULL

A supplier-less rule prices the ГП rows without a supplier — **set rows**, bar
the odd stray that the next `sync_set_rows` moves away ([[product/set-rows]]) —
through `_fitting_unsupplied_mps` (`models.py:326`):

- only from ГП prices (`MP_PRICES`) or a fixed price — a source from the
  supplier price list matches no row at all (`mps.none()`), it does not compute
  from an empty price;
- never the `prime_cost` of a set row (`is_set` rows are excluded for that dest:
  the components own it);
- category/brand scope, the price range and the formula work as for any rule.

In the form the empty supplier choice is labelled «Наборы — строки наборов».
In `update_prices` these rules get a second pass after `sync_set_rows`
([[product_price_manager/pricing]]).

## Fixed markup — a `PriceTag` with no rule

A markup on **one ГП row**: `PriceTag` with `p_manager` NULL, «фиксированная
наценка». Either a fixed price or a formula from a ГП/supplier price.
`update_prices` applies these **after** the rules, so they override them.

- Added from the tag button of a row on the product card: `PriceTagCreate`,
  `pricetag/create-for/<mp pk>`.
- Edited **and deleted** in the same modal: `PriceTagUpdate`
  (`pricetag/<pk>/update`, `POST delete=true` deletes). Its queryset is
  `p_manager__isnull=True`, so opening a **rule's** tag there is a **404** — a
  rule tag is edited through its rule, and the next recalculation would
  overwrite a hand edit anyway.
- Form checks: `_pricetag_form_error` (fixed price present, or a source that is
  not the dest).

## «Наценки» — `/price-manager/pricetags/` (`PriceTagPage`)

Every `PriceTag`, of rules and fixed, as a tab next to «Менеджеры цен».
Filters: `?rule=none|<pk>` (`none` = fixed markups), `?supplier=none|<pk>`
(`none` = set rows), `?q=` (sku, article or name of the row or its Product),
`?dest=`, `?deprecated=1`. A rule tag's edit button opens **its rule's** modal
(`pricemanager-update`); a fixed tag's opens `PriceTagUpdate`.

The old `/price-manager/fixed/` («Фиксированные наценки») redirects here with
`rule=none`, keeping the rest of the query (`fixed_pricetags_redirect`).
