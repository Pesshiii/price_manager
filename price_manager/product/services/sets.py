"""Наборы: зеркало ассоциации PIM «Состав набора» (code SET_ASSOCIATION_CODE).

Набор в PIM — обычный товар, связанный с компонентами ассоциацией, у каждой
связи есть amount. Набор бывает и собранным на складе — тогда у него есть
свои MainProduct и свой Product с PMP, — и чисто виртуальным, без
поставщиков. Второго существующий конвейер не видит: reindex_pim_ids толкает
в PIM только Product с MainProduct, а бэкфилл контента берёт только Product с
pim_id. Отсюда отдельная синхронизация, которая делает всё сама: находит (или,
для виртуального, заводит) Product набора, пишет на него контент PIM и
полностью пересобирает его состав.

Ассоциация двусторонняя: PIM сам заводит обратную «Входит в набор», и у той
amount пустой. Читаем только прямую — количество живёт там.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from django.db import transaction
from django.db.models import Exists, OuterRef

from main_product_manager.models import MainProduct
from pim_api import EntityList, Where, fetch_list

from .. import pim_client
from ..models import Product, ProductSetItem
from .pim_sync import _fetch_pim_product, apply_pim_product

SET_ASSOCIATION_CODE = 'set_components'

# Сколько id класть в один where[in]: список уходит в query string, и на
# сотнях id URL упрётся в лимит прокси раньше, чем в лимит PIM.
_IN_CHUNK = 100

logger = logging.getLogger(__name__)


def _chunks(values: list[str], size: int = _IN_CHUNK):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _fetch_all(query: EntityList) -> list[dict]:
    """fetch_list, который не терпит обрезанного ответа.

    Неполный список связей здесь хуже ошибки: синхронизация пересобирает
    состав целиком, и недочитанная страница молча укоротила бы наборы.
    """
    result = fetch_list(pim_client.site, query)
    if result.truncated:
        raise RuntimeError(
            f'sets: PIM отдал {len(result.items)} из {result.total} строк {query.name} — '
            'список неполный, синхронизация остановлена')
    return result.items


def _fetch_set_association_id() -> str | None:
    rows = _fetch_all(EntityList(
        name='Association', select=['id', 'code'],
        where=[Where(attribute='code', type='equals', value=SET_ASSOCIATION_CODE)],
    ))
    return rows[0]['id'] if rows else None


def _fetch_set_links(association_id: str) -> list[dict]:
    """Все прямые связи «набор → компонент»."""
    return _fetch_all(EntityList(
        name='AssociatedProduct',
        select=['associatingItemId', 'associatedItemId', 'amount', 'sorting'],
        where=[Where(attribute='associationId', type='equals', value=association_id)],
    ))


def _fetch_pim_products_brief(product_ids: list[str]) -> dict[str, dict]:
    """id товара PIM -> {number, name}. Для снимка компонента в составе."""
    found = {}
    for chunk in _chunks(product_ids):
        for row in _fetch_all(EntityList(
            name='Product', select=['id', 'number', 'name'],
            where=[Where(attribute='id', type='in', value=chunk)],
        )):
            found[row['id']] = row
    return found


def _fetch_platform_ids(product_ids: list[str]) -> dict[str, list[int]]:
    """id товара PIM -> pk наших Product, привязанных к нему через PriceManagerProduct.

    platformID у PMP — это наш Product.pk. Товаров на одном товаре PIM может
    быть несколько, поэтому список.
    """
    found = defaultdict(list)
    for chunk in _chunks(product_ids):
        for row in _fetch_all(EntityList(
            name='PriceManagerProduct', select=['productId', 'platformID'],
            where=[Where(attribute='productId', type='in', value=chunk)],
        )):
            try:
                pk = int(row['platformID'])
            except (KeyError, TypeError, ValueError):
                continue
            found[row['productId']].append(pk)
    return found


def _candidates(platform_pks: list[int], number: str | None) -> list[Product]:
    """Наши Product, которые могут быть этим товаром PIM.

    Связь через PMP — главный признак, номер — запасной: у товара, которому
    reindex_pim_ids ещё не завёл PMP, другого способа нет. iexact, потому что
    уникальность number нечувствительна к регистру (Lower('number')).
    """
    by_pk = Product.objects.filter(pk__in=platform_pks) if platform_pks else Product.objects.none()
    by_number = Product.objects.filter(number__iexact=number) if number else Product.objects.none()
    return list((by_pk | by_number).distinct().annotate(
        has_stock=Exists(MainProduct.objects.filter(product=OuterRef('pk'), stock__gt=0)),
        has_suppliers=Exists(MainProduct.objects.filter(product=OuterRef('pk'))),
    ))


def _pick(candidates: list[Product], platform_pks: list[int]) -> Product:
    """Из нескольких кандидатов — привязанный через PMP, затем с остатком,
    затем с поставщиками, затем самый старый."""
    linked = set(platform_pks)
    return min(candidates, key=lambda p: (
        p.pk not in linked, not p.has_stock, not p.has_suppliers, p.pk))


def _resolve(pim_product_id: str, number: str | None, platform_ids: dict, what: str) -> Product | None:
    platform_pks = platform_ids.get(pim_product_id, [])
    candidates = _candidates(platform_pks, number)
    if not candidates:
        return None
    chosen = _pick(candidates, platform_pks)
    if len(candidates) > 1:
        logger.warning(
            'sets: %s %s (%s) — несколько наших товаров %s, взят %s',
            what, pim_product_id, number, [p.pk for p in candidates], chosen.pk)
    return chosen


def _resolve_set_product(pim_product_id: str, data: dict, platform_ids: dict) -> tuple[Product | None, bool]:
    """Product набора: найденный или новый. Новый — без pim_id: PMP ему никто
    не заведёт, и он ему не нужен, контент приходит отсюда же.

    Без артикула и без PMP нового не заводим (None): следующий прогон такой
    набор не узнал бы и завёл бы ещё один.
    """
    number = data.get('number') or None
    product = _resolve(pim_product_id, number, platform_ids, 'набор')
    if product is not None:
        return product, False
    if number is None:
        return None, False
    return Product(number=number), True


def _parse_amount(link: dict) -> int | None:
    """amount в PIM — целое и может быть пустым. Пустое — одна штука; ноль и
    меньше — ошибка заполнения, такую позицию пропускаем."""
    amount = link.get('amount')
    if amount is None:
        return 1
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def sync_product_sets() -> dict:
    """Приводит наборы и их состав в соответствие с PIM целиком.

    Идемпотентна: состав каждого набора пересобирается заново в своей
    транзакции, так что прерванный прогон просто доделает следующий. Всё,
    что не удалось сопоставить, пишется в лог и пропускается — один битый
    набор не повод не обновить остальные.
    """
    stats = {
        'sets': 0, 'created_sets': 0, 'failed_sets': 0, 'skipped_sets': 0, 'items': 0,
        'unresolved_components': 0, 'skipped_links': 0, 'pruned_sets': 0,
    }

    association_id = _fetch_set_association_id()
    if association_id is None:
        logger.error('sets: в PIM нет ассоциации с code=%s — наборы не синхронизированы',
                     SET_ASSOCIATION_CODE)
        return stats

    links_by_set = defaultdict(list)
    for link in _fetch_set_links(association_id):
        set_id, component_id = link.get('associatingItemId'), link.get('associatedItemId')
        if not set_id or not component_id or set_id == component_id:
            stats['skipped_links'] += 1
            continue
        links_by_set[set_id].append(link)

    component_ids = sorted({link['associatedItemId'] for links in links_by_set.values() for link in links})
    briefs = _fetch_pim_products_brief(component_ids)
    platform_ids = _fetch_platform_ids(sorted(set(component_ids) | set(links_by_set)))

    synced_set_pks = set()
    for set_id, links in links_by_set.items():
        try:
            data = _fetch_pim_product(set_id)
        except Exception:
            stats['failed_sets'] += 1
            logger.warning('sets: не удалось получить набор %s из PIM', set_id, exc_info=True)
            continue

        product, created = _resolve_set_product(set_id, data, platform_ids)
        if product is None:
            # Не failed_sets: такой набор у нас не заводился ни разу, и
            # чистку исчезнувших он не должен блокировать.
            stats['skipped_sets'] += 1
            logger.warning('sets: у набора %s в PIM нет артикула — пропущен', set_id)
            continue
        if product.pk in synced_set_pks:
            stats['failed_sets'] += 1
            logger.warning('sets: набор %s сопоставился с Product %s, который уже занят '
                           'другим набором этого прогона — пропущен', set_id, product.pk)
            continue

        items, seen = [], set()
        for link in sorted(links, key=lambda row: row.get('sorting') or 0):
            component_id = link['associatedItemId']
            amount = _parse_amount(link)
            if amount is None or component_id in seen:
                stats['skipped_links'] += 1
                logger.warning('sets: набор %s, компонент %s — пропущен (amount=%r%s)',
                               set_id, component_id, link.get('amount'),
                               ', повтор' if component_id in seen else '')
                continue
            seen.add(component_id)
            brief = briefs.get(component_id, {})
            number = brief.get('number') or None
            component = _resolve(component_id, number, platform_ids, 'компонент')
            if component is None:
                stats['unresolved_components'] += 1
                logger.warning('sets: набор %s (%s) — компонента %s (%s) нет в Price Manager',
                               set_id, data.get('number'), component_id, number)
            items.append(ProductSetItem(
                component=component,
                component_pim_product_id=component_id,
                component_number=number or '',
                component_name=brief.get('name') or '',
                amount=amount,
                sorting=link.get('sorting') or 0,
            ))

        with transaction.atomic():
            apply_pim_product(product, data)
            if not product.name:
                # У виртуального набора display_name откатываться не на что:
                # ни поставщиков, ни PMP. Без названия — голый артикул.
                product.name = product.number
                product.save(update_fields=['name'])
            product.set_items.all().delete()
            for item in items:
                item.set_product = product
            ProductSetItem.objects.bulk_create(items)

        synced_set_pks.add(product.pk)
        stats['sets'] += 1
        stats['created_sets'] += created
        stats['items'] += len(items)

    if stats['failed_sets']:
        # Набор, который не удалось прочитать, неотличим здесь от удалённого
        # из PIM. Лучше оставить устаревший состав до следующего прогона, чем
        # стереть живой из-за одного таймаута.
        logger.warning('sets: %s наборов не синхронизированы — чистка исчезнувших пропущена',
                       stats['failed_sets'])
    else:
        stale = (Product.objects.filter(set_items__isnull=False)
                 .exclude(pk__in=synced_set_pks).distinct())
        stale_pks = list(stale.values_list('pk', flat=True))
        if stale_pks:
            ProductSetItem.objects.filter(set_product_id__in=stale_pks).delete()
            stats['pruned_sets'] = len(stale_pks)
            logger.warning('sets: наборов больше нет в PIM, состав очищен: %s', stale_pks)

    logger.info('sets: синхронизация завершена — %s', stats)
    return stats
