from __future__ import annotations

import logging
import time

from pim_api import Entity, EntityList, Where, fetch_list

from .. import pim_client
from ..models import Brand, Category, Product

# Поля товара PIM, которые нужны странице. Без явного select PIM не отдаёт ни
# categoriesIds, ни description — в списочном режиме они просто отсутствуют в
# ответе, молча, и зеркало наполняется товарами без категорий.
PRODUCT_SELECT = [
    'id', 'number', 'name', 'brandId', 'brandName',
    'description', 'longDescription', 'tag', 'categoriesIds',
]

# Сколько раз пытаться взять одну страницу каталога, прежде чем сдаться.
_PAGE_RETRIES = 4

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


def sync_category_tree_from_pim(page_size: int = 200) -> dict:
    """Приводит локальное дерево категорий в соответствие с PIM целиком.

    Существует отдельно от _ensure_pim_category, потому что тот вызывается
    только когда на категорию сослался синхронизируемый товар, и НИКОГДА не
    обновляет уже найденную строку. Переименование категории в PIM так не
    доедет до зеркала никогда, а смена родителя тихо уводит товары в чужую
    ветку дерева, по которой categories_method потом разворачивает выбор.
    Пока зеркало было списком фасетов, это была косметика; теперь по нему
    фильтруют, поэтому расхождение надо чинить целенаправленно.

    Порядок вставки — от корней вниз: родитель обязан существовать раньше
    ребёнка, иначе MPTT некуда его подвесить.
    """
    listing = fetch_list(
        pim_client.site,
        EntityList(name='Category', select=['id', 'name', 'parentId']),
        page_size=page_size,
    )
    rows = {row['id']: row for row in listing.items if row.get('id')}

    ordered, seen = [], set()

    def visit(pim_id):
        if pim_id in seen or pim_id not in rows:
            return
        seen.add(pim_id)
        parent_id = rows[pim_id].get('parentId')
        if parent_id:
            visit(parent_id)
        ordered.append(pim_id)

    for pim_id in rows:
        visit(pim_id)

    local = {c.pim_id: c for c in Category.objects.exclude(pim_id__isnull=True)}
    created = renamed = reparented = 0

    for pim_id in ordered:
        row = rows[pim_id]
        name = row.get('name') or pim_id
        parent = local.get(row.get('parentId'))
        category = local.get(pim_id)

        if category is None:
            category = Category.objects.create(pim_id=pim_id, name=name, parent=parent)
            local[pim_id] = category
            created += 1
            continue

        if category.name != name:
            category.name = name
            category.save(update_fields=['name'])
            renamed += 1
        if category.parent_id != (parent.pk if parent else None):
            # move_to, а не присваивание parent: MPTT держит lft/rght/level, и
            # обычный save() их не пересчитает — дерево останется битым.
            category.move_to(parent, position='last-child')
            reparented += 1

    result = {
        'total': listing.total, 'created': created,
        'renamed': renamed, 'reparented': reparented,
    }
    logger.info('pim_sync: дерево категорий синхронизировано — %s', result)
    return result


def load_products_by_number(page_size: int = 1000, limit: int | None = None,
                            start_offset: int = 0, progress=None) -> dict:
    """Наполняет зеркало содержимым PIM, сопоставляя по number.

    Идёт постранично по товарам PIM и раскладывает их на локальные Product с
    тем же number. Это НЕ замена backfill_products_from_pim: тот ходит за
    каждым товаром через его PriceManagerProduct и нужен в бою, а этот
    вытаскивает каталог оптом и ничего в PIM не пишет. На 178k товаров разница
    между 179 запросами и 300 тысячами.

    Сопоставление по number законно: number локального Product — это
    MainProduct.sku, а привязка к PIM и строится по равенству sku и number.
    """
    by_number = {
        number: pk for pk, number in
        Product.objects.exclude(number__isnull=True).values_list('pk', 'number')
    }
    categories = {c.pim_id: c.pk for c in Category.objects.exclude(pim_id__isnull=True)}
    brands = {b.pim_id: b.pk for b in Brand.objects.all()}
    through = Product.categories.through

    matched = skipped = 0
    # Смещение, с которого продолжаем. Прогон по 178 тыс. товаров идёт минуты, и
    # если его прервали, начинать заново — это заново платить за уже пройденные
    # страницы. Перекрытие безвредно: раскладка идемпотентна.
    offset = start_offset
    total = 0

    while True:
        # Ретраи с отступом: прогон идёт минуты и держит соединение к PIM всё
        # это время, поэтому разрыв — не исключение, а ожидаемое событие.
        # Наблюдалось: httpx.ConnectError [SSL: UNEXPECTED_EOF_WHILE_READING]
        # на середине прохода. Без ретрая одна такая икота выбрасывает весь
        # прогон, включая уже разобранные страницы.
        response = None
        for attempt in range(_PAGE_RETRIES):
            try:
                response = pim_client.site.get(
                    EntityList(name='Product', select=PRODUCT_SELECT,
                               offset=offset, maxSize=page_size),
                    timeout=120,
                )
                break
            except Exception:
                if attempt == _PAGE_RETRIES - 1:
                    logger.error('pim_sync: страница offset=%s не далась за %s попыток',
                                 offset, _PAGE_RETRIES, exc_info=True)
                    raise
                wait = 2 ** attempt
                logger.warning('pim_sync: сбой на offset=%s, повтор через %sс', offset, wait,
                               exc_info=True)
                time.sleep(wait)

        total = int(response.get('total') or 0)
        batch = response.get('list') or []
        if not batch:
            break

        updates, links = [], []
        for row in batch:
            pk = by_number.get(row.get('number'))
            if pk is None:
                skipped += 1
                continue

            brand_pk = None
            brand_id = row.get('brandId')
            if brand_id:
                if brand_id not in brands:
                    brand = Brand.objects.create(
                        pim_id=brand_id, name=row.get('brandName') or brand_id)
                    brands[brand_id] = brand.pk
                brand_pk = brands[brand_id]

            updates.append(Product(pk=pk, name=row.get('name') or None,
                                   raw_data=row, brand_id=brand_pk))
            for cid in (row.get('categoriesIds') or []):
                if cid in categories:
                    links.append(through(product_id=pk, category_id=categories[cid]))
            matched += 1

        if updates:
            Product.objects.bulk_update(updates, ['name', 'raw_data', 'brand'], batch_size=500)
        if links:
            through.objects.bulk_create(links, ignore_conflicts=True, batch_size=1000)

        offset += len(batch)
        if progress:
            progress(offset, total, matched)
        if limit is not None and offset >= limit:
            break
        if offset >= total:
            break

    result = {'pim_total': total, 'scanned': offset, 'matched': matched, 'skipped': skipped}
    logger.info('pim_sync: контент загружен — %s', result)
    return result
