from celery import shared_task

from core.task_runner import execute_locked_task

from .services.pim_sync import sync_product_from_pim


@shared_task(name='product.sync_product_from_pim')
def sync_product_from_pim_task(pim_id: str) -> dict:
    return execute_locked_task(
        task_name=f'product.sync_product_from_pim:{pim_id}',
        lock_ttl=60 * 5,
        runner=lambda: sync_product_from_pim(pim_id),
    )
