import logging

from celery import shared_task

from core.task_runner import dispatch_after_commit, execute_locked_task

from .services.photos import TASK_NAME as PHOTOS_TASK_NAME
from .services.photos import last_successful_run, plan_photo_batches, refresh_photo_batch
from .services.pim_sync import (
    iter_unsynced_product_pk_batches,
    stale_product_pks,
    sync_product_from_pim,
    sync_products,
)
from .services.brands import adopt_supplier_brands, sync_brands_from_pim
from .services.set_rows import sync_set_rows
from .services.sets import sync_product_sets

logger = logging.getLogger(__name__)


@shared_task(name='product.sync_product_from_pim')
def sync_product_from_pim_task(pim_id: str) -> dict:
    return execute_locked_task(
        task_name=f'product.sync_product_from_pim:{pim_id}',
        lock_ttl=60 * 5,
        runner=lambda: sync_product_from_pim(pim_id),
    )


# Лимиты задач PIM — явные числа. time_limit=None для Celery значит «не
# задан» и отдаёт задачу общему CELERY_TASK_TIME_LIMIT (30 минут), а не снимает
# лимит: так полный проход фото (около часа) каждую ночь убивался SIGKILL, не
# записав ни строки. Каждый лимит — он же lock_ttl задачи: прогон, переживший
# свою блокировку, пустил бы вторую копию поверх себя. Мягкий лимит на минуту
# раньше бросает в runner исключение, и execute_locked_task пишет ошибку в
# TaskRunHistory и снимает блокировку; SIGKILL не даёт сделать ни того, ни
# другого. Но только если runner исключение не проглотит: поштучный
# except Exception в sync_products и push_pim_links и повтор страниц в
# stale_product_pks его глотают, и такой прогон снимает уже жёсткий лимит.
PIM_SCAN_TIME_LIMIT = 60 * 60
PIM_BATCH_TIME_LIMIT = 30 * 60


@shared_task(name='product.backfill_products_from_pim', time_limit=PIM_SCAN_TIME_LIMIT,
             soft_time_limit=PIM_SCAN_TIME_LIMIT - 60)
def backfill_products_from_pim_task(delay: float = 0.5, batch_size: int = 500,
                                    refresh: bool = False) -> dict:
    """Наполняет Product контентом из PIM: name, raw_data, категории, бренд, вектор.

    Второй шаг конвейера, не первый:

        reindex_pim_ids (проставляет pim_id) -> backfill_products_from_pim -> вектор

    Вектор отдельным шагом не нужен — sync_product_from_pim пересобирает его сам
    сразу после записи raw_data, из которых он и строится.

    Без этого прогона новая страница пуста по существу: у заготовок из 0005/0007
    есть pim_id и number, но нет ни названия, ни категорий, ни бренда, ни вектора
    — то есть ни поиска, ни фасетов.
    """
    def _runner():
        # dispatch_after_commit, а не .delay(): execute_locked_task оборачивает
        # runner в transaction.atomic(). Сам этот runner ничего не пишет, но при
        # откате родителя уже разосланные партии продолжили бы работать, а
        # прогон записался бы как упавший — ровно тот случай, ради которого
        # dispatch_after_commit и заведён в reindex_pim_ids.
        dispatched = 0
        for pks in iter_unsynced_product_pk_batches(batch_size=batch_size, refresh=refresh):
            dispatch_after_commit(sync_products_batch_task, pks=pks, delay=delay)
            dispatched += 1
        logger.info('backfill_products_from_pim: разослано партий: %s', dispatched)
        return dispatched

    return execute_locked_task(
        task_name='product.backfill_products_from_pim',
        lock_ttl=PIM_SCAN_TIME_LIMIT,
        runner=_runner,
    )


@shared_task(name='product.sync_products_batch', time_limit=PIM_BATCH_TIME_LIMIT,
             soft_time_limit=PIM_BATCH_TIME_LIMIT - 60)
def sync_products_batch_task(pks: list[int], delay: float = 0.5) -> dict:
    return execute_locked_task(
        task_name=f'product.sync_products_batch:{pks[0]}-{pks[-1]}',
        lock_ttl=PIM_BATCH_TIME_LIMIT,
        runner=lambda: sync_products(pks, delay=delay),
        # Партия висит на HTTP (два запроса на товар плюс категории) и спит
        # между ними — держать транзакцию открытой на весь проход нельзя.
        # Требование к runner-у: идемпотентность. sync_products ей отвечает,
        # записи сбойных товаров просто попадут в следующий прогон.
        atomic=False,
    )


@shared_task(name='product.refresh_products_from_pim', time_limit=PIM_SCAN_TIME_LIMIT,
             soft_time_limit=PIM_SCAN_TIME_LIMIT - 60)
def refresh_products_from_pim_task(delay: float = 0.5, batch_size: int = 500) -> dict:
    """Ночью: забирает из PIM контент товаров, у которых он разошёлся с зеркалом.

    Бэкфилл берёт только строки без raw_data и сам не запускается, поэтому
    PMP, привязанные к товару PIM уже после него, и описания, дописанные в PIM,
    до зеркала не доезжали. Здесь устаревшие строки находит
    stale_product_pks (сверка списком), а забирают их те же партии, что у
    бэкфилла. Первый прогон после долгого перерыва забирает весь накопившийся
    хвост и надолго занимает воркер очереди pim (CELERY_TASK_ROUTES), но не
    общий: импорт, выгрузки и цены его не ждут.
    """
    def _runner():
        pks = stale_product_pks()
        dispatched = 0
        for start in range(0, len(pks), batch_size):
            dispatch_after_commit(sync_products_batch_task, pks=pks[start:start + batch_size],
                                  delay=delay)
            dispatched += 1
        logger.info('refresh_products_from_pim: устаревших строк %s, разослано партий %s',
                    len(pks), dispatched)
        return len(pks)

    return execute_locked_task(
        task_name='product.refresh_products_from_pim',
        lock_ttl=PIM_SCAN_TIME_LIMIT,
        runner=_runner,
        # Сверка — сотни списочных запросов к PIM подряд, без записей в базу.
        atomic=False,
    )


@shared_task(name=PHOTOS_TASK_NAME, time_limit=PIM_SCAN_TIME_LIMIT,
             soft_time_limit=PIM_SCAN_TIME_LIMIT - 60)
def refresh_product_photos_task(full: bool = False) -> dict:
    """Ночью: фото товаров зеркала и их публичные ссылки (services/photos.py).

    Сам проход — партии refresh_product_photos_batch_task: одной задачей
    полный шёл около часа. Здесь — только раздача и ссылки по createdAt. По
    будням ссылки инкрементально, от прошлого успешного прогона этой задачи
    (партии водяной знак не двигают — у них своё имя); по воскресеньям
    (full=True) партии читают ссылки всех своих файлов и стирают отозванные.
    """
    def _runner():
        plan = plan_photo_batches(full=full, since=last_successful_run())
        for pks in plan['batches']:
            # full из плана, а не аргумент: без успешного прогона проход
            # полный и при full=False.
            dispatch_after_commit(refresh_product_photos_batch_task, pks=pks, full=plan['full'])
        return plan['deleted'] + plan['links']

    return execute_locked_task(
        task_name=PHOTOS_TASK_NAME,
        lock_ttl=PIM_SCAN_TIME_LIMIT,
        runner=_runner,
        # Ссылки по createdAt — списочные запросы к PIM. Запись — своей
        # короткой транзакцией, когда всё прочитано (plan_photo_batches), и
        # партии уходят уже после неё.
        atomic=False,
    )


@shared_task(name='product.refresh_product_photos_batch', time_limit=PIM_BATCH_TIME_LIMIT,
             soft_time_limit=PIM_BATCH_TIME_LIMIT - 60)
def refresh_product_photos_batch_task(pks: list[int], full: bool = False) -> dict:
    def _runner():
        stats = refresh_photo_batch(pks, full=full)
        return stats['created'] + stats['updated'] + stats['deleted'] + stats['links']

    return execute_locked_task(
        task_name=f'product.refresh_product_photos_batch:{pks[0]}-{pks[-1]}',
        lock_ttl=PIM_BATCH_TIME_LIMIT,
        runner=_runner,
        # Запросы к PIM, затем одна транзакция записи — своя, в
        # refresh_photo_batch: общая держала бы соединение весь проход.
        atomic=False,
    )


@shared_task(name='product.sync_product_sets')
def sync_product_sets_task() -> dict:
    """Наборы и их состав из PIM (services/sets.py). Ночью, после reindex_pim_ids:
    компоненты находятся через PriceManagerProduct, который тот заводит."""
    def _runner():
        synced = sync_product_sets()['sets']
        # Строка ГП нового набора — сразу, не ждать update_prices: без неё
        # виртуальный набор без цен и не виден наценкам. Цены от её
        # себестоимости посчитает ближайший update_prices.
        sync_set_rows()
        return synced

    return execute_locked_task(
        task_name='product.sync_product_sets',
        lock_ttl=60 * 30,
        runner=_runner,
        # Запросы к PIM идут между записями, а каждый набор и так пишется в
        # своей транзакции — общая держала бы соединение весь прогон.
        # sync_product_sets идемпотентна.
        atomic=False,
    )

@shared_task(name='product.sync_brands')
def sync_brands_task() -> dict:
    """Список брендов PIM целиком и пересопоставление строк ПП (services/brands.py).

    Ночью и по кнопке «Обновить из PIM» в окне «Бренды». Не в очереди pim:
    это несколько списочных запросов, а кнопку человек ждёт.
    """
    return execute_locked_task(
        task_name='product.sync_brands',
        lock_ttl=60 * 15,
        runner=sync_brands_from_pim,
        # Список брендов читается из PIM до записей; запись брендов идёт в
        # своей транзакции, пересопоставление строк идемпотентно.
        atomic=False,
    )


@shared_task(name='product.adopt_supplier_brands')
def adopt_supplier_brands_task() -> dict:
    """Бренд поставщиков — товарам без бренда, где поставщики не спорят.

    Отправляется после каждого сопоставления брендов строк ПП
    (apply_brand_resolution): загрузка прайса, синоним в окне «Бренды», ночная
    синхронизация брендов. Проход всегда по всему каталогу — он идемпотентен,
    и пропущенный из-за блокировки запуск доделает следующий. Не в очереди
    pim: в PIM не ходит.
    """
    return execute_locked_task(
        task_name='product.adopt_supplier_brands',
        lock_ttl=60 * 30,
        runner=lambda: adopt_supplier_brands().adopted,
    )


# Весь каталог — ~158 тыс. товаров: общего лимита воркера (30 мин) на него
# впритык, а lock_ttl должен пережить самый долгий прогон.
EXPORT_TIME_LIMIT = 60 * 60


def _run_export(task_name: str, title: str, user_id: int, build,
                lock_ttl: int = EXPORT_TIME_LIMIT) -> dict:
    """Общий ход экспорта: блокировка, файл, уведомление со ссылкой на скачивание.

    build() возвращает сохранённый ProductExport.
    """
    from django.urls import reverse
    from django.utils.html import escape

    from core.tasks import _notify

    created = {}

    def _runner():
        export = build()
        created['export'] = export
        return export.rows_count

    try:
        payload = execute_locked_task(
            task_name=task_name,
            lock_ttl=lock_ttl,
            runner=_runner,
            # Минуты чтения и в конце одна загрузка файла и одна вставка —
            # транзакция на весь проход ничего не даёт, а держалась бы открытой.
            atomic=False,
        )
    except Exception as exc:
        _notify(user_id, 'danger', f'{title} завершился с ошибкой: {escape(exc)}')
        raise

    export = created.get('export')
    if payload.get('status') == 'skipped':
        _notify(user_id, 'warning', f'{title} пропущен: предыдущий ещё выполняется.')
    elif export is not None:
        _notify(
            user_id,
            'success',
            f'{title} готов. Строк: {export.rows_count}.',
            link=reverse('product-export-download', kwargs={'pk': export.pk}),
            link_text='Скачать файл',
            kind='export',
        )
    return payload


@shared_task(name='product.export_products', time_limit=EXPORT_TIME_LIMIT,
             soft_time_limit=EXPORT_TIME_LIMIT - 60)
def export_products_task(query: str, columns: list[str], user_id: int) -> dict:
    """Экспорт товарной страницы в xlsx. Ссылка на скачивание — в уведомлении.

    query — строка запроса страницы (фильтры, поиск, сортировка) в том виде,
    в каком она стоит в адресной строке; columns — выбор колонок на момент
    нажатия.
    """
    from django.http import QueryDict

    from .export import build_product_export

    return _run_export(
        f'product.export_products:{user_id}', 'Экспорт товаров', user_id,
        lambda: build_product_export(QueryDict(query), columns, user_id))


@shared_task(name='product.export_products_full_csv', time_limit=EXPORT_TIME_LIMIT,
             soft_time_limit=EXPORT_TIME_LIMIT - 60)
def export_products_full_csv_task(user_id: int) -> dict:
    """Полный экспорт каталога в csv (кнопка в админке). Ссылка — в уведомлении.

    Своя блокировка, не общая с xlsx: идущий экспорт страницы не должен
    пропускать полный.
    """
    from .export import build_full_csv_export

    return _run_export(
        f'product.export_products_full_csv:{user_id}', 'Полный экспорт товаров (csv)', user_id,
        lambda: build_full_csv_export(user_id))


# Выгрузка Satu ходит в PIM за характеристиками всего каталога — ~1 600
# запросов по ~2 с, дольше часа полного csv.
SATU_EXPORT_TIME_LIMIT = 3 * 60 * 60


@shared_task(name='product.export_products_satu', time_limit=SATU_EXPORT_TIME_LIMIT,
             soft_time_limit=SATU_EXPORT_TIME_LIMIT - 60)
def export_products_satu_task(user_id: int) -> dict:
    """Выгрузка каталога в формате Satu.kz (кнопка в админке). Ссылка — в уведомлении."""
    from .satu_export import build_satu_export

    return _run_export(
        f'product.export_products_satu:{user_id}', 'Выгрузка для Satu', user_id,
        lambda: build_satu_export(user_id), lock_ttl=SATU_EXPORT_TIME_LIMIT)
