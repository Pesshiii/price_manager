---
title: Isolation from the live stack
summary: The four apps are isolated with one qualification — verify before claiming otherwise.
code: price_manager/api_urls.py
---
# Isolation from the live stack

## Isolation is clean, with one qualification — verify before claiming otherwise

Nothing in the live apps (`core`, `supplier_manager`, `supplier_product_manager`,
`main_product_manager`, `product_price_manager`) imports `pricing`, `supplier`,
`supplier_feed`, or `dataframe`. That isolation is the single most valuable
property they have: it is what makes eventual deletion cheap (see
[[retiring_stack/rules]]). **A live app importing one of these is a
blocker**, not a shortcut.

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
six sites would only break when the code path actually runs.
`product/tests/test_migration_0007.py:10-11` does the same thing in reverse
(`product` importing `supplier`/`supplier_feed` at module top) — see
[[retiring_stack/rules]] for that migration coupling.

Direction overall is retiring → carved-out, so this isn't the "live app
depends on retiring app" blocker the paragraph above warns about — but it does
mean `supplier_feed` cannot be deleted independently of `product` without
breaking these call sites, in either direction.
