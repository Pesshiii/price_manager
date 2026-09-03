# supplier_manager

The reference-data app: who supplies, in what currency, under what category
tree. Small (1187 LOC) but nearly everything else imports it.

## Models (`supplier_manager/models.py`)

- **`Currency:15`** — `name` + `value`, where `value` is the rate **in tenge**
  (`verbose_name='Тенге'`). Prices elsewhere are converted through this.
- **`Supplier:32`** — the hub. Beyond `name`/`currency`/`pim_id`:
  - `sku_type` + `sku_value` — a **prefix or suffix** applied to build the SKU.
    The builder is `compute_supplier_sku(article, supplier)` in
    `main_product_manager/utils.py:392`, not here.
  - `delivery_days_available` / `delivery_days_navailable`, selected by
    `get_delivery_days_for_stock(stock)` (`:97`).
  - `msg_available` / `msg_navailable` — customer-facing stock strings.
  - `price_update_rate` / `stock_update_rate` + `price_updated_at` /
    `stock_updated_at`.
- **`Discount:103`** — a named discount group belonging to a supplier.
  [[product_price_manager]] matches rules against these.
- **`Manufacturer:125`** and **`ManufacturerDict:137`** — the dict holds
  *variations* (`verbose_name='Вариация'`) that normalise onto one manufacturer.
  When an import can't match a manufacturer name, `ManufacturerDict` is the
  place that fixes it, not a code change.
- **`Category(MPTTModel):155`** — see below.

## `Category` is MPTT *and* full-text indexed

`parent` is a `TreeForeignKey` with `on_delete=CASCADE`, unique on
`(parent, name)`, `order_insertion_by = ['name']`. `__str__` renders the path as
`parent>child`.

`_build_searchvector()` (`:176`) indexes the **whole ancestor path**:
`' '.join(a.name for a in self.get_ancestors(include_self=True))`, weight A,
`config='russian'`, behind `GinIndex(name='category_search_vector_gin')`.

Two consequences:
1. `get_ancestors()` is a query per category. Rebuilding vectors in a loop is
   N queries — that's what `recalculate_category_vectors_missing_task`
   (`tasks.py:8`) exists for.
2. **Renaming or reparenting a category invalidates every descendant's vector**,
   not just its own. Nothing recalculates descendants automatically. If you add
   a move/rename path, queue the rebuild for the subtree.

`rebuild_search_vector()` (`:181`) uses `.filter(pk=...).update(...)`, not
`save()` — same reason as in [[main_product_manager]]: no joined fields in a
SET expression.

Unlike `MainProduct._build_searchvector`, this one makes **no PIM call**. It is
cheap per row apart from the ancestor query.

## Tasks

Two, both via `execute_locked_task`: `recalculate_category_vectors_missing`
(`tasks.py:8`) and `sync_categories` (`tasks.py:25`).

## Note

There is a *separate, retiring* `supplier` app and a separate `product.Category`
MPTT model. Three similarly-named things. This app is the live one; see
[[retiring_stack]] and [[product]].
