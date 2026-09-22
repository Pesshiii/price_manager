# retiring_stack — `pricing`, `supplier`, `supplier_feed`, `dataframe`

These four are the remains of an API-first rewrite that did not work out.
(`product` was the fifth; it has been carved out and is being rebuilt — see
[[product]].)

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
`tests/fixtures.py:39`, and three test modules that reference
`product.models.Product` inside a test method (`test_api_feeds.py:128`,
`test_feed_models.py:86`, `test_api_queue.py:26`) — all seven of those are
function-local imports. `tests/test_matcher.py:10` is the one exception to the
exception: `from product.models import Product` sits at module top next to the
`django.test` import, not inside a function. That means
`supplier_feed.tests.test_matcher` fails at import time (collection), not just
at call time, if `product.models.Product` ever moves or is renamed — the other
six sites would only break when the code path actually runs. (See the previous
section for the mirror case: `product/tests/test_migration_0007.py` does the
same thing in reverse.)

Direction overall is retiring → carved-out, so this isn't the "live app
depends on retiring app" blocker the paragraph above warns about — but it does
mean `supplier_feed` cannot be deleted independently of `product` without
breaking these call sites, in either direction.

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
  viewset — `api/urls.py:12-15` registers only `mappings` (`FeedMappingViewSet`,
  which manages `FeedMapping`, not `FeedColumnMapping`), `feeds`
  (`SupplierFeedViewSet`) and `links` (`SupplierLinkViewSet`). There is no CRUD
  surface for column mappings at all, and (as of this pass) no dedicated test
  module for it either — see Testing note.
- **`pricing`** (370 LOC) — `PriceType:4`, `PricingRule:17`. The abandoned
  counterpart to [[product_price_manager]]. `PricingRule.category`
  (`models.py:46-53`) is an FK to `product.Category` — another
  retiring-app-into-carved-out-app edge, alongside `supplier_feed`'s.
- **`supplier`** (173 LOC) — a second `Supplier:4`. The live one is in
  [[supplier_manager]]. Getting these two confused is the most common way to
  waste an hour in this repo.

## Testing note

These apps carry more test files than the live stack does (`supplier_feed`'s
`tests/` package alone has 10 files). Coverage here is not evidence of
importance — it is a fossil of how the rewrite was built. Don't spend effort
maintaining it; don't delete it either.

**A previously-recorded failure catalog for `supplier_feed` is stale — don't
repeat the old numbers.** Two specific things this file used to document are
gone, by deletion rather than by fix:

- `tests/test_api_column_mappings.py` (said to produce 11 ×
  `NoReverseMatch: Reverse for 'feedcolumnmapping-detail' not found`) does not
  exist in the current tree. The underlying gap it was testing is still real
  (see `FeedColumnMapping` above — still no viewset), but the test module that
  exercised the missing route is gone too, not wired up.
- The NaN-sanitization test this file used to name
  (`ReadRowsNanSanitizationTests.test_nan_values_become_none`) no longer
  exists. `tests/test_tasks.py:154-162` now carries `ReadRowsPassthroughTests`,
  whose docstring says outright that NaN handling "is deliberately NOT covered
  here... The test that caught that was removed in #135 when the retiring API
  stack was frozen; the defect is real and still present."
  `_read_rows_from_sessions` (`tasks.py:40-57`) still does
  `df.where(df.notna(), other=None)`, which pandas coerces back to `NaN` on a
  float column — so the original bug is unfixed, just untested now.

Get a fresh pass/fail count from an actual run before quoting one — this
keeper has no Docker access and can't produce one itself, and the two failure
modes it previously cited no longer apply as described.

This still has a real consequence: `.github/workflows/ci.yml:128` runs
`python manage.py test --verbosity 2` — the whole suite, unfiltered, no app
selection, no `continue-on-error` — so whatever is red in `supplier_feed`
today gates CI for every PR in the repo, not just changes that touch it.
Whether to fix, skip, or deselect any of it is a human call, not something to
decide unasked.
