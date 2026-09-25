"""Основные цены Product из строк поставщиков (MainProduct).

У товара несколько поставщиков, у каждого свои семь цен (MP_PRICES). Товару
нужна одна цена каждого вида — берётся то же «основное значение», что стоит в
экспорте и в себестоимости набора (main_values.main_row): верхний уровень
Supplier.price_priority, внутри него минимальная ненулевая. Одно правило на
всё — иначе экспорт, набор и цена товара разошлись бы на одном и том же товаре.

Пересчёт целиком локальный: ни PIM, ни сети. Идёт партиями по pk, чтобы не
держать в памяти все 150 тыс. товаров со строками поставщиков разом.
"""
from django.db.models import Prefetch
from django.utils import timezone

from main_product_manager.models import MP_PRICES, MainProduct

from ..main_values import main_row
from ..models import Product

BATCH_SIZE = 2000


def base_prices(main_products) -> dict:
    """{поле: основная цена} по строкам поставщиков одного товара.

    Строки — с select_related('supplier'). None — ни у кого нет цены, 0 — есть
    только нули (так же, как в экспорте).
    """
    return {
        field: main_row(main_products, field, 'price_priority', min)[0]
        for field in MP_PRICES
    }


def recalculate_base_prices(pks=None, batch_size: int = BATCH_SIZE) -> int:
    """Пересчитывает основные цены; возвращает число товаров, у которых они изменились.

    pks=None — весь каталог. Пишутся только изменившиеся товары: цены меняются
    у немногих, а prices_updated_at — это «когда цены поменялись», а не «когда
    последний раз проверяли».
    """
    queryset = Product.objects.order_by('pk')
    if pks is not None:
        queryset = queryset.filter(pk__in=pks)
    rows = MainProduct.objects.select_related('supplier').only(
        'product_id', 'supplier__price_priority', *MP_PRICES)
    all_pks = list(queryset.values_list('pk', flat=True))
    now = timezone.now()
    changed_total = 0
    for start in range(0, len(all_pks), batch_size):
        chunk = all_pks[start:start + batch_size]
        products = Product.objects.filter(pk__in=chunk).only('pk', *MP_PRICES).prefetch_related(
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
            Product.objects.bulk_update(changed, fields=[*MP_PRICES, 'prices_updated_at'])
        changed_total += len(changed)
    return changed_total
