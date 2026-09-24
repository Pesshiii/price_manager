---
title: Tests — re-fetch, don't trust the returned instance
summary: Why product tests re-read rows instead of inspecting returned instances.
code: price_manager/product/tests/
---
# Tests — re-fetch, don't trust the returned instance

`test_pim_sync.py` (`SyncProductFromPimTests`) asserts via
`Product.objects.get(pk=product.pk)`, not on the instance
`sync_product_from_pim` returned — that's why the phantom-field bug (see
[[product/pim-sync]]) went undetected as long as it did. It's
`Product.objects.get(...)`, not `refresh_from_db()`: a fresh instance carries
only real columns, while `refresh_from_db()` leaves stray non-field
attributes on the existing instance intact and would let the same class of
bug pass silently again. `test_migration_0007.py` runs the migration's
`RunPython` function directly against ORM-created rows inside a normal
`TestCase` — the only place its filters meet real data (CI's DB is otherwise
empty; see [[product/migrations]]).
