---
name: prod-snapshot
description: Restore the newest production dump from backups/ into a throwaway pricemanager_snapshot database and investigate it. Use when a question needs production scale or production data shape — query plans over 156k MainProducts, 527k PriceTags, real supplier column mappings, the real MPTT category tree — and a hand-built fixture cannot answer it. Never for tests that must pass in CI, and never for anything whose values leave this machine.
---

# Investigating against a production snapshot

`backups/` holds pg_dump custom-format snapshots of the production database
(`pricemanager_YYYYMMDD_HHMMSS.dump`). They are gitignored (`.gitignore:17`) and
hold real business and personal data. The dev database is empty, so this is the
only real data available locally.

## When to reach for this (the eval)

Restore only when the answer depends on production **scale** or **shape**, and a
fixture cannot supply it:

| Warranted | Why the snapshot, not a fixture |
|---|---|
| Query-plan / N+1 work (`django-orm-perf`) | 156k MainProduct, 168k SupplierProduct, 527k PriceTag; GIN `search_vector` planning only diverges at volume |
| Excel import column mapping (`supplier_product_manager`) | 85 real `Setting`s, 830 `Link`s, 34 `DictItem`s across 42 suppliers — real header shapes no one invents |
| MPTT category tree behaviour (`supplier_manager`) | 816 categories, 5 levels deep |
| `update_prices()` / markup rules (`product_price_manager`) | 118 real rules against a real price spread — 76,833 products with `basic_price > 0`, 92,461 with `prime_cost > 0` |
| Screens that only break at real volume (`ui-review`) | infinite scroll, table rendering, autocomplete |

Do **not** restore for:

- Anything a fixture can express. Default to a fixture.
- **Anything CI must reproduce.** `backups/` is gitignored and
  `.github/workflows/ci.yml` runs the suite against an empty pgvector service. A
  test that needs this snapshot passes on your machine and fails or silently
  skips in CI. Prod data is for **investigation**; convert every finding into a
  committed fixture before it becomes a test.
- Schema / migration drift — `.claude/hooks/check_migrations.py` covers that with no data.
- Anything you would have to copy a value out of.

## Rules

1. **Never restore over `price_manager_db`.** Always a separate database.
   `.claude/hooks/guard_prod_data.py` refuses the obvious ways to break this.
2. **Read-only.** Investigate; do not write back and do not point the running app at it.
3. **Nothing derived from it leaves this machine.** No dump-derived values in
   commits, PR bodies, GitHub issues, or Telegram messages — `.claude/telegram-bot/`
   posts to a group chat and the `tg-*` skills file public issues. The dump holds
   `auth_user` (12 real accounts, emails + password hashes), `core_cartitem`, and
   supplier pricing. Row counts and aggregates only.
4. Drop the snapshot database when done.

## Pick a mode before you migrate

Migrating the snapshot is not free. `supplier_product_manager/migrations/0008_decouple_and_unique_main_product.py:28`
deletes **every** `PriceTag`, zeroes `stock`, `prime_cost`, `wholesale_price`,
`basic_price`, `m_price` and `wholesale_price_extra` on every `MainProduct`, then
splits shared products (156,481 -> 164,325 rows).

| | A — raw | B — ORM-ready (default) | C — fully migrated |
|---|---|---|---|
| Steps | restore only | + migrate `main_product_manager`, `product_price_manager` | + migrate `supplier_product_manager` |
| Tooling | SQL; ORM limited to `.count()` / `.values()` | full ORM | full ORM |
| Prices, `PriceTag`s, linkage | intact | **intact** | destroyed |
| Use for | quick SQL probes | almost everything | only when you need `SupplierProduct.main_product`'s current uniqueness constraint |

In mode A any query that materializes a model instance (`.first()`, `.get()`,
`.all()`) fails with
`ProgrammingError: column main_product_manager_mainproduct.kaspi_price does not exist`
— the snapshot predates that field. `.count()` and `.values(...)` still work.
Mode B is the fix and costs nothing: both apps' pending migrations are field
alterations only.

## How

Every container-side absolute path needs `MSYS_NO_PATHCONV=1` on Git Bash (see
Traps). The stack must be up: `docker compose up -d`.

```bash
# 0. Newest dump, copied into the db container, and a preflight on its origin.
DUMP=$(ls -t backups/*.dump | head -1); echo "$DUMP"
docker compose cp "$DUMP" db:/tmp/snap.dump
MSYS_NO_PATHCONV=1 docker compose exec -T db pg_restore -l /tmp/snap.dump | sed -n '1,12p'

# 1. A separate database. Never price_manager_db.
docker compose exec -T db createdb -U priceuser pricemanager_snapshot

# 2. Restore. ~25s for a 48MB dump, 611 TOC entries.
MSYS_NO_PATHCONV=1 docker compose exec -T db pg_restore \
  --no-owner --no-privileges --exit-on-error \
  -U priceuser -d pricemanager_snapshot /tmp/snap.dump
```

Instead of `docker compose cp`, you can mount the directory once by adding this
under `db.volumes` in `docker-compose.yml`, then using `/backups/<file>.dump`:

```yaml
      - ./backups:/backups:ro
```

**Mode A stops here.** Query with SQL:

```bash
docker compose exec -T db psql -U priceuser -d pricemanager_snapshot -c "<SQL>"
```

**Mode B** — migrate the two safe apps *by label*; a bare `migrate` fails (see Traps):

```bash
for app in main_product_manager product_price_manager; do
  docker compose exec -T -e POSTGRES_DB=pricemanager_snapshot web \
    python manage.py migrate "$app"
done
```

Every `manage.py` call against the snapshot carries `-e POSTGRES_DB=pricemanager_snapshot`
(`settings/databases.py:9` reads that env var). Omit it and you are talking to the
live dev database.

```bash
docker compose exec -T -e POSTGRES_DB=pricemanager_snapshot web python manage.py shell -c "
from main_product_manager.models import MainProduct
print(MainProduct.objects.filter(basic_price__gt=0).count())"
```

**Mode C** — only if you need it, knowing it destroys prices and PriceTags:

```bash
docker compose exec -T -e POSTGRES_DB=pricemanager_snapshot web \
  python manage.py migrate supplier_product_manager
```

Teardown:

```bash
docker compose exec -T db dropdb -U priceuser pricemanager_snapshot
MSYS_NO_PATHCONV=1 docker compose exec -T db rm -f /tmp/snap.dump
```

## Traps

- **Git Bash mangles container paths.** Without `MSYS_NO_PATHCONV=1`,
  `/tmp/snap.dump` is rewritten to a Windows path before Docker sees it, and
  pg_restore reports "No such file or directory" — which reads like a missing
  file, not a path bug. Carry the flag on the teardown `rm` too: a rewritten path
  would make `rm -f` exit 0 without deleting anything.
- **`--exit-on-error` is not optional.** Without it pg_restore walks past failures
  and hands you a partial database that looks fine.
- **The image must be `pgvector/pgvector:pg17`.** The dump requires `btree_gin`,
  `pg_trgm` and `vector`; plain `postgres:17` fails on the last one. The compose
  `db` service is already the right image.
- **A bare `manage.py migrate` fails** with
  `ProgrammingError: column "sku" of relation "product_product" already exists`.
  The snapshot's `product` app is the old API-first schema (`embedding`,
  `embedding_text_hash`, `characteristics`, `image_urls`, `brand_id`, `status`) at
  `product.0011_*`, while this repo's `product` was recreated from a fresh
  `0001_initial`. Django name-matches `0001_initial`, then applies
  `0002_product_sku` onto the old table. **Never migrate the `product` app on a
  snapshot** — nothing in the legacy stack imports it.
- **PG18 dump into a PG17 server is not an officially supported direction.** It
  worked cleanly for the 2026-09-03 dump (archive 1.16, exit 0), but re-run step 0
  after any production upgrade rather than assuming it keeps working.
- The snapshot carries tables no current model owns — `product_importjob`,
  `product_characteristicmutationjob`, `pricing_*`, `supplier_feed_*`,
  `dataframe_*`. Expected; they are the retired lineage.

## What is in there (2026-09-03 dump, verified 2026-09-07)

| Table | Rows |
|---|---|
| `django_admin_log` | 961,146 |
| `product_price_manager_pricetag` | 526,679 (0 in mode C) |
| `supplier_product_manager_supplierproduct` | 168,004 |
| `main_product_manager_mainproduct` | 156,481 (164,325 in mode C) |
| `main_product_manager_mainproductlog` | 57,263 |
| `core_taskrunhistory` | 9,141 |
| `core_persistentnotification` | 1,168 |
| `supplier_product_manager_link` | 830 |
| `supplier_manager_category` | 816 (max MPTT level 5) |
| `supplier_manager_manufacturer` | 632 |
| `supplier_manager_discount` | 626 |
| `product_price_manager_pricemanager` | 118 |
| `supplier_product_manager_setting` | 85 |
| `supplier_manager_supplier` | 42 |
| `auth_user` | 12 |
