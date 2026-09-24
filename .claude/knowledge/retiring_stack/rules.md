---
title: The two rules
summary: Rule 1 — do not build here; rule 2 — do not delete them either: all four are mounted under /api/ behind session auth.
code: price_manager/api_urls.py, price_manager/price_manager/settings/api.py
---
# The two rules

## The two rules

**1. Do not build here.** New models, views, serializers or endpoints belong in
the live stack: `core`, `supplier_manager`, `supplier_product_manager`,
`main_product_manager`, `product_price_manager`.

**2. Do not delete them either.** All four are mounted in
`price_manager/api_urls.py`:

```
/api/dataframe/       → dataframe.api.urls
/api/supplier-feed/   → supplier_feed.api.urls
/api/suppliers/       → supplier.api.urls
/api/pricing/         → pricing.api.urls
```

They sit behind the same session-cookie auth as the rest of the site, not a
token. `settings/api.py:9-14` sets `DEFAULT_AUTHENTICATION_CLASSES` to
`rest_framework.authentication.SessionAuthentication` and
`DEFAULT_PERMISSION_CLASSES` to `IsAuthenticated` — there is no
`rest_framework.authtoken` and no `TokenAuthentication` anywhere in the repo.
`api_auth/views.py` (`CsrfView`/`LoginView`/`LogoutView`/`MeView`) is a
CSRF-cookie + username/password login that calls `django.contrib.auth.login`,
i.e. it establishes the same Django session a browser gets from the normal
login form. `supplier_feed/api/views.py` sets
`authentication_classes = [SessionAuthentication]` explicitly on every
viewset; the other three apps don't override and just inherit the same
default. None of them use a bearer/API token.

**Answered 2026-09-19: nothing outside this repo calls them.** The owner confirmed
the `/api/` routes have no external consumer, so the four apps can be removed.
This used to be an open question, and the rule was not to infer "unused" from the
absence of internal callers. That rule was right; what settled it was the owner's
answer, not a grep.

**What still blocks a naive removal is the migration graph, not the API.**
`product/migrations/0007_product_pim_id_is_price_manager_product.py:48-52`
depends on `('supplier_feed', '0001_initial')` and loads
`SupplierFeedEntry`/`SupplierLink` via `apps.get_model` in its `RunPython`
(`reset_pim_ids`); `supplier_feed/migrations/0001_initial.py:11-16` in turn
depends on `dataframe.0001`, `pricing.0001`, `product.0001` **and
`supplier.0001`**, and holds FKs into `product.Product`
(`SupplierFeedEntry.product`, `SupplierLink.product`). Cut that edge first
(drop the dependency and the two `get_model` calls from `0007`, or squash
[[product]]'s migrations), or every `migrate` fails on a missing parent node —
including CI's fresh database. Production has already applied `0007`.

There is a second, independent coupling to the same migration:
`product/tests/test_migration_0007.py` is `product`'s own regression test for
`reset_pim_ids` — it imports `supplier.models.Supplier` (as `FeedSupplier`)
and `supplier_feed.models.SupplierLink` at module top (lines 10-11, not inside
a test method) to build a `SupplierLink` row and assert the migration's
`on_delete=CASCADE` guard against orphan deletion. Renaming either model
breaks this test at collection time, same failure mode as
`tests/test_matcher.py` below, just in the opposite direction (`product`
depending on `supplier`/`supplier_feed` instead of the reverse).
