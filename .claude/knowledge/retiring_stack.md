# retiring_stack — `pricing`, `supplier`, `supplier_feed`, `dataframe`

These four are the remains of an API-first rewrite that did not work out.
(`product` was the fifth; it has been carved out and is being rebuilt — see
[[product]].)

## The two rules

**1. Do not build here.** New models, views, serializers or endpoints belong in
the live stack: `core`, `supplier_manager`, `supplier_product_manager`,
`main_product_manager`, `product_price_manager`.

**2. Do not delete them either.** All four are mounted in
`price_manager/api_urls.py` behind token auth:

```
/api/dataframe/       → dataframe.api.urls
/api/supplier-feed/   → supplier_feed.api.urls
/api/suppliers/       → supplier.api.urls
/api/pricing/         → pricing.api.urls
```

Whether anything **outside this repo** calls them is an **open question**. Ask a
human before removing any app, model, or route. Do not infer "unused" from the
absence of internal callers — internal callers were never the point of an API.

## Isolation is clean, with one qualification — verify before claiming otherwise

Nothing in the live apps (`core`, `supplier_manager`, `supplier_product_manager`,
`main_product_manager`, `product_price_manager`) imports `pricing`, `supplier`,
`supplier_feed`, or `dataframe`. That isolation is the single most valuable
property they have: it is what makes eventual deletion cheap. **A live app
importing one of these is a blocker**, not a shortcut.

The one exception: `supplier_feed` imports `product` — the carved-out mirror
app (see [[product]]), not one of these four and not part of the live stack
either. Import sites: `api/views.py:223` and `api/views.py:273` (the latter is
`product.services.pim_sync.sync_product_from_pim`), `api/serializers.py:41`,
`tests/fixtures.py:39`, and three of four test modules that reference
`product.models.Product` inside a test method (`test_api_feeds.py`,
`test_feed_models.py`, `test_api_queue.py`) — all seven of those are
function-local imports. `tests/test_matcher.py:10` is the one exception to the
exception: `from product.models import Product` sits at module top next to the
`django.test` import, not inside a function. That means
`supplier_feed.tests.test_matcher` fails at import time (collection), not just
at call time, if `product.models.Product` ever moves or is renamed — the other
six sites would only break when the code path actually runs. Direction overall
is retiring → carved-out, so this isn't the "live app depends on retiring app"
blocker the paragraph above warns about — but it does mean `supplier_feed`
cannot be deleted independently of `product` without breaking these call
sites.

## What each one holds

- **`dataframe`** (1686 LOC) — `Dataframe:13`, plus `registry.py`,
  `services.py`, `sessions.py`, `cache.py` and a `functions/` package. The most
  machinery of the four.
- **`supplier_feed`** (3077 LOC, largest) — `FeedMapping:23`, `SupplierFeed:53`,
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
  about what an endpoint returns.
- **`pricing`** (370 LOC) — `PriceType:4`, `PricingRule:17`. The abandoned
  counterpart to [[product_price_manager]].
- **`supplier`** (180 LOC) — a second `Supplier:4`. The live one is in
  [[supplier_manager]]. Getting these two confused is the most common way to
  waste an hour in this repo.

## Testing note

These apps carry more test files than the live stack does (`supplier_feed`
alone has 10). Coverage here is not evidence of importance — it is a fossil of
how the rewrite was built. Don't spend effort maintaining it; don't delete it
either.

As of 2026-09, `supplier_feed`'s suite is red on a clean checkout: `docker
compose exec -T celery_worker python manage.py test supplier_feed` → 117
tests, 1 failure + 11 errors, unrelated to any specific in-flight change (the
mechanisms below are verified directly; the counts are a point-in-time
snapshot and could drift).

- 11 × `NoReverseMatch: Reverse for 'feedcolumnmapping-detail' not found` in
  `tests/test_api_column_mappings.py`. Not a naming mismatch: there is no
  `FeedColumnMappingViewSet` anywhere in `api/views.py`, and `api/urls.py:12-15`
  registers only `mappings` (`FeedMappingViewSet`), `feeds`
  (`SupplierFeedViewSet`) and `links` (`SupplierLinkViewSet`) — the whole CRUD
  resource that test module exercises was never wired into the router.
- 1 × `test_tasks.py::ReadRowsNanSanitizationTests.test_nan_values_become_none`
  — `AssertionError: nan is not None`; `_read_rows_from_sessions`
  (`supplier_feed/tasks.py`) is not converting pandas NaN to `None` on the path
  that test exercises.

This now has a consequence it didn't used to: `.github/workflows/ci.yml` runs
`python manage.py test --verbosity 2` — the whole suite, unfiltered, no app
selection, no `continue-on-error` — so these pre-existing `supplier_feed`
failures gate CI for every PR in the repo, not just changes that touch it.
Whether to fix, skip, or deselect them is a human call, not something to
decide unasked.
