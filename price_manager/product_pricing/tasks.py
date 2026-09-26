from celery import shared_task

from core.task_runner import execute_locked_task
from product.services.prices import recalculate_base_prices

from .services import calculate_product_prices


@shared_task(name='product_pricing.update_product_prices', time_limit=None, soft_time_limit=None)
def update_product_prices_task() -> dict:
    """Основные цены товаров -> наценки.

    В одной транзакции execute_locked_task: расчётные цены не должны увидеть
    наполовину пересчитанные основные.
    """
    def _runner():
        changed = recalculate_base_prices()
        changed += calculate_product_prices()
        return changed

    return execute_locked_task(
        task_name='product_pricing.update_product_prices',
        lock_ttl=60 * 30,
        runner=_runner,
    )
