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
from django.db.models import Exists, OuterRef
from django.utils import timezone

from product.filters import category_with_descendants
from product.models import Product, ProductSetItem

from .models import SOURCE_PRICES, ProductPrice, ProductPriceRule, ProductPriceType

logger = logging.getLogger(__name__)

PIM_LINK_ENTITY = 'PriceManagerProduct'


# --- наценки ---------------------------------------------------------------

def scope_queryset(rule, categories=None, brand_ids=None, product_ids=None):
    """Товары, подходящие под условия правила, — без учёта цены-источника.

    categories/brand_ids/product_ids — для несохранённого правила из формы
    (предпросмотр). None — взять у самого правила; у несохранённого M2M нет,
    и не переданное условие для него просто пустое.
    """
    def own(relation):
        return list(getattr(rule, relation).all()) if rule.pk else []

    queryset = Product.objects.all()
    if product_ids is None:
        product_ids = [product.pk for product in own('products')]
    if product_ids:
        queryset = queryset.filter(pk__in=product_ids)
    categories = own('categories') if categories is None else list(categories)
    if categories:
        queryset = queryset.filter(
            pk__in=Product.categories.through.objects
            .filter(category_id__in=category_with_descendants(categories)).values('product_id'))
    if brand_ids is None:
        brand_ids = [brand.pk for brand in own('brands')]
    if brand_ids:
        queryset = queryset.filter(brand_id__in=brand_ids)
    if rule.only_sets:
        queryset = queryset.filter(Exists(ProductSetItem.objects.filter(set_product=OuterRef('pk'))))
    return queryset


def priced_queryset(rule, scope):
    """Из товаров scope — те, что правило посчитает: с ценой-источником в диапазоне.

    У фиксированной цены источника нет, и диапазон к ней не применяется. У
    остальных товары без цены-источника (NULL или 0) не отбираются вовсе:
    такое правило не должно «занимать» товар, который может посчитать
    следующее по приоритету.
    """
    if rule.is_fixed:
        return scope
    source = rule.source
    queryset = scope.filter(**{f'{source}__isnull': False}).exclude(**{source: 0})
    if rule.price_from is not None:
        queryset = queryset.filter(**{f'{source}__gte': rule.price_from})
    if rule.price_to is not None:
        queryset = queryset.filter(**{f'{source}__lte': rule.price_to})
    return queryset


def rule_products(rule, categories=None, brand_ids=None, product_ids=None):
    """Товары, которые правило считает, — [(pk, цена-источник), …]."""
    queryset = priced_queryset(rule, scope_queryset(rule, categories, brand_ids, product_ids))
    if rule.is_fixed:
        return [(pk, None) for pk in queryset.values_list('pk', flat=True)]
    return list(queryset.values_list('pk', rule.source))


def product_price_rows(product) -> list[dict]:
    """Цены одного товара для карточки: по каждому типу цены — расчётная цена
    и наценки, которые подходят товару сейчас, в порядке приоритета. Первая из
    них — действующая (та, что дала цену при пересчёте), остальные перекрыты.

    Отбор проверяется запросом на правило — правил десятки, а товар один.
    """
    prices = {price.price_type_id: price
              for price in ProductPrice.objects.filter(product=product).select_related('rule')}
    rules = list(ProductPriceRule.objects.in_effect().select_related('price_type')
                 .prefetch_related('categories', 'brands', 'products').order_by('priority', 'pk'))
    matching = {}
    for rule in rules:
        if priced_queryset(rule, scope_queryset(rule)).filter(pk=product.pk).exists():
            matching.setdefault(rule.price_type_id, []).append(rule)
    return [
        {'type': price_type, 'price': prices.get(price_type.pk), 'rules': matching.get(price_type.pk, [])}
        for price_type in ProductPriceType.objects.all()
    ]


def outranks(other, rule) -> bool:
    """Действует ли other раньше rule на общих товарах: меньший приоритет, при
    равном — созданное раньше. Несохранённое правило проигрывает равным."""
    if other.priority != rule.priority:
        return other.priority < rule.priority
    return rule.pk is None or other.pk < rule.pk


def preview_rule(rule, categories=None, brand_ids=None, product_ids=None, examples=8) -> dict:
    """Что сделает правило, если его сохранить и пересчитать цены.

    Ответ на «на что оно влияет»: сколько товаров подходит под условия, у
    скольких из них нет цены-источника, сколько заберут более приоритетные
    правила того же типа, у скольких цена появится или изменится и у каких
    правил правило заберёт товары, — и несколько примеров «было → станет».
    """
    scope = scope_queryset(rule, categories, brand_ids, product_ids)
    in_scope = scope.count()
    matched = dict(rule_products(rule, categories, brand_ids, product_ids))

    taken_by = []
    effective = set(matched)
    if rule.price_type_id:
        others = (ProductPriceRule.objects.in_effect().filter(price_type_id=rule.price_type_id)
                  .exclude(pk=rule.pk).order_by('priority', 'pk'))
        for other in others:
            if not outranks(other, rule) or not effective:
                continue
            overlap = effective & {pk for pk, _ in rule_products(other)}
            if overlap:
                taken_by.append((other, len(overlap)))
                effective -= overlap

    current = {}
    if rule.price_type_id:
        current = {
            product_id: (value, rule_id)
            for product_id, value, rule_id in ProductPrice.objects.filter(
                price_type_id=rule.price_type_id).values_list('product_id', 'value', 'rule_id')
        }
    new_values = {}
    for pk in effective:
        value = rule.compute(matched[pk])
        if value is not None:
            new_values[pk] = value
    appear = sum(1 for pk in new_values if pk not in current)
    change = sum(1 for pk, value in new_values.items() if pk in current and current[pk][0] != value)
    displaced = {}
    for pk in new_values:
        rule_id = current.get(pk, (None, None))[1]
        if pk in current and rule_id != rule.pk:
            displaced[rule_id] = displaced.get(rule_id, 0) + 1
    displaced_rules = {r.pk: r for r in ProductPriceRule.objects.filter(pk__in=[k for k in displaced if k])}
    sample = list(
        Product.objects.filter(pk__in=list(new_values)[:500]).order_by('name', 'pk')[:examples]
    )
    return {
        'in_scope': in_scope,
        'no_source': in_scope - len(matched) if not rule.is_fixed else 0,
        'matched': len(matched),
        'taken_by': taken_by,
        'effective': len(new_values),
        'appear': appear,
        'change': change,
        'same': len(new_values) - appear - change,
        'displaced': [(displaced_rules.get(rule_id), count) for rule_id, count in displaced.items()],
        'examples': [
            {
                'product': product,
                'source': matched[product.pk],
                'value': new_values[product.pk],
                'current': current.get(product.pk, (None, None))[0],
            }
            for product in sample
        ],
        'is_active': rule.is_active,
        'in_window': _in_window(rule),
    }


def _in_window(rule, now=None) -> bool:
    now = now or timezone.now()
    return (rule.date_from is None or rule.date_from <= now) and (rule.date_to is None or rule.date_to >= now)


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
