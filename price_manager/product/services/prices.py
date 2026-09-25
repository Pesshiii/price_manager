"""Основные цены Product из строк поставщиков (MainProduct и их прайсы).

У товара несколько поставщиков, у каждого свои цены. Товару нужна одна цена
каждого вида — берётся то же «основное значение», что стоит в экспорте
(export.ProductExport.main_value_cells):

- поставщики идут по уровням Supplier.price_priority (меньше — выше,
  непроранжированные — общий нижний уровень, строки без поставщика — в конце);
- на одном уровне первым идёт поставщик с минимальной себестоимостью, и цены
  берутся у него — чтобы цены товара были от одного поставщика, а не
  минимумы, собранные у разных;
- нет у него какой-то цены (0 или пусто) — она берётся у следующего по
  себестоимости, затем с уровней ниже.

Цены прайса поставщика (SupplierProduct: цена поставщика, РРЦ, цена со
скидкой) идут тем же порядком и переводятся в тенге по курсу валюты
поставщика строки — как PriceTag.get_sprice у наценок поставщика.

Пересчёт целиком локальный: ни PIM, ни сети. Идёт партиями по pk, чтобы не
держать в памяти все 150 тыс. товаров со строками поставщиков разом.
"""
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from django.db.models import Prefetch
from django.utils import timezone

from main_product_manager.models import MP_PRICES, MainProduct

from ..main_values import cost_key, is_zero, level_key, main_value
from ..models import SUPPLIER_PRICE_FIELDS, Product

BATCH_SIZE = 2000
CENT = Decimal('0.01')
NEVER = datetime.min.replace(tzinfo=dt_timezone.utc)

# Все основные цены Product: из ГП и из прайса поставщика.
BASE_PRICE_FIELDS = [*MP_PRICES, *SUPPLIER_PRICE_FIELDS]


def ordered_rows(main_products) -> list:
    """Строки поставщиков в порядке, в котором из них берутся цены.

    Уровень по цене, на уровне — поставщик с меньшей себестоимостью (его
    минимальная ненулевая по строкам; без себестоимости — в конце уровня), при
    равной — по имени; строки одного поставщика — тоже по себестоимости.
    Строки должны идти с select_related('supplier').
    """
    by_supplier = {}
    for row in main_products:
        by_supplier.setdefault(row.supplier_id, []).append(row)

    def supplier_key(rows):
        supplier = rows[0].supplier
        cost = main_value([[row.prime_cost for row in rows]], min)
        return (level_key(supplier, 'price_priority'), cost_key(cost),
                supplier.name if supplier else '', supplier.pk if supplier else 0)

    result = []
    for rows in sorted(by_supplier.values(), key=supplier_key):
        result.extend(sorted(rows, key=lambda row: cost_key(row.prime_cost)))
    return result


def supplier_row_price(row, sp_field):
    """Цена прайса поставщика строки в тенге; None — нет прайса, цены или курса."""
    supplier_products = list(row.supplierproducts.all())
    if not supplier_products:
        return None
    # Уникальность SupplierProduct.main_product делает строку единственной;
    # max по updated_at — тот же выбор, что у наценок поставщика.
    supplier_product = max(supplier_products, key=lambda sp: sp.updated_at or NEVER)
    price = getattr(supplier_product, sp_field)
    if is_zero(price):
        return price
    currency = row.supplier.currency if row.supplier else None
    if currency is None or currency.value is None:
        return None
    return (price * currency.value).quantize(CENT)


def base_prices(main_products) -> dict:
    """{поле Product: основная цена} по строкам поставщиков одного товара.

    None — ни у кого нет цены, 0 — есть только нули (так же, как в экспорте).
    """
    rows = ordered_rows(main_products)
    prices = {
        field: main_value(([getattr(row, field)] for row in rows), min)
        for field in MP_PRICES
    }
    for field, sp_field in SUPPLIER_PRICE_FIELDS.items():
        prices[field] = main_value(([supplier_row_price(row, sp_field)] for row in rows), min)
    return prices


def recalculate_base_prices(pks=None, batch_size: int = BATCH_SIZE) -> int:
    """Пересчитывает основные цены; возвращает число товаров, у которых они изменились.

    pks=None — весь каталог. Пишутся только изменившиеся товары: цены меняются
    у немногих, а prices_updated_at — это «когда цены поменялись», а не «когда
    последний раз проверяли».
    """
    queryset = Product.objects.order_by('pk')
    if pks is not None:
        queryset = queryset.filter(pk__in=pks)
    rows = MainProduct.objects.select_related('supplier__currency').prefetch_related('supplierproducts')
    all_pks = list(queryset.values_list('pk', flat=True))
    now = timezone.now()
    changed_total = 0
    for start in range(0, len(all_pks), batch_size):
        chunk = all_pks[start:start + batch_size]
        products = Product.objects.filter(pk__in=chunk).only('pk', *BASE_PRICE_FIELDS).prefetch_related(
            Prefetch('main_products', queryset=rows))
        changed = []
        for product in products:
            prices = base_prices(list(product.main_products.all()))
            if any(getattr(product, field) != value for field, value in prices.items()):
                for field, value in prices.items():
                    setattr(product, field, value)
                product.prices_updated_at = now
                changed.append(product)
        if changed:
            Product.objects.bulk_update(changed, fields=[*BASE_PRICE_FIELDS, 'prices_updated_at'])
        changed_total += len(changed)
    return changed_total
