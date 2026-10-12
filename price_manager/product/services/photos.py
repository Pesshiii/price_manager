"""Фото товаров из PIM: все файлы товара (ProductFile) и их публичные ссылки (Sharing).

В raw_data товара PIM кладёт только mainImageId, поэтому всё остальное
зеркалируется в ProductPhoto отдельным ночным проходом
(product.refresh_product_photos). Отрисовка в сеть не ходит: страница берёт
public_url, если он есть, а иначе — наш прокси (pim_image_url), как было до
публичных ссылок.

Цена прохода, замеренная на живом PIM 2026-10-12 (maxSize=1000): ProductFile —
466 тыс. строк, ~1,5 с на страницу, ~12 минут целиком; Sharing — 293 тыс.
строк, ~8,4 с на страницу (PIM считает в каждой строке пути превью), ~41
минута целиком. Поэтому ProductFile сканируется каждую ночь полностью — иначе
не узнать об отвязанных фото, — а Sharing ночью только инкрементально: новые
ссылки (createdAt) плюс ссылки на файлы, впервые появившиеся у товаров.
Полный проход Sharing (full=True) — раз в неделю: он же стирает ссылки,
которые PIM отозвал. До него отозванную ссылку подменяет на прокси сам
браузер (static/js/pim-photo-fallback.js).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import transaction
from django.db.models.fields.json import KT
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from pim_api import Asc, EntityList, Ordering, Where

from .. import pim_client
from ..models import Product, ProductPhoto

logger = logging.getLogger(__name__)

TASK_NAME = 'product.refresh_product_photos'

PAGE_SIZE = 1000
# Отбор fileId in [...] уходит в строку запроса; на 200 uuid PIM отвечает
# 414 URI Too Long, 100 проходят (см. pim_api.FlatEntityList).
FILE_ID_CHUNK = 100
WRITE_CHUNK = 2000
# createdAt в PIM и started_at прошлого прогона могут жить в разных часовых
# поясах, а ссылку могли создать, пока прошлый прогон шёл. Сутки нахлёста
# покрывают и то и другое; повторно найденная ссылка ничего не меняет.
SHARING_OVERLAP = timedelta(days=1)

# В ProductFile лежат не только фото — у товара бывают инструкции и
# сертификаты. Тип файла список не отдаёт, поэтому отбор — по расширению
# имени: карусель из PDF показала бы битые картинки, а прокси их и не отдаёт
# (fetch_pim_image принимает только image/*).
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.svg', '.avif')

PRODUCT_FILE_FIELDS = ['productId', 'fileId', 'fileName', 'isMainImage', 'sorting']
SHARING_FIELDS = ['fileId', 'link', 'active', 'available', 'validTill']


# --- отрисовка ---------------------------------------------------------------

def photo_sources(pim_file_id: str, public_url: str = '') -> dict | None:
    """Адреса одного фото для <img>: src и увеличенный, каждый со своим запасным.

    С публичной ссылкой оба адреса — она (PIM отдаёт по ней оригинал, превью
    у ссылки нет), запасные — наш прокси. Без неё — прокси, запасных нет.
    None — у файла негодный id и показать его нечем.
    """
    from main_product_manager.utils import pim_image_url

    medium = pim_image_url(pim_file_id)
    large = pim_image_url(pim_file_id, 'large')
    if public_url:
        return {'src': public_url, 'fallback': medium or '', 'zoom': public_url, 'zoom_fallback': large or ''}
    if not medium:
        return None
    return {'src': medium, 'fallback': '', 'zoom': large, 'zoom_fallback': ''}


def product_photos(product: Product) -> list[dict]:
    """Фото товара по порядку показа, главное первым.

    Из ProductPhoto (предзагрузите photos, иначе это запрос на товар). Пока
    ночной проход их не завёл — новый товар, — одно главное фото по
    raw_data['mainImageId'] через прокси, как было до ProductPhoto.
    """
    photos = list(product.photos.all()) if product.pk else []
    if photos:
        sources = (photo_sources(photo.pim_file_id, photo.public_url) for photo in photos)
        return [source for source in sources if source]
    data = product.raw_data or {}
    main = photo_sources(data.get('mainImageId') or data.get('imageId'))
    return [main] if main else []


# --- чтение PIM --------------------------------------------------------------

def _iter_pages(name: str, fields: list[str], where: list[Where] | None = None):
    """Все строки списка PIM — страницами по id (keyset), а не по offset.

    Скан ProductFile идёт минуты, и PIM в это время живёт: файлы привязывают
    и отвязывают. Offset после удаления строки сдвигает страницы, и следующая
    строка молча пропускается — товар на сутки потерял бы фото. Отбор
    «id greaterThan последнего» так не сдвигается: удалённая строка просто не
    приходит, новая — приходит в конце (id в PIM — UUIDv7, растут со временем).
    Ошибка PIM поднимается наверх, до какой-либо записи в базу.
    """
    last_id = None
    while True:
        conditions = list(where or [])
        if last_id:
            conditions.append(Where(attribute='id', type='greaterThan', value=last_id))
        page = pim_client.site.get(
            EntityList(name=name, select=['id', *fields], where=conditions or None,
                       ordering=Ordering(sortBy='id', asc=Asc.ASC), maxSize=PAGE_SIZE),
            timeout=120)
        rows = page.get('list') or []
        yield from rows
        if len(rows) < PAGE_SIZE:
            return
        last_id = rows[-1].get('id')
        if not last_id:
            raise RuntimeError(f'photos: PIM отдал строку {name} без id — дальше страницы не взять')


def _is_image(file_name: str | None) -> bool:
    return (file_name or '').lower().endswith(IMAGE_EXTENSIONS)


def _sorting(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _local_products() -> dict[str, list[int]]:
    """Id товара PIM → наши Product на нём (их бывает несколько, см. Product.name)."""
    products = defaultdict(list)
    rows = (Product.objects.annotate(pim_product_id=KT('raw_data__id'))
            .filter(pim_product_id__isnull=False).exclude(pim_product_id='')
            .values_list('pk', 'pim_product_id'))
    for pk, pim_product_id in rows.iterator(chunk_size=5000):
        products[pim_product_id].append(pk)
    return products


def _desired_photos(products: dict[str, list[int]]) -> dict[int, list[tuple[str, bool]]]:
    """pk товара → [(id файла, главное)] в порядке показа — из полного скана ProductFile."""
    files = defaultdict(list)
    for row in _iter_pages('ProductFile', PRODUCT_FILE_FIELDS):
        product_id, file_id = row.get('productId'), row.get('fileId')
        if product_id not in products or not file_id or not _is_image(row.get('fileName')):
            continue
        is_main = bool(row.get('isMainImage'))
        files[product_id].append((not is_main, _sorting(row.get('sorting')), row.get('fileName') or '', file_id))

    desired = {}
    for product_id, entries in files.items():
        entries.sort()
        ordered, seen = [], set()
        for not_main, _, _, file_id in entries:
            if file_id not in seen:
                seen.add(file_id)
                ordered.append((file_id, not not_main))
        for pk in products[product_id]:
            desired[pk] = ordered
    return desired


def _as_aware(value: datetime) -> datetime:
    return value if timezone.is_aware(value) else value.replace(tzinfo=dt_timezone.utc)


def _usable_link(row: dict, now: datetime) -> str | None:
    """Ссылка из строки Sharing, если по ней сейчас откроется файл.

    Отсутствие active/available в ответе — «не знаем», а не «выключена»:
    списочный режим PIM молча теряет поля, и строгая проверка обнулила бы
    все ссылки разом.
    """
    from main_product_manager.utils import pim_public_url

    if row.get('active') is False or row.get('available') is False:
        return None
    valid_till = parse_datetime(row.get('validTill') or '')
    if valid_till and _as_aware(valid_till) <= now:
        return None
    return pim_public_url(row.get('link'))


def _collect_links(rows, wanted: set[str] | None = None) -> dict[str, str]:
    now = timezone.now()
    links = {}
    for row in rows:
        file_id = row.get('fileId')
        if not file_id or file_id in links or (wanted is not None and file_id not in wanted):
            continue
        link = _usable_link(row, now)
        if link:
            links[file_id] = link
    return links


def _links_created_since(since: datetime) -> dict[str, str]:
    stamp = _as_aware(since).astimezone(dt_timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    return _collect_links(_iter_pages(
        'Sharing', SHARING_FIELDS,
        [Where(attribute='createdAt', type='greaterThanOrEquals', value=stamp)]))


def _links_for_files(file_ids) -> dict[str, str]:
    file_ids = sorted(file_ids)
    links = {}
    for start in range(0, len(file_ids), FILE_ID_CHUNK):
        chunk = file_ids[start:start + FILE_ID_CHUNK]
        links.update(_collect_links(_iter_pages(
            'Sharing', SHARING_FIELDS, [Where(attribute='fileId', type='in', value=chunk)])))
    return links


def last_successful_run() -> datetime | None:
    from core.models import TaskRunHistory

    run = (TaskRunHistory.objects.filter(task_name=TASK_NAME, status='success')
           .order_by('-started_at').first())
    return run.started_at if run else None


# --- запись ------------------------------------------------------------------

def _chunks(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _plan_rows(desired: dict[int, list[tuple[str, bool]]]):
    """Что сделать с ProductPhoto, чтобы он совпал с desired, — без записи.

    Возвращает (создать, обновить, удалить) кортежами, а не моделями: на первом
    прогоне создать надо все ~466 тыс. строк, и экземпляры моделей заняли бы
    в памяти воркера в разы больше.

    Товар, которого нет в desired, теряет все фото: в PIM у него их больше
    нет, или он отвязан от товара PIM.
    """
    creates, updates, deletes = [], [], []
    pks = sorted(set(desired) | set(ProductPhoto.objects.values_list('product_id', flat=True).distinct()))
    for chunk in _chunks(pks, WRITE_CHUNK):
        existing = defaultdict(dict)
        rows = ProductPhoto.objects.filter(product_id__in=chunk).values_list(
            'pk', 'product_id', 'pim_file_id', 'position', 'is_main')
        for photo_pk, product_pk, file_id, position, is_main in rows:
            existing[product_pk][file_id] = (photo_pk, position, is_main)
        for pk in chunk:
            wanted = desired.get(pk, [])
            have = existing.get(pk, {})
            wanted_ids = {file_id for file_id, _ in wanted}
            deletes += [row[0] for file_id, row in have.items() if file_id not in wanted_ids]
            for position, (file_id, is_main) in enumerate(wanted):
                row = have.get(file_id)
                if row is None:
                    creates.append((pk, file_id, position, is_main))
                elif row[1:] != (position, is_main):
                    updates.append((row[0], position, is_main))
    return creates, updates, deletes


def _write_rows(creates, updates, deletes) -> int:
    """Пишет план _plan_rows. Возвращает число созданных строк.

    Товар, удалённый, пока шёл скан, пропускается: его строка упала бы на
    внешнем ключе и откатила бы весь ночной прогон.
    """
    for chunk in _chunks(deletes, WRITE_CHUNK):
        ProductPhoto.objects.filter(pk__in=chunk).delete()
    created = 0
    for chunk in _chunks(creates, WRITE_CHUNK):
        alive = set(Product.objects.filter(pk__in={row[0] for row in chunk}).values_list('pk', flat=True))
        photos = [ProductPhoto(product_id=pk, pim_file_id=file_id, position=position, is_main=is_main)
                  for pk, file_id, position, is_main in chunk if pk in alive]
        ProductPhoto.objects.bulk_create(photos, batch_size=1000)
        created += len(photos)
    for chunk in _chunks(updates, WRITE_CHUNK):
        ProductPhoto.objects.bulk_update(
            [ProductPhoto(pk=pk, position=position, is_main=is_main) for pk, position, is_main in chunk],
            ['position', 'is_main'], batch_size=1000)
    return created


def _apply_links(links: dict[str, str], clear_missing: bool) -> int:
    """Ставит public_url строкам по id файла. Возвращает число изменённых строк.

    clear_missing — только для полного прохода: тогда links — все действующие
    ссылки, и строка, которой в нём нет, ссылку потеряла. Инкрементальный
    проход видит лишь новые ссылки и ничего не стирает.
    """
    if clear_missing:
        rows = ProductPhoto.objects.all()
    elif links:
        rows = ProductPhoto.objects.filter(pim_file_id__in=list(links))
    else:
        return 0
    changed = []
    for pk, file_id, current in rows.values_list('pk', 'pim_file_id', 'public_url').iterator(chunk_size=5000):
        url = links.get(file_id, '' if clear_missing else current)
        if url != current:
            changed.append(ProductPhoto(pk=pk, public_url=url))
    for chunk in _chunks(changed, WRITE_CHUNK):
        ProductPhoto.objects.bulk_update(chunk, ['public_url'], batch_size=1000)
    return len(changed)


def refresh_product_photos(full: bool = False, since: datetime | None = None) -> dict:
    """Ночной проход: фото всех товаров зеркала и их публичные ссылки.

    full=True — ссылки полным проходом Sharing (раз в неделю; и первый запуск).
    Иначе — ссылки, созданные после since минус SHARING_OVERLAP, плюс ссылки
    файлов, впервые появившихся у товаров в этот проход. since=None при
    full=False — значит, успешного прогона ещё не было, и проход полный.

    Сначала всё читается из PIM, включая ссылки файлов новых строк, и только
    потом одной транзакцией пишется база. Сбой PIM на любом шаге не пишет
    ничего, и следующий прогон начинает с того же места. Запиши мы строки до
    поиска их ссылок, упавший поиск оставил бы их без ссылок до воскресенья:
    на следующую ночь эти строки уже не новые, а ссылки старше водяного знака.
    """
    products = _local_products()
    desired = _desired_photos(products)
    full = full or since is None
    wanted = {file_id for files in desired.values() for file_id, _ in files}
    if full:
        links = _collect_links(_iter_pages('Sharing', SHARING_FIELDS), wanted)
    else:
        links = _links_created_since(since - SHARING_OVERLAP)

    creates, updates, deletes = _plan_rows(desired)
    if not full:
        missing = {file_id for _, file_id, _, _ in creates} - links.keys()
        links.update(_links_for_files(missing))

    with transaction.atomic():
        created = _write_rows(creates, updates, deletes)
        linked = _apply_links({k: v for k, v in links.items() if k in wanted}, clear_missing=full)
    stats = {'created': created, 'updated': len(updates), 'deleted': len(deletes), 'links': linked,
             'full': full, 'products': len(desired), 'files': len(wanted), 'linked_files': len(links)}
    logger.info('refresh_product_photos: %s', stats)
    return stats
