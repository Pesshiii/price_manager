---
title: The two rules
summary: Rule 1 — do not build here. Rule 2 — removal is allowed (owner confirmed 2026-09-19), but cut product's migration dependency on supplier_feed first.
code: price_manager/api_urls.py, price_manager/price_manager/settings/api.py
---
# The two rules

## Rule 1 — do not build here

New models, views, serializers or endpoints belong in the live stack: `core`,
`supplier_manager`, `supplier_product_manager`, `main_product_manager`,
`product_price_manager`. See CLAUDE.md's "Direction of travel" for why.

## Rule 2 — removal is allowed, but the migration edge has to be cut first

All four are mounted in `price_manager/api_urls.py`:

```
/api/dataframe/       → dataframe.api.urls
/api/supplier-feed/   → supplier_feed.api.urls
/api/suppliers/       → supplier.api.urls
/api/pricing/         → pricing.api.urls
```

They sit behind the same session-cookie auth as the rest of the site, not a
token. `price_manager/price_manager/settings/api.py:9-14` sets
`DEFAULT_AUTHENTICATION_CLASSES` to
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

**CLAUDE.md's "Direction of travel" section is the source of truth here: the
owner confirmed on 2026-09-19 that nothing outside the repo calls the `/api/`
routes, so the four apps can be removed.** That used to be an open question —
don't re-derive it from a grep for callers, and don't ask again.

**What still blocks a naive removal is the migration graph, not the API.**
`product/migrations/0007_product_pim_id_is_price_manager_product.py:48-52`
depends on `('supplier_feed', '0001_initial')` and loads
`SupplierFeedEntry`/`SupplierLink` via `apps.get_model` in its `RunPython`
(`reset_pim_ids`, lines 27-43); `supplier_feed/migrations/0001_initial.py:11-16`
in turn depends on `dataframe.0001`, `pricing.0001`, `product.0001` **and
`supplier.0001`**, and holds FKs into `product.Product`
(`SupplierFeedEntry.product` at `supplier_feed/migrations/0001_initial.py:82`,
`SupplierLink.product` at the same file's line 95). Cut that edge first (drop
the dependency and the two `get_model` calls from `0007`, or squash
[[product]]'s migrations), or every `migrate` fails on a missing parent node —
including CI's fresh database. Production has already applied `0007`, so
editing it changes nothing there; the edit only has to keep a fresh database
migrating.

This is a one-directional edge inside a graph that also runs the other way
elsewhere in the tree — `product/migrations/0002_product_sku.py:15` depends on
`supplier_manager.0001` (a stale FK, `product.brand → supplier_manager.Manufacturer`,
long since replaced) and `supplier_manager/migrations/0011_retire_category_and_manufacturer.py:59`
depends on `product.0003` before it can drop `Manufacturer`. Neither of those
touches `supplier_feed`/`dataframe`/`pricing`/`supplier`; they're `product` ↔
`supplier_manager`, a live-stack pairing, not a retiring-stack one. Mentioned
here only so the retiring-stack edge isn't mistaken for the only cross-app
migration dependency in the repo — see [[product]] for that half.

There is a second, independent coupling to the same migration:
`product/tests/test_migration_0007.py:10-11` is `product`'s own regression
test for `reset_pim_ids` — it imports `supplier.models.Supplier` (as
`FeedSupplier`) and `supplier_feed.models.SupplierLink` at module top, not
inside a test method, to build a `SupplierLink` row and assert the
migration's `on_delete=CASCADE` guard against orphan deletion. Renaming
either model breaks this test at collection time, same failure mode as
`tests/test_matcher.py` in [[retiring_stack/isolation]], just in the opposite
direction (`product` depending on `supplier`/`supplier_feed` instead of the
reverse).
