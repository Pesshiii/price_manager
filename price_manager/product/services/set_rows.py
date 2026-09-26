"""Строка ГП набора: без поставщика, себестоимость — из комплектующих.

У каждого набора (Product с составом) есть ровно одна такая строка
(MainProduct.is_set). Она ведёт себя как любая строка ГП — остаток, цены,
наценки, заявки, выгрузка, основные цены товара, — кроме себестоимости: её
пишет только этот модуль, и это сумма «количество × основная себестоимость»
по составу (set_costs.set_totals_for). Отсюда же у виртуального набора — без
своих поставщиков — появляются цены вообще.

Неполная сумма не пишется. Если хоть у одного компонента нет цены или его
нет в Price Manager, себестоимость строки — пусто, а не сумма остальных:
наценка от неё посчитала бы цену набора без части комплектующих и выдала бы
за настоящую. Пустой источник наценки затем очищает и её цену
(clear_unsourced_prices) — как у любой строки ГП.

Вызывается из update_prices (после наценок, которые меняют себестоимость
комплектующих, — поэтому наборы «последние») и после синхронизации наборов.
Всё — локальная работа с БД, без PIM.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from main_product_manager.models import MainProduct, MainProductLog

from ..models import Product, ProductSetItem
from ..set_costs import set_totals_for

logger = logging.getLogger(__name__)

CENT = Decimal('0.01')
# Набор в наборе: себестоимость внутреннего набора меняется на первом
# проходе, внешнего — на следующем. Больше пяти уровней вложенности в PIM нет;
# цикл в составе (набор внутри самого себя) не должен крутиться вечно.
MAX_PASSES = 5
NUMBER_MAX_LENGTH = Product._meta.get_field('number').max_length


def set_cost(totals) -> Decimal | None:
    """Себестоимость набора для строки ГП — только полная сумма, иначе None."""
    if totals is None or not totals.count or totals.missing_cost or totals.cost is None:
        return None
    return totals.cost.quantize(CENT)


def _create_missing_rows(set_pks) -> int:
    """Строка набора каждому набору, у которого её ещё нет.

    Артикул строки — артикул товара: по нему строка и привязана (ensure-правило
    — строка ГП без товара не бывает). Набор без артикула пропускается: его
    не по чему найти ни здесь, ни в PIM, и такие наборы sync_product_sets не
    создаёт.
    """
    have_row = set(MainProduct.objects.filter(is_set=True, product_id__in=set_pks)
                   .values_list('product_id', flat=True))
    new_rows = [
        MainProduct(product=product, supplier=None, is_set=True, sku=product.number,
                    article=product.number, name=product.name or product.number)
        for product in Product.objects.filter(pk__in=set_pks).exclude(pk__in=have_row)
        .exclude(number__isnull=True).exclude(number='').only('pk', 'number', 'name')
        if len(product.number) <= NUMBER_MAX_LENGTH
    ]
    try:
        # Точка сохранения: update_prices идёт в транзакции execute_locked_task,
        # и ошибка без неё сломала бы весь прогон.
        with transaction.atomic():
            MainProduct.objects.bulk_create(new_rows)
    except IntegrityError:
        # Строку успел создать параллельный прогон; этот доделает следующий.
        logger.warning('set_rows: строка набора уже создана параллельно — пропуск')
        return 0
    return len(new_rows)


def _retire_stale_rows(set_pks, logs: bool) -> int:
    """Товар перестал быть набором — его строка становится обычной строкой без поставщика.

    Не удаляется: у неё могут быть остаток, наценки, место в заявках. Но
    себестоимость из комплектующих больше не от чего считать — она очищается,
    иначе застывшая сумма выглядела бы введённой руками.
    """
    stale = list(MainProduct.objects.filter(is_set=True).exclude(product_id__in=set_pks))
    now = timezone.now()
    for row in stale:
        if logs and row.prime_cost is not None:
            MainProductLog.objects.create(main_product=row, price_type='prime_cost', price=None)
        row.is_set = False
        row.prime_cost = None
        row.price_updated_at = now
    MainProduct.objects.bulk_update(stale, fields=['is_set', 'prime_cost', 'price_updated_at'])
    return len(stale)


def _refresh_costs(set_pks, logs: bool) -> int:
    updated = 0
    for _ in range(MAX_PASSES):
        totals = set_totals_for(set_pks)
        now = timezone.now()
        changed = []
        for row in MainProduct.objects.filter(is_set=True, product_id__in=set_pks):
            cost = set_cost(totals.get(row.product_id))
            if row.prime_cost != cost:
                row.prime_cost = cost
                row.price_updated_at = now
                changed.append(row)
        if not changed:
            break
        MainProduct.objects.bulk_update(changed, fields=['prime_cost', 'price_updated_at'])
        if logs:
            MainProductLog.objects.bulk_create(
                MainProductLog(main_product=row, price_type='prime_cost', price=row.prime_cost)
                for row in changed)
        updated += len(changed)
    return updated


def sync_set_rows(logs: bool = True) -> dict:
    """Создать недостающие строки наборов, снять флаг с бывших, пересчитать себестоимость."""
    set_pks = list(ProductSetItem.objects.values_list('set_product_id', flat=True).distinct())
    created = _create_missing_rows(set_pks)
    retired = _retire_stale_rows(set_pks, logs)
    updated = _refresh_costs(set_pks, logs)
    if created or retired or updated:
        logger.info('set_rows: создано %s, снято %s, себестоимость изменена у %s', created, retired, updated)
    return {'created': created, 'retired': retired, 'updated': updated}
