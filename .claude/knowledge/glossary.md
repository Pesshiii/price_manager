# Glossary — UI terms ↔ code ↔ PIM

Hand-written, unlike the READMEs. The interface and the people using it speak
Russian; the code speaks English. When a user, an issue or a Telegram message
names something in Russian, this is where it maps to a model, a field or a PIM
entity. Add a term when you meet one that cost you a search; link the topic
that explains it rather than explaining it here.

## Catalog

| Term (UI) | Code | Notes |
|---|---|---|
| Товар, «Товары» (`/products/`) | `product.Product` | The root of search and filtering since the product shift. Mirrors a PIM product. [[product/overview]] |
| Карточка товара | `product.views.ProductDetailView`, `/products/<pk>/` | Prices with their rules, ГП rows (attach/move), set composition; edit and delete. See CLAUDE.md on why ГП rows are moved, never unlinked. |
| ГП, главный прайс, «Главный продукт», строка поставщика | `main_product_manager.MainProduct` | One supplier's stock and prices for one `Product`. `/mainproduct/` redirects to `/products/`. [[main_product_manager/overview]] |
| Артикул | `Product.number` = `MainProduct.sku` | Local match key; unique case-insensitively. [[product/pim-link]] |
| Артикул поставщика | `MainProduct.article`, `SupplierProduct.article` | The supplier's own code; `sku` is built from it (`compute_supplier_sku`). [[main_product_manager/sku-and-linking]] |
| Категория, Бренд | `product.Category` (MPTT), `product.Brand` | Both come from PIM; supplier-side categories and manufacturers were retired. [[supplier_manager/retired-models]] |
| Набор, «Состав набора», «Позиция набора» | `product.ProductSetItem` | A `Product` with composition rows. [[product/sets]] |
| «Из комплектующих» | `product.set_costs` | Set cost and buildable count computed from the components. [[product/sets]] |

## Prices and stock

| Term (UI) | Code | Notes |
|---|---|---|
| Себестоимость | `MainProduct.prime_cost` | The page column shows a min–max range across suppliers. |
| Оптовая цена, Оптовая цена доп., Базовая цена, Цена ИМ, Цена Каспи, Цена со скидкой | `wholesale_price`, `wholesale_price_extra`, `basic_price`, `m_price`, `kaspi_price`, `discount_price` | `MP_PRICES` in `main_product_manager/models.py`, all in tenge. |
| Остаток | `MainProduct.stock`, `SupplierProduct.stock` | `NULL` («Нет данных») and `0` are different states. |
| Цена поставщика, РРЦ, цена со скидкой (в валюте поставщика) | `SupplierProduct.supplier_price`, `rrp`, `discount_price` | `SP_PRICES`; not comparable across suppliers. |
| Уровень по цене, уровень по остаткам | `Supplier.price_priority`, `Supplier.stock_priority` | Smaller is higher; empty is the shared bottom level. |
| Основная цена / основной остаток | `product.main_values` | The value by supplier levels, used by the export and by set cost. [[product/export]] |
| Наценка, менеджер наценок | `PriceManager` (rule), `PriceTag` (verbose name «Наценка») | Applying a rule rewrites prices catalog-wide. [[product_price_manager/overview]] |
| Основные цены товара | `Product.prime_cost` … `kaspi_price`, `supplier_price`, `rrp`, `supplier_discount_price` | ГП prices plus ПП prices in tenge, taken from the top price-level supplier with the lowest prime cost; `product/services/prices.py`. |
| ПП, прайс поставщика (в наценках) | `SupplierProduct.supplier_price` / `rrp` / `discount_price` → `Product.supplier_price` / `rrp` / `supplier_discount_price` | Source group «Прайс поставщика (ПП)» in the rule form. |
| Цены товаров, наценка на товар, тип цены, расчётная цена | `product_pricing`: `ProductPriceRule`, `ProductPriceType`, `ProductPrice` | Second pricing level, on `Product`; shown as columns on «Товары». See CLAUDE.md. |

## Suppliers and import

| Term (UI) | Code | Notes |
|---|---|---|
| Поставщик | `supplier_manager.Supplier` | Not the retiring `supplier` app. [[supplier_manager/overview]] |
| Валюта, Группа скидок | `Currency` (rate in tenge), `Discount` | |
| Прайс поставщика, строка прайса | `supplier_product_manager.SupplierProduct` | The supplier's raw row, one per `MainProduct`. |
| Настройка (импорта) | `Setting` + `Link` + `DictItem` | Column mapping for one supplier file. [[supplier_product_manager/import-config]] |
| Файл поставщика | `SupplierFile` | Upload queue. [[supplier_product_manager/upload-and-cleanup]] |
| Импорт прайса, проверка импорта | `ImportRun` | History and the confirmation guard. [[supplier_product_manager/import-run-and-guard]] |
| Копирование товаров поставщика в ГП | `CopySupplierProductsToMainRun` | |

## Cart, notifications, the rest of the UI

| Term (UI) | Code | Notes |
|---|---|---|
| Заявка, корзина | `core.ShoppingTab` | |
| Позиция заявки, «Запрос», подтверждённый товар | `CartItem`, `.search_query`, `.confirmed_product` | Candidates are `CartItem.products`. [[core/views]] |
| «из набора X» | `CartItem.source_set` | Lines exploded from a set. [[core/cart-sets]] |
| Оповещения | `core.PersistentNotification` | [[core/models-and-notifications]] |
| История запусков задач | `core.TaskRunHistory` | Written by `execute_locked_task`. [[core/task-runner]] |
| «Обновления», «Что нового» | `releases.Release` | Release notes at `/releases/<version>/`. |
| «Разработчикам», обратная связь | `developers.Feedback` | Each message becomes a Bitrix24 task. |
| Вход через Bitrix24 | `core.Bitrix24Account`, `core/bitrix24.py` | [[core/bitrix24-login]] |

## PIM (AtroPIM)

| Term | Meaning here | Notes |
|---|---|---|
| PMP, `PriceManagerProduct` | The link record between our `Product` and a PIM product | `platformID` is our `Product.pk`; `Product.pim_id` is the PMP id. [[main_product_manager/pim-link]] |
| Classification | PIM's product type with its own attributes | Not mirrored locally. |
| Association, `AssociatedProduct` | Typed product-to-product link with `amount` | Sets use code `set_components`; its reverse `part_of_set` has no amount. [[product/sets]] |
| Бэкфилл | `product.backfill_products_from_pim` | Pulls PIM content onto `Product`s that have a `pim_id`. [[product/pim-sync]] |
