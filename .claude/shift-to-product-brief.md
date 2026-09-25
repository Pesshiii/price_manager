# Brief: shift search & filtering from MainProduct to Product

Handoff spec for an implementing agent. Every decision below was made by the user
across four rounds of questions; the "Rationale / hazard" lines are findings from the
code, not preferences. Read `CLAUDE.md` and `.claude/knowledge/product/` first.

**Ships in two phases. Phase 1 is additive and reversible. Phase 2 is destructive.**

*Revised through 2026-09-19, at Phase 1 ship. §0.1 records a base change that
invalidated part of the original spec — read it before trusting anything dated earlier.
§0.4–§0.5 hold the measurements that settled D15 and D1.*

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

*Phase 1 shipped as one PR. Branch commit SHAs are deliberately not cited: the repo
squash-merges, so they do not survive onto `main`.*

| Section | State |
|---|---|
| §3.1 Model work — `Brand`, `search_vector`, `display_name`, migration `0008` | ✅ **Done** |
| §3.1a Backfill orchestrator | ✅ **Done** |
| §3.2 The page `/products/` | ✅ **Done** — incl. HTMX wiring fix, tree facet, search fix |
| §3.3 P1-G3 observability counter | ✅ **Done** |
| §3.3 P1-G1 / P1-G2 coverage gates | ✅ **Measured on the prod snapshot** — linkage ~100%, PIM content **36%**, see §0.4 |
| §5 `pim_api` extension | ✅ **Done** — paging, list-valued `where`, `fetch_list` |
| §5a Probe | ✅ **Run against live PIM** — **the named exit fired** |
| §5 Live-PIM filter (D15) | ✅ **Resolved: dropped.** Local mirror is the final design |
| R8 stale category mirror | ✅ **Closed** — `sync_category_tree_from_pim` |
| D1 revisited | ✅ **Reaffirmed as final** — see §0.5; imposes **P2-G4** |
| §4.0 Phase 2a — decouple and port (additive, no migrations) | ✅ **Done** — see §4.0 |
| §4 P2-G4 — manufacturer export | ✅ **Run in prod and handed over** (user, 2026-09-21) |
| §4.0b 2b-1 — retire the old main page (item 5, code only) | ✅ **Done** |
| §4.0b 2b-2 — the column drops (items 1–3) | ✅ **Done** — validated on the restored snapshot, see §4.0b |
| §4.0b 2b-3 — retire `supplier_manager` Category/Manufacturer (item 4) | ✅ **Done** — **Phase 2 complete** |

Full suite green (428 tests). Verified end to end on a restore of the production snapshot
with content loaded from the live PIM.

**What the page does today:** flat Product list at `/products/`, filter panel on the left,
each row expandable to its supplier price rows. Search, category (with MPTT descendant
expansion), brand, supplier, availability and price-range filters all work **against the
local mirror** — which, after the §5a probe and the D15 revision, is the finished design
rather than half of one. **Phase 1 is functionally complete.**

What limits it now is data, not code: only **36%** of Products have PIM content (§0.4), so
most rows show a fallback name and cannot be reached by the category or brand facets. D1 is
settled (§0.5); closing that gap is PIM enrichment, and Phase 2 is gated on exporting the
manufacturer data first (P2-G4).

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

## 0.4 PIM coverage — measured 2026-09-19. **The premise is weaker than assumed.**

Measured by loading the full live PIM catalog into the snapshot and matching it (see
`load_pim_mirror`), then investigating why the match rate was low. Aggregates only.

**The number:** of **155,087** local Products, **55,281 (36%)** have a PIM counterpart. Of
those, 22,690 have a brand and 25,528 have a category — so **brand covers 15% of the whole
catalog, category 16%.** Every one of the rest was checked: no `brandId` / `categoriesIds`
exists in their PIM payload. It is missing data, not a loading bug.

**Why it isn't higher — every hypothesis tested:**

| Hypothesis | Test | Result |
|---|---|---|
| The old links recover it: the snapshot linked **154,969** distinct PIM ids | 450 random old ids looked up in live PIM, with a control id to prove the `in` filter works | **0 of 450** exist. Individual GETs return **404 as both `Product` and `PriceManagerProduct`** |
| Whitespace in `sku`/`number` | All 178,605 PIM numbers fetched (none truncated), matched stripped | **+400** |
| Letter case | Stripped + casefold | **+380** |
| Supplier prefix/suffix (`sku = prefix + article + suffix`) | Matched the bare `article` against PIM numbers | ~58k, **marginal** |

**Why the old links are dead.** The old ids are time-ordered UUIDs whose timestamp prefix is
older than every live PIM id seen, so they come from an **earlier generation** of
PIM records. They were never made by `import_main_products_pim`, which keys on
`PriceManagerId` and only imports categories. They came from the push path in
`_push_pim_products`: search PIM by `number`, and if nothing matches, **create a record in
PIM** and store the id that comes back. *(Inference, not proven:)* much of the "155k linked"
figure was therefore price_manager's own data echoed back through PIM rather than curated
content, and that generation has since been removed. **The old 155k was never a measure of
coverage.**

**What this changes:**

- **R7 has fired, decisively.** D1/D11 drop `SupplierProduct.manufacturer` (**74%** of products)
  in favour of PIM brands. PIM brands cover **15%**, and no matching fix recovers the gap —
  the products simply are not in PIM. Doing Phase 2 as specified permanently loses brand
  information for roughly **59% of the catalog**. This is the evidence R7 was written to
  wait for, and it points against D1 as it stands.
- **The Product-shift premise has a hole.** "Product (PIM-backed) owns content, search and
  filtering" holds for 36% of the catalog. For the other 64%, the new page shows a fallback
  name from the supplier row, and **category and brand filters cannot reach those products
  at all** — ticking a brand hides everything PIM does not know about. That is a real
  obstacle to D10's cutover (retiring the old page).
- **Whitespace in `sku` — not a production issue.** 32,123 local `number`s (21%) carry
  leading or trailing whitespace (supplier articles flow into `sku` unstripped), against 3
  in PIM. **PIM strips whitespace from numbers itself** (confirmed by the user), and in
  production the matching happens inside PIM, so these rows match normally. The only place
  it shows is `load_pim_mirror`'s local exact match, a dev tool, where it costs ~400 rows.

**Recovery path — decided 2026-09-19 (§0.5):** enrich PIM. D1 stands; supplier-side
manufacturer is *not* kept as a fallback.

---

## 0.5 D1 revisited — brand vs manufacturer, per product (2026-09-19)

"74% vs 15%" compared two different populations. This is the per-product version the D1
decision was actually made on.

| Per product (of 155,087) | Count | |
|---|---|---|
| Has a supplier manufacturer | 118,277 | 76% |
| Has a PIM brand | 22,690 | 15% |
| Both | 21,552 | |
| **Manufacturer only — loses its brand under D1** | **96,725** | **62%** |
| PIM brand only — what PIM adds | 1,138 | 0.7% |
| Neither | 35,672 | |

**Agreement where both exist**, checked against the *raw* `SupplierProduct.manufacturer`
from the Excel import. That matters because `sync_pim_relations` overwrites
`MainProduct.manufacturer` with the PIM brand, so testing against `MainProduct` would be
partly PIM agreeing with itself. On raw supplier data: **21,381 of 21,559 agree exactly
(99.2%)**, 87 are containment variants, 91 genuinely differ. 309 manufacturer names are in
use against 89 PIM brands.

**Correction (P2-G4 build, same day).** The per-product table above and a "38 products whose
suppliers disagree" figure that used to stand here were measured on `MainProduct.manufacturer`
— the exact column this section warns against. Re-measured on the raw
`SupplierProduct.manufacturer`, matching the export command to the row: **118,346** products
have a supplier manufacturer (not 118,277), and **392** have suppliers naming different
manufacturers (not 38 — PIM overwrites on `MainProduct` had evened most of them out). The
96,725 figure shares that basis, so treat it as approximate (±~100). None of this moves D1;
it does mean the export's «Поставщики расходятся» rows are ~10× more common than first said.

**So the case for dropping manufacturer rested on PIM being more complete and more
accurate, and neither held**: PIM is less complete (15% vs 76%) and no more accurate (99.2%
agreement, with the disagreements pointing at a likely PIM-side error — see P2-G4).

**The user reaffirmed D1 anyway** — the second time, now with this table in front of them —
choosing to close the gap by enriching PIM rather than keeping supplier data. That is a
legitimate strategic choice: it keeps a single source of truth instead of a merged one, and
the direction of travel is PIM-first. **It is recorded as final. Do not reopen it.**

What it imposes is sequencing, not a reversal: **P2-G4** — export the manufacturer data for
the enrichment before Phase 2 deletes it.

---

## 1. The target state

`product.Product` becomes the catalog: it owns identity, content, search and filtering.
`main_product_manager.MainProduct` shrinks to a per-supplier **stock + price row** hanging
off a Product.

Filtering on the new page draws on exactly three sources:

1. **A local search vector on `Product`** — free text.
2. **PIM content fields (categories, brands)** — mirrored locally into `product.Category` /
   `product.Brand` and queried from there. See §5: the live-PIM variant was measured and
   rejected.
3. **`MainProduct` stock and price fields** — traversed via `Product.main_products`.

---

## 2. Decisions (locked)

| # | Decision | Rationale / hazard |
|---|---|---|
| D1 | **CONFIRMED TWICE — final.** Both `MainProduct` and `SupplierProduct` lose `category`/`categories` and `manufacturer`. Brand comes from PIM alone; the gap is closed by **enriching PIM**, not by keeping supplier data. | Reaffirmed 2026-09-19 with the per-product cost measured (§0.5): **96,725 products (62%) lose their only brand**. **Do not reopen this** — it has been decided on full evidence. What it *does* impose is **P2-G4**: the manufacturer data must be exported for the enrichment before Phase 2 deletes it. |
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
| D15 | ~~Hybrid: facet lists local, result set live from PIM.~~ **REVISED 2026-09-16 → local mirror only, no live leg.** | The §5a probe measured the live leg as unworkable for broad filters: enumerating a wide category costs ~45 requests and ~a minute, and 9 of 15 roots are affected. User chose option A on that evidence. Already how the page works — no code change. Trades freshness, not fidelity; the cost is **R8**. |

---

## 3. Phase 1 — additive, nothing is dropped

### 3.1 Model work (`product/`) — ✅ done

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

### 3.1a Backfill orchestrator — ✅ done

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

### 3.2 The page — ✅ done

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

### 4.0 Phase 2a — decouple and port first (additive, done)

Measuring §4's blast radius before writing a migration turned up consumers this brief never
named. Phase 2 is therefore **two PRs**: 2a moves every survivor off the doomed columns and
ports what the old page had, with **no migration**; 2b is the drops. 2a can ship and be used
on real data first, and 2b then arrives as a diff that is mostly migrations, which is what
§4.2's snapshot validation needs.

**The finding: `MainProductFilter` had three consumers that outlive the old page.** It was
built on `MainProduct.search_vector`, `.categories` and `.manufacturer`, and `core/views.py`
imports it at module scope — so dropping those columns would not break a page, it would stop
**the whole app booting**. The consumers:

| Consumer | What it is |
|---|---|
| `core/views.py` `CartItemProductSelectView` | the cart's «Добавить товары» modal |
| `core/utils.py` `find_main_products` | auto-match when a shopping-tab spreadsheet is imported |
| `main_product_manager/views.py` `ResolveMainproduct` | «Привязать из ГП» on the MainProduct card |

**What 2a did:**
- `MainProductFilter` keeps **MainProduct as the row** — you buy from a specific supplier —
  but searches and facets **through `MainProduct.product`**: the product page's own search
  (`product/filters.py` `matching_product_pks`, now shared), `product.Brand`,
  `product.Category`. Rows with `product IS NULL` are still found by their own
  `sku`/`name`/`article`: D5 accepted invisibility on the browse page, and in the cart
  invisibility would mean *unbuyable*, which nobody decided.
- The old page got its own **`MainPageFilter`** (the previous code, unchanged) and lives on it
  until 2b deletes both.
- The cart, its candidate list and its Excel export show the **PIM brand** instead of
  `manufacturer`. The export column keeps its «Производитель» header for downstream users.
- **Port of the old page onto `/products/`** (user chose "full port incl. column picker"):
  per-user column picker (`product/columns.py`) over the expanded supplier rows — all seven
  prices, supplier price/РРЦ/discount from the latest `SupplierProduct`, stock message,
  delivery days, supplier fields, update dates; optional PIM columns on the product row
  (tags, EAN, status, photo); «В заявку» and card link per supplier row; «Добавить товар» and
  «Обновить» buttons. Not ported, deliberately: the dropped fields, and the `pim_*` columns
  the product row already shows. **Photo is the one network call on the page** (PIM knows the
  file URL, `raw_data` only the id), so it is opt-in.
- Column preferences live under **their own cache key**. The old page's key holds lists
  naming `manufacturer`, `weight` and the rest; `normalize_columns` would drop them, but 2b
  should not depend on that for data nobody chose here.

### 4.0b Phase 2b — three PRs, in this order

**2b-1 — retire the old main page (item 5). ✅ Done, code only, no migration.** Deleted:
the page's views, `MainPageFilter`, `MainProductTable`, `grouping.py`, `columns.py`, the
old column-preference cache helpers, `MAINPRODUCT_GROUPING_ROW_LIMIT`, the bulk-category
modal, their templates and `test_grouping.py`/`test_tables.py`, plus six `core` templates
of an even earlier main page that nothing referenced. `/mainproduct/` is a permanent
redirect to `/products/`; the navbar brand and `LOGIN_REDIRECT_URL` point there directly.
The card, update, create, resolve, logs and price-tag routes survive — they are reached
from `/products/`. `maybe_notify_pim_error` moved to the card views, the last place that
calls PIM live on render.

**2b-2 — the column drops (items 1–3), migrations.** Beyond the items below:
- drop `manufacturer`, `categories` and the dimensions from
  `MainProductCreateForm`/`MainProductForm`, and the lazy category tree of the create
  modal (`mainproduct-create-categories`);
- **the import pipeline loses its Product link — the silent one.** Copy-to-main
  (`supplier_product_manager/tasks.py`) links new MainProducts to their Product only as a
  side effect of `recalculate_search_vectors` → `_build_searchvector` →
  `_link_to_local_product`. Item 1 deletes that chain, and every newly imported row would
  then land with `product IS NULL`, invisible on `/products/` until `reindex_pim_ids`
  runs. Nothing errors. Give it an explicit link step over the copied ids;
- the same for «Добавить товар»: call `_link_to_local_product` explicitly in
  `MainProductCreate.form_valid` (today it is `rebuild_search_vector()`'s side effect);
- the «Обновить» chain (`sync_main_products_task`) loses `recalculate_vectors_missing_task`;
  `rebuild_categories_task` goes with 2b-3;
- **canary for the PR:** P1-G3's `unlinked_main_product_count()` on `/products/` must stay
  flat across an import run after deploy.

**2b-2 — done.** Three migrations, each with a data step in front, run against a
restore of the production snapshot migrated to today's schema (modes C + D of the
`prod-snapshot` skill; nothing pushed to PIM):

| Migration | Reported on the snapshot | Matches |
|---|---|---|
| `product_price_manager.0004` — categories → `product.Category` | 0 rules with categories | G4 = 0 |
| `main_product_manager.0012` — drop the 8 catalog fields | 2 descriptions with no source | F4 = 2 |
| `supplier_product_manager.0010` — drop category, manufacturer | 85 + 75 Links deleted, 0 DictItems | P2-G3 = 160 |

Then, on the same data: all 118 pricing rules resolve `get_fitting_mps` without
error; `/products/`, search, supplier rows, the card and the create/update modals
render; row counts unchanged. **0004's refusal was proven, not assumed:** rolled
back, one rule given a category, re-run — it raised, applied nothing, and the
rule kept its category.

What 2b-2 also had to do, found by consulting the three keepers first:
- explicit Product links (`link_to_local_products` in copy-to-main,
  `_link_to_local_product` in «Добавить товар») — the silent one above;
- `AUTO_LINK_ALIASES` loses «производитель»/«категория», or the mapping screen
  would re-create the deleted Links; `load_setting` ignores keys outside `LINKS`;
- both admins' `list_filter` (a stale entry fails system check E116 suite-wide);
- `push_pim_links` reads the description from the supplier row it was copied
  from; the rule form's category picker reads through `MainProduct.product`;
- the whole `sync_pim_relations` chain, the «Добавить производителя в ГП» admin
  action, `CategoryFilter`, the PIM-categories import resource and command, and
  `export_manufacturers_for_pim` (P2-G4 done) are deleted;
- the main-price export keeps «Название_группы» / «HTML_описание» and no longer
  imports them. **Description** reads the supplier row first (what the dropped
  column was copied from), then PIM — coverage kept. **«Производитель» is
  removed from the export — the user's decision.** Its only remaining source,
  the PIM brand (D1), covers ~15% of products against ~76% for the supplier
  manufacturer it replaced (§0.4); a mostly empty column was judged worse than
  none. The cart's own Excel export (Phase 2a) still has a PIM-brand
  «Производитель» column — a separate file, not part of that decision.

**Deploy note:** the three migrations are independent of each other but all
run after deploy; run them with the app briefly idle — 0004 is the one that can
refuse, and if it does, nothing has changed yet. Messages still queued in Redis
for the deleted tasks (`populate_pim_relations`, `recalculate_vectors_missing`)
are rejected by the worker as `NotRegistered` — expected, harmless, once.

**2b-3 — retire `supplier_manager.Category`, `Manufacturer`, `ManufacturerDict` (item 4).
✅ Done.** Their tables could only go once every FK and M2M into them was gone (2b-2), so
`supplier_manager.0011` declares those three migrations as dependencies — the autodetector
cannot see the link, and a fresh-DB `migrate` passes in any order; only a populated database
fails. Validated on the snapshot (816 categories, 632 manufacturers dropped; `/products/`,
all 118 rules, supplier pages, admin render) and on an empty database from zero.

- **R5 was checked first, as this brief required** — see R5 below. It materialised mildly;
  the user chose to retire `ManufacturerDict` anyway and fix duplicates in PIM. `0011`
  exports the alias table to `media/exports/manufacturer_aliases.csv` before dropping it
  (empty on production, so it only reports that).
- User-visible: «Категории» and «Производители» of the old catalog leave `/admin/`. Their
  pages had already lost their routes; the category autocomplete had no callers.
- The «Обновить» chain loses `rebuild_categories`; beat loses `sync-categories`.

**A lesson from 2b-2 that belongs here:** CI's first run of 2b-2 failed on a fresh-database
`migrate` that every local check had passed — `supplier_product_manager.0008` read
`PriceTag` without declaring the dependency, and 2b-2's new edge shifted the plan order.
`--keepdb` and the snapshot both start migrated, so neither can see this. **Run a
fresh-database `migrate` locally before pushing any migration change** (create a scratch DB,
`migrate` with `POSTGRES_DB` pointed at it, drop it).


Separate PR. Each item is irreversible on prod. Unchanged from the original spec except
where F2/F4 relaxed the gates.

1. Drop `MainProduct.search_vector`, `description`, `categories`, `manufacturer`,
   `weight`, `length`, `width`, `depth`.
   - Also strips the writes in `supplier_product_manager/tasks.py:239-274` (copy-to-main)
     and `main_product_manager/utils.py:437-449` (`sync_pim_relations`).
   - ~~Bonus: may make `main_product_manager/pim_client.py` deletable.~~ **No longer:**
     `get_file_url`/`fetch_pim_image` (the photo proxy, 2026-09-21) and the card views'
     `get_pim_data` still use its `site`.
   - Log or assert on the 2 descriptions with no SupplierProduct counterpart (F4).
2. Drop `SupplierProduct.category` and `.manufacturer`; remove both from `LINKS`; data
   migration deleting the 160 orphaned `Link` rows (D11). **Only after P2-G4's export has
   been run in production and handed over** — and delete `export_manufacturers_for_pim`
   (command, service and its tests) in the same change, since it reads these columns.
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

> **P2-G4 — 🔴 BLOCKING: export manufacturer data before dropping it.** D1 closes the brand
> gap by enriching PIM. The best input for that enrichment is the very data this phase
> deletes: for **96,725 products** `SupplierProduct.manufacturer` is the *only* brand
> information that exists anywhere. Run Phase 2 first and the enrichment project loses its
> source. Before the manufacturer columns are dropped, produce an export of
> `(Product.number, name, manufacturer)` for every product without a PIM brand, and hand
> it to whoever enriches PIM. This is **ordering, not a reversal of D1** — D1 stands.
>
> **Tool: `manage.py export_manufacturers_for_pim`** (`product/services/manufacturer_export.py`).
> Run it **in production, after the content backfill and before Phase 2**. After the
> backfill, "no PIM brand" means exactly that; before it, every product looks brand-less
> and the export is merely wider than needed, which is the safe direction. CSV goes to
> stdout, counts to stderr; `--output` writes a file with a BOM for Excel. The rows are:
> - **one row per (product, manufacturer)**, so a product whose suppliers disagree shows up
>   as several rows flagged «Поставщики расходятся», rather than a silently picked winner;
> - taken from the **raw `SupplierProduct.manufacturer`**, never `MainProduct.manufacturer`,
>   which `sync_pim_relations` overwrites with the PIM brand;
> - `--with-disagreements` adds the products whose PIM brand no supplier confirms — the
>   PIM-side check below.
>
> The file holds production data: write it outside the repo (`/app` in the container *is*
> the repo), and it never goes into a commit, PR or issue. `*.csv` is gitignored anyway.
> **Phase 2 must delete this command** along with the columns it reads.
> Two data points for that export's recipients:
> - Where PIM and supplier both have a brand, they agree **99.2%** — the supplier value is a
>   trustworthy seed, not noise.
> - The ~91 disagreements are almost all PIM saying **DENZEL** where suppliers report seven
>   different manufacturers between them. One PIM brand against seven
>   different manufacturers looks like a bulk mis-assignment *in PIM*. Suggestive, not
>   proven — worth a PIM-side check.

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

## 5. Category/brand filtering — ✅ RESOLVED: local mirror, no live leg

**D15 is revised.** The original decision was hybrid — mirrored facet lists, live PIM for
the result set. The §5a probe measured that against the real PIM and it does not hold: see
the numbers below. Presented with them, the user chose **option A — drop the live leg and
keep the local mirror.**

**This requires no code change.** The page already filters `product.Category` /
`product.Brand` locally, and that is now the final design rather than half of one.

**What this trades:** freshness, not fidelity. The mirror is itself PIM-sourced through
`pim_sync`, so filter results reflect the last sync rather than the last minute. What it
buys: instant filtering, real facet counts, pagination, and no network call anywhere in the
page's query path — which is the pattern `CLAUDE.md` flags on `_build_searchvector`.

**The consequence that is now load-bearing — see R8.** While the mirror was only a facet
list, staleness was cosmetic. Now the mirror *is* the answer, and
`_ensure_pim_category` (`pim_sync.py:26`) **returns early when the category already
exists — it never updates `name` or `parent`.** A category renamed in PIM keeps its old
local name forever; one re-parented in PIM filters into the wrong branch. (`Brand` does not
have this problem: `_ensure_pim_brand` refreshes the name on change.)

The rest of this section is kept as the record of *why* the live leg was rejected, and what
it would take if PIM ever changes.

### The client blocker (closed, and still worth having)

Closed. It is no longer on the critical path, but it fixed two real defects and
powers the probe:

**The client blocker is now closed.** What was wrong and what it became:

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
  `category_path` trap in `.claude/knowledge/product/pim-sync.md`. No existing caller passes it.

### 5a. Probe — RUN 2026-09-16 against the live PIM. **The named exit fired.**

```bash
docker compose --env-file <path-to>/.env run --rm --no-deps -T web \
    python manage.py probe_pim_category_size
```

The probe reads the category tree **from PIM itself**, not from local categories — the
question is about PIM and does not depend on whether the backfill has run. (The first
version walked local `Category` rows and answered "no local categories" on an empty
database, which is not an answer.)

**Shape of the live catalog:** 668 categories, 15 roots, 36,051 products.

**Four measured findings:**

1. **Hard URI limit.** 100 category ids in one `linkedWith` request works; **125 returns
   `HTTP 414 URI Too Long`.** Root branches run to 186 nodes, so the widest selections
   cannot be expressed in a single request at all. Chunking at 90 ids works and is cheap.
2. **PIM does not expand a category to its children.** A root id sent alone returns **0**
   products — links are to leaf categories. The full descendant set must be sent, so §5b's
   local MPTT expansion is mandatory, not an optimisation.
3. **Counting is cheap.** A chunked count over a 186-node branch is ~1.8s total, each
   request ~0.6s. **A live facet *count* is affordable.**
4. **Enumerating is not.** Fetching the actual product ids — which is what
   `Product.pim_id IN (...)` needs — took **19.0s for 3,000 ids, and was still truncated
   at a `total` of 5,583.** The worst branch holds ~8,597 products: roughly 45 paged
   requests and a minute of wall clock, per filter click.

**Distribution:** **9 of 15 root categories exceed 1,000 products.** The largest single
root holds ~7,281 on its own. This is not a tail case; it is most of the catalog.

> **Verdict.** The live leg as specified in D15 is **not viable for broad filters.** It is
> fine for narrow ones — a leaf category of a few hundred products is one request,
> sub-second. The split is sharp and it falls in the middle of normal use.
>
> Per the named exit, this goes back to the user rather than being capped silently. The
> options, and what each costs:
>
> - **A — drop the live leg; keep the local mirror.** ← **CHOSEN 2026-09-16.** Already built
>   and working. Instant, paginates, gives real facet counts. The mirror is itself
>   PIM-sourced via `pim_sync`, so this is a freshness trade, not a fidelity one: results
>   reflect the last sync. Its cost is **R8**.
> - **B — live counts, local result set.** Finding 3 says counts are affordable. Facet
>   numbers could come from PIM live while the rows come from the mirror. Cheap, but the
>   count and the list can disagree, which needs saying in the UI copy.
> - **C — live leg for narrow selections only, mirror above a threshold.** Honest but
>   two code paths, and the mirror path has to exist anyway, so it buys little.
>
> Nothing here reopens D15 on preference. It reopens it on evidence that did not exist when
> it was made.

### 5b. Descendant semantics — ✅ handled, and still required

`categories_method` expands the selection through `product.Category`'s MPTT tree locally
before filtering. This is **not** live-leg-specific: with the mirror it is what makes
selecting a parent category match everything beneath it. Finding 2 of the probe confirms PIM
behaves the same way — it links products to leaves only — so the expansion is correct
against both. Pinned by `test_selecting_a_parent_finds_products_in_its_descendants`.

### 5c. If the live leg is ever revisited

It would need a PIM-side change first, not a client-side one. The blocker is that PIM can
**count** a wide category cheaply but cannot **enumerate** it cheaply, and enumeration is
what `pim_id IN (...)` requires. What would unblock it:

- a category filter that expands to descendants server-side (removing the 186-id URI
  problem), and
- a POST-based search, or any transport not bounded by URI length.

If that ever lands, the requirements that still apply: use
`fetch_list(..., max_items=…)` and **surface `result.truncated`** rather than returning a
silent prefix; cache per facet with a short TTL; decide explicitly what happens when PIM is
down (falling back to the mirror is now the obvious answer, since the mirror is the primary);
and never call it inside a `transaction.atomic()` runner.

---

## 6. Risks carried forward

- **R1 — ✅ CLOSED.** The hybrid filter was the highest-risk item; the §5a probe measured it
  as unworkable for broad filters and the user chose the local mirror (option A). There is
  no longer a network call anywhere in the page's query path. **Replaced by R8, which is the
  cost of that choice.**
- **R8 — the category mirror goes stale, and that now matters.**
  `_ensure_pim_category` (`pim_sync.py:26`) returns early when a category already exists: it
  **never updates `name` or `parent`.** A rename in PIM leaves the old label on the filter
  forever; a re-parent silently puts products in the wrong branch of the MPTT tree, which
  `categories_method` then expands incorrectly. While the mirror was only a facet list this
  was cosmetic — under option A it is the answer itself.
  `_ensure_pim_brand` does **not** share this bug; it refreshes the name on change.
  **Fix shape:** a `sync_categories_from_pim` reconciliation task that walks PIM's category
  list and updates names and parents, rather than patching `_ensure_pim_category` (which
  only ever runs when a product happens to reference the category, so it can never see a
  rename on an untouched branch). This is also the first genuine production use of
  `fetch_list` — 668 categories is 4 paged requests.
- **R2 — ✅ resolved.** Coverage was measured (§0.3). G1/G2 need one re-read post-`#184`,
  not a fresh investigation.
- **R3 — two PIM clients.** `product/pim_client.py` and `main_product_manager/pim_client.py`
  are separate `SiteAPI` instances against the same PIM. The live filter leg would be a
  third consumer. Don't add a fourth — pick one and note why.
- **R4 — D9 rests on an assumption.** Dropping `article` search assumes users only search by
  the prefixed `sku` they see. If a supplier has `sku_type` set **and** users search by raw
  article, search silently stops finding those rows. *Partly mitigated:* the page also
  matches the linked MainProduct's `name`, so such a product is still reachable by name.
- **R5 — ✅ checked 2026-09-21, materialised mildly, resolved on the PIM side.** Of 321
  PIM brands, 14 names exist as two separate brand *records* differing only by case or
  punctuation (28 records — STAYER/Stayer, DENZEL/Denzel, Sturm/Sturm!, …), so the brand
  facet lists both. They are duplicate entities, not free-text variants, so an alias layer
  here would be papering over PIM data. The user chose: retire `ManufacturerDict` as
  planned (it mapped supplier spellings, not PIM brands, and was empty on production) and
  merge the duplicates in PIM. *Original text:* D3 assumes PIM brands are a controlled
  vocabulary; if not, reconsider deleting `ManufacturerDict` rather than rebuilding it.
- **R6 — `product.Category` becomes mixed-provenance if D8 is softened.** `pim_sync`'s
  `_ensure_pim_category` does `get_or_create(parent=…, name=…)`; carrying non-PIM categories
  across would collide. D8 keeps the tree pure — keep it that way.
- **R7 — ✅ CLOSED: fired, measured, and accepted.** It fired on 2026-09-19 (§0.4): PIM
  brands cover **15%** of products against **76%** for supplier manufacturer, and no matching
  fix closes the gap. D1 was then revisited with the per-product cost in hand (§0.5) —
  **96,725 products lose their only brand** — and **the user reaffirmed it**, choosing PIM
  enrichment over keeping supplier data. The remaining obligation is P2-G4 (export before
  delete). *Original text below.*
  **Brand coverage is unmeasured and accepted (D1/D3/D11).** 74% manufacturer density
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
- **A category facet narrowed to the result set must keep the ancestors of what is
  *selected*, not just of what is found.** `{% recursetree %}` treats a node without its
  parent as a root, and a later node of lower level then raises «not in depth-first order» —
  a 500, not a cosmetic glitch. It happens exactly when a search excludes the products of an
  already-ticked category. Take `get_ancestors(include_self=True)` of the *union*. Found in
  the cart modal during 2a; `ProductFilter` is immune only because it offers the whole tree.
- **Facets built in a filterset's `__init__` run before form validation.** A non-numeric id
  from the address bar reaches `pk__in` raw and raises `ValueError`. Keep only digits there.

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
