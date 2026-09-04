# product

**Read this before assuming anything about `product`.** It is the one app whose
status recently inverted, and stale mental models of it are actively wrong.

## What it is *now*

A plain **PIM-linked mirror**, being deliberately recreated and reconnected to
the live legacy stack. 45 of the last 200 commits — second-highest churn in the
repo, so treat anything here as in-motion.

`product/models.py` is short and complete — read the whole file, it's ~65 lines:
- `Category(MPTTModel)` — `parent`(PROTECT) / `name` / `slug` / `pim_id`,
  unique constraint on `(parent, name)`, `order_insertion_by = ['name']`.
  `save()` auto-generates a unique `slug` via `slugify(allow_unicode=True)`
  with a `-2`, `-3` … suffix loop.
- `Product` (`models.py:48`) — three unique columns, two of them nullable:
  `pim_id` required; `number` (`:50`) and `name` (`:51`) both
  `unique=True, null=True, blank=True`. **A missing `number`/`name` must be
  written as `None`, never `''`.** Postgres unique indexes treat NULLs as
  distinct but treat `''` as equal, so writing `''` for a missing value lets
  the first such row save and `IntegrityError`s every later one.
  `product/services/pim_sync.py:88-89` handles this correctly (`or None`,
  comment at `:84-87` explaining why not `or ''`). Regression tests
  `product/tests/test_models.py:63` (name) and `:71` (number).

  **Sharper trap underneath that one: Django's unset-field default for a
  `CharField` *inverts* depending on `null`, and this app hit both sides of
  it.** `Field._get_default` (`django/db/models/fields/__init__.py`, Django
  5.2.5 — the app is pinned to this version in `requirements.txt`) — for a
  field with `empty_strings_allowed=True` (true for `CharField`) on a backend
  where `connection.features.interprets_empty_strings_as_nulls` is `False`
  (Postgres; only Oracle sets it `True`) — resolves to: **`null=True` →
  default is `None`; `null=False` → default is `''`.** Backwards from the
  naive reading (you'd expect `null=True` to just *permit* `None`, not
  *become* the default). Two call sites construct a bare `Product(pim_id=…)`
  with `number`/`name` unset and can land on opposite defaults, because they
  see the field through different lenses:
  - `migrations/0005_seed_products_from_main_product_pim_ids.py` uses
    `apps.get_model('product', 'Product')` — the migration-**historical**
    frozen model, where `name` was still `null=False` (as of `0005`'s place
    in the dependency chain, before `0006` existed) → default `''`. This is
    what `0006`'s own docstring means by "under name's old NOT NULL
    definition every seeded row carries `''`".
  - `pim_sync.py:83`'s `Product.objects.get_or_create(pim_id=pim_id)` imports
    the **live** `product.models.Product` class, which reflects whatever
    `models.py` currently says regardless of what's actually been migrated.
    If `models.py` ever declares `name`/`number` `null=True` before the
    matching migration ships — models ahead of migrations, exactly the drift
    this session fixed with `0006` — the live model's default becomes `None`
    while the DB column is still `NOT NULL`, and `get_or_create` inserts
    literal NULL: `psycopg.errors.NotNullViolation` on `product_product`.
    This is not an edge case: `:83` only ever passes `pim_id`, so *every*
    call that creates a new product hits the same bare INSERT before
    `number`/`name` are ever assigned at `:88-89`, regardless of what the PIM
    payload contains. That is why, in that drifted state, all six tests in
    `SyncProductFromPimTests` (`product/tests/test_pim_sync.py`) fail
    identically — each one calls `sync_product_from_pim` for a `pim_id` that
    doesn't exist yet, so each one's very first action is the same doomed
    `get_or_create`, independent of whether its payload includes a name.

  Post-`0006` the live model and the applied schema agree (`null=True` in
  both), so `get_or_create`'s implicit default is already `None` and matches
  the `:88-89` fix-up — no bug currently reachable through this path. The
  trap is general, not fixed once: **whenever this app's `models.py` moves
  ahead of its migrations again, `pim_sync.py:83` is exactly where it will
  resurface** — and it will fail every sync that creates a new product, not
  just some of them.

`migrations/0005_seed_products_from_main_product_pim_ids.py` seeds it from
`MainProduct.pim_id` — bridge to [[main_product_manager]]. It never touches
`name`, so on a populated database every seeded row ends up with `name=''`
(per `0006`'s own docstring, and per the historical-model default above) —
meaning **`0005` seeds zero rows against CI's empty test database**, so a
schema migration whose correctness depends on data cleanup here can pass CI
and still fail on deploy. `migrations/0006_alter_product_name.py` exists to
make `name` unique despite that: three *ordered* operations — `AlterField`
to nullable, then `RunPython` turning `''` into `NULL` (raising with the
offending values if duplicate non-null names exist, rather than a bare
`IntegrityError` naming only an index), then `AlterField` adding
`unique=True`. The column has to be nullable before NULLs can be written,
and the `''` rows have to be gone before the constraint goes on —
collapsing the three into one `AlterField` is exactly what would pass CI and
fail on a populated database. As a rider, the same `RunPython` also
nullifies `number`'s `''` rows (`number` was already unique+nullable from
`0004`, so at most one such row could exist, but it blocked the next
nameless product from syncing). `makemigrations --check`
(`.github/workflows/ci.yml`, `.claude/hooks/check_migrations.py`) only diffs
model state against migration state and never touches data, so it cannot
catch either of these — not the seed-vs-populated-DB gap, and not the
live-model-vs-applied-schema drift that produces the `NotNullViolation`
above.

Open question, not resolved: whether PIM can legitimately return duplicate
product names. Nothing asserts it, no test covers it, and display-name-shared
variants are the usual way this breaks. `0006` refuses (raises) rather than
corrupts if duplicates exist at migrate time, but nobody has checked this
against a populated database.

## What it is *not* — earlier docs described these; they do not exist

No embeddings. No characteristics JSONB. No `ImportJob`. No
`CharacteristicMutationJob`. No pgvector usage anywhere in the Python code. If
you find a reference to any of these, it is stale documentation, not code you
haven't found yet.

## Sync path

`services/pim_sync.py` — `sync_product_from_pim(pim_id, data=None)` at `:72`,
with `_ensure_pim_category` (`:22`) walking/creating the category tree and
`_compute_category_path` (`:60`). Driven by the single task
`product.sync_product_from_pim` (`tasks.py:8`), which **does** route through
`execute_locked_task` with a per-`pim_id` lock name — good, copy this shape.
See the `Product` bullet above for the live-model-vs-historical-model default
trap that the `:83` `get_or_create` call sits on.

**`category_path` is computed but not persisted — re-verify against
`models.py` before trusting this note, it was in flight as of this session.**
`pim_sync.py:94` sets `product.category_path = _compute_category_path(...)`
and then calls `.save()`, but `category_path` is not a declared field on
`Product` — Django's `save()` only writes declared fields, so the value lives
only on that in-memory instance and is silently dropped from the row.
`test_pim_sync.py`'s `category_path` assertions (e.g. `:80`, `:96`, where a
real non-empty path is expected) all check the instance
`sync_product_from_pim` just returned in the same call, never re-fetching
via `Product.objects.get(...)` — this suite structurally cannot catch a
dropped field through that assertion style, so a green run here doesn't mean
the DB actually has the value. Worth keeping in mind before trusting other
"looks covered" assertions in this file too. See [[retiring_stack]]:
`supplier_feed/api/views.py:268`'s docstring claims `category_path` is
populated by this sync call — not currently true.

Note `product/pim_client.py` is its own client, separate from
`main_product_manager/pim_client.py`. Two clients against the same PIM.

## Status boundary — the subtle part

`product` sits in the *retiring* five in `CLAUDE.md`/`AGENTS.md`, but it is
carved out by an explicit exception: work that serves the PIM-mirror
reconnection is fine; growing `product` into an independent catalog is not.
It is also the only one of the five with no `api/` package — it is not mounted
in `api_urls.py`. Its siblings are covered by [[retiring_stack]].

It has real tests (`tests/test_models.py`, `tests/test_pim_sync.py`) — unusual
for this repo, and worth keeping green. But green isn't proof of correct: see
the `category_path` gap above for a case this suite's own assertion pattern
(assert on the returned instance, never re-fetch) structurally cannot catch.
