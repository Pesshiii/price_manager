from __future__ import annotations

import logging
import time

from pim_api import Entity

from .. import pim_client
from ..models import Brand, Category, Product

logger = logging.getLogger(__name__)


def _fetch_pim_link(pim_id: str) -> dict:
    """Raw GET PriceManagerProduct/{pim_id}. Raises on failure — callers decide how to handle it."""
    return pim_client.site.get(Entity(name='PriceManagerProduct', id=pim_id))


def _fetch_pim_product(product_id: str) -> dict:
    """Raw GET Product/{product_id}. Raises on failure — callers decide how to handle it."""
    return pim_client.site.get(Entity(name='Product', id=product_id))


def _fetch_pim_category(pim_category_id: str) -> dict:
    return pim_client.site.get(Entity(name='Category', id=pim_category_id))


def _ensure_pim_category(pim_category_id: str) -> Category | None:
    """Find or create the local Category matching a PIM category id.

    Walks up `parentsIds[0]` (the immediate parent — the local Category tree only
    supports a single parent) creating any missing ancestors too, so the full
    branch ends up marked in the tree. Returns None if the category can't be
    resolved (PIM error) rather than risk misplacing it under the wrong parent,
    so one bad id in a product's categoriesIds doesn't abort the whole sync.
    """
    if not pim_category_id:
        return None
    category = Category.objects.filter(pim_id=pim_category_id).first()
    if category:
        return category

    try:
        data = _fetch_pim_category(pim_category_id)
    except Exception:
        logger.warning('pim_sync: failed to fetch PIM category %s', pim_category_id, exc_info=True)
        return None

    parent_ids = data.get('parentsIds') or []
    parent = None
    if parent_ids:
        parent = _ensure_pim_category(parent_ids[0])
        if parent is None:
            return None

    category, created = Category.objects.get_or_create(
        parent=parent, name=data.get('name') or pim_category_id,
        defaults={'pim_id': pim_category_id},
    )
    if not created and not category.pim_id:
        category.pim_id = pim_category_id
        category.save(update_fields=['pim_id'])
    return category


def _ensure_pim_brand(data: dict) -> Brand | None:
    """Find or create the Brand matching a PIM Product's brandId/brandName.

    Keyed on brandId, never on the name: PIM staff rename brands, and matching
    by name would fork one brand into two on the first rename. The name is kept
    in sync as a display label only. Mirrors _resolve_manufacturer in
    main_product_manager/utils.py, which does the same against the
    supplier-side Manufacturer this replaces.
    """
    brand_id = data.get('brandId')
    if not brand_id:
        return None
    name = data.get('brandName') or brand_id
    brand, created = Brand.objects.get_or_create(pim_id=brand_id, defaults={'name': name})
    if not created and brand.name != name:
        brand.name = name
        brand.save(update_fields=['name'])
    return brand


def sync_product_from_pim(pim_id: str, data: dict | None = None) -> Product:
    """Persist PIM data onto the local Product whose PriceManagerProduct is `pim_id`.

    pim_id is a PriceManagerProduct id. The local Product is the one already
    holding it; failing that, the Product whose number is the PMP's number
    and which has no pim_id yet adopts it; failing that, a new Product is
    created with both.

    `data` is the PIM Product that PMP points at, fetched through the PMP's
    productId unless given. It supplies name, raw_data and categoriesIds ->
    M2M. number is never taken from it: number is the local sku match key,
    and PIM staff may link the PMP to a Product numbered differently. A PMP
    not linked to a PIM Product yet leaves name/raw_data/categories as they are.

    Lets IntegrityError (a new Product whose number another Product already
    holds under a different pim_id) and any PIM-fetch error propagate — it's
    the caller's job to decide how to surface them. Fetches happen before the
    first write, so a failed fetch leaves no half-made row behind.
    """
    link = None
    product = Product.objects.filter(pim_id=pim_id).first()
    if product is None:
        link = _fetch_pim_link(pim_id)
        # `or None`, not `or ''`: number is unique, and Postgres treats NULLs
        # as distinct in a unique index but '' as equal.
        number = link.get('number') or None
        product = (
            Product.objects.filter(number=number, pim_id__isnull=True).first() if number else None
        ) or Product(number=number)
        product.pim_id = pim_id
    if data is None:
        if link is None:
            link = _fetch_pim_link(pim_id)
        product_id = link.get('productId')
        data = _fetch_pim_product(product_id) if product_id else None
    if data is None:
        product.save()
        return product

    product.name = data.get('name') or None
    product.raw_data = data
    product.brand = _ensure_pim_brand(data)

    category_ids = data.get('categoriesIds') or []
    categories = [c for c in (_ensure_pim_category(cid) for cid in category_ids) if c]
    product.save()
    product.categories.set(categories)
    # После save(), а не до: rebuild_search_vector() делает update() по pk, и до
    # первого сохранения у новой строки pk ещё нет. Вектор собирается из
    # raw_data, которые мы только что записали, — в PIM он не ходит.
    product.rebuild_search_vector()
    return product


def unsynced_products(refresh: bool = False):
    """Product-ы, которым нужен контент из PIM.

    Синхронизировать можно только строку, у которой уже есть pim_id: он и есть
    тот PriceManagerProduct, через который мы ходим за товаром. Заготовки без
    pim_id — работа reindex_pim_ids, не наша, и порядок здесь жёсткий:

        reindex_pim_ids (проставляет pim_id) -> этот бэкфилл -> вектор

    Признак «ни разу не синхронизировали» — пустой raw_data. Миграции 0005/0007
    оставляют заготовки именно такими: pim_id есть, а name, категории, бренд и
    вектор пустые.
    """
    queryset = Product.objects.filter(pim_id__isnull=False)
    return queryset if refresh else queryset.filter(raw_data={})


def iter_unsynced_product_pk_batches(batch_size: int = 500, refresh: bool = False):
    """pk-шки под бэкфилл, партиями. Порядок по pk — чтобы партии не пересекались."""
    pks = list(unsynced_products(refresh=refresh).order_by('pk').values_list('pk', flat=True))
    for start in range(0, len(pks), batch_size):
        yield pks[start:start + batch_size]


def sync_products(pks: list[int], delay: float = 0.5) -> int:
    """Синхронизирует партию Product-ов, возвращает число успешных.

    Ошибка на одном товаре не роняет партию: PIM отвечает по товару за раз, и
    один 404 или таймаут не повод потерять остальные 499. Та же логика, что у
    _ensure_pim_category с битым id категории. Сбойные строки останутся с
    пустым raw_data и попадут в следующий прогон — бэкфилл идемпотентен.
    """
    synced = 0
    failed = 0
    for pim_id in (
        Product.objects.filter(pk__in=pks)
        .exclude(pim_id__isnull=True)
        .values_list('pim_id', flat=True)
    ):
        try:
            sync_product_from_pim(pim_id)
            synced += 1
        except Exception:
            failed += 1
            logger.warning('pim_sync: не удалось синхронизировать PMP %s', pim_id, exc_info=True)
        if delay:
            time.sleep(delay)
    logger.info('pim_sync: партия завершена — синхронизировано %s, с ошибкой %s', synced, failed)
    return synced
