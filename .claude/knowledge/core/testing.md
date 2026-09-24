---
title: Testing core — the --keepdb trap
summary: Why running the core tests empties the database for every later --keepdb run.
code: price_manager/core/tests.py
---
# Testing core — the --keepdb trap

## Trap: running `core` empties the DB for every later `--keepdb` run

`ExecuteLockedTaskAtomicTests` (`core/tests.py:35`) must stay a
`TransactionTestCase` — `TestCase` wraps each test in a transaction, which
would make `connection.in_atomic_block` true regardless of `atomic=`. Django
truncates **every table** at a `TransactionTestCase`'s teardown and only
restores migration-seeded rows when `serialized_rollback = True` (not set
here, deliberately — re-serializing the whole DB on every run just papers
over the coupling rather than removing it). So running `core`'s tests deletes
the `KZT` `Currency` row seeded by `supplier_manager/migrations/0001_initial.py`;
since CLAUDE.md says to run with `--keepdb`, that deletion persists into later
runs and surfaces as 22 `Currency.DoesNotExist` errors from
`supplier_product_manager`'s `setUp` — in a *different* app, with nothing
wrong in the code under test. CI never reproduces it (fresh DB every run).
Symptom to recognise: an app's tests fail on `--keepdb` but pass without it,
in fixtures rather than assertions.

The fix is on the consuming side — no fixture may read a migration-seeded
row. Use `Currency.objects.get_or_create(name="KZT", defaults={"value":
Decimal("1")})`, as `supplier_product_manager/tests.py` (`:60`, `:561`,
`:645`, `:713`, `:799`) and `product_price_manager/tests.py:15` do. The
inline `get_or_create(name='KZT', value=1)` still at
`main_product_manager/tests.py:14`/`:106`/`:255`/`:478` is fragile: inline
kwargs are *lookups*, so a KZT row carrying any other value makes it attempt
an INSERT and die on the unique `name`. `Currency` is the only static seed in
the tree.
