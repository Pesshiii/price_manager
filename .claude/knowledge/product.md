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
- `Product` — `pim_id` (unique), `number` (unique), `name`, M2M `categories`,
  `raw_data` JSON, timestamps. `ordering = ['-updated_at']`.

`migrations/0005_seed_products_from_main_product_pim_ids.py` seeds it from
`MainProduct.pim_id` — that migration is the bridge to [[main_product_manager]].

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

Note `product/pim_client.py` is its own client, separate from
`main_product_manager/pim_client.py`. Two clients against the same PIM.

## Status boundary — the subtle part

`product` sits in the *retiring* five in `CLAUDE.md`/`AGENTS.md`, but it is
carved out by an explicit exception: work that serves the PIM-mirror
reconnection is fine; growing `product` into an independent catalog is not.
It is also the only one of the five with no `api/` package — it is not mounted
in `api_urls.py`. Its siblings are covered by [[retiring_stack]].

It has real tests (`tests/test_models.py`, `tests/test_pim_sync.py`) — unusual
for this repo, and worth keeping green.
