"""Строка ГП набора: без поставщика, себестоимость и остаток — из комплектующих.

У каждого набора (Product с составом) есть ровно одна такая строка
(MainProduct.is_set). Она ведёт себя как любая строка ГП — цены, наценки,
заявки, выгрузка, основные цены товара, — кроме трёх цифр, которые пишет только
этот модуль, по составу (set_costs.set_totals_for):
- себестоимость — сумма «количество × основная себестоимость»;
- остаток — сколько наборов можно собрать из основных остатков компонентов;
- срок поставки (set_delivery_days) — самый долгий по компонентам.
Отсюда же у виртуального набора — без своих поставщиков — появляются цены и
остаток вообще.

Неполное не пишется. Если хоть у одного компонента нет цены или его нет в
Price Manager, себестоимость строки — пусто, а не сумма остальных: наценка от
неё посчитала бы цену набора без части комплектующих и выдала бы за настоящую.
Пустой источник наценки затем очищает и её цену (clear_unsourced_prices) — как
у любой строки ГП. Так же остаток и срок: пусто, если хоть у одного компонента
их нет.

Вызывается из update_prices (после наценок, которые меняют себестоимость
комплектующих, — поэтому наборы «последние») и после синхронизации наборов;
остаток и срок — ещё и в конце update_stocks (sync_set_stocks), чтобы не ждать
пересчёта цен. Всё — локальная работа с БД, без PIM.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from main_product_manager.models import MainProduct, MainProductLog
from supplier_manager.models import Supplier

from ..models import Product, ProductSetItem
from ..set_costs import set_totals_for

logger = logging.getLogger(__name__)

CENT = Decimal('0.01')
# Набор в наборе: цифры внутреннего набора меняются на первом проходе,
# внешнего — на следующем. Больше пяти уровней вложенности в PIM нет; цикл в
# составе (набор внутри самого себя) не должен крутиться вечно.
MAX_PASSES = 5
NUMBER_MAX_LENGTH = Product._meta.get_field('number').max_length
COST_FIELDS = ['prime_cost', 'price_updated_at']
STOCK_FIELDS = ['stock', 'stock_updated_at', 'set_delivery_days']


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
        .only('pk', 'number', 'name')
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
    """Товар перестал быть набором — его строка переходит к «Своему складу».

    Не удаляется: у неё могут быть наценки, место в заявках. Но себестоимость
    из комплектующих больше не от чего считать — она очищается, иначе застывшая
    сумма выглядела бы введённой руками. Остаток остаётся последним посчитанным
    и дальше правится руками: строки прайса у неё нет, и update_stocks его не
    трогает.

    Туда же, но с ценами как есть, — любая строка без поставщика, которая не
    строка набора: без поставщика бывают только наборы. Такие остаются,
    например, от импорта в админке с пустым поставщиком.
    """
    stale = list(MainProduct.objects.filter(is_set=True).exclude(product_id__in=set_pks))
    strays = list(MainProduct.objects.filter(is_set=False, supplier__isnull=True))
    if not stale and not strays:
        return 0
    own_stock = Supplier.own_stock()
    now = timezone.now()
    for row in stale:
        if logs and row.prime_cost is not None:
            MainProductLog.objects.create(main_product=row, price_type='prime_cost', price=None)
        row.is_set = False
        row.prime_cost = None
        row.set_delivery_days = None
        row.price_updated_at = now
    for row in stale + strays:
        row.supplier = own_stock
    MainProduct.objects.bulk_update(stale, fields=['is_set', 'prime_cost', 'set_delivery_days',
                                                   'price_updated_at'])
    MainProduct.objects.bulk_update(stale + strays, fields=['supplier'])
    return len(stale) + len(strays)


def _refresh(set_pks, logs: bool, costs: bool = True, stocks: bool = True) -> int:
    """Пересчитать у строк наборов себестоимость и/или остаток со сроком.

    Возвращает, сколько раз строки менялись (по всем проходам).
    """
    fields = (COST_FIELDS if costs else []) + (STOCK_FIELDS if stocks else [])
    updated = 0
    for _ in range(MAX_PASSES):
        totals = set_totals_for(set_pks)
        now = timezone.now()
        changed, entries = [], []
        for row in MainProduct.objects.filter(is_set=True, product_id__in=set_pks):
            set_totals = totals.get(row.product_id)
            row_changed = False
            if costs:
                cost = set_cost(set_totals)
                if row.prime_cost != cost:
                    row.prime_cost = cost
                    row.price_updated_at = now
                    entries.append(MainProductLog(main_product=row, price_type='prime_cost', price=cost))
                    row_changed = True
            if stocks:
                stock = set_totals.stock if set_totals else None
                days = set_totals.delivery_days if set_totals else None
                if row.stock != stock:
                    row.stock = stock
                    row.stock_updated_at = now
                    entries.append(MainProductLog(main_product=row, stock=stock))
                    row_changed = True
                if row.set_delivery_days != days:
                    row.set_delivery_days = days
                    row_changed = True
            if row_changed:
                changed.append(row)
        if not changed:
            break
        MainProduct.objects.bulk_update(changed, fields=fields)
        if logs:
            MainProductLog.objects.bulk_create(entries)
        updated += len(changed)
    return updated


def _set_pks() -> list:
    return list(ProductSetItem.objects.order_by().values_list('set_product_id', flat=True).distinct())


def sync_set_stocks(logs: bool = True) -> int:
    """Только остаток и срок строк наборов — после обновления остатков компонентов."""
    return _refresh(_set_pks(), logs, costs=False)


def sync_set_rows(logs: bool = True) -> dict:
    """Создать недостающие строки наборов, перевести бывшие к «Своему складу»,
    пересчитать себестоимость, остаток и срок."""
    set_pks = _set_pks()
    created = _create_missing_rows(set_pks)
    retired = _retire_stale_rows(set_pks, logs)
    updated = _refresh(set_pks, logs)
    if created or retired or updated:
        logger.info('set_rows: создано %s, переведено к «Своему складу» %s, изменено %s',
                    created, retired, updated)
    return {'created': created, 'retired': retired, 'updated': updated}
