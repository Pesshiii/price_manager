"""Расчёт цен товаров по наценкам и отправка их в PIM.

Конвейер (tasks.update_product_prices):

    recalculate_base_prices   основные цены Product из строк поставщиков
    calculate_product_prices  наценки -> ProductPrice
    push_prices_to_pim        изменившиеся цены -> PriceManagerProduct в PIM

Первые два шага локальные и идут в одной транзакции; третий ходит в сеть и
рассылается после коммита отдельной задачей.
"""
import logging
import time

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from product.filters import category_with_descendants
from product.models import Product

from .models import SOURCE_PRICES, ProductPrice, ProductPriceRule, ProductPriceType

logger = logging.getLogger(__name__)

PIM_LINK_ENTITY = 'PriceManagerProduct'


# --- наценки ---------------------------------------------------------------

def rule_products(rule):
    """Товары, которые правило отбирает, — [(pk, цена-источник), …].

    У фиксированной цены источника нет, и диапазон цены к ней не применяется.
    У остальных товары без цены-источника (NULL или 0) не отбираются вовсе:
    такое правило не должно «занимать» товар, который может посчитать
    следующее по приоритету.
    """
    queryset = Product.objects.all()
    categories = list(rule.categories.all())
    if categories:
        queryset = queryset.filter(categories__in=category_with_descendants(categories))
    brand_ids = list(rule.brands.values_list('pk', flat=True))
    if brand_ids:
        queryset = queryset.filter(brand_id__in=brand_ids)
    if rule.is_fixed:
        return [(pk, None) for pk in queryset.values_list('pk', flat=True).distinct()]
    source = rule.source
    queryset = queryset.filter(**{f'{source}__isnull': False}).exclude(**{source: 0})
    if rule.price_from is not None:
        queryset = queryset.filter(**{f'{source}__gte': rule.price_from})
    if rule.price_to is not None:
        queryset = queryset.filter(**{f'{source}__lte': rule.price_to})
    return list(queryset.values_list('pk', source).distinct())


def calculate_product_prices(now=None) -> int:
    """Пересчитывает все ProductPrice; возвращает число созданных, изменённых и удалённых.

    По каждому типу цены правила идут по приоритету, и товар достаётся
    первому подошедшему. Цена, у которой не осталось правила (правило
    выключили, товар ушёл из категории, пропала цена-источник), удаляется —
    старая цена не должна висеть как действующая.
    """
    now = now or timezone.now()
    rules = list(
        ProductPriceRule.objects.in_effect(now)
        .select_related('price_type').order_by('priority', 'pk')
    )
    touched = 0
    for price_type in ProductPriceType.objects.all():
        claimed = {}
        for rule in (rule for rule in rules if rule.price_type_id == price_type.pk):
            for pk, source_value in rule_products(rule):
                if pk in claimed:
                    continue
                value = rule.compute(source_value)
                if value is not None:
                    claimed[pk] = (value, source_value, rule.pk)
        touched += _store(price_type, claimed, now)
    return touched


def _store(price_type, claimed, now) -> int:
    existing = {
        price.product_id: price
        for price in ProductPrice.objects.filter(price_type=price_type)
    }
    create, update = [], []
    for pk, (value, source_value, rule_id) in claimed.items():
        price = existing.get(pk)
        if price is None:
            create.append(ProductPrice(product_id=pk, price_type=price_type, value=value,
                                       source_value=source_value, rule_id=rule_id, calculated_at=now))
        elif (price.value, price.source_value, price.rule_id) != (value, source_value, rule_id):
            price.value, price.source_value, price.rule_id = value, source_value, rule_id
            price.calculated_at = now
            update.append(price)
    stale = [price.pk for pk, price in existing.items() if pk not in claimed]
    ProductPrice.objects.bulk_create(create, batch_size=2000)
    ProductPrice.objects.bulk_update(update, ['value', 'source_value', 'rule', 'calculated_at'], batch_size=2000)
    if stale:
        ProductPrice.objects.filter(pk__in=stale).delete()
    return len(create) + len(update) + len(stale)


# --- PIM -------------------------------------------------------------------

def base_price_pim_fields() -> dict:
    """{поле Product: поле PriceManagerProduct} для основных цен — из настроек.

    PIM_PRODUCT_PRICE_FIELDS (settings/project.py). Поля в PIM заводит
    PIM-администратор; пока сопоставление пустое, основные цены не уходят.
    """
    mapping = getattr(settings, 'PIM_PRODUCT_PRICE_FIELDS', None) or {}
    return {field: pim_field for field, pim_field in mapping.items() if field in SOURCE_PRICES and pim_field}


def pim_price_payloads(products) -> dict:
    """{pk: {поле PIM: значение}} — что должно лежать в PIM у каждого товара.

    Пустая цена уходит как null: цена, которой больше нет, должна исчезнуть и
    в PIM, а не остаться последним отправленным значением.
    """
    base_fields = base_price_pim_fields()
    types = {pt.pk: pt.pim_field for pt in ProductPriceType.objects.exclude(pim_field='')}
    payloads = {}
    for product in products:
        payload = {pim_field: _json_number(getattr(product, field)) for field, pim_field in base_fields.items()}
        for pim_field in types.values():
            payload[pim_field] = None
        for price in product.prices.all():
            if price.price_type_id in types:
                payload[types[price.price_type_id]] = _json_number(price.value)
        payloads[product.pk] = payload
    return payloads


def _json_number(value):
    return None if value is None else float(value)


def pim_push_enabled() -> bool:
    return bool(base_price_pim_fields()) or ProductPriceType.objects.exclude(pim_field='').exists()


def iter_pim_push_batches(batch_size: int = 500):
    """pk товаров со связью в PIM, партиями. Сравнение со снимком — уже в партии."""
    pks = list(Product.objects.filter(pim_id__isnull=False).order_by('pk').values_list('pk', flat=True))
    for start in range(0, len(pks), batch_size):
        yield pks[start:start + batch_size]


def push_prices_to_pim(pks, delay: float = 0.5) -> int:
    """Отправляет изменившиеся цены товаров pks в их PriceManagerProduct.

    Только товары, у которых то, что должно лежать в PIM, отличается от
    снимка pim_pushed_prices. Запись — upsertAsync по id связи, тем же путём,
    что reindex_pim_ids; снимок обновляется только у принятых PIM записей, так
    что отклонённые уйдут снова в следующий раз. Возвращает число отправленных.
    Идемпотентно — задача идёт с atomic=False.
    """
    from main_product_manager.utils import PimScanError, _record_pim_error, _upsert_async, site

    if not pim_push_enabled():
        return 0
    products = list(
        Product.objects.filter(pk__in=pks, pim_id__isnull=False).prefetch_related('prices').order_by('pk'))
    payloads = pim_price_payloads(products)
    targets = [p for p in products if payloads[p.pk] and payloads[p.pk] != p.pim_pushed_prices]
    if not targets:
        return 0
    # id + оба уникальных поля связи: по ним PIM сопоставляет upsert (см.
    # main_product_manager.utils._push_pim_links), и запись обновляется, а не
    # создаётся новая.
    items = [
        {'entity': PIM_LINK_ENTITY,
         'payload': {'id': p.pim_id, 'platformID': str(p.pk),
                     **({'number': p.number} if p.number else {}), **payloads[p.pk]}}
        for p in targets
    ]
    t0 = time.monotonic()
    try:
        results = _upsert_async(site, items)
    except Exception as exc:
        _record_pim_error('push_prices_to_pim', exc, int((time.monotonic() - t0) * 1000))
        raise PimScanError(f'PIM не принял цены партии из {len(targets)} товаров: {exc}') from exc
    time.sleep(delay)
    if not isinstance(results, list) or len(results) != len(targets):
        raise PimScanError(f'PIM вернул {len(results) if isinstance(results, list) else results!r:.200} '
                           f'результатов на {len(targets)} товаров')
    accepted, rejected = [], []
    for product, result in zip(targets, results):
        if isinstance(result, dict) and result.get('status') != 'Failed' and result.get('id'):
            product.pim_pushed_prices = payloads[product.pk]
            accepted.append(product)
        else:
            rejected.append(result)
    Product.objects.bulk_update(accepted, ['pim_pushed_prices'])
    if rejected:
        error = PimScanError(f'PIM отклонил цены {len(rejected)} из {len(targets)} товаров; '
                             f'первый ответ: {rejected[0]!r:.500}')
        _record_pim_error('push_prices_to_pim', error, int((time.monotonic() - t0) * 1000))
        raise error
    return len(accepted)
