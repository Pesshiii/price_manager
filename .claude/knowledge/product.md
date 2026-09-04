# product

**Read this before assuming anything about `product`.** It is the one app whose
status recently inverted, and stale mental models of it are actively wrong.

## What it is *now*

A plain **PIM-linked mirror**, being deliberately recreated and reconnected to
the live legacy stack — treat anything here as in-motion; check
`git log -- product/` if something surprises you.

`product/models.py` is short and complete — read the whole file, it's ~65 lines:
- `Category(MPTTModel)` — `parent`(PROTECT) / `name` / `slug` / `pim_id`,
  unique constraint on `(parent, name)`, `order_insertion_by = ['name']`.
  `save()` auto-generates a unique `slug` via `slugify(allow_unicode=True)`
  with a `-2`, `-3` … suffix loop.
- `Product` — `pim_id` (unique), `number` (unique, nullable), `name`
  (`models.py:51`, `unique=True, null=True, blank=True` — matches the
  migrations as of `0006_alter_product_name.py`, merged), M2M `categories`,
  `raw_data` JSON, timestamps. `ordering = ['-updated_at']`.

`migrations/0005_seed_products_from_main_product_pim_ids.py` seeds it from
`MainProduct.pim_id` — that migration is the bridge to [[main_product_manager]].

## What it is *not* — earlier docs described these; they do not exist

No embeddings. No characteristics JSONB. No `ImportJob`. No
`CharacteristicMutationJob`. No pgvector usage anywhere in the Python code. If
you find a reference to any of these, it is stale documentation, not code you
haven't found yet. (`0002_product_sku.py` briefly added `sku`/`description`/
`status`/`characteristics`/`image_urls`/`brand`/`category`/
`embedding_text_hash` — those are the pre-rewrite fields; `0003_...py` removes
every one of them in the same breath. Current model state matches all six
migrations (0001-0006) exactly.)

## Sync path

`services/pim_sync.py` — `sync_product_from_pim(pim_id, data=None)` at `:60`,
with `_ensure_pim_category` (`:22`) walking/creating the category tree. Driven
by the single task `product.sync_product_from_pim` (`tasks.py:8`), which
**does** route through `execute_locked_task` with a per-`pim_id` lock name —
good, copy this shape.

Note `product/pim_client.py` is its own client, separate from
`main_product_manager/pim_client.py`. Two clients against the same PIM.

`pim_sync.py:76-77` writes `data.get('number') or None` /
`data.get('name') or None` — deliberately not `or ''`. Both fields are unique;
Postgres treats `NULL`s as distinct in a unique index but `''` as equal, so
coercing a missing value to `''` on a unique column lets the first such
nameless/numberless product save and `IntegrityError`s every one after it.
This is exactly the kind of thing that gets "simplified" back to `or ''` by
someone who doesn't know why it's there — keep it as `or None`.

### The phantom-field trap (fixed here; the shape can recur)

`sync_product_from_pim` used to write `product.category_path = ...`
(via a `_compute_category_path` helper) before `save()` — but `category_path`
was never a field on `Product`; no migration ever added one. Django's `save()`
silently ignores assignment to a non-field attribute, so the write was a no-op
on every sync, and `Product.objects.get(...).category_path` raised
`AttributeError` on any fresh fetch. Both the helper and the assignment are
now deleted (`pim_sync.py`), and the docstrings that referenced it
(`pim_sync.py`, `supplier_feed/api/views.py:267`) are corrected.

There is **no** denormalised category-path column, deliberately: PIM's
payload carries no path string (only `categoriesIds`/`categoriesNames`), so a
path must be derived from the local MPTT tree via `Category.get_ancestors()`
— the `categories` M2M is the source of truth. If something needs a path
string, derive it at read time from `product.categories`; don't reintroduce a
stored field.

## Tightening a constraint on `Product` — mind the seeded rows

`0005` bulk-creates a `Product` per `MainProduct.pim_id`, so any migration
that adds or tightens a constraint on `Product` runs against rows that are
already there. `0006_alter_product_name.py` is the worked example: nullable →
`RunPython` nullifying `''` sentinels → unique, in three deliberate steps.
Collapsing that into one `AlterField` passes against an empty test database
and fails against any populated one.

Do not read a green local `--keepdb` run as proof the migrations agree with
`models.py` — `--keepdb` reuses whatever database was already migrated, and
that is precisely what hid a `name`-column divergence in this app's history.
`manage.py makemigrations --check --dry-run` is what actually catches it.

## Tests — re-fetch, don't trust the returned instance

`tests/test_pim_sync.py` (`SyncProductFromPimTests`) asserts via
`Product.objects.get(pk=product.pk)`, not on the instance
`sync_product_from_pim` returned. That's deliberate, and it's *why* the
phantom-field bug above went undetected as long as it did: asserting on the
returned instance only proves an in-memory Python attribute got set, not that
anything reached the DB. Note it's `Product.objects.get(...)`, not
`refresh_from_db()` — a fresh instance carries only real columns, while
`refresh_from_db()` leaves stray non-field attributes on the existing
instance intact and would let the same class of bug pass silently again.
Keep new assertions in this module on the re-fetched row.

`tests/test_models.py` still asserts on freshly-`.create()`d instances
without a re-fetch, but harmlessly — those are `IntegrityError`/uniqueness
checks (including `test_name_unique`, `test_products_without_name_coexist`,
`test_products_without_number_coexist` covering the `or None` rule above), not
attribute round-trips.

## Status boundary — the subtle part

`product` sits in the *retiring* five in `CLAUDE.md`/`AGENTS.md`, but it is
carved out by an explicit exception: work that serves the PIM-mirror
reconnection is fine; growing `product` into an independent catalog is not.
It is also the only one of the five with no `api/` package — it is not mounted
in `api_urls.py`. Its siblings are covered by [[retiring_stack]].
