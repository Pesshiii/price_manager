import logging

from celery import shared_task

from core.task_runner import dispatch_after_commit, execute_locked_task

from .services.pim_sync import (
    iter_unsynced_product_pk_batches,
    sync_product_from_pim,
    sync_products,
)

logger = logging.getLogger(__name__)


@shared_task(name='product.sync_product_from_pim')
def sync_product_from_pim_task(pim_id: str) -> dict:
    return execute_locked_task(
        task_name=f'product.sync_product_from_pim:{pim_id}',
        lock_ttl=60 * 5,
        runner=lambda: sync_product_from_pim(pim_id),
    )


@shared_task(name='product.backfill_products_from_pim', time_limit=None, soft_time_limit=None)
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
        lock_ttl=60 * 60,
        runner=_runner,
    )


@shared_task(name='product.sync_products_batch', time_limit=None, soft_time_limit=None)
def sync_products_batch_task(pks: list[int], delay: float = 0.5) -> dict:
    return execute_locked_task(
        task_name=f'product.sync_products_batch:{pks[0]}-{pks[-1]}',
        lock_ttl=60 * 30,
        runner=lambda: sync_products(pks, delay=delay),
        # Партия висит на HTTP (два запроса на товар плюс категории) и спит
        # между ними — держать транзакцию открытой на весь проход нельзя.
        # Требование к runner-у: идемпотентность. sync_products ей отвечает,
        # записи сбойных товаров просто попадут в следующий прогон.
        atomic=False,
    )


# Весь каталог — ~158 тыс. товаров: общего лимита воркера (30 мин) на него
# впритык, а lock_ttl должен пережить самый долгий прогон.
EXPORT_TIME_LIMIT = 60 * 60


@shared_task(name='product.export_products', time_limit=EXPORT_TIME_LIMIT,
             soft_time_limit=EXPORT_TIME_LIMIT - 60)
def export_products_task(query: str, columns: list[str], user_id: int) -> dict:
    """Экспорт товарной страницы в xlsx. Ссылка на скачивание — в уведомлении.

    query — строка запроса страницы (фильтры, поиск, сортировка) в том виде,
    в каком она стоит в адресной строке; columns — выбор колонок на момент
    нажатия.
    """
    from django.http import QueryDict
    from django.urls import reverse
    from django.utils.html import escape

    from core.tasks import _notify

    from .export import build_product_export

    created = {}

    def _runner():
        export = build_product_export(QueryDict(query), columns, user_id)
        created['export'] = export
        return export.rows_count

    try:
        payload = execute_locked_task(
            task_name=f'product.export_products:{user_id}',
            lock_ttl=EXPORT_TIME_LIMIT,
            runner=_runner,
            # Минуты чтения и в конце одна загрузка файла и одна вставка —
            # транзакция на весь проход ничего не даёт, а держалась бы открытой.
            atomic=False,
        )
    except Exception as exc:
        _notify(user_id, 'danger', f'Экспорт товаров завершился с ошибкой: {escape(exc)}')
        raise

    export = created.get('export')
    if payload.get('status') == 'skipped':
        _notify(user_id, 'warning', 'Экспорт товаров пропущен: предыдущий ещё выполняется.')
    elif export is not None:
        _notify(
            user_id,
            'success',
            f'Экспорт товаров готов. Строк: {export.rows_count}.',
            link=reverse('product-export-download', kwargs={'pk': export.pk}),
            link_text='Скачать файл',
        )
    return payload
