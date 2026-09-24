---
title: Testing the retiring apps
summary: A fossil test suite — neither maintain nor delete it; the old supplier_feed failure catalog is stale.
code: price_manager/supplier_feed/tests/
---
# Testing the retiring apps

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
