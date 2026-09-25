---
title: retiring_stack — overview
summary: pricing, supplier, supplier_feed, dataframe: where they came from and what each holds.
code: price_manager/pricing/, price_manager/supplier/, price_manager/supplier_feed/, price_manager/dataframe/
---
# retiring_stack — overview

These four are the remains of an API-first rewrite that did not work out.
(`product` was the fifth; it has been carved out and is being rebuilt — see
[[product]].)

## What each one holds

(LOC counts are `grep -c ^` over each app's `.py` files, migrations and tests
included, `__init__.py`s excluded since they're empty — re-derive rather than
trust a stale number here, they drift every time a test file is added.)

- **`dataframe`** (1686 LOC) — `Dataframe:13`, plus `registry.py`,
  `services.py`, `sessions.py`, `cache.py` and a `functions/` package. The most
  machinery of the four.
- **`supplier_feed`** (2891 LOC, largest) — `FeedMapping:23`, `SupplierFeed:53`,
  `SupplierFeedEntry:88`, `FeedColumnMapping:123`, `SupplierLink:170`, plus
  `matcher.py` and one `@shared_task`. It is a parallel, unfinished
  implementation of what [[supplier_product_manager]] does for real. Do not
  copy patterns *out* of it; do not add to it. Its docstrings conflate two
  different things and can mislead — `SupplierFeedViewSet.create_product`
  (`api/views.py:263-271`) is the example: the docstring's field list
  ("number, name, categories and raw_data") describes what the PIM sync writes
  onto the `Product` row, not what the endpoint returns. The actual response
  is `SupplierFeedEntrySerializer(entry)`, whose `Meta.fields`
  (`api/serializers.py:61`) is `['id', 'supplier_sku', 'data',
  'match_candidates', 'best_score']` — none of those product fields ever reach
  the client. Read the serializer, not the docstring, before trusting a claim
  about what an endpoint returns. `FeedColumnMapping` (`models.py:123`) has no
  viewset — `api/urls.py:13-15` registers only `mappings` (`FeedMappingViewSet`,
  which manages `FeedMapping`, not `FeedColumnMapping`), `feeds`
  (`SupplierFeedViewSet`) and `links` (`SupplierLinkViewSet`). There is no CRUD
  surface for column mappings at all, and (as of this pass) no dedicated test
  module for it either — see [[retiring_stack/testing]].
- **`pricing`** (370 LOC) — `PriceType:4`, `PricingRule:17`. The abandoned
  counterpart to [[product_price_manager]]. `PricingRule.category`
  (`models.py:46-53`) is an FK to `product.Category` — another
  retiring-app-into-carved-out-app edge, alongside `supplier_feed`'s (see
  [[retiring_stack/isolation]]).
- **`supplier`** (173 LOC) — a second `Supplier:4`. The live one is in
  [[supplier_manager]]. Getting these two confused is the most common way to
  waste an hour in this repo.

See [[retiring_stack/rules]] for whether it's safe to build in or delete these,
and [[retiring_stack/isolation]] for how they connect (or don't) to the rest
of the tree.
