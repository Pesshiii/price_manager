# Brief: shift search & filtering from MainProduct to Product

Handoff spec for an implementing agent. Every decision below was made by the user
across four rounds of questions; the "Rationale / hazard" lines are findings from the
code, not preferences. Read `CLAUDE.md` and `.claude/knowledge/product.md` first.

**Ships in two phases. Phase 1 is additive and reversible. Phase 2 is destructive.**

*Revised 2026-09-16 after Phase 1 implementation. §0.1 records a base change that
invalidated part of the original spec — read it before trusting anything dated earlier.*

---

## 0.1 Base drift — the spec was written against a superseded model

The brief was specified against `main` at `3dd1514`. Two commits had already landed on
`origin/main`:

- `3cad760` (`#183`) — rejected PIM products no longer lost silently.
- `21175bb` (`#184`) — **PriceManagerProduct: сквозная связь с PIM.** This one changed
  the model the brief was built on.

What `#184` changed, and what it means here:

| Before (what the brief assumed) | After (what is true) |
|---|---|
| `Product.pim_id` = the PIM **Product** id, unique, not null | `Product.pim_id` = the **PriceManagerProduct** link id, nullable. The PIM product is a second hop via that record's `productId` |
| `Product.number` = a PIM-supplied number | `Product.number` = **`MainProduct.sku`**, local, never overwritten from PIM |
| `Product.name` unique | not unique — several Products can sit on one PIM Product |
| `create_pim_links` links MainProducts | **deleted.** `reindex_pim_ids` does the linking, locally, by `sku → number` |
| — | migration `0007` **zeroed every `pim_id`** and deleted stubs with no number and no references |

Three consequences that matter:

1. **D9 is now confirmed by the code, not inferred.** `product/models.py` states outright
   that `number` is the `MainProduct.sku` match key. The original brief reasoned its way
   there from `_search_pim_id_result`; it no longer has to.
2. **The backfill is a three-stage pipeline, not two** — see §3.1a. A Product with no
   `pim_id` cannot be synced at all, because `pim_id` *is* the record you fetch through.
3. **Linking no longer needs PIM.** `reindex_pim_ids` matches `MainProduct.sku` to
   `Product.number` locally, in its own transaction, and only the PMP *push* goes out to
   PIM. This makes D5's accepted invisibility much cheaper than the brief assumed.

---

## 0.2 Status

| Section | State |
|---|---|
| §3.1 Model work — `Brand`, `search_vector`, `display_name`, migration `0008` | ✅ **Done** — `667747a` |
| §3.1a Backfill orchestrator | ✅ **Done** — `df575c9` |
| §3.2 The page `/products/` | ✅ **Done** — `e71796c`, HTMX wiring fixed in `cb98183` |
| §3.3 P1-G3 observability counter | ✅ **Done** (in `e71796c`) |
| §3.3 P1-G1 / P1-G2 coverage gates | ⚠️ **Need re-measuring** — see §0.3 |
| §5 `pim_api` extension (the D15 blocker) | ✅ **Done** — `e5ba73c` |
| §5a Probe | ⚠️ **Runnable, not run** — needs real PIM credentials |
| §5 Hybrid live-PIM filter (D15) itself | ❌ **Not built** — gated on the probe |
| §4 Phase 2 (all destructive work) | ❌ Not started, by design (D10) |

Branch `worktree-product-shift-phase1`, full suite green (409 tests).

**What the page does today:** flat Product list at `/products/`, filter panel on the left,
each row expandable to its supplier price rows. Search, category (with MPTT descendant
expansion), brand, supplier, availability and price-range filters all work **against the
local mirror**. The live-PIM leg of D15 is the one piece missing.

---

## 0.3 Measurements — taken 2026-09-16 against the 2026-09-03 snapshot

`pricemanager_snapshot`, mode A (raw restore, no migrations). Aggregates only — nothing
below leaves this machine.

**Caveat, now doubled.** The snapshot predates the `product`-app recreation, the `#181` FK
refactor *and* `#184`. In it, `mainproduct` still carries `pim_id` as a CharField and
`product_product` is the dead API-first schema. G1 and G2 were **projections** computed
from `pim_id`; after `#184` they no longer describe the same quantities (see below).

| Gate | Number | Verdict |
|---|---|---|
| **G1** MainProducts with no PIM link | **122** of 156,481 (**0.08%**) | ✅ Green — and now cheaper still, see below |
| **G2** Products seeded with `raw_data={}` / `name IS NULL` | **154,969** | ⚠️ **The real Phase 1 cost** |
| **G3** `supplier_manager.Category` without `pim_id` | **787** of 816 (**96.4%**) | ✅ Green anyway — see F2 |
| **G4** `PriceManager` rules using category scoping | **0** of 118 | ✅ **D4 is a no-op** |
| **G5** MainProducts carrying any category | **465** of 156,481 (**0.3%**) | ✅ `MainProduct.categories` is vestigial |
| **G6** Settings mapping `category` / `manufacturer` | **75** / **85** of 85 | 🔴 Red — see F1 |

### Supporting density

| | Rows | Note |
|---|---|---|
| `SupplierProduct` with `manufacturer` | **124,227** of 168,004 (**74%**) | Dense, real, actively populated |
| `SupplierProduct` with `category` | **13** of 168,004 | Vestigial — the mapping exists, the data doesn't |
| `MainProduct` with `manufacturer` | 118,805 (76%) | 118,754 re-derivable from SupplierProduct |
| `MainProduct` with `description` | 11,361 (7%) | **11,359 covered by a SupplierProduct description** |
| `supplier_manager.Manufacturer` | 632 total, **29 with `pim_id`** | Same 96% cliff as categories |
| `ManufacturerDict` | **0 rows** | Never used — see F3 |

### What G1 and G2 mean after `#184`

- **G1 (122)** measured `MainProduct.pim_id IS NULL`. The equivalent question is now
  "MainProducts `reindex_pim_ids` cannot link", i.e. rows with **no `sku`** — because
  linking is `sku → Product.number` and runs locally. Anything with an sku gets a Product,
  created if missing. Expect the real figure to be **at or below 122**, and to shrink to
  near zero once `reindex_pim_ids` has run. **Re-measure as
  `COUNT(*) FROM main_product_manager_mainproduct WHERE sku IS NULL OR sku = ''`.**
- **G2 (154,969)** was "distinct non-null `pim_id`". After `0007` zeroed every `pim_id`,
  the Product population is rebuilt by `reindex_pim_ids` from `MainProduct.sku`, so the
  backfill volume is the **distinct sku count**, and every one of those rows needs a PMP
  pushed to PIM *before* it can be content-synced. The order of magnitude is unchanged
  (~155k); the prerequisite is new and is the expensive half.

### What the numbers change

**F1 — D1 and D11 confirmed as specified, trade-off measured and accepted.**
The numbers split cleanly and the user chose to drop both anyway:

- **Category is vestigial** — 13 SupplierProducts of 168,004, 465 MainProducts. Free to drop.
- **Manufacturer is dense** — **124,227 SupplierProducts (74%)**, all 85 Settings map the
  column, and only **29 of 632** manufacturers carry a `pim_id`.

Presented with those figures the user reaffirmed the original decision: drop both from both
models, delete all 160 `Link` rows, let brand come from PIM alone via D3.

**Treat this as deliberate, not an oversight.** What is knowingly given up: 124,227
supplier-supplied manufacturer values stop being captured, and brand coverage becomes
whatever PIM returns — a figure nobody has measured. Sparse brand facets after the backfill
are this decision surfacing, not a bug. See R7.

**F2 — D8 is safe.** Dropping 787 non-PIM categories looked risky; G4 = 0 and G5 = 465 say
it isn't. No pricing rule scopes by category and 0.3% of products are categorised. P2-G1 and
P2-G2 need no further measurement.

**F3 — `ManufacturerDict` has 0 rows, and `core/utils.py:45` is a latent crash.**
`match_manufacturer` does `ManufacturerDict.objects.filter(...)[0]` with no guard — an
`IndexError` on an empty table. `resolve_manufacturer` (`:63`) is the safe one callers use.
Unrelated to this shift; worth a separate fix. Confirms D3's "no normalisation layer" —
the layer was never used.

**F4 — D13's "drop description, no migration" is safe, with a named exception.**
11,359 of 11,361 descriptions are recoverable from `SupplierProduct.description`. **2 rows**
hold text found nowhere else. The Phase 2 migration should log or assert on that residue
rather than discard it silently.

**F5 — Phase 1's cost is the backfill, not the page.** The page is built and green; nothing
renders meaningfully until ~155k Products have a PMP pushed and content fetched. Size it
before committing to a cutover date. `_push_pim_products`
(`main_product_manager/utils.py:625`) uses `batch_size=1000, delay=0.5` as its precedent.
Throughput question, not correctness — but it is the critical path.

---

## 1. The target state

`product.Product` becomes the catalog: it owns identity, content, search and filtering.
`main_product_manager.MainProduct` shrinks to a per-supplier **stock + price row** hanging
off a Product.

Filtering on the new page draws on exactly three sources:

1. **A local search vector on `Product`** — free text.
2. **PIM content fields (categories, brands)** — hybrid, see §5.
3. **`MainProduct` stock and price fields** — traversed via `Product.main_products`.

---

## 2. Decisions (locked)

| # | Decision | Rationale / hazard |
|---|---|---|
| D1 | **CONFIRMED after measurement.** Both `MainProduct` and `SupplierProduct` lose `category`/`categories` and `manufacturer`. | Both are entries in the `LINKS` choices map — dropping them touches the Excel import. See F1. |
| D2 | `product.Category` survives. `supplier_manager.Category` is **retired**. | Two MPTT trees mirror the same PIM tree: `main_product_manager/utils.py:441-449` writes one, `product/services/pim_sync.py` the other. |
| D3 | New `product.Brand`, **keyed by PIM `brandId`**. No alias/normalisation layer. | ✅ Built. PIM returns `brandId`/`brandName` as **scalars**, so FK not M2M — confirmed against `_resolve_manufacturer` (`utils.py:362-374`), which does the same shape against the supplier-side Manufacturer this replaces. |
| D4 | `PriceManager` rules scope via `product__categories`. ✅ **No-op in practice — G4 = 0.** | `product_price_manager/models.py:187-188` currently filters on `MainProduct.categories`. |
| D5 | MainProducts with `product_id IS NULL` are **invisible** on the new page. Accepted. | ✅ Counter shipped (P1-G3). Cheaper than assumed post-`#184`: linking is local, see §0.1. |
| D6 | New page at a **new route**, parallel to the existing one. | ✅ Built at `/products/` with its own reverse names (`products`, `product-filter`, `product-suppliers`). |
| D7 | **One row = one Product, expandable to its supplier MainProducts.** | ✅ Built. `grouping.py` deliberately **not** ported — see §3.2. |
| D8 | Category migration maps **by `pim_id` only**; non-PIM categories dropped. | Safe per F2. Keeps `product.Category` a pure PIM mirror — see R6. |
| D9 | Search by raw supplier `article` is **dropped**. `sku` is covered by `Product.number`. | **Now confirmed in code**, not inferred: `product/models.py` documents `number` as the `MainProduct.sku` match key. `article` is the *unprefixed* article (`sku = prefix + article + suffix`) and is not covered. See R4. |
| D10 | **Phased**: new page ships first, MainProduct field drops after cutover. | ✅ Honoured — Phase 1 touches no existing app except one `urls.py` insertion. |
| D11 | **CONFIRMED after measurement** (85/85 map `manufacturer`, 75 map `category` — 160 Links deleted). | Also removes the `'brand'/'бренд'/'производитель'` column auto-detection at `functions.py:72`. |
| D12 | `MainProduct` **keeps**: `sku`, `article`, `name`, `supplier` FK, all price fields, `stock`, `price_updated_at`, `stock_updated_at`, `MainProductLog`. | `sku` cannot go — it is the link key to `Product.number`. |
| D13 | `MainProduct` **drops**: `search_vector`, `description`, `categories`, `manufacturer`, `weight`, `length`, `width`, `depth`. No data migration for description. | Safe per F4, with the 2-row residue named. |
| D14 | **No category sidebar.** Flat product list; categories are a filter facet only. | ✅ Built. `tables_bycat.html`, `CategoryFilter`, `Paginator(cat_filter.qs, 5)`, `has_nulled`/`nulled_mp_count` **not ported**. Consequence: `product.Category` needs **no** `search_vector`/GIN — and none was added. |
| D15 | Category/brand filtering is **hybrid**: facet lists from local mirrors, result set live from PIM. | ❌ **Live leg not built.** Local leg works. See §5 — the blocker is real and unresolved. |

---

## 3. Phase 1 — additive, nothing is dropped

### 3.1 Model work (`product/`) — ✅ done, `667747a`

- **`Product.search_vector`** — `SearchVectorField(null=True, editable=False)` + `GinIndex`
  (`product_search_vector_gin`), `config='russian'`. Built **only** from `raw_data`
  (`categoriesNames`, `tag`, `name`, `brandName`, `description`, `longDescription`) plus
  `number`. **No network call** — that is the defect `MainProduct._build_searchvector()`
  has, and the whole reason the vector moves.
  - Weights: `A` categories/tags/name, `B` number/brand, `C` descriptions.
  - `rebuild_search_vector()` does `update()` by pk, so it must run **after** `save()`.
  - **Bug fixed while porting:** the MainProduct version used `''.join(...)` on category
    names and tags, gluing them into one token — `Сантехника`+`Смесители` was unsearchable
    by either word. The new one uses `' '.join(...)`, pinned by
    `test_category_names_are_separate_tokens`.
- **`product.Brand`** — `pim_id` (unique), `name`, `ordering = ['name']`. `Product.brand`
  is a nullable FK. Matched on `brandId` only; `name` is kept in sync as a display label,
  because matching on the name would fork one brand into two on the first PIM rename.
- `sync_product_from_pim` resolves brand via `_ensure_pim_brand` and rebuilds the vector.
- **Migration `0008_brand_and_product_search_vector`** — fully additive (create model, two
  nullable fields, one index). No three-step staging needed; nothing is tightened.

### 3.1a Backfill orchestrator — ✅ done, `df575c9`

**The ordering is three stages, not two.** The original brief had this wrong because it
predated `#184`:

> **`reindex_pim_ids` (fills `pim_id`) → `backfill_products_from_pim` (fills content) → vector**

Stage 1 already exists in `main_product_manager` and is the prerequisite: `pim_id` *is* the
PriceManagerProduct record you fetch the product through, so a Product without one cannot be
synced at all. `unsynced_products()` filters to `pim_id__isnull=False` for exactly this
reason — it skips those rows rather than failing on them.

There is **no separate vector-rebuild stage**: `sync_product_from_pim` rebuilds the vector
itself, immediately after writing the `raw_data` it is built from.

`create_pim_links` **no longer exists** (deleted in `#184`). Any doc or prompt still naming
it is stale.

Built:
- `unsynced_products(refresh=False)` — `pim_id` present, `raw_data={}`. `refresh=True` takes
  everything with a `pim_id`.
- `iter_unsynced_product_pk_batches(batch_size)` — ordered by pk so batches don't overlap.
- `sync_products(pks, delay)` — **one product's failure does not abort the batch.** PIM
  answers per product; one 404 is no reason to lose the other 499. Failed rows keep
  `raw_data={}` and are picked up by the next run, so the backfill is idempotent.
- `backfill_products_from_pim_task` — fans out via **`dispatch_after_commit()`**, not
  `.delay()`. The runner writes nothing itself, but on a parent rollback already-dispatched
  batches would keep running while the run is recorded as failed — the `reindex_pim_ids`
  precedent exactly.
- `sync_products_batch_task` — `atomic=False`, because the batch is HTTP-bound and sleeps
  between calls.

**Row display name:** `Product.display_name` falls back to the first `main_products` row's
name when `name IS NULL`, then to `number`. Every unsynced row is nameless until the
backfill reaches it, and an empty cell reads as broken data rather than pending work.

### 3.2 The page — ✅ done, `e71796c`

Routes `products`, `product-filter`, `product-suppliers`, registered centrally in
`price_manager/price_manager/urls.py`. Russian UI strings throughout.

**The page serves its own table fragment.** `get_template_names()` returns
`product/partials/table.html` when `request.htmx`, and `list.html` otherwise. Both the
filter form and the search box `hx-get` back to `products` — not to a fragment endpoint —
so `hx-push-url` writes `/products/?…`, which reloads and bookmarks correctly. A separate
table endpoint existed briefly and was deleted as dead code once this landed. See §7; the
failure mode is a whole page rendered inside `#products-table`.

- **`ProductFilter`** — search (`search_vector` + `number`), categories, brand, supplier,
  availability, price range.
  - **Every `main_products` traversal uses `Exists()`, never a join.** A join multiplies the
    product row by its supplier count. `.distinct()` would fix the duplication but would
    break relevance ordering, since DISTINCT requires the ORDER BY expression in the select
    list and `rank` only exists on a non-empty search. Four tests pin the no-duplication
    property.
  - **Search also matches the linked MainProduct's name.** Not in the original spec, and not
    a violation of D9 (which is about `article`): an unsynced Product's vector is just its
    `number`, so without this predicate such a row is unfindable by any word until the
    backfill reaches it.
  - **Category selection expands through the MPTT tree locally** (§5b). Selecting a parent
    matches everything beneath it. Pinned by
    `test_selecting_a_parent_finds_products_in_its_descendants`.
- **`ProductTable`** — real aggregation over `Product.main_products`
  (`supplier_count`, `total_stock`, `min/max_prime_cost`), not window functions.
  `grouping.py` is **not ported**: its windows exist only to fake grouping over a flat
  MainProduct queryset. `MAINPRODUCT_GROUPING_ROW_LIMIT` and the `#163` perf gate are
  likewise irrelevant here. `NO_STOCK_DATA = 'Нет данных'` **does** carry over — NULL stock
  is a third state, not zero.
- **`ProductPage`** is `SingleTableMixin, FilterView`. A bare `FilterView` puts no `table`
  in the context; the main page gets away with it because its tables load as separate
  per-category requests.
- Supplier rows load **on demand** per product, not as a join into the list query.

### 3.3 Phase 1 gates

> **P1-G1 — linkage coverage.** ⚠️ Re-measure post-`#184` as
> `COUNT(*) FROM main_product_manager_mainproduct WHERE sku IS NULL OR sku = ''`, then run
> `reindex_pim_ids` to completion and re-count. The old `create_pim_links` reference is dead.

> **P1-G2 — content coverage.**
> `COUNT(*) FROM product_product WHERE raw_data = '{}'::jsonb OR name IS NULL`, before and
> after `backfill_products_from_pim`. This is the number that decides whether the page is
> worth showing anyone.

> **P1-G3 — observability.** ✅ Shipped. `product/partials/coverage_note.html` shows both
> "строк поставщиков без товара PIM" and "товаров без данных из PIM" on the page itself, so
> the accepted invisibility (D5) and the pending backfill stay visible to an operator.

Restore via the **`prod-snapshot` skill** (never over `price_manager_db`). **Aggregates only
— no dump-derived values in commits, PR bodies or issues.**

---

## 4. Phase 2 — destructive, after the new page is in real use

Separate PR. Each item is irreversible on prod. Unchanged from the original spec except
where F2/F4 relaxed the gates.

1. Drop `MainProduct.search_vector`, `description`, `categories`, `manufacturer`,
   `weight`, `length`, `width`, `depth`.
   - Also strips the writes in `supplier_product_manager/tasks.py:239-274` (copy-to-main)
     and `main_product_manager/utils.py:437-449` (`sync_pim_relations`).
   - **Bonus:** dropping `search_vector` removes the PIM network call from the MainProduct
     save path, which may make `main_product_manager/pim_client.py` deletable — the
     import-time `SiteAPI(...)` that crashes the **whole app** at boot when `PIM_TOKEN` is
     unset. Check whether `supplier_product_manager/admin.py`'s transitive import is the
     last consumer.
   - Log or assert on the 2 descriptions with no SupplierProduct counterpart (F4).
2. Drop `SupplierProduct.category` and `.manufacturer`; remove both from `LINKS`; data
   migration deleting the 160 orphaned `Link` rows (D11).
3. Repoint `PriceManager.categories` at `product.Category`; rewrite `get_fitting_mps` to
   `product__categories__in=...`. **G4 = 0 makes this mechanical** — no live rule is affected.
4. Retire `supplier_manager.Category`, `Manufacturer`, `ManufacturerDict`, and the
   `CategoryFilter` / `match_manufacturer` / `resolve_manufacturer` helpers
   (`core/utils.py:44-77`, `main_product_manager/resources.py:82-87`).
5. Retire the old MainPage; redirect `mainproducts` to `/products/`.

### 4.1 Phase 2 gates

> **P2-G1 / P2-G2 — ✅ resolved by measurement.** G4 = 0 rules use category scoping and
> G5 = 465 products carry a category. Neither gate has anything left to catch.

> **P2-G3 — ✅ measured, and it is the red one.** 85 of 85 Settings map `manufacturer`,
> 75 map `category`, 0 DictItems hang off either. The user accepted this (F1). The migration
> should still report how many Links it deletes rather than doing it silently.

### 4.2 Migration staging — non-negotiable

Follow `product/migrations/0006_alter_product_name.py`: **ordered** `AlterField` →
`RunPython` (data cleanup that **raises** on unexpected data) → constraint. Collapsing them
passes CI and fails on a populated database.

`makemigrations --check` only diffs model state against migration state and never touches
data. **A green `--keepdb` run is not evidence** — `--keepdb` reuses an already-migrated
database, which is exactly what hid the `name`-column drift in this app's history. Validate
every Phase 2 migration against a restored snapshot.

```bash
docker compose exec -T celery_worker python manage.py test <app_label> --keepdb
```

---

## 5. The hybrid filter (D15) — ❌ not built, and here is exactly why

**Decision unchanged:** mirrored facet lists, live PIM for the result set. The user chose
this with the latency and failure-mode risk in front of them. It is not up for re-argument
without evidence.

**What exists today:** the category and brand filters query the **local mirror**
(`product.Category`, `product.Brand`). That is the correct half, and the seam for the live
leg is the `categories_method` / `brand_method` pair in `product/filters.py`.

**The client blocker is now closed** (`e5ba73c`). What was wrong and what it became:

- `EntityList` had `select`/`where`/`ordering` but **no `offset`/`maxSize`**, so PIM returned
  its default first page and said nothing — a wide query looked successful while being
  incomplete. Now `offset`/`maxSize` are emitted, and **`fetch_list()`** walks the pages.
  (`total` was always in the raw JSON — `{'total': N, 'list': [...]}`. The client simply
  never paged. Existing callers search `number equals`, expecting 0–1 hits, which is why
  none of them were bitten.)
- `Where.value` was `Optional[str]`. Now `Union[str, List[str]]`: a list is emitted as
  PHP array notation (`where[0][value][]` repeated), which is what `linkedWith` needs.
  **The scalar branch is untouched** — every existing PIM link lookup goes through it.
- `SiteAPI.get(method, timeout=...)` overrides the 5s default per call, for interactive
  paths where 5 seconds is a frozen page.
- **`fetch_list()` returns `ListResult(total, items, truncated)`.** `truncated` is the point:
  a capped set is indistinguishable from a complete one by the items alone, and returning a
  silent prefix is the exact bug the paging exists to prevent. It covers both causes — the
  `max_items` cap and PIM returning fewer rows than its own `total` claims.
- **Phantom field fixed in passing:** `EntityList.ordering` was declared on the model and
  **never emitted into the request**. Assigning it did nothing. Same class as the
  `category_path` trap in `.claude/knowledge/product.md`. No existing caller passes it.

### 5a. Probe before building — named exit

⚠️ **Runnable but NOT RUN.** This environment has `PIM_HOST = http://pim.invalid` and an
11-character placeholder token, so no live probe is possible here.

Shipped as a management command:

```bash
docker compose exec web python manage.py probe_pim_category_size --top 5
```

It takes the largest local categories, expands each branch through MPTT, asks PIM how many
products are linked with that id set, and prints a verdict against a `--max-items` limit
(default 1000). **If the worst case exceeds what one `pim_id IN (...)` can carry, the honest
finding is that the live leg only serves narrow filters** — take that back to the user
rather than capping silently. The command says exactly that, and says so explicitly when the
credentials are placeholders.

Two prerequisites before the probe means anything:
1. Real `PIM_TOKEN` / `PIM_HOST`. Note `SiteAPI` builds `https://{host}/api/`, so `host`
   must be a bare hostname — the current placeholder carries a `http://` scheme and would
   produce a malformed URL even if the token were real.
2. The §3.1a backfill must have run far enough for local categories to have products; the
   probe reports "no local categories with products" otherwise, which it did here.

### 5b. Descendant semantics — ✅ already handled

`categories_method` expands the selection through `product.Category`'s MPTT tree locally
before filtering. When the live leg lands it must send that **full descendant id set** to
PIM, because `linkedWith` matches only the ids you send. The expansion and its test are
already in place, so this regression cannot happen by omission.

### 5c. Minimum requirements for the live leg

1. Bounded result set — use `fetch_list(..., max_items=…)` and **check `result.truncated`**.
   The client now reports it; the UI must surface it. A silent prefix is the bug the whole
   paging change exists to prevent.
2. Cache the id set per (facet, page) with a short TTL. Reuse the cache-key idioms in
   `main_product_manager/utils.py` (`pim_no_match:{pk}`, the 404 threshold).
3. **Graceful degradation when PIM is down.** Pick one and implement it: fall back to the
   local mirror, or show an explicit Russian error. Silently returning zero results is the
   failure mode to avoid.
4. Never inside a `transaction.atomic()` runner — `atomic=False` if a task drives it.
5. No facet counts are possible on the live leg. Either show names without counts, or take
   counts from the local mirror and accept that they will disagree with the result set.
   **Pick one and make it visible in the UI copy.**

---

## 6. Risks carried forward

- **R1 — hybrid filtering (D15).** Still the highest-risk decision and the only unbuilt one.
  The *client* blocker is closed; what remains unknown is whether PIM can answer a broad
  category query at all, which only the §5a probe against real credentials can say. A
  network call in the page's query path is the exact pattern `CLAUDE.md` flags on
  `_build_searchvector`. §5c is mandatory, not optional.
- **R2 — ✅ resolved.** Coverage was measured (§0.3). G1/G2 need one re-read post-`#184`,
  not a fresh investigation.
- **R3 — two PIM clients.** `product/pim_client.py` and `main_product_manager/pim_client.py`
  are separate `SiteAPI` instances against the same PIM. The live filter leg would be a
  third consumer. Don't add a fourth — pick one and note why.
- **R4 — D9 rests on an assumption.** Dropping `article` search assumes users only search by
  the prefixed `sku` they see. If a supplier has `sku_type` set **and** users search by raw
  article, search silently stops finding those rows. *Partly mitigated:* the page also
  matches the linked MainProduct's `name`, so such a product is still reachable by name.
- **R5 — D3 assumes PIM brands are a controlled vocabulary.** If brand is free text the
  facet list shows duplicate spellings. `ManufacturerDict` solved exactly this and is
  scheduled for deletion in Phase 2 — if R5 materialises, reconsider that deletion rather
  than rebuilding it.
- **R6 — `product.Category` becomes mixed-provenance if D8 is softened.** `pim_sync`'s
  `_ensure_pim_category` does `get_or_create(parent=…, name=…)`; carrying non-PIM categories
  across would collide. D8 keeps the tree pure — keep it that way.
- **R7 — brand coverage is unmeasured and accepted (D1/D3/D11).** 74% manufacturer density
  traded for PIM brand coverage nobody has sampled. **Cheapest early warning: after the
  backfill, count Products that resolved a brand and compare against 74% — before the old
  page is retired.** Past that point the supplier-side data is gone and the only recovery is
  PIM-side enrichment.

---

## 7. Implementation notes — traps hit while building Phase 1

Every one of these passed the test suite and was caught only by loading the page.

- **A multi-line `{# … #}` is not a comment.** Django closes a single-line comment at the
  tag, not the newline, so the block renders into the response as literal text — and a
  `{% … %}` tag inside it is parsed as real, which crashed the page with
  `IndexError: pop from empty list` from `render_table`. Use `{% comment %}` for anything
  spanning lines.
- **`hx-get` on a toggle button fires on every click, including the collapsing one.** The
  row hid and the response then refilled it: a wasted request per collapse and content
  living in a hidden row. Put the URL in a `data-` attribute and call `htmx.ajax()` from the
  expand branch only.
- **The web container does not pick up `.py` edits.** A "defect" in the expand behaviour was
  really stale `tables.py` in the container — the button still carried its old attributes.
  `docker compose restart web` after Python changes, or you debug code that isn't running.
  (Templates *do* reload per request, which makes this more confusing, not less.)
- **`f'{value:.2f}'` bypasses localisation.** The UI is Russian and Django renders decimals
  with a comma; python formatting produced `99.00` beside `99,00` in the table below. Use
  `django.utils.formats.number_format`.
- **A page whose own filters `hx-get` back to it must return the fragment itself.** Without
  an `request.htmx` branch in `get_template_names()`, the response is the whole `list.html`
  and HTMX drops it — navbar, filter panel and all — inside `#products-table`. Page inside
  page. The main page has exactly this branch; omitting it is the default outcome, not an
  exotic mistake.
  - **Don't "fix" it by pointing the filter at a fragment endpoint.** `hx-push-url` is on,
    so that writes the *fragment's* URL into the address bar and a reload hands the user a
    bare table. The page serving its own fragment is what keeps the pushed URL honest — and
    it makes any separate table endpoint dead code.
- **A form widget needs an explicit `id` if HTMX selects on it.** Django renders
  `id_<field>` by default. The search field was wired as `#products-search` in two places —
  the search box's `hx-trigger="… from:#products-search"` and the filter form's
  `hx-include` — and both selectors silently matched nothing. Result: typing in the search
  box did nothing at all, **and applying any filter discarded the search term**. Neither
  threw, because "selector found nothing" is not an error in either HTMX or the DOM.

**The meta-lesson, worth more than any single item above.** Every bug in this list passed a
green suite. The filter-wiring ones survived even a browser pass, because I had exercised
expand/collapse by hand but checked the filters through the Django test client — which
issues plain GETs and never evaluates `hx-target`, `hx-include` or `hx-trigger`. **A test
client cannot see a swap-target mistake.** Any HTMX screen needs at least one real
interaction driven in a browser: apply a filter, read back the DOM, and assert the target
contains only what it should.
- **`self.data` is not always a QueryDict.** `MainProductFilter` calls `.getlist()` on it
  directly and gets away with it because views always pass `request.GET`. Constructing a
  filterset from a plain dict — from tests, or from code — raises `AttributeError` inside
  `__init__` and takes the whole filterset down. `ProductFilter._selected()` handles both.
- **`FilterView` alone puts no `table` in the context.** Use `SingleTableMixin, FilterView`
  when the table renders inline.

---

## 8. Keepers to consult

Per `CLAUDE.md`, consult before working in each app, and `/record-insight <app>` afterwards:

| Touches | Agent |
|---|---|
| `product/` | `product-keeper` |
| `main_product_manager/` | `main-product-keeper` |
| `supplier_product_manager/` | `supplier-product-keeper` |
| `supplier_manager/` | `supplier-manager-keeper` |
| `product_price_manager/` | `price-rules-keeper` |
| `core/` | `core-keeper` |

`django-orm-perf` is worth a pass on `/products/` before Phase 1 merges — `main_products`
traversal plus (eventually) a live PIM leg is exactly the shape it exists to catch.
