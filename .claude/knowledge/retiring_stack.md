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

## Isolation is clean — verify before claiming otherwise

Nothing in the live apps imports `pricing`, `supplier`, `supplier_feed`, or
`dataframe`. These four reference only each other and are reachable only via
`/api/`. That isolation is the single most valuable property they have: it is
what makes eventual deletion cheap. **A live app importing one of these is a
blocker**, not a shortcut.

## What each one holds

- **`dataframe`** (1686 LOC) — `Dataframe:13`, plus `registry.py`,
  `services.py`, `sessions.py`, `cache.py` and a `functions/` package. The most
  machinery of the four.
- **`supplier_feed`** (3077 LOC, largest) — `FeedMapping:23`, `SupplierFeed:53`,
  `SupplierFeedEntry:88`, `FeedColumnMapping:123`, `SupplierLink:170`, plus
  `matcher.py` and one `@shared_task`. It is a parallel, unfinished
  implementation of what [[supplier_product_manager]] does for real. Do not
  copy patterns *out* of it; do not add to it.
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
